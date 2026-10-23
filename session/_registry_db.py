"""
identity registry 커널 — `<data_root>/system/registry.db` 접근 (session 내부 전용).

공개 API 는 `session.identity_registry` 가 관문이다. 이 모듈은 인증 경로(identity_registry)와
관리 경로(registry_admin)가 함께 쓰는 DB 접근만 담아 순환 import 를 막는다.

registry 에는 **위치 정보와 계정 상태만** 둔다(②-4.3, ②-6.4):

| 테이블 | 내용 |
|--------|------|
| `users` | user_key PK, (tenant_id, object_id) UNIQUE, status, auth_epoch, graph_email, 시각 |
| `credential_index` | bearer key `kid → user_key` (digest·scope·만료는 사용자 auth.db) |
| `oauth_state_index` | `state_hash → (user_key, attempt_id, expires_at)` |
| `oauth_ticket_index` | 브라우저 ticket 해시 → (user_key, attempt_id, expires_at) — 1회 소비 |
| `tombstones` | 삭제된 사용자의 재사용 방지 기록 (user_key, tid, oid, deleted_at, last_auth_epoch) |

같은 (tid, oid) 는 같은 user_key 이므로, 삭제 후 reinstate 한 사용자의 auth_epoch 는 tombstone 의
`last_auth_epoch + 1` 부터 시작한다 — epoch 가 이전 수명과 겹치면 다른 프로세스의 서비스 풀
`(user_key, domain, auth_epoch)` 항목(이전 principal·키에 묶인 서비스)이 재사용되기 때문이다.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from mcp_common.user_paths import ensure_system_dirs, system_paths

from ._mu_common import Tx, executescript_tx, iso, length_delimited, open_db, sha256_hex, utcnow
from .user_auth_store import UserAuthStore

USER_STATUSES = ("pending_link", "active", "disabled", "deleting", "deleted")
#: bearer 인증·요청 처리를 허용하는 상태. pending_link 는 Graph 연결 전 단계(연결 API 사용 가능).
USABLE_STATUSES = ("pending_link", "active")

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS users (
        user_key TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending_link', 'active', 'disabled', 'deleting', 'deleted')),
        auth_epoch INTEGER NOT NULL DEFAULT 0,
        graph_email TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (tenant_id, object_id)
    )""",
    """CREATE TABLE IF NOT EXISTS credential_index (
        kid TEXT PRIMARY KEY,
        user_key TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_credential_user ON credential_index(user_key)",
    """CREATE TABLE IF NOT EXISTS oauth_state_index (
        state_hash TEXT PRIMARY KEY,
        user_key TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_ticket_index (
        ticket_hash TEXT PRIMARY KEY,
        user_key TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tombstones (
        user_key TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        deleted_at TEXT NOT NULL,
        last_auth_epoch INTEGER NOT NULL DEFAULT 0
    )""",
)

def key_digest(deployment_id: str, kid: str, secret: str) -> str:
    """bearer key digest — SHA-256(길이 구분 결합("m365v1-key", deployment_id, kid, secret))."""
    return sha256_hex(length_delimited("m365v1-key", deployment_id, kid, secret))


class RegistryMissing(Exception):
    """registry.db 가 아직 없다(`admin_cli init` 전)."""


def registry_path() -> Path:
    return system_paths().registry_db


@contextmanager
def registry(*, create: bool = False) -> Iterator[sqlite3.Connection]:
    """registry 연결. create=False 면 파일이 없을 때 만들지 않는다(요청 경로)."""
    path = registry_path()
    if create:
        ensure_system_dirs()
        conn = open_db(path, create=True)
        probe = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tombstones'"
        if conn.execute(probe).fetchone() is None:
            executescript_tx(conn, _SCHEMA)
        elif "last_auth_epoch" not in {r["name"] for r in conn.execute("PRAGMA table_info(tombstones)")}:
            # 초기 스키마(열 없음) 이전 — 재등록 epoch 단조 증가용 (아래 tombstones 설명)
            executescript_tx(conn, ["ALTER TABLE tombstones ADD COLUMN last_auth_epoch INTEGER NOT NULL DEFAULT 0"])
    else:
        try:
            conn = open_db(path, create=False)
        except (FileNotFoundError, sqlite3.OperationalError) as exc:
            raise RegistryMissing("registry missing") from exc
    try:
        yield conn
    finally:
        conn.close()


def ensure_registry() -> Path:
    with registry(create=True):
        pass
    return registry_path()


@dataclass(frozen=True)
class UserRecord:
    user_key: str
    tenant_id: str
    object_id: str
    status: str
    auth_epoch: int
    graph_email: Optional[str]
    created_at: str
    updated_at: str

    @property
    def usable(self) -> bool:
        return self.status in USABLE_STATUSES

    def store(self) -> UserAuthStore:
        return UserAuthStore(self.user_key, self.tenant_id, self.object_id)


def _record(row: Optional[sqlite3.Row]) -> Optional[UserRecord]:
    if row is None:
        return None
    return UserRecord(
        user_key=row["user_key"],
        tenant_id=row["tenant_id"],
        object_id=row["object_id"],
        status=row["status"],
        auth_epoch=int(row["auth_epoch"]),
        graph_email=row["graph_email"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_user(user_key: str) -> Optional[UserRecord]:
    try:
        with registry() as conn:
            return _record(conn.execute("SELECT * FROM users WHERE user_key = ?", (user_key,)).fetchone())
    except RegistryMissing:
        return None


def all_users() -> List[UserRecord]:
    try:
        with registry() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at, user_key").fetchall()
    except RegistryMissing:
        return []
    return [r for r in (_record(row) for row in rows) if r is not None]


def user_for_kid(kid: str) -> Optional[str]:
    try:
        with registry() as conn:
            row = conn.execute("SELECT user_key FROM credential_index WHERE kid = ?", (kid,)).fetchone()
    except RegistryMissing:
        return None
    return row["user_key"] if row else None


# ----------------------------------------------------------------------
# 상태·epoch
# ----------------------------------------------------------------------
def bump_epoch(user_key: str, *, set_status: Optional[str] = None,
               only_from: Tuple[str, ...] = ("pending_link", "active", "disabled")) -> int:
    """auth_epoch 를 1 올리고(필요하면 상태도 바꿔) 새 epoch 를 돌려준다. 대상 없으면 LookupError."""
    marks = ", ".join("?" for _ in only_from)
    with registry(create=True) as conn, Tx(conn):
        if set_status:
            cur = conn.execute(
                f"UPDATE users SET auth_epoch = auth_epoch + 1, status = ?, updated_at = ?"
                f" WHERE user_key = ? AND status IN ({marks})",
                (set_status, iso(utcnow()), user_key, *only_from),
            )
        else:
            cur = conn.execute(
                f"UPDATE users SET auth_epoch = auth_epoch + 1, updated_at = ?"
                f" WHERE user_key = ? AND status IN ({marks})",
                (iso(utcnow()), user_key, *only_from),
            )
        if cur.rowcount != 1:
            raise LookupError("user not found or status not eligible")
        return int(conn.execute("SELECT auth_epoch FROM users WHERE user_key = ?", (user_key,)).fetchone()[0])


def mark_graph_linked(user_key: str, graph_email: str, *, expected_epoch: int) -> int:
    """OAuth 연결 완료: active + graph_email, epoch+1. 시작 시점 epoch 와 다르면 LookupError."""
    with registry(create=True) as conn, Tx(conn):
        cur = conn.execute(
            "UPDATE users SET status = 'active', graph_email = ?, auth_epoch = auth_epoch + 1, updated_at = ?"
            " WHERE user_key = ? AND auth_epoch = ? AND status IN ('pending_link', 'active')",
            (graph_email, iso(utcnow()), user_key, expected_epoch),
        )
        if cur.rowcount != 1:
            raise LookupError("user state changed")
        return expected_epoch + 1


def mark_graph_unlinked(user_key: str) -> int:
    """Graph 연결 해제: active→pending_link, graph_email 제거, epoch+1."""
    with registry(create=True) as conn, Tx(conn):
        cur = conn.execute(
            "UPDATE users SET status = CASE WHEN status = 'active' THEN 'pending_link' ELSE status END,"
            " graph_email = NULL, auth_epoch = auth_epoch + 1, updated_at = ?"
            " WHERE user_key = ? AND status IN ('pending_link', 'active', 'disabled')",
            (iso(utcnow()), user_key),
        )
        if cur.rowcount != 1:
            raise LookupError("user not found or status not eligible")
        return int(conn.execute("SELECT auth_epoch FROM users WHERE user_key = ?", (user_key,)).fetchone()[0])


# ----------------------------------------------------------------------
# OAuth 위치 인덱스
# ----------------------------------------------------------------------
def index_ticket(ticket_hash: str, user_key: str, attempt_id: str, expires_at: str) -> None:
    with registry(create=True) as conn, Tx(conn):
        conn.execute(
            "INSERT INTO oauth_ticket_index (ticket_hash, user_key, attempt_id, expires_at) VALUES (?, ?, ?, ?)",
            (ticket_hash, user_key, attempt_id, expires_at),
        )


def take_ticket(ticket_hash: str) -> Optional[Tuple[str, str, str]]:
    """ticket 위치를 꺼내며 지운다(1회 소비). 없으면 None."""
    try:
        with registry() as conn, Tx(conn):
            row = conn.execute(
                "SELECT user_key, attempt_id, expires_at FROM oauth_ticket_index WHERE ticket_hash = ?",
                (ticket_hash,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM oauth_ticket_index WHERE ticket_hash = ?", (ticket_hash,))
            return row["user_key"], row["attempt_id"], row["expires_at"]
    except RegistryMissing:
        return None


def index_state(state_hash: str, user_key: str, attempt_id: str, expires_at: str) -> None:
    with registry(create=True) as conn, Tx(conn):
        conn.execute(
            "INSERT INTO oauth_state_index (state_hash, user_key, attempt_id, expires_at) VALUES (?, ?, ?, ?)",
            (state_hash, user_key, attempt_id, expires_at),
        )


def lookup_state(state_hash: str) -> Optional[Tuple[str, str, str]]:
    try:
        with registry() as conn:
            row = conn.execute(
                "SELECT user_key, attempt_id, expires_at FROM oauth_state_index WHERE state_hash = ?",
                (state_hash,),
            ).fetchone()
    except RegistryMissing:
        return None
    return (row["user_key"], row["attempt_id"], row["expires_at"]) if row else None


def drop_state(state_hash: str) -> None:
    try:
        with registry() as conn, Tx(conn):
            conn.execute("DELETE FROM oauth_state_index WHERE state_hash = ?", (state_hash,))
    except RegistryMissing:
        pass


def drop_attempt_indexes(user_key: str, attempt_id: str) -> None:
    try:
        with registry() as conn, Tx(conn):
            conn.execute("DELETE FROM oauth_state_index WHERE user_key = ? AND attempt_id = ?", (user_key, attempt_id))
            conn.execute("DELETE FROM oauth_ticket_index WHERE user_key = ? AND attempt_id = ?", (user_key, attempt_id))
    except RegistryMissing:
        pass


def prune_indexes() -> None:
    now = iso(utcnow())
    try:
        with registry() as conn, Tx(conn):
            conn.execute("DELETE FROM oauth_state_index WHERE expires_at < ?", (now,))
            conn.execute("DELETE FROM oauth_ticket_index WHERE expires_at < ?", (now,))
    except RegistryMissing:
        pass


__all__ = [
    "key_digest",
    "USER_STATUSES",
    "USABLE_STATUSES",
    "RegistryMissing",
    "UserRecord",
    "registry",
    "registry_path",
    "ensure_registry",
    "get_user",
    "all_users",
    "user_for_kid",
    "bump_epoch",
    "mark_graph_linked",
    "mark_graph_unlinked",
    "index_ticket",
    "take_ticket",
    "index_state",
    "lookup_state",
    "drop_state",
    "drop_attempt_indexes",
    "prune_indexes",
]
