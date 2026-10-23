"""
사용자별 인증 DB — `<data_root>/users/<user_key>/auth/auth.db` (spec/spec_멀티유저.md ②-6.1).

| 테이블 | 내용 |
|--------|------|
| `store_owner` | 이 DB 의 소유자 `(user_key, tenant_id, object_id)` 와 스키마 버전 — 단일 행 |
| `graph_tokens` | 앱별 Graph 토큰 묶음(access/refresh/id)의 **ciphertext** + nonce·버전·만료·scope |
| `api_credentials` | bearer key 의 digest·scope·만료·폐기 (원문 키 없음) |
| `oauth_attempts` | 연결 시도: state/ticket/브라우저 바인딩/nonce 는 해시, PKCE verifier 는 암호화 |

- 열 때마다 `store_owner` 가 기대한 principal 과 같은지 확인한다 — 파일이 사용자 디렉터리
  안에 있다는 사실만으로 소유권을 믿지 않는다. 불일치·누락은 `StoreOwnerMismatch`.
- `create=False` 로 열면 DB 파일이 없을 때 새로 만들지 않는다(`StoreMissing`).
- 이 모듈은 평문 토큰을 SQL 에 넘기지 않는다. 암호화는 `user_crypto` 가 먼저 한다.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from mcp_common.principal import is_valid_user_key
from mcp_common.user_paths import UserPaths, paths_for

from ._mu_common import Tx, executescript_tx, iso, open_db, utcnow

logger = logging.getLogger(__name__)

STORE_SCHEMA_VERSION = 1

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS store_owner (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        user_key TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        object_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS graph_tokens (
        app_id TEXT PRIMARY KEY,
        token_version INTEGER NOT NULL,
        ciphertext BLOB NOT NULL,
        nonce BLOB NOT NULL,
        dek_version INTEGER NOT NULL,
        expires_at TEXT,
        scope TEXT,
        state TEXT NOT NULL DEFAULT 'ok' CHECK (state IN ('ok', 'reauth_required')),
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS api_credentials (
        kid TEXT PRIMARY KEY,
        digest TEXT NOT NULL,
        scopes TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_attempts (
        attempt_id TEXT PRIMARY KEY,
        status TEXT NOT NULL CHECK (status IN
            ('created', 'pending', 'redeeming', 'completed', 'failed', 'expired', 'superseded')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        ticket_hash TEXT,
        ticket_expires_at TEXT,
        state_hash TEXT,
        browser_binding_hash TEXT,
        nonce_hash TEXT,
        verifier_ciphertext BLOB,
        verifier_nonce BLOB,
        dek_version INTEGER,
        expected_tenant_id TEXT NOT NULL,
        expected_object_id TEXT NOT NULL,
        auth_epoch INTEGER NOT NULL,
        credential_id TEXT,
        error_code TEXT
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_attempt_state ON oauth_attempts(state_hash) WHERE state_hash IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_attempt_ticket ON oauth_attempts(ticket_hash) WHERE ticket_hash IS NOT NULL",
)

ACTIVE_ATTEMPT_STATUSES = ("created", "pending", "redeeming")

_ATTEMPT_COLUMNS = frozenset({
    "attempt_id", "status", "created_at", "updated_at", "expires_at", "ticket_hash", "ticket_expires_at",
    "state_hash", "browser_binding_hash", "nonce_hash", "verifier_ciphertext", "verifier_nonce", "dek_version",
    "expected_tenant_id", "expected_object_id", "auth_epoch", "credential_id", "error_code",
})


def _check_columns(names) -> None:
    unknown = set(names) - _ATTEMPT_COLUMNS
    if unknown:
        raise ValueError("unknown oauth_attempts column")


class StoreMissing(Exception):
    """사용자 인증 DB 가 없다."""


class StoreOwnerMismatch(Exception):
    """사용자 인증 DB 의 소유자 기록이 기대한 principal 과 다르다(복사·손상)."""


@dataclass(frozen=True)
class TokenRow:
    app_id: str
    token_version: int
    ciphertext: bytes
    nonce: bytes
    dek_version: int
    expires_at: Optional[str]
    scope: Optional[str]
    state: str


class UserAuthStore:
    """한 사용자의 auth.db. 인스턴스는 가볍다 — 메서드마다 연결을 열고 닫는다."""

    def __init__(self, user_key: str, tenant_id: str, object_id: str, *, root: Optional[Path] = None):
        if not is_valid_user_key(user_key):
            raise ValueError("user_key invalid")
        self.user_key = user_key
        self.tenant_id = tenant_id.lower()
        self.object_id = object_id.lower()
        self.root = root
        self.paths: UserPaths = paths_for(user_key, root=root)

    # ------------------------------------------------------------------
    # 연결·소유자
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """DB·스키마·소유자 행을 만든다(사용자 등록 시 1회). 이미 있으면 소유자만 검증한다."""
        conn = open_db(self.paths.auth_db, create=True)
        try:
            executescript_tx(conn, _SCHEMA)
            with Tx(conn):
                row = conn.execute("SELECT * FROM store_owner WHERE singleton = 1").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO store_owner (singleton, user_key, tenant_id, object_id, schema_version,"
                        " created_at) VALUES (1, ?, ?, ?, ?, ?)",
                        (self.user_key, self.tenant_id, self.object_id, STORE_SCHEMA_VERSION, iso(utcnow())),
                    )
                else:
                    self._check_owner_row(row)
        finally:
            conn.close()

    def _check_owner_row(self, row: Optional[sqlite3.Row]) -> None:
        if (
            row is None
            or row["user_key"] != self.user_key
            or row["tenant_id"] != self.tenant_id
            or row["object_id"] != self.object_id
        ):
            raise StoreOwnerMismatch("store owner mismatch")
        if int(row["schema_version"]) > STORE_SCHEMA_VERSION:
            raise StoreOwnerMismatch("store schema newer than code")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        try:
            conn = open_db(self.paths.auth_db, create=False)
        except (FileNotFoundError, sqlite3.OperationalError) as exc:
            raise StoreMissing("user auth store missing") from exc
        try:
            try:
                row = conn.execute("SELECT * FROM store_owner WHERE singleton = 1").fetchone()
            except sqlite3.DatabaseError as exc:
                raise StoreOwnerMismatch("store unreadable") from exc
            self._check_owner_row(row)
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # graph_tokens
    # ------------------------------------------------------------------
    @staticmethod
    def _token_row(row: Optional[sqlite3.Row]) -> Optional[TokenRow]:
        if row is None:
            return None
        return TokenRow(
            app_id=row["app_id"],
            token_version=int(row["token_version"]),
            ciphertext=bytes(row["ciphertext"]),
            nonce=bytes(row["nonce"]),
            dek_version=int(row["dek_version"]),
            expires_at=row["expires_at"],
            scope=row["scope"],
            state=row["state"],
        )

    def get_token_row(self, app_id: str) -> Optional[TokenRow]:
        with self.connect() as conn:
            return self._token_row(conn.execute("SELECT * FROM graph_tokens WHERE app_id = ?", (app_id,)).fetchone())

    def token_version(self, app_id: str) -> int:
        row = self.get_token_row(app_id)
        return row.token_version if row else 0

    def replace_tokens_if_version(
        self,
        app_id: str,
        *,
        expected_version: int,
        new_version: int,
        ciphertext: bytes,
        nonce: bytes,
        dek_version: int,
        expires_at: Optional[str],
        scope: Optional[str],
    ) -> bool:
        """버전 조건부 저장. expected_version=0 이면 행이 없을 때만 INSERT. 성공 여부 반환."""
        now = iso(utcnow())
        with self.connect() as conn, Tx(conn):
            if expected_version == 0:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO graph_tokens (app_id, token_version, ciphertext, nonce, dek_version,"
                    " expires_at, scope, state, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'ok', ?)",
                    (app_id, new_version, ciphertext, nonce, dek_version, expires_at, scope, now),
                )
            else:
                cur = conn.execute(
                    "UPDATE graph_tokens SET token_version = ?, ciphertext = ?, nonce = ?, dek_version = ?,"
                    " expires_at = ?, scope = ?, state = 'ok', updated_at = ?"
                    " WHERE app_id = ? AND token_version = ?",
                    (new_version, ciphertext, nonce, dek_version, expires_at, scope, now, app_id, expected_version),
                )
            return cur.rowcount == 1

    def mark_reauth_required(self, app_id: str, *, expected_version: int) -> None:
        with self.connect() as conn, Tx(conn):
            conn.execute(
                "UPDATE graph_tokens SET state = 'reauth_required', updated_at = ?"
                " WHERE app_id = ? AND token_version = ?",
                (iso(utcnow()), app_id, expected_version),
            )

    def delete_tokens(self, app_id: Optional[str] = None) -> int:
        with self.connect() as conn, Tx(conn):
            if app_id is None:
                cur = conn.execute("DELETE FROM graph_tokens")
            else:
                cur = conn.execute("DELETE FROM graph_tokens WHERE app_id = ?", (app_id,))
            return cur.rowcount

    def delete_tokens_if_version(self, app_id: str, version: int) -> bool:
        """`token_version == version` 일 때만 지우는 단일 조건부 DELETE (되돌림용 — 새 버전을 지우지 않는다)."""
        with self.connect() as conn, Tx(conn):
            cur = conn.execute("DELETE FROM graph_tokens WHERE app_id = ? AND token_version = ?", (app_id, version))
            return cur.rowcount == 1

    def token_app_ids(self) -> List[str]:
        with self.connect() as conn:
            return [r["app_id"] for r in conn.execute("SELECT app_id FROM graph_tokens")]

    # ------------------------------------------------------------------
    # api_credentials
    # ------------------------------------------------------------------
    def add_credential(self, kid: str, digest: str, scopes: List[str], expires_at: str) -> None:
        with self.connect() as conn, Tx(conn):
            conn.execute(
                "INSERT INTO api_credentials (kid, digest, scopes, expires_at, revoked_at, created_at)"
                " VALUES (?, ?, ?, ?, NULL, ?)",
                (kid, digest, json.dumps(sorted(scopes)), expires_at, iso(utcnow())),
            )

    def get_credential(self, kid: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM api_credentials WHERE kid = ?", (kid,)).fetchone()
        return self._cred(row) if row else None

    @staticmethod
    def _cred(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "kid": row["kid"],
            "digest": row["digest"],
            "scopes": frozenset(json.loads(row["scopes"])),
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "created_at": row["created_at"],
        }

    def list_credentials(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM api_credentials ORDER BY created_at").fetchall()
        return [self._cred(r) for r in rows]

    def revoke_credential(self, kid: str) -> bool:
        with self.connect() as conn, Tx(conn):
            cur = conn.execute(
                "UPDATE api_credentials SET revoked_at = ? WHERE kid = ? AND revoked_at IS NULL",
                (iso(utcnow()), kid),
            )
            return cur.rowcount == 1

    def shorten_credential(self, kid: str, expires_at: str) -> None:
        with self.connect() as conn, Tx(conn):
            conn.execute(
                "UPDATE api_credentials SET expires_at = MIN(expires_at, ?) WHERE kid = ? AND revoked_at IS NULL",
                (expires_at, kid),
            )

    def revoke_all_credentials(self) -> int:
        with self.connect() as conn, Tx(conn):
            cur = conn.execute("UPDATE api_credentials SET revoked_at = ? WHERE revoked_at IS NULL", (iso(utcnow()),))
            return cur.rowcount

    # ------------------------------------------------------------------
    # oauth_attempts — 상태 전환은 전부 "기대 상태" 조건부 UPDATE (원자적)
    # ------------------------------------------------------------------
    def insert_attempt(self, values: Dict[str, Any]) -> None:
        _check_columns(values)
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self.connect() as conn, Tx(conn):
            conn.execute(f"INSERT INTO oauth_attempts ({cols}) VALUES ({marks})", tuple(values.values()))

    def get_attempt(self, attempt_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM oauth_attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        return dict(row) if row else None

    def transition_attempt(self, attempt_id: str, *, from_status: str, to_status: str,
                           match: Optional[Dict[str, Any]] = None, **updates: Any) -> bool:
        """`status = from_status` (및 match 열 일치)일 때만 바꾼다. 성공 여부 반환."""
        sets = {"status": to_status, "updated_at": iso(utcnow()), **updates}
        _check_columns(sets)
        _check_columns(match or {})
        set_sql = ", ".join(f"{k} = ?" for k in sets)
        where = "attempt_id = ? AND status = ?"
        params: List[Any] = list(sets.values()) + [attempt_id, from_status]
        for key, value in (match or {}).items():
            where += f" AND {key} = ?"
            params.append(value)
        with self.connect() as conn, Tx(conn):
            cur = conn.execute(f"UPDATE oauth_attempts SET {set_sql} WHERE {where}", params)
            return cur.rowcount == 1

    def fail_attempt(self, attempt_id: str, error_code: str, *, from_statuses=ACTIVE_ATTEMPT_STATUSES,
                     to_status: str = "failed") -> bool:
        marks = ", ".join("?" for _ in from_statuses)
        with self.connect() as conn, Tx(conn):
            cur = conn.execute(
                f"UPDATE oauth_attempts SET status = ?, error_code = ?, updated_at = ?,"
                f" verifier_ciphertext = NULL, verifier_nonce = NULL, ticket_hash = NULL"
                f" WHERE attempt_id = ? AND status IN ({marks})",
                (to_status, error_code, iso(utcnow()), attempt_id, *from_statuses),
            )
            return cur.rowcount == 1

    def active_attempts(self) -> List[Dict[str, Any]]:
        marks = ", ".join("?" for _ in ACTIVE_ATTEMPT_STATUSES)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM oauth_attempts WHERE status IN ({marks}) ORDER BY created_at, rowid",
                ACTIVE_ATTEMPT_STATUSES,
            ).fetchall()
        return [dict(r) for r in rows]

    def prune_attempts(self, *, older_than: str) -> int:
        """끝난 시도 중 오래된 행 삭제 (조회용 보존 기간 경과)."""
        marks = ", ".join("?" for _ in ACTIVE_ATTEMPT_STATUSES)
        with self.connect() as conn, Tx(conn):
            cur = conn.execute(
                f"DELETE FROM oauth_attempts WHERE status NOT IN ({marks}) AND updated_at < ?",
                (*ACTIVE_ATTEMPT_STATUSES, older_than),
            )
            return cur.rowcount

    def delete_all_attempts(self) -> int:
        with self.connect() as conn, Tx(conn):
            return conn.execute("DELETE FROM oauth_attempts").rowcount


__all__ = [
    "STORE_SCHEMA_VERSION",
    "ACTIVE_ATTEMPT_STATUSES",
    "StoreMissing",
    "StoreOwnerMismatch",
    "TokenRow",
    "UserAuthStore",
]
