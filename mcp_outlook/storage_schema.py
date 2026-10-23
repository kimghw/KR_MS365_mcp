"""
Outlook 사용자별 저장소 — `db/outlook.db` (spec/spec_멀티유저.md ②-7.3, WP4).

mode 1 에서 "처리 완료 메일·첨부" 메타데이터를 공용 `mail_metadata.json`(message_id 키,
전체 덮어쓰기) 대신 사용자 DB 에 둔다. mode 0 은 기존 JSON(`MailMetadataManager`)을 그대로 쓴다.

| 테이블 | 키 | 내용 |
|------|------|------|
| `schema_meta` | `key` | `schema_version` |
| `processed_messages` | `(owner_key, message_id)` | 제목·발신자·수신시각·폴더·첨부 수·처리 시각 |
| `processed_files` | `(owner_key, message_id, seq)` | 저장 파일 참조(`files/` 기준 상대경로 또는 OneDrive URL) |

- 모든 테이블에 `owner_key`(= user_key) 를 두고 **모든 SQL 에 owner 조건**을 건다. DB 파일이
  이미 사용자별이어도 생략하지 않는다(②-7.3).
- 쓰기는 `BEGIN IMMEDIATE` 트랜잭션 1건 — 같은 사용자의 동시 요청도 lost update 가 없다.
- 요청에 principal 이 묶여 있으면 그 user_key 와 저장소 owner 가 같아야 한다(아니면 `not_found`).
- 경로는 `UserPaths.outlook_db` 로만 정한다. `ensure_storage()` 는 그 사용자 저장소만
  초기화하고 Graph 호출·기본 사용자 탐색을 하지 않는다(②-11.1).
"""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from mcp_common.principal import Principal, current_principal
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.user_paths import UserPaths

SCHEMA_VERSION = 1

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processed_messages (
        owner_key         TEXT NOT NULL,
        message_id        TEXT NOT NULL,
        subject           TEXT NOT NULL DEFAULT '',
        from_address      TEXT NOT NULL DEFAULT '',
        received_datetime TEXT NOT NULL DEFAULT '',
        folder_path       TEXT NOT NULL DEFAULT '',
        attachment_count  INTEGER NOT NULL DEFAULT 0,
        processed_at      TEXT NOT NULL,
        PRIMARY KEY (owner_key, message_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processed_files (
        owner_key  TEXT NOT NULL,
        message_id TEXT NOT NULL,
        seq        INTEGER NOT NULL,
        file_ref   TEXT NOT NULL,
        PRIMARY KEY (owner_key, message_id, seq),
        FOREIGN KEY (owner_key, message_id)
            REFERENCES processed_messages (owner_key, message_id) ON DELETE CASCADE
    )
    """,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def ensure_outlook_db(paths: UserPaths) -> Path:
    """`paths.outlook_db` 스키마를 만든다(멱등). 디렉터리는 사용자 `db/` 만."""
    db_path = Path(paths.outlook_db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db_path)) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _DDL:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO NOTHING",
                (str(SCHEMA_VERSION),),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return db_path


def ensure_storage(principal: Principal, paths: UserPaths) -> None:
    """WP11 이전 도구·서비스 공용 진입점(②-11.1). 다른 사용자의 경로는 거부한다."""
    if not isinstance(principal, Principal) or principal.user_key != paths.user_key:
        raise SecurityError(ErrorCode.NOT_FOUND)
    ensure_outlook_db(paths)


class OutlookMetadataStore:
    """`MailMetadataManager` 와 같은 인터페이스의 사용자별 SQLite 구현."""

    def __init__(self, db_path: Path, owner_key: str):
        if not owner_key:
            raise ValueError("owner_key 가 필요합니다")
        self.db_path = Path(db_path)
        self.owner_key = owner_key

    @classmethod
    def for_paths(cls, paths: UserPaths) -> "OutlookMetadataStore":
        return cls(paths.outlook_db, paths.user_key)

    # ------------------------------------------------------------------
    def _check_owner(self) -> None:
        principal = current_principal()
        if principal is not None and principal.user_key != self.owner_key:
            raise SecurityError(ErrorCode.NOT_FOUND)

    def _conn(self) -> sqlite3.Connection:
        self._check_owner()
        return _connect(self.db_path)

    # ------------------------------------------------------------------
    def is_duplicate(self, message_id: str) -> bool:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_messages WHERE owner_key = ? AND message_id = ?",
                (self.owner_key, message_id),
            ).fetchone()
        return row is not None

    def filter_new_messages(self, message_ids: Iterable[str]) -> List[str]:
        ids = list(message_ids)
        if not ids:
            return []
        with closing(self._conn()) as conn:
            seen = set()
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                marks = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT message_id FROM processed_messages "
                    f"WHERE owner_key = ? AND message_id IN ({marks})",
                    (self.owner_key, *chunk),
                ).fetchall()
                seen.update(r[0] for r in rows)
        return [mid for mid in ids if mid not in seen]

    def add_processed_mail(
        self,
        message_id: str,
        mail_data: Dict[str, Any],
        folder_path: str,
        saved_files: List[str],
    ) -> None:
        sender = (mail_data.get("from") or {}).get("emailAddress", {}).get("address", "") or ""
        values = (
            self.owner_key,
            message_id,
            str(mail_data.get("subject") or ""),
            str(sender),
            str(mail_data.get("receivedDateTime") or ""),
            str(folder_path or ""),
            len(mail_data.get("attachments") or []),
            datetime.now().isoformat(),
        )
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO processed_messages (owner_key, message_id, subject, from_address,
                        received_datetime, folder_path, attachment_count, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(owner_key, message_id) DO UPDATE SET
                        subject = excluded.subject,
                        from_address = excluded.from_address,
                        received_datetime = excluded.received_datetime,
                        folder_path = excluded.folder_path,
                        attachment_count = excluded.attachment_count,
                        processed_at = excluded.processed_at
                    """,
                    values,
                )
                conn.execute(
                    "DELETE FROM processed_files WHERE owner_key = ? AND message_id = ?",
                    (self.owner_key, message_id),
                )
                conn.executemany(
                    "INSERT INTO processed_files (owner_key, message_id, seq, file_ref) VALUES (?, ?, ?, ?)",
                    [(self.owner_key, message_id, i, str(ref)) for i, ref in enumerate(saved_files or [])],
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def get_processed_count(self) -> int:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM processed_messages WHERE owner_key = ?", (self.owner_key,)
            ).fetchone()
        return int(row[0]) if row else 0

    def get_processed_message_ids(self) -> List[str]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT message_id FROM processed_messages WHERE owner_key = ? ORDER BY processed_at",
                (self.owner_key,),
            ).fetchall()
        return [r[0] for r in rows]

    def get_processed_mail(self, message_id: str) -> Optional[Dict[str, Any]]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT subject, from_address, received_datetime, folder_path, attachment_count, processed_at "
                "FROM processed_messages WHERE owner_key = ? AND message_id = ?",
                (self.owner_key, message_id),
            ).fetchone()
            if row is None:
                return None
            files = conn.execute(
                "SELECT file_ref FROM processed_files WHERE owner_key = ? AND message_id = ? ORDER BY seq",
                (self.owner_key, message_id),
            ).fetchall()
        return {
            "subject": row[0],
            "from": row[1],
            "received_datetime": row[2],
            "folder_path": row[3],
            "attachment_count": row[4],
            "processed_at": row[5],
            "saved_files": [f[0] for f in files],
        }


__all__ = [
    "SCHEMA_VERSION",
    "ensure_outlook_db",
    "ensure_storage",
    "OutlookMetadataStore",
]
