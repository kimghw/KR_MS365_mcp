"""
멀티유저 인증 계층(WP2) 공용 헬퍼 — 시각·인코딩·SQLite 연결·배포 ID 캐시.

이 모듈은 session 패키지 내부 전용이다(밑줄 접두). 외부 WP 는 공개 모듈
(`identity_registry`, `token_store`, `graph_connect`, `mcp_common.auth`)만 쓴다.

- 시각은 전부 UTC ISO 8601(`+00:00`) 문자열로 저장하고 Python 에서 비교한다.
- SQLite 는 요청마다 짧게 열고 닫는다(프로세스 간 공유 핸들 없음). WAL·busy_timeout·
  secure_delete 를 켠다 — 삭제된 ciphertext 페이지를 0 으로 덮게 한다.
- `open_db(..., create=False)` 는 파일이 없으면 만들지 않는다(`mode=rw`). 사용자 저장소가
  없을 때 빈 DB 를 새로 만들어 "정상"처럼 보이게 하지 않는다(②-1.1 불변조건 6).
"""

import base64
import hashlib
import os
import sqlite3
import struct
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Union

BytesLike = Union[bytes, bytearray, memoryview]

_SQLITE_TIMEOUT_SECONDS = 15.0


# ----------------------------------------------------------------------
# 시각
# ----------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso_in(seconds: float) -> str:
    return iso(utcnow() + timedelta(seconds=seconds))


# ----------------------------------------------------------------------
# 인코딩
# ----------------------------------------------------------------------
def b64e(data: BytesLike) -> str:
    return base64.b64encode(bytes(data)).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def b64url_nopad(data: BytesLike) -> str:
    return base64.urlsafe_b64encode(bytes(data)).rstrip(b"=").decode("ascii")


def length_delimited(*parts: Union[str, bytes, int]) -> bytes:
    """길이가 명확한 결합 — 각 조각 앞에 4바이트 big-endian 길이를 붙인다.

    `("ab", "c")` 와 `("a", "bc")` 가 같은 바이트열이 되지 않게 하는 것이 목적이다
    (digest·AAD 의 도메인 분리).
    """
    out = bytearray()
    for part in parts:
        if isinstance(part, int):
            raw = str(part).encode("ascii")
        elif isinstance(part, str):
            raw = part.encode("utf-8")
        else:
            raw = bytes(part)
        out += struct.pack(">I", len(raw))
        out += raw
    return bytes(out)


def sha256_hex(value: Union[str, bytes]) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------------
# 배포 ID (데이터 루트별 캐시)
# ----------------------------------------------------------------------
_dep_cache: Dict[str, str] = {}
_dep_lock = threading.Lock()


def current_root() -> Path:
    from mcp_common.security_policy import data_root

    return data_root()


def deployment_id_for(root: Optional[Path] = None) -> str:
    """`deployment.json` 의 배포 ID. 매 요청 파일을 읽지 않도록 루트별로 캐시한다."""
    from mcp_common.security_policy import ensure_deployment

    root = root or current_root()
    key = str(root)
    with _dep_lock:
        cached = _dep_cache.get(key)
    if cached:
        return cached
    value = ensure_deployment(root)["deployment_id"]
    with _dep_lock:
        _dep_cache[key] = value
    return value


# ----------------------------------------------------------------------
# SQLite
# ----------------------------------------------------------------------
def open_db(path: Path, *, create: bool) -> sqlite3.Connection:
    """짧게 쓰는 연결. autocommit(`isolation_level=None`) — 쓰기는 `BEGIN IMMEDIATE` 로 감싼다."""
    path = Path(path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=_SQLITE_TIMEOUT_SECONDS, isolation_level=None)
    else:
        if not path.is_file():
            raise FileNotFoundError("database not found")
        uri = path.resolve().as_uri() + "?mode=rw"
        conn = sqlite3.connect(uri, uri=True, timeout=_SQLITE_TIMEOUT_SECONDS, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(_SQLITE_TIMEOUT_SECONDS * 1000)}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA secure_delete = ON")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class Tx:
    """`with Tx(conn):` — BEGIN IMMEDIATE … COMMIT/ROLLBACK."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")


def executescript_tx(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    with Tx(conn):
        for stmt in statements:
            conn.execute(stmt)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """같은 디렉터리의 임시파일에 쓰고 fsync 후 `os.replace` 로 교체한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise


__all__ = [
    "utcnow",
    "iso",
    "parse_iso",
    "iso_in",
    "b64e",
    "b64d",
    "b64url_nopad",
    "length_delimited",
    "sha256_hex",
    "current_root",
    "deployment_id_for",
    "open_db",
    "Tx",
    "executescript_tx",
    "atomic_write_bytes",
]
