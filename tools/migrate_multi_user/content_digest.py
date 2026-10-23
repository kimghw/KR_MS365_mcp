"""
DB 내용 digest — 이전이 쓴 행의 정규화 digest (N07).

`plan` 이 **apply 가 쓸 값 그대로** 테이블별 digest 를 계산해 manifest(`digests`)에 넣고, verify
(staging·live·재개)는 실제 DB 에서 같은 열을 읽어 다시 계산해 비교한다. 행 수·owner_key·user_id 만
보던 검사로는 요약·제목·ID 가 바뀐 DB 를 잡지 못했다.

- 행 digest = sha256(canonical JSON `{열: 값}`). 열은 **apply 가 쓰는 열**(target 스키마 ∩ 원본 열, + owner_key)
  에서 volatile 열(`id`, `created_at`, `updated_at`, `processed_at`)을 뺀 것. 열 목록은 manifest 에 같이 적는다.
- 테이블 digest = sha256(정렬한 행 digest 들을 `\\n` 으로 이은 것) — 순서 무관, 중복 행 보존.
- apply 가 쓰지 않아 기본값으로만 채워지는 열은 digest 밖이다(legacy 데이터가 아니다).
- target 열 목록은 도메인 `storage_schema` 로 임시 DB 를 만들어 읽는다(DDL 을 두 벌 두지 않는다).
"""

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .assignment import Assignment

#: 값이 실행 시각·autoincrement 에 따라 달라지는 열 — digest 에서 뺀다.
VOLATILE_COLUMNS = frozenset({"id", "created_at", "updated_at", "processed_at"})
#: 구버전 onenote_items 열 이름 → 현행 (storage_schema 의 parent_* 이전과 같은 규칙)
ALIASES = {"section_id": "parent_id", "section_name": "parent_name"}
#: 레코드 계획(metadata·메일)이 쓰는 열 — `applier._record_writer` 의 INSERT 와 같아야 한다.
RECORD_COLUMNS = {
    "file_metadata": ("owner_key", "file_url", "keywords", "metadata", "created_at", "updated_at"),
    "processed_messages": ("owner_key", "message_id", "subject", "from_address", "received_datetime",
                           "folder_path", "attachment_count", "processed_at"),
    "processed_files": ("owner_key", "message_id", "seq", "file_ref"),
}
_CHUNK_IDS = 500
_target_columns_cache: Optional[Dict[str, List[str]]] = None


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ----------------------------------------------------------------------
# target 스키마
# ----------------------------------------------------------------------
def target_columns() -> Dict[str, List[str]]:
    """도메인 storage_schema 가 만드는 사용자 DB 테이블의 열 목록 (프로세스당 1회 계산)."""
    global _target_columns_cache
    if _target_columns_cache is not None:
        return _target_columns_cache
    from mcp_common.user_paths import paths_for
    from mcp_file_handler.metadata.storage import init_owned_schema
    from mcp_onenote.storage_schema import ensure_schema as onenote_schema
    from mcp_outlook.storage_schema import ensure_outlook_db
    from mcp_teams.storage_schema import ensure_schema as teams_schema

    columns: Dict[str, List[str]] = {}
    with tempfile.TemporaryDirectory(prefix="ms365-schema-") as tmp:
        paths = paths_for("0" * 64, root=Path(tmp))
        paths.db_dir.mkdir(parents=True, exist_ok=True)
        onenote_schema(paths.onenote_db, legacy_backfill=False)
        teams_schema(paths.teams_db, legacy_backfill=False)
        ensure_outlook_db(paths)
        init_owned_schema(paths.metadata_db)
        for db_path in (paths.onenote_db, paths.teams_db, paths.outlook_db, paths.metadata_db):
            with closing(sqlite3.connect(os.fspath(db_path))) as conn:
                for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    if table.startswith("sqlite_") or table == "schema_meta":
                        continue
                    columns[table] = [r[1] for r in conn.execute(f"PRAGMA table_info({_q(table)})")]
    _target_columns_cache = columns
    return columns


def written_columns(table: str, source_columns: Sequence[str]) -> List[str]:
    """apply 가 `table` 에 쓰는 열 — target 스키마 순서, owner_key 포함, autoincrement id 제외."""
    source = set(source_columns)
    return [
        c for c in target_columns()[table]
        if c != "id" and (c == "owner_key" or c in source or ALIASES.get(c) in source)
    ]


def row_values(row: Dict[str, Any], columns: Sequence[str], owner_key: str) -> Tuple[Any, ...]:
    def value(col: str) -> Any:
        if col == "owner_key":
            return owner_key
        return row[col] if col in row else row.get(ALIASES.get(col, ""))

    return tuple(value(c) for c in columns)


def rows_by_id(snapshot: Path, table: str, rowids: Sequence[int]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with closing(sqlite3.connect(os.fspath(snapshot))) as conn:
        conn.row_factory = sqlite3.Row
        for start in range(0, len(rowids), _CHUNK_IDS):
            chunk = list(rowids[start:start + _CHUNK_IDS])
            marks = ",".join("?" for _ in chunk)
            out.extend(dict(r) for r in conn.execute(
                f"SELECT * FROM {_q(table)} WHERE rowid IN ({marks}) ORDER BY rowid", chunk))
    return out


# ----------------------------------------------------------------------
# digest
# ----------------------------------------------------------------------
def _normalize(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    return value


def digest_columns(columns: Sequence[str]) -> List[str]:
    return [c for c in columns if c not in VOLATILE_COLUMNS]


def digest_rows(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> Dict[str, Any]:
    """`columns` 순서의 값 튜플들 → {"columns", "rows", "sha256"}. volatile 열은 여기서 뺀다."""
    keep = [i for i, c in enumerate(columns) if c not in VOLATILE_COLUMNS]
    names = [columns[i] for i in keep]
    row_digests = []
    for row in rows:
        payload = {names[j]: _normalize(row[i]) for j, i in enumerate(keep)}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        row_digests.append(hashlib.sha256(encoded).hexdigest())
    table_digest = hashlib.sha256("\n".join(sorted(row_digests)).encode("ascii")).hexdigest()
    return {"columns": names, "rows": len(rows), "sha256": table_digest}


def expected_digests(assignment: Assignment, snapshots: Dict[str, Optional[Path]], user_key: str) -> Dict[str, Any]:
    """plan 시점: apply 가 이 사용자의 각 target 테이블에 쓸 행의 digest."""
    per_table: Dict[str, Tuple[List[str], List[Tuple[Any, ...]]]] = {}

    def add(table: str, columns: Sequence[str], rows: Sequence[Tuple[Any, ...]]) -> None:
        cols, acc = per_table.setdefault(table, (list(columns), []))
        if cols != list(columns):
            raise ValueError(f"{table}: 열 목록이 계획 사이에서 다릅니다")
        acc.extend(rows)

    for plan in assignment.rows:
        if plan.key == "onenote_page_summaries":
            add(plan.target_table, written_columns(plan.target_table, ()), [])  # 요약은 쓰지 않는다 → 0행
            continue
        rowids = plan.by_user.get(user_key, [])
        snapshot = snapshots.get(plan.source)
        rows = rows_by_id(snapshot, plan.source_table, rowids) if rowids and snapshot is not None else []
        columns = written_columns(plan.target_table, rows[0].keys() if rows else ())
        add(plan.target_table, columns, [row_values(r, columns, user_key) for r in rows])
    for plan in assignment.records:
        records = plan.by_user.get(user_key, [])
        if plan.target_table == "processed_messages":
            add("processed_messages", RECORD_COLUMNS["processed_messages"], [
                (user_key, r["message_id"], r["subject"], r["from_address"], r["received_datetime"],
                 r["folder_path"], r["attachment_count"], None) for r in records])
            add("processed_files", RECORD_COLUMNS["processed_files"], [
                (user_key, r["message_id"], i, ref) for r in records for i, ref in enumerate(r["files"])])
        else:
            add("file_metadata", RECORD_COLUMNS["file_metadata"], [
                (user_key, r["file_url"], r["keywords"], r["metadata"], None, None) for r in records])
    return {table: digest_rows(cols, rows) for table, (cols, rows) in sorted(per_table.items())}


def actual_digest(db_path: Path, table: str, columns: Sequence[str], owner_key: str) -> Dict[str, Any]:
    """실제 DB 에서 이 소유자의 행을 같은 열로 읽어 digest 한다 (열이 없으면 sqlite3.OperationalError)."""
    cols = list(columns)
    sql = f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(table)} WHERE owner_key = ?"
    try:
        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error:
        conn = sqlite3.connect(os.fspath(db_path), timeout=30)  # WAL DB 라 ro 가 안 되면 일반 연결(읽기만 한다)
    with closing(conn):
        rows = conn.execute(sql, (owner_key,)).fetchall()
    return digest_rows(cols, rows)


__all__ = [
    "VOLATILE_COLUMNS",
    "ALIASES",
    "RECORD_COLUMNS",
    "target_columns",
    "written_columns",
    "row_values",
    "rows_by_id",
    "digest_columns",
    "digest_rows",
    "expected_digests",
    "actual_digest",
]
