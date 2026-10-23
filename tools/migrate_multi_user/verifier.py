"""
`verify` — staging(또는 활성화된 live 영역)이 manifest 와 정확히 같고 사용자 사이에 섞인 것이 없는지 (②-8.4 6단계).

사용자마다, 영역(`db`·`files`)별로 검사한다 — activate 가 재개할 때 영역 하나씩 다시 쓰기 위해서다(R11).

`db` 영역:
- DB 4개(`onenote`·`teams`·`metadata`·`outlook`)가 owner_key 스키마이고, 테이블별 행 수가 manifest 와 같다
- `owner_key != user_key` 또는 NULL 인 행이 0 — **다른 사용자의 행이 없다**
- 테이블별 **내용 digest**(`content_digest.py` — apply 가 쓴 열의 정규화 행 digest)가 manifest 와 같다 (N07)
- `user_id` 열이 있으면 값이 그 사용자에게 매핑된 legacy 이메일뿐이다
- `onenote_page_summaries` 는 0행 (요약은 이전하지 않는다)
- 이전 표식(`_ms365_migration`)이 이 run 의 단계마다 있다
- legacy 인증 테이블(`azure_token_info` 등)이 어떤 DB 에도 없다, `db/` 에 예상 밖 파일이 없다

`files` 영역: 파일 집합이 manifest 배정과 같고 hash 가 같다 — manifest 밖 파일·링크가 없다.

사용자 루트: staging 은 `auth/db/files` 만 있고 `auth/` 가 비어 있어야 한다. live(`--live`)는
`manifest.json` 이 더 있을 수 있고 `auth/`(토큰·DEK)는 보지 않는다.

격리 보관: `rows.db` 의 사유별 행 수, `json/*.json`, `files.json` 의 파일과 hash.
결과는 `reports/<run_id>.verify.json`(live 는 `.verify-live.json`)에 남고 activate 가 다시 실행한다.
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Set

from mcp_common.principal import normalize_email_for_compare

from .assignment import RECORD_TARGETS, ROW_TABLES
from .common import (
    MARKER_TABLE,
    Layout,
    audit_event,
    has_files,
    read_json_optional,
    sha256_file,
    utcnow_iso,
    write_json,
)
from .content_digest import actual_digest

#: UserPaths 속성 → 그 DB 에서 확인할 테이블
USER_TABLES = {
    "teams_db": ("teams_chats",),
    "onenote_db": ("onenote_items", "onenote_page_changes", "onenote_page_summaries"),
    "metadata_db": ("file_metadata",),
    "outlook_db": ("processed_messages", "processed_files"),
}
_USER_ID_TABLES = {"teams_chats", "onenote_items", "onenote_page_changes", "onenote_page_summaries"}
#: 사용자 DB 에 있으면 안 되는 테이블 (legacy 인증·원본 형식)
FORBIDDEN_TABLES = {"azure_token_info", "azure_app_config", "azure_user_info", "legacy_users", "metadata"}
_DB_SUFFIXES = ("", "-wal", "-shm", "-journal")
AREAS = ("db", "files")
_ROOT_ENTRIES = {"staging": {"auth", "db", "files"}, "live": {"auth", "db", "files", "manifest.json"}}


def _step_db() -> Dict[str, str]:
    mapping = {f"rows:{key}": target_db for key, _s, _t, target_db, *_rest in ROW_TABLES}
    mapping.update({f"records:{key}": target[1] for key, target in RECORD_TARGETS.items()})
    return mapping


def _open_ro(path: Path) -> sqlite3.Connection:
    """읽기 전용으로 연다. WAL DB 라 ro 가 안 되면 일반 연결(읽기만 한다)."""
    try:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.Error:
        return sqlite3.connect(os.fspath(path), timeout=30)


def _tables(conn: sqlite3.Connection) -> Set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _is_link(path: Path) -> bool:
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def _paths_for(layout: Layout, user_key: str, live: bool):
    return layout.live_paths(user_key) if live else layout.staging_paths(user_key)


# ----------------------------------------------------------------------
# db 영역
# ----------------------------------------------------------------------
def _check_content(db_path: Path, table: str, user_key: str, expected: Dict[str, Any]) -> List[str]:
    """plan 이 적어 둔 열로 이 소유자의 행을 다시 digest 해 비교한다 — 요약·제목·ID 변경을 잡는다 (N07)."""
    try:
        actual = actual_digest(db_path, table, expected["columns"], user_key)
    except sqlite3.Error as exc:
        return [f"{table}: 내용 digest 를 계산할 수 없습니다 ({type(exc).__name__})"]
    if actual["sha256"] != expected["sha256"]:
        return [f"{table}: 내용 digest 가 manifest 와 다릅니다 (행 {actual['rows']}/{expected['rows']})"]
    return []


def _check_db(paths, attr: str, user_key: str, emails: Set[str], expected: Dict[str, int],
              markers: Dict[str, Set[str]], digests: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    db_path = Path(getattr(paths, attr))
    if not db_path.is_file():
        return [f"{db_path.name} 가 없습니다"]
    with closing(_open_ro(db_path)) as conn:
        tables = _tables(conn)
        for bad in sorted(tables & FORBIDDEN_TABLES):
            problems.append(f"{db_path.name} 에 있으면 안 되는 테이블 {bad}")
        for table in USER_TABLES[attr]:
            if table not in tables:
                problems.append(f"{db_path.name}: {table} 테이블이 없습니다")
                continue
            cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            if "owner_key" not in cols:
                problems.append(f"{db_path.name}: {table} 에 owner_key 가 없습니다 (구형 스키마)")
                continue
            mine = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE owner_key = ?', (user_key,)).fetchone()[0]
            foreign = conn.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE owner_key IS NULL OR owner_key != ?', (user_key,)
            ).fetchone()[0]
            if mine != expected.get(table, 0):
                problems.append(f"{table}: 행 수 {mine} ≠ manifest {expected.get(table, 0)}")
            if foreign:
                problems.append(f"{table}: 다른 사용자(owner_key)의 행 {foreign}개")
            if table in _USER_ID_TABLES and "user_id" in cols:
                for (user_id,) in conn.execute(f'SELECT DISTINCT user_id FROM "{table}"'):
                    if not isinstance(user_id, str) or normalize_email_for_compare(user_id) not in emails:
                        problems.append(f"{table}: 이 사용자에게 매핑되지 않은 legacy user_id 의 행이 있습니다")
                        break
            if table in digests:
                problems.extend(_check_content(db_path, table, user_key, digests[table]))
            else:
                problems.append(f"{table}: manifest 에 내용 digest 가 없습니다 — plan 을 다시 실행하세요")
        if MARKER_TABLE in tables:
            for step_id, run_id in conn.execute(f"SELECT step_id, run_id FROM {MARKER_TABLE}"):
                markers.setdefault(attr, set()).add(f"{step_id}@{run_id}")
    return problems


def _db_area_problems(paths, manifest: Dict[str, Any], user: Dict[str, Any]) -> List[str]:
    user_key = user["user_key"]
    db_dir = Path(paths.db_dir)
    if not db_dir.is_dir() or _is_link(db_dir):
        return ["db/ 가 없거나 링크입니다"]
    problems: List[str] = []
    allowed = {Path(getattr(paths, attr)).name + suffix for attr in USER_TABLES for suffix in _DB_SUFFIXES}
    for entry in db_dir.iterdir():
        if entry.name not in allowed:
            problems.append("db/ 에 예상 밖 파일이 있습니다")
            break
    emails = {normalize_email_for_compare(e) for e in user.get("legacy_emails", [])}
    expected = manifest["expected"][user_key]
    digests = (manifest.get("digests") or {}).get(user_key, {})
    markers: Dict[str, Set[str]] = {}
    for attr in USER_TABLES:
        problems.extend(_check_db(paths, attr, user_key, emails, expected, markers, digests))
    step_db = _step_db()
    for step_id in manifest["steps"][user_key]:
        if f"{step_id}@{manifest['run_id']}" not in markers.get(step_db[step_id], set()):
            problems.append(f"이전 표식 {step_id} 가 없습니다")
    return problems


# ----------------------------------------------------------------------
# files 영역
# ----------------------------------------------------------------------
def _files_area_problems(paths, manifest: Dict[str, Any], user: Dict[str, Any]) -> List[str]:
    files_root = Path(paths.files)
    if not files_root.is_dir() or _is_link(files_root):
        return ["files/ 가 없거나 링크입니다"]
    expected_files = {f["dest"]: f["sha256"] for f in manifest["files"] if f.get("owner") == user["user_key"]}
    problems: List[str] = []
    seen: Set[str] = set()
    for current, dirs, files in os.walk(files_root, followlinks=False):
        for name in dirs:
            if _is_link(Path(current) / name):
                problems.append("files/ 에 링크 디렉터리가 있습니다")
        for name in files:
            full = Path(current) / name
            rel = full.relative_to(files_root).as_posix()
            if full.is_symlink():
                problems.append("files/ 에 링크가 있습니다")
                continue
            if rel not in expected_files:
                problems.append("files/ 에 manifest 배정에 없는 파일이 있습니다")
                continue
            seen.add(rel)
            if sha256_file(full) != expected_files[rel]:
                problems.append("files/ 파일 hash 가 manifest 와 다릅니다")
    missing = set(expected_files) - seen
    if missing:
        problems.append(f"files/ 에 manifest 배정 파일 {len(missing)}개가 없습니다")
    return problems


# ----------------------------------------------------------------------
# 공개
# ----------------------------------------------------------------------
def verify_area(layout: Layout, manifest: Dict[str, Any], user: Dict[str, Any], area: str, *, live: bool = False) -> List[str]:
    """사용자 영역 하나(`db`|`files`)를 staging 또는 live 위치에서 manifest 와 대조한다."""
    paths = _paths_for(layout, user["user_key"], live)
    if area == "db":
        return _db_area_problems(paths, manifest, user)
    if area == "files":
        return _files_area_problems(paths, manifest, user)
    raise ValueError(area)


def _root_problems(paths, *, live: bool) -> List[str]:
    root = Path(paths.root)
    if not root.is_dir():
        return ["사용자 디렉터리가 없습니다"]
    if _is_link(root):
        return ["사용자 디렉터리가 링크입니다"]
    problems: List[str] = []
    allowed = _ROOT_ENTRIES["live" if live else "staging"]
    for entry in root.iterdir():
        if entry.name not in allowed:
            problems.append("사용자 루트에 예상 밖 항목이 있습니다")
            break
    if not live and has_files(Path(paths.auth_dir)):
        problems.append("auth/ 에 파일이 있습니다 — 이전 도구는 인증 저장소를 쓰지 않습니다")
    return problems


def verify_user(layout: Layout, manifest: Dict[str, Any], user: Dict[str, Any], *, live: bool = False) -> List[str]:
    paths = _paths_for(layout, user["user_key"], live)
    problems = _root_problems(paths, live=live)
    if not Path(paths.root).is_dir():
        return problems
    for area in AREAS:
        problems.extend(verify_area(layout, manifest, user, area, live=live))
    return problems


def _quarantine_counts(rows_db: Path) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {}
    if not rows_db.is_file():
        return counts
    with closing(_open_ro(rows_db)) as conn:
        for table in sorted(_tables(conn) - {MARKER_TABLE}):
            for reason, n in conn.execute(f'SELECT _quarantine_reason, COUNT(*) FROM "{table}" GROUP BY 1'):
                counts.setdefault(table, {})[reason] = n
    return counts


def verify_quarantine(layout: Layout, manifest: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    qdir = layout.quarantine_dir(manifest["run_id"])
    counts = _quarantine_counts(qdir / "rows.db")
    sources = {key: (source, table) for key, source, table, *_rest in ROW_TABLES}
    sources["metadata_db"] = ("metadata_db", "metadata")
    for key, reasons in manifest["quarantine"]["rows"].items():
        if key in sources:
            source, table = sources[key]
            got = counts.get(f"{source}__{table}", {})
        else:
            doc = read_json_optional(qdir / "json" / f"{key}.json") or {}
            got = {reason: len(entries) for reason, entries in (doc.get("reasons") or {}).items()}
        if got != reasons:
            problems.append(f"격리 {key}: 사유별 수 {got} ≠ manifest {reasons}")
    expected = [f for f in manifest["files"] if not f.get("owner") and f.get("reason") not in ("link", "skipped")]
    index = read_json_optional(qdir / "files.json") or []
    if len(index) != len(expected):
        problems.append(f"격리 파일 {len(index)}개 ≠ manifest {len(expected)}개")
    for entry in index:
        stored = qdir / entry["stored_as"]
        if not stored.is_file() or sha256_file(stored) != entry["sha256"]:
            problems.append("격리 파일이 없거나 hash 가 다릅니다")
    return problems


def run_verify(layout: Layout, manifest: Dict[str, Any], *, write_report: bool = True, live: bool = False) -> Dict[str, Any]:
    """staging(기본) 또는 활성화된 live 영역(`live=True`)을 manifest 와 대조한다."""
    run_id = manifest["run_id"]
    problems: List[str] = []
    users = {u["user_key"]: u for u in manifest["users"]}
    if not live:
        checkpoint = read_json_optional(layout.checkpoints / f"{run_id}.apply.json") or {}
        if checkpoint.get("status") != "complete":
            problems.append("apply 가 끝나지 않았습니다 — apply 를 다시 실행하세요")
        marker = read_json_optional(layout.staging_marker) or {}
        if marker.get("run_id") != run_id:
            problems.append("staging 이 이 manifest 의 run 이 아닙니다")
        if layout.staging_users.is_dir():
            extra = [d for d in layout.staging_users.iterdir() if d.name not in users]
            if extra:
                problems.append(f"staging 에 manifest 밖 사용자 디렉터리 {len(extra)}개")
    per_user: Dict[str, Any] = {}
    for user_key, user in sorted(users.items()):
        found = verify_user(layout, manifest, user, live=live)
        per_user[user_key] = {"ok": not found, "problems": found}
        problems.extend(f"user_key {user_key}: {p}" for p in found)
    problems.extend(verify_quarantine(layout, manifest))
    report = {
        "status": "ok" if not problems else "failed",
        "target": "live" if live else "staging",
        "run_id": run_id,
        "manifest_sha256": manifest["_sha256"],
        "verified_at": utcnow_iso(),
        "users": per_user,
        "problems": problems,
    }
    if write_report:
        suffix = ".verify-live.json" if live else ".verify.json"
        write_json(layout.reports / f"{run_id}{suffix}", report, root=layout.migration)
    audit_event("verify", "success" if not problems else "failure",
                error_code=None if not problems else "verify_failed")
    return report


__all__ = ["AREAS", "USER_TABLES", "FORBIDDEN_TABLES", "verify_area", "verify_user", "verify_quarantine", "run_verify"]
