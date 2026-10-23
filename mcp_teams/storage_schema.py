"""
Teams 저장소 스키마 (spec/spec_멀티유저.md ②-7.3, ②-11.1 `ensure_storage`).

| 모드 | DB 파일 | `owner_key` 값 |
|------|---------|----------------|
| 0 (단일 운영자) | `database/auth.db` (기존 위치 그대로) | 그 행의 `user_id`(이메일)와 같은 값 |
| 1 (멀티유저) | `<MS365_DATA_ROOT>/users/<user_key>/db/teams.db` — **auth.db 금지** | principal 의 `user_key` |

- `teams_chats` 의 유일성은 `(owner_key, chat_id)` 다. 모든 SQL 에 owner 조건을 단다.
- mode 0 구버전 테이블(auth.db 안)은 재생성하지 않는다 — 인증 DB 의 테이블을 갈아엎지 않도록
  `owner_key` 열을 더하고 `user_id` 로 채운 뒤 `(owner_key, chat_id)` 유일 인덱스만 만든다.
  기존 `UNIQUE(user_id, chat_id)` 는 남아 있어도 mode 0 에서는 owner_key = user_id 라 충돌하지 않는다.
- mode 1 DB 에서는 소유자를 추정하지 않는다 — owner_key 없는 구형 테이블이면 `LegacySchemaError`.
"""

import logging
import os
import sqlite3
from typing import List, Union

from mcp_common.principal import Principal
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.user_paths import UserPaths, ensure_user_dirs

logger = logging.getLogger(__name__)

PathLike = Union[str, "os.PathLike[str]"]

CHATS_TABLE = "teams_chats"


class LegacySchemaError(RuntimeError):
    """사용자 전용 DB 에 소유자 열이 없는 구형 테이블이 있음 — 소유자를 추정하지 않는다."""


_CHATS_DDL = f"""
    CREATE TABLE IF NOT EXISTS {CHATS_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_key TEXT NOT NULL,
        user_id TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        chat_type TEXT DEFAULT 'unknown',
        topic TEXT,
        topic_kr TEXT,
        member_count INTEGER DEFAULT 0,
        members_json TEXT,
        peer_user_name TEXT,
        peer_user_email TEXT,
        last_message_preview TEXT,
        last_message_time TEXT,
        last_sent_at TEXT,
        last_received_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_sync_at TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        UNIQUE(owner_key, chat_id)
    )
"""

_INDEXES = (
    f"CREATE INDEX IF NOT EXISTS idx_teams_chats_owner_active ON {CHATS_TABLE}(owner_key, is_active, last_message_time DESC)",
)


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def is_auth_db_path(db_path: PathLike) -> bool:
    return os.path.basename(os.fspath(db_path)).lower() == "auth.db"


def ensure_schema(db_path: PathLike, *, legacy_backfill: bool) -> None:
    """`teams_chats` 생성·이전. 한 트랜잭션이라 실패하면 아무것도 바뀌지 않는다.

    Args:
        legacy_backfill: True(mode 0)면 구형 테이블에 owner_key 를 더해 user_id 로 채운다.
            False(mode 1)면 구형 테이블을 만나면 `LegacySchemaError`.
    """
    conn = sqlite3.connect(os.fspath(db_path), timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (CHATS_TABLE,)
            ).fetchone()
            if not exists:
                conn.execute(_CHATS_DDL)
            elif "owner_key" not in _columns(conn, CHATS_TABLE):
                if not legacy_backfill:
                    raise LegacySchemaError(
                        f"{CHATS_TABLE}: owner_key 가 없는 구형 테이블입니다. 사용자 전용 DB 에서는 "
                        "소유자를 추정하지 않습니다 — 마이그레이션 도구로 이전하세요."
                    )
                conn.execute(f"ALTER TABLE {CHATS_TABLE} ADD COLUMN owner_key TEXT")
                conn.execute(f"UPDATE {CHATS_TABLE} SET owner_key = user_id WHERE owner_key IS NULL")
                conn.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_teams_chats_owner_chat "
                    f"ON {CHATS_TABLE}(owner_key, chat_id)"
                )
                logger.info("%s owner_key 이전 완료", CHATS_TABLE)
            for sql in _INDEXES:
                conn.execute(sql)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def ensure_storage(principal: Principal, paths: UserPaths) -> None:
    """해당 사용자의 `db/teams.db` 만 초기화한다. Graph 호출·기본 사용자 탐색 없음."""
    if not isinstance(principal, Principal) or paths.user_key != principal.user_key:
        raise SecurityError(ErrorCode.NOT_FOUND)
    ensure_user_dirs(paths)
    ensure_schema(paths.teams_db, legacy_backfill=False)


__all__ = [
    "CHATS_TABLE",
    "LegacySchemaError",
    "is_auth_db_path",
    "ensure_schema",
    "ensure_storage",
]
