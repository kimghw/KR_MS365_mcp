"""
OneNote 저장소 스키마 (spec/spec_멀티유저.md ②-7.3, ②-11.1 `ensure_storage`).

| 모드 | DB 파일 | `owner_key` 값 |
|------|---------|----------------|
| 0 (단일 운영자) | `database/onenote.db` (기존 공용 파일) | 그 행의 `user_id`(이메일)와 같은 값 |
| 1 (멀티유저) | `<MS365_DATA_ROOT>/users/<user_key>/db/onenote.db` | principal 의 `user_key` |

- 세 테이블(`onenote_items`, `onenote_page_summaries`, `onenote_page_changes`) 모두
  `owner_key` 를 갖는다. 유일성은 `(owner_key, item_id)` / `(owner_key, page_id)` 다 —
  같은 Graph 페이지를 두 사용자가 써도 요약·이력이 섞이지 않는다.
- 모든 SQL 은 owner 조건을 단다. DB 파일이 이미 사용자별이어도 생략하지 않는다.
- **mode 0 구버전 DB 는 초기화 때 자동 이전한다**: `owner_key` 를 `user_id` 로 채우고,
  전역 `UNIQUE(item_id)` / `UNIQUE(page_id)` 를 owner 복합 유일성으로 바꾼다
  (rename → create → copy → drop, 한 트랜잭션). 데이터는 그대로 옮긴다.
- **mode 1 DB 에서는 소유자를 추정하지 않는다**: owner_key 가 없는 구형 테이블이 보이면
  채우지 않고 `LegacySchemaError` 로 실패한다(이전은 마이그레이션 도구 몫, ②-8).
"""

import logging
import os
import sqlite3
from typing import List, Sequence, Union

from mcp_common.principal import Principal
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.user_paths import UserPaths, ensure_user_dirs

logger = logging.getLogger(__name__)

PathLike = Union[str, "os.PathLike[str]"]


class LegacySchemaError(RuntimeError):
    """사용자 전용 DB 에 소유자 열이 없는 구형 테이블이 있음 — 소유자를 추정하지 않는다."""


ITEMS_TABLE = "onenote_items"
SUMMARIES_TABLE = "onenote_page_summaries"
CHANGES_TABLE = "onenote_page_changes"

_ITEMS_DDL = """
    CREATE TABLE IF NOT EXISTS {name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_key TEXT NOT NULL,
        user_id TEXT NOT NULL,
        item_type TEXT NOT NULL CHECK(item_type IN ('section', 'page')),
        item_id TEXT NOT NULL,
        item_name TEXT NOT NULL,
        notebook_id TEXT,
        notebook_name TEXT,
        section_id TEXT,
        section_name TEXT,
        web_url TEXT,
        last_accessed TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(owner_key, item_id)
    )
"""
_ITEMS_COLUMNS = (
    "id", "user_id", "item_type", "item_id", "item_name", "notebook_id", "notebook_name",
    "section_id", "section_name", "web_url", "last_accessed", "created_at", "updated_at",
)

_SUMMARIES_DDL = """
    CREATE TABLE IF NOT EXISTS {name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_key TEXT NOT NULL,
        page_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        page_title TEXT,
        summary TEXT,
        paragraph_summaries TEXT,
        keywords TEXT,
        content_hash TEXT,
        summarized_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(owner_key, page_id)
    )
"""
_SUMMARIES_COLUMNS = (
    "id", "page_id", "user_id", "page_title", "summary", "paragraph_summaries", "keywords",
    "content_hash", "summarized_at", "created_at", "updated_at",
)

_CHANGES_DDL = """
    CREATE TABLE IF NOT EXISTS {name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_key TEXT NOT NULL,
        page_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        action TEXT NOT NULL,
        content_snippet TEXT,
        target TEXT,
        content_hash TEXT,
        previous_hash TEXT,
        change_summary TEXT,
        change_keywords TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
"""

_INDEXES = (
    f"CREATE INDEX IF NOT EXISTS idx_onenote_items_owner_type ON {ITEMS_TABLE}(owner_key, item_type)",
    f"CREATE INDEX IF NOT EXISTS idx_onenote_items_owner_section ON {ITEMS_TABLE}(owner_key, section_id, item_type)",
    f"CREATE INDEX IF NOT EXISTS idx_onenote_items_owner_accessed ON {ITEMS_TABLE}(owner_key, item_type, last_accessed DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_page_summaries_owner ON {SUMMARIES_TABLE}(owner_key, summarized_at DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_page_changes_owner_page ON {CHANGES_TABLE}(owner_key, page_id, created_at DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_page_changes_owner ON {CHANGES_TABLE}(owner_key, created_at DESC)",
)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _rebuild_with_owner(
    conn: sqlite3.Connection, table: str, ddl: str, columns: Sequence[str]
) -> int:
    """구형 테이블을 owner 복합 유일성 스키마로 다시 만든다. owner_key ← user_id. 옮긴 행 수."""
    old = f"{table}__pre_owner"
    conn.execute(f"ALTER TABLE {table} RENAME TO {old}")
    conn.execute(ddl.format(name=table))
    old_cols = set(_columns(conn, old))
    cols = [c for c in columns if c in old_cols]
    col_list = ", ".join(cols)
    conn.execute(
        f"INSERT INTO {table} (owner_key, {col_list}) SELECT user_id, {col_list} FROM {old}"
    )
    moved = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    # 구 테이블의 인덱스는 DROP 과 함께 사라진다 — 새 인덱스는 호출자가 마지막에 만든다.
    conn.execute(f"DROP TABLE {old}")
    return moved


def _legacy(table: str) -> LegacySchemaError:
    return LegacySchemaError(
        f"{table}: owner_key 가 없는 구형 테이블입니다. 사용자 전용 DB 에서는 소유자를 "
        "추정하지 않습니다 — 마이그레이션 도구로 이전하세요."
    )


def _migrate_items(conn: sqlite3.Connection, legacy_backfill: bool) -> None:
    if not _table_exists(conn, ITEMS_TABLE):
        conn.execute(_ITEMS_DDL.format(name=ITEMS_TABLE))
        return
    cols = _columns(conn, ITEMS_TABLE)
    if "owner_key" in cols:
        return
    if not legacy_backfill:
        raise _legacy(ITEMS_TABLE)
    # 이전 세대 마이그레이션(parent_* → section_*, 누락 열 추가)을 먼저 맞춘다
    if "parent_id" in cols:
        conn.execute(f"ALTER TABLE {ITEMS_TABLE} RENAME COLUMN parent_id TO section_id")
        if "parent_name" in cols:
            conn.execute(f"ALTER TABLE {ITEMS_TABLE} RENAME COLUMN parent_name TO section_name")
    cols = _columns(conn, ITEMS_TABLE)
    for col in ("web_url", "notebook_id", "notebook_name", "section_id", "section_name"):
        if col not in cols:
            conn.execute(f"ALTER TABLE {ITEMS_TABLE} ADD COLUMN {col} TEXT")
    # 전역 UNIQUE(item_id)·이름 UNIQUE 를 걷고 (owner_key, item_id) 로 바꾼다
    moved = _rebuild_with_owner(conn, ITEMS_TABLE, _ITEMS_DDL, _ITEMS_COLUMNS)
    logger.info("%s owner_key 이전 완료 (%d행)", ITEMS_TABLE, moved)


def _migrate_summaries(conn: sqlite3.Connection, legacy_backfill: bool) -> None:
    if not _table_exists(conn, SUMMARIES_TABLE):
        conn.execute(_SUMMARIES_DDL.format(name=SUMMARIES_TABLE))
        return
    if "owner_key" in _columns(conn, SUMMARIES_TABLE):
        return
    if not legacy_backfill:
        raise _legacy(SUMMARIES_TABLE)
    moved = _rebuild_with_owner(conn, SUMMARIES_TABLE, _SUMMARIES_DDL, _SUMMARIES_COLUMNS)
    logger.info("%s owner_key 이전 완료 (%d행)", SUMMARIES_TABLE, moved)


def _migrate_changes(conn: sqlite3.Connection, legacy_backfill: bool) -> None:
    if not _table_exists(conn, CHANGES_TABLE):
        conn.execute(_CHANGES_DDL.format(name=CHANGES_TABLE))
        return
    if "owner_key" in _columns(conn, CHANGES_TABLE):
        return
    if not legacy_backfill:
        raise _legacy(CHANGES_TABLE)
    # 변경 이력에는 유일성 제약이 없어 재생성 없이 열만 더하고 채운다
    conn.execute(f"ALTER TABLE {CHANGES_TABLE} ADD COLUMN owner_key TEXT")
    conn.execute(f"UPDATE {CHANGES_TABLE} SET owner_key = user_id WHERE owner_key IS NULL")
    logger.info("%s owner_key 이전 완료", CHANGES_TABLE)


# ----------------------------------------------------------------------
# public
# ----------------------------------------------------------------------
def ensure_schema(db_path: PathLike, *, legacy_backfill: bool) -> None:
    """테이블 생성·이전. 한 트랜잭션(BEGIN IMMEDIATE)이라 실패하면 아무것도 바뀌지 않는다.

    Args:
        db_path: DB 파일 경로 (상위 디렉터리는 호출자가 만든다)
        legacy_backfill: True(mode 0)면 구형 테이블의 owner_key 를 user_id 로 채워 이전,
            False(mode 1)면 구형 테이블을 만나면 `LegacySchemaError`
    """
    conn = sqlite3.connect(os.fspath(db_path), timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_items(conn, legacy_backfill)
            _migrate_summaries(conn, legacy_backfill)
            _migrate_changes(conn, legacy_backfill)
            for sql in _INDEXES:
                conn.execute(sql)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def ensure_storage(principal: Principal, paths: UserPaths) -> None:
    """해당 사용자의 `db/onenote.db` 만 초기화한다. Graph 호출·기본 사용자 탐색 없음."""
    if not isinstance(principal, Principal) or paths.user_key != principal.user_key:
        raise SecurityError(ErrorCode.NOT_FOUND)
    ensure_user_dirs(paths)
    ensure_schema(paths.onenote_db, legacy_backfill=False)


__all__ = [
    "LegacySchemaError",
    "ITEMS_TABLE",
    "SUMMARIES_TABLE",
    "CHANGES_TABLE",
    "ensure_schema",
    "ensure_storage",
]
