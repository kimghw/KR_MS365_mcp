"""
소유자 배정 계산 — snapshot·JSON·파일 목록·매핑 → 사용자별 이전 목록 + 격리 목록 (순수 함수).

`plan` 과 `apply` 가 **같은 함수**를 부른다. apply 는 snapshot·매핑·파일 hash 가 그대로인지 확인한 뒤
다시 계산하고 digest 가 manifest 와 같아야 진행한다 — 행 식별자를 manifest 에 싣지 않고도
plan 이 본 것과 정확히 같은 것을 옮긴다.

## 배정 규칙

| 대상 | 소유자 근거 | 격리 사유 |
|------|-------------|-----------|
| `teams_chats`·`onenote_items`·`onenote_page_changes` | 행의 `user_id` ↔ 매핑 이메일 | `unmapped_owner` `ambiguous_owner` `owner_mismatch` `invalid_row` `duplicate_after_merge` |
| `onenote_page_summaries` | — | 전부 `regenerate` |
| `metadata.db`·`metadata.json` | `owners.<src>_rows[file_url]` → `owners.<src>` | `unowned` `unmapped_local_path` `duplicate` |
| `mail_metadata.json` | `owners.mail_metadata_rows[message_id]` → `owners.mail_metadata` | `unowned` |
| 파일 | `owners.paths` 규칙 (접두 성분 일치) | `unowned` `ambiguous_owner` `admin_only` `unsafe_name` (복사 안 함: `link` `skipped`) |

로컬 경로를 가리키는 참조(metadata `file_url`, 메일 `saved_files`)는 **같은 사용자에게 이전된
파일**이면 `files/` 기준 상대경로로 고쳐 쓴다. 그렇지 않은 메일 참조는 버리고 개수만 센다.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .common import FILE_DEST_PREFIX, digest_of, norm
from .legacy import FileEntry, Sources, read_table
from .mapping import AMBIGUOUS, Mapping

REMOTE_PREFIXES = ("http://", "https://", "onedrive:")

#: (key, 원본, 원본 테이블, 대상 UserPaths 속성, 대상 테이블, 중복 키, 필수 열, 방식)
ROW_TABLES: Tuple[Tuple[str, str, str, str, str, Optional[str], Tuple[str, ...], str], ...] = (
    ("teams_chats", "auth_db", "teams_chats", "teams_db", "teams_chats", "chat_id", ("chat_id",), "split"),
    ("onenote_items", "onenote_db", "onenote_items", "onenote_db", "onenote_items", "item_id",
     ("item_id", "item_type", "item_name"), "split"),
    ("onenote_page_changes", "onenote_db", "onenote_page_changes", "onenote_db", "onenote_page_changes", None,
     ("page_id", "action"), "split"),
    ("onenote_page_summaries", "onenote_db", "onenote_page_summaries", "onenote_db", "onenote_page_summaries", None,
     (), "quarantine_all"),
)

#: 레코드 계획 → (원본, 대상 UserPaths 속성, 대상 테이블)
RECORD_TARGETS = {
    "metadata_db": ("metadata_db", "metadata_db", "file_metadata"),
    "metadata_json": ("metadata_json", "metadata_db", "file_metadata"),
    "mail_metadata": ("mail_metadata", "outlook_db", "processed_messages"),
}

#: 복사하지 않고 기록만 하는 파일 사유
NOT_COPIED = ("link", "skipped")


@dataclass
class RowPlan:
    key: str
    source: str
    source_table: str
    target_db: str
    target_table: str
    by_user: Dict[str, List[int]] = field(default_factory=dict)
    quarantine: Dict[str, List[int]] = field(default_factory=dict)


@dataclass
class RecordPlan:
    key: str
    source: str
    target_db: str
    target_table: str
    by_user: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    quarantine: Dict[str, List[Any]] = field(default_factory=dict)  # rowid(int) 또는 원본 키(str)
    refs_dropped: Dict[str, int] = field(default_factory=dict)


@dataclass
class FileItem:
    source: str
    rel: str
    size: int
    sha256: Optional[str]
    owner: Optional[str] = None
    dest: Optional[str] = None      # 사용자 files/ 기준 posix
    reason: Optional[str] = None    # None 이면 배정됨


@dataclass
class Assignment:
    rows: List[RowPlan]
    records: List[RecordPlan]
    files: List[FileItem]

    def to_json(self) -> Dict[str, Any]:
        return {
            "rows": [asdict(r) for r in self.rows],
            "records": [asdict(r) for r in self.records],
            "files": [asdict(f) for f in self.files],
        }

    def digest(self) -> str:
        return digest_of(self.to_json())

    def user_keys(self) -> List[str]:
        keys = set()
        for plan in self.rows:
            keys.update(plan.by_user)
        for plan in self.records:
            keys.update(plan.by_user)
        keys.update(f.owner for f in self.files if f.owner)
        return sorted(keys)


@dataclass
class Inputs:
    mapping: Mapping
    sources: Sources
    snapshots: Dict[str, Optional[Path]]   # auth_db / onenote_db / metadata_db
    json_docs: Dict[str, Any]              # metadata_json / mail_metadata (없으면 None)
    files: List[FileEntry]


# ----------------------------------------------------------------------
# 파일
# ----------------------------------------------------------------------
def _file_key(source: str, rel: str) -> Tuple[str, str]:
    return source, os.path.normcase(rel.replace("/", os.sep))


def _plan_files(inputs: Inputs) -> List[FileItem]:
    items: List[FileItem] = []
    for entry in inputs.files:
        item = FileItem(entry.source, entry.rel, entry.size, entry.sha256)
        if entry.kind in NOT_COPIED:
            item.reason = entry.kind
        elif entry.admin_only:
            item.reason = "admin_only"
        elif entry.unsafe:
            item.reason = "unsafe_name"
        else:
            owner, why = inputs.mapping.owner_of_path(entry.source, tuple(entry.rel.split("/")))
            if owner:
                item.owner = owner
                item.dest = f"{FILE_DEST_PREFIX[entry.source]}/{entry.rel}"
            else:
                item.reason = why
        items.append(item)
    return items


def _ref_rewriter(inputs: Inputs, files: List[FileItem]) -> Callable[[Any, str], Tuple[Optional[str], bool]]:
    """참조 → (새 참조, 원격 여부). 로컬인데 같은 사용자에게 이전되지 않았으면 (None, False)."""
    index = {_file_key(f.source, f.rel): f for f in files if f.owner}
    dirs = {name: norm(inputs.sources.path(name)) for name in FILE_DEST_PREFIX}
    root = inputs.sources.legacy_root

    def rewrite(ref: Any, owner: str) -> Tuple[Optional[str], bool]:
        if not isinstance(ref, str) or not ref.strip():
            return None, False
        if ref.strip().lower().startswith(REMOTE_PREFIXES):
            return ref, True
        path = ref if os.path.isabs(ref) else os.path.join(root, ref)
        target = norm(Path(path))
        for source, base in dirs.items():
            if target.startswith(base.rstrip(os.sep) + os.sep):
                rel = target[len(base.rstrip(os.sep)) + 1:]
                item = index.get((source, rel))
                if item is not None and item.owner == owner:
                    return item.dest, False
        return None, False

    return rewrite


# ----------------------------------------------------------------------
# 행 (SQLite 원본)
# ----------------------------------------------------------------------
def _owner_problem(mapping: Mapping, row: Dict[str, Any], cols: List[str]) -> Tuple[Optional[str], Optional[str]]:
    legacy_owner = row.get("owner_key")
    if "owner_key" in cols and legacy_owner not in (None, "") and legacy_owner != row.get("user_id"):
        return None, "owner_mismatch"   # mode 0 이전본은 owner_key == user_id 여야 한다
    owner = mapping.owner_of_email(row.get("user_id"))
    if owner is None:
        return None, "unmapped_owner"
    if owner == AMBIGUOUS:
        return None, "ambiguous_owner"
    return owner, None


#: 비어 있으면 안 되는 식별자 열 (나머지 필수 열은 NULL 만 아니면 된다 — 빈 제목 페이지도 정상)
_KEY_COLUMNS = {"chat_id", "item_id", "page_id"}
_ITEM_TYPES = {"section", "page"}


def _invalid(row: Dict[str, Any], required: Tuple[str, ...]) -> bool:
    """대상 스키마의 NOT NULL·CHECK 를 어길 행 — 넣으면 단계 전체가 실패하므로 미리 격리한다."""
    for col in required:
        value = row.get(col)
        if value is None or (col in _KEY_COLUMNS and str(value).strip() == ""):
            return True
    return "item_type" in required and row.get("item_type") not in _ITEM_TYPES


def _plan_rows(inputs: Inputs) -> List[RowPlan]:
    plans: List[RowPlan] = []
    for key, source, table, target_db, target_table, dedupe, required, mode in ROW_TABLES:
        plan = RowPlan(key, source, table, target_db, target_table)
        cols, rows = read_table(inputs.snapshots.get(source), table)
        winners: Dict[Tuple[str, Any], Dict[str, Any]] = {}
        for row in rows:
            rid = int(row["_rowid"])
            if mode == "quarantine_all":
                plan.quarantine.setdefault("regenerate", []).append(rid)
                continue
            if _invalid(row, required):
                plan.quarantine.setdefault("invalid_row", []).append(rid)
                continue
            owner, why = _owner_problem(inputs.mapping, row, cols)
            if owner is None:
                plan.quarantine.setdefault(why, []).append(rid)
                continue
            if dedupe is None:
                plan.by_user.setdefault(owner, []).append(rid)
                continue
            slot = (owner, row.get(dedupe))
            current = winners.get(slot)
            rank = (str(row.get("updated_at") or ""), rid)
            if current is None:
                winners[slot] = row
            else:
                current_rank = (str(current.get("updated_at") or ""), int(current["_rowid"]))
                loser = row if rank < current_rank else current
                if rank > current_rank:
                    winners[slot] = row
                plan.quarantine.setdefault("duplicate_after_merge", []).append(int(loser["_rowid"]))
        for (owner, _k), row in winners.items():
            plan.by_user.setdefault(owner, []).append(int(row["_rowid"]))
        for ids in list(plan.by_user.values()) + list(plan.quarantine.values()):
            ids.sort()
        plans.append(plan)
    return plans


# ----------------------------------------------------------------------
# 레코드 (metadata·메일 메타데이터)
# ----------------------------------------------------------------------
def _record_owner(mapping: Mapping, source: str, row_key: str) -> Optional[str]:
    return mapping.row_owner.get(source, {}).get(row_key) or mapping.whole_owner.get(source)


def _keywords(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return "" if value is None else str(value)


def _plan_file_metadata(inputs: Inputs, rewrite, seen: Dict[str, set]) -> List[RecordPlan]:
    plans = []
    db_plan = RecordPlan("metadata_db", *RECORD_TARGETS["metadata_db"])
    _cols, rows = read_table(inputs.snapshots.get("metadata_db"), "metadata")
    entries: List[Tuple[RecordPlan, Any, str, Dict[str, Any]]] = []
    for row in rows:
        entries.append((db_plan, int(row["_rowid"]), str(row.get("file_url") or ""), {
            "keywords": row.get("keywords") or "",
            "metadata": row.get("metadata") or "{}",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }))
    json_plan = RecordPlan("metadata_json", *RECORD_TARGETS["metadata_json"])
    doc = inputs.json_docs.get("metadata_json")
    if isinstance(doc, dict):
        for file_url in sorted(doc):
            data = doc[file_url] if isinstance(doc[file_url], dict) else {}
            entries.append((json_plan, file_url, file_url, {
                "keywords": _keywords(data.get("keywords")),
                "metadata": json.dumps(data.get("metadata") or {}, ensure_ascii=False),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
            }))
    for plan, qkey, file_url, values in entries:
        owner = _record_owner(inputs.mapping, plan.key, file_url) if file_url else None
        if owner is None:
            plan.quarantine.setdefault("unowned", []).append(qkey)
            continue
        new_url, _remote = rewrite(file_url, owner)
        if new_url is None:
            plan.quarantine.setdefault("unmapped_local_path", []).append(qkey)
            continue
        if new_url in seen.setdefault(owner, set()):
            plan.quarantine.setdefault("duplicate", []).append(qkey)
            continue
        seen[owner].add(new_url)
        plan.by_user.setdefault(owner, []).append({"file_url": new_url, **values})
    plans.extend([db_plan, json_plan])
    return plans


def _plan_mail(inputs: Inputs, rewrite) -> RecordPlan:
    plan = RecordPlan("mail_metadata", *RECORD_TARGETS["mail_metadata"])
    doc = inputs.json_docs.get("mail_metadata")
    messages = doc.get("processed_messages") if isinstance(doc, dict) else None
    if not isinstance(messages, dict):
        return plan
    for message_id in sorted(messages):
        data = messages[message_id] if isinstance(messages[message_id], dict) else {}
        owner = _record_owner(inputs.mapping, "mail_metadata", message_id)
        if owner is None:
            plan.quarantine.setdefault("unowned", []).append(message_id)
            continue
        refs: List[str] = []
        for ref in data.get("saved_files") or []:
            new_ref, _remote = rewrite(ref, owner)
            if new_ref is None:
                plan.refs_dropped[owner] = plan.refs_dropped.get(owner, 0) + 1
            else:
                refs.append(new_ref)
        plan.by_user.setdefault(owner, []).append({
            "message_id": message_id,
            "subject": str(data.get("subject") or ""),
            "from_address": str(data.get("from") or ""),
            "received_datetime": str(data.get("received_datetime") or ""),
            "folder_path": "",  # legacy 절대경로는 싣지 않는다 (mode 1 은 files/ 기준)
            "attachment_count": int(data.get("attachment_count") or 0),
            "processed_at": str(data.get("processed_at") or ""),
            "files": refs,
        })
    return plan


# ----------------------------------------------------------------------
# 공개
# ----------------------------------------------------------------------
def compute_assignment(inputs: Inputs) -> Assignment:
    files = _plan_files(inputs)
    rewrite = _ref_rewriter(inputs, files)
    rows = _plan_rows(inputs)
    records = _plan_file_metadata(inputs, rewrite, {})
    records.append(_plan_mail(inputs, rewrite))
    return Assignment(rows=rows, records=records, files=files)


def expected_counts(assignment: Assignment, user_key: str) -> Dict[str, int]:
    """verify 가 staging 에서 확인할 대상 테이블별 행 수."""
    counts: Dict[str, int] = {
        "teams_chats": 0, "onenote_items": 0, "onenote_page_changes": 0, "onenote_page_summaries": 0,
        "file_metadata": 0, "processed_messages": 0, "processed_files": 0,
    }
    for plan in assignment.rows:
        counts[plan.target_table] += len(plan.by_user.get(user_key, []))
    for plan in assignment.records:
        records = plan.by_user.get(user_key, [])
        counts[plan.target_table] += len(records)
        if plan.target_table == "processed_messages":
            counts["processed_files"] += sum(len(r["files"]) for r in records)
    return counts


def step_ids(assignment: Assignment, user_key: str) -> List[str]:
    """그 사용자에게 적용할 단계 — 행이 없는 단계도 표식을 남겨 '처리했음'을 기록한다."""
    return [f"rows:{p.key}" for p in assignment.rows if p.key != "onenote_page_summaries"] + [
        f"records:{p.key}" for p in assignment.records
    ]


def summarize(assignment: Assignment) -> Dict[str, Any]:
    users: Dict[str, Any] = {}
    for user_key in assignment.user_keys():
        users[user_key] = {
            "rows": expected_counts(assignment, user_key),
            "files": sum(1 for f in assignment.files if f.owner == user_key),
            "refs_dropped": sum(p.refs_dropped.get(user_key, 0) for p in assignment.records),
        }
    quarantine_rows: Dict[str, Dict[str, int]] = {}
    for plan in list(assignment.rows) + list(assignment.records):
        if plan.quarantine:
            quarantine_rows[plan.key] = {reason: len(ids) for reason, ids in sorted(plan.quarantine.items())}
    quarantine_files: Dict[str, int] = {}
    for item in assignment.files:
        if item.reason:
            quarantine_files[item.reason] = quarantine_files.get(item.reason, 0) + 1
    return {"users": users, "quarantine": {"rows": quarantine_rows, "files": quarantine_files}}


def file_listing(assignment: Assignment) -> List[Dict[str, Any]]:
    """manifest 의 파일 귀속 목록 (②-8.2 — 파일 귀속·원본 hash·대상 경로)."""
    return [asdict(f) for f in assignment.files]


__all__ = [
    "REMOTE_PREFIXES",
    "ROW_TABLES",
    "RECORD_TARGETS",
    "NOT_COPIED",
    "RowPlan",
    "RecordPlan",
    "FileItem",
    "Assignment",
    "Inputs",
    "compute_assignment",
    "expected_counts",
    "step_ids",
    "summarize",
    "file_listing",
]
