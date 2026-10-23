"""
legacy(mode 0) 원본 — 위치·교차 사용 검사·snapshot·읽기.

| 이름표 | 기본 위치 (`--legacy-root` 기준) | 형식 |
|--------|------|------|
| `auth_db` | `database/auth.db` | SQLite — `teams_chats` 만 이전, 토큰·앱 설정은 snapshot 에도 넣지 않는다 |
| `onenote_db` | `database/onenote.db` | SQLite — owner_key 이전 전/후 스키마 모두 읽는다 |
| `metadata_db` | `metadata.db` | SQLite `metadata` 테이블 (FileHandler mode 0) |
| `metadata_json` | `metadata.json` | FileHandler JSONStorage |
| `mail_metadata` | `downloads/mail_metadata.json` | Outlook `MailMetadataManager` |
| `downloads` / `output` | `downloads/` / `output/` | 파일 트리 |

## 교차 사용 거부 (②-8.1, M03)

- legacy 원본이 멀티유저 데이터 루트 안에 있으면 거부 (사용자 DB 를 legacy 원본으로 오인 금지)
- 데이터 루트가 legacy 원본 디렉터리(`database/`·`downloads/`·`output/`) 안이거나 legacy 루트 자체면 거부
- legacy 루트에 멀티유저 deployment marker 가 있으면 거부

## snapshot

실행 중 파일·WAL 을 그대로 복사하지 않고 **SQLite backup API** 로 일관된 사본을 만든다(②-8.4).
`auth.db` 는 메모리로 backup 한 뒤 `teams_chats` 와 `azure_user_info(user_email, object_id)` 만
디스크 snapshot 에 옮긴다 — 토큰·client secret 은 데이터 루트 어디에도 쓰지 않는다.
"""

import os
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 경로 성분 판정은 secure_files 와 같은 기준을 쓴다(두 벌 두지 않는다) — 복사 시 ensure_within 이
# 거부할 이름을 plan 단계에서 미리 unsafe_name 으로 격리한다.
from mcp_common.secure_files import _component_problem

from .common import FILE_SOURCES, LOCK_NAME, Layout, MigrationError, is_within, norm, sha256_file

SQLITE_SOURCES = ("auth_db", "onenote_db", "metadata_db")
JSON_SOURCES = ("metadata_json", "mail_metadata")

DEFAULTS = {
    "auth_db": ("database", "auth.db"),
    "onenote_db": ("database", "onenote.db"),
    "metadata_db": ("metadata.db",),
    "metadata_json": ("metadata.json",),
    "mail_metadata": ("downloads", "mail_metadata.json"),
    "downloads": ("downloads",),
    "output": ("output",),
}

#: auth.db 에서 snapshot 으로 옮기는 것 (나머지는 행 수만 센다)
AUTH_KEEP_TABLES = ("teams_chats",)
AUTH_COUNT_ONLY = ("azure_token_info", "azure_app_config", "azure_user_info")

#: 파일 트리에서 사용자에게 배정하지 않고 관리자 격리로 보내는 이름 (로그·DB·백업·비밀)
_ADMIN_SUFFIXES = (
    ".log", ".db", ".sqlite", ".sqlite3", "-wal", "-shm", "-journal", ".bak", ".backup",
    ".pem", ".pfx", ".p12", ".key", ".jsonl", ".pid",
)
_ADMIN_DIRS = {"logs", "backups"}
#: 이전 대상이 아닌 산출물 디렉터리 — 복사·격리하지 않고 기록만 한다
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".mcp_pids", ".pytest_cache"}
#: 원본 최상위에서만 건너뛰는 디렉터리 (`output/bundles` = export_ms365 번들 산출물)
_SKIP_TOP_DIRS = {"output": {"bundles"}}


@dataclass(frozen=True)
class Sources:
    legacy_root: Path
    auth_db: Path
    onenote_db: Path
    metadata_db: Path
    metadata_json: Path
    mail_metadata: Path
    downloads: Path
    output: Path

    def as_dict(self) -> Dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}

    def path(self, name: str) -> Path:
        return getattr(self, name)


def resolve_sources(legacy_root: Path, overrides: Optional[Dict[str, Optional[str]]] = None) -> Sources:
    root = Path(legacy_root).resolve()
    values: Dict[str, Path] = {}
    for name, parts in DEFAULTS.items():
        override = (overrides or {}).get(name)
        values[name] = Path(override).resolve() if override else root.joinpath(*parts)
    return Sources(legacy_root=root, **values)


def sources_from_manifest(raw: Dict[str, str]) -> Sources:
    return Sources(**{k: Path(v) for k, v in raw.items()})


def check_cross_use(sources: Sources, layout: Layout) -> None:
    """mode 0/1 저장소를 섞어 쓰는 구성을 거부한다 (M03)."""
    data_root = layout.data_root
    for name in DEFAULTS:
        if is_within(sources.path(name), data_root):
            raise MigrationError("cross_use", f"legacy 원본 {name} 이 멀티유저 데이터 루트 안에 있습니다.")
    if is_within(sources.legacy_root, data_root):
        raise MigrationError("cross_use", "legacy 루트가 멀티유저 데이터 루트 안에 있습니다.")
    if norm(data_root) == norm(sources.legacy_root):
        raise MigrationError("cross_use", "멀티유저 데이터 루트를 legacy 루트와 같은 곳에 둘 수 없습니다.")
    for name in ("downloads", "output"):
        if is_within(data_root, sources.path(name)):
            raise MigrationError("cross_use", f"멀티유저 데이터 루트가 legacy {name} 디렉터리 안에 있습니다.")
    if is_within(data_root, sources.auth_db.parent) or is_within(data_root, sources.onenote_db.parent):
        raise MigrationError("cross_use", "멀티유저 데이터 루트가 legacy database 디렉터리 안에 있습니다.")
    from mcp_common.security_policy import is_multi_user_data_root

    if is_multi_user_data_root(sources.legacy_root):
        raise MigrationError("cross_use", "legacy 루트가 멀티유저 데이터 루트(deployment marker)입니다.")


# ----------------------------------------------------------------------
# fingerprint (원본이 plan 이후 바뀌었는지)
# ----------------------------------------------------------------------
def fingerprint(path: Path) -> Optional[str]:
    """파일(+ SQLite `-wal`) 의 sha256. 없으면 None."""
    path = Path(path)
    if not path.is_file():
        return None
    value = sha256_file(path)
    wal = Path(str(path) + "-wal")
    if wal.is_file() and wal.stat().st_size:
        value = value + ":" + sha256_file(wal)
    return value


# ----------------------------------------------------------------------
# SQLite snapshot
# ----------------------------------------------------------------------
def _open_source(path: Path) -> sqlite3.Connection:
    """원본을 읽기 전용으로 연다. WAL 이라 ro 가 실패하면 일반 연결(읽기만 한다)."""
    try:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.Error:
        return sqlite3.connect(os.fspath(path), timeout=30)


def snapshot_sqlite(src: Path, dst: Path) -> None:
    """SQLite backup API 로 일관된 사본을 만든다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    with closing(_open_source(src)) as source, closing(sqlite3.connect(os.fspath(dst))) as target:
        source.backup(target)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def snapshot_auth_db(src: Path, dst: Path) -> Dict[str, int]:
    """auth.db → 메모리 backup → 비밀 없는 테이블만 디스크 snapshot. 테이블별 행 수를 돌려준다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    counts: Dict[str, int] = {}
    with closing(_open_source(src)) as source, closing(sqlite3.connect(":memory:")) as memory:
        source.backup(memory)
        tables = {r[0] for r in memory.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in AUTH_COUNT_ONLY + AUTH_KEEP_TABLES:
            if table in tables:
                counts[table] = int(memory.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])
        with closing(sqlite3.connect(os.fspath(dst))) as target:
            for table in AUTH_KEEP_TABLES:
                if table not in tables:
                    continue
                ddl = memory.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                target.execute(ddl)
                cols = [r[1] for r in memory.execute(f"PRAGMA table_info({_quote(table)})")]
                col_sql = ", ".join(_quote(c) for c in cols)
                marks = ", ".join("?" for _ in cols)
                rows = memory.execute(f"SELECT rowid, {col_sql} FROM {_quote(table)}").fetchall()
                target.executemany(
                    f"INSERT INTO {_quote(table)} (rowid, {col_sql}) VALUES (?, {marks})", rows
                )
            if "azure_user_info" in tables:
                cols = {r[1] for r in memory.execute("PRAGMA table_info(azure_user_info)")}
                target.execute("CREATE TABLE legacy_users (user_email TEXT, object_id TEXT)")
                if {"user_email", "object_id"} <= cols:
                    target.executemany(
                        "INSERT INTO legacy_users VALUES (?, ?)",
                        memory.execute("SELECT user_email, object_id FROM azure_user_info").fetchall(),
                    )
            target.commit()
    return counts


# ----------------------------------------------------------------------
# 읽기
# ----------------------------------------------------------------------
def table_names(db: Path) -> List[str]:
    with closing(sqlite3.connect(os.fspath(db))) as conn:
        return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def read_table(db: Optional[Path], table: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """(열 이름, 행 목록). 행에는 `_rowid` 가 붙는다. DB·테이블이 없으면 빈 결과."""
    if db is None or not Path(db).is_file():
        return [], []
    with closing(sqlite3.connect(os.fspath(db))) as conn:
        if table not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            return [], []
        conn.row_factory = sqlite3.Row
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_quote(table)})")]
        rows = []
        for row in conn.execute(f"SELECT rowid AS _rowid, * FROM {_quote(table)} ORDER BY rowid"):
            item = dict(row)
            rows.append(item)
        return cols, rows


def read_legacy_users(auth_snapshot: Optional[Path]) -> List[Tuple[str, Optional[str]]]:
    _cols, rows = read_table(auth_snapshot, "legacy_users")
    return [(r.get("user_email"), r.get("object_id")) for r in rows]


def read_json_source(path: Path) -> Optional[Any]:
    import json

    if not Path(path).is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (UnicodeDecodeError, ValueError):
        raise MigrationError("source_invalid", f"{Path(path).name} 을 JSON 으로 읽을 수 없습니다.") from None


# ----------------------------------------------------------------------
# 파일 트리
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class FileEntry:
    source: str
    rel: str            # posix, 원본 표기
    kind: str           # file | link | skipped
    size: int = 0
    sha256: Optional[str] = None
    admin_only: bool = False
    unsafe: bool = False


def _is_link(path: str) -> bool:
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


_BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def _unsafe_part(part: str) -> bool:
    return _component_problem(part) is not None or bool(_BIDI.search(part)) or part in ("", ".", "..")


def _admin_name(name: str) -> bool:
    lower = name.lower()
    if lower == ".env" or lower.startswith(".env."):
        return True
    if lower.endswith(_ADMIN_SUFFIXES):
        return True
    return ".log." in lower


def walk_files(source: str, top: Path, exclude: List[Path]) -> List[FileEntry]:
    """`top` 아래 파일 목록 (링크는 따라가지 않는다). `exclude` 는 다른 원본이라 건너뛴다."""
    if source not in FILE_SOURCES:
        raise ValueError(source)
    top = Path(top)
    if not top.is_dir():
        return []
    excluded = {norm(p) for p in exclude}
    entries: List[FileEntry] = []
    top_s = os.fspath(top)
    for current, dirs, files in os.walk(top_s, followlinks=False):
        rel_dir = os.path.relpath(current, top_s)
        rel_parts = [] if rel_dir == "." else rel_dir.replace("\\", "/").split("/")
        admin_dir = any(p.lower() in _ADMIN_DIRS for p in rel_parts)
        keep = []
        for name in sorted(dirs):
            full = os.path.join(current, name)
            rel = "/".join(rel_parts + [name])
            if _is_link(full):
                entries.append(FileEntry(source, rel + "/", "link"))
            elif name in _SKIP_DIRS or (not rel_parts and name in _SKIP_TOP_DIRS.get(source, ())):
                entries.append(FileEntry(source, rel + "/", "skipped"))
            else:
                keep.append(name)
        dirs[:] = keep
        for name in sorted(files):
            full = os.path.join(current, name)
            if norm(Path(full)) in excluded or name == LOCK_NAME:
                continue  # 다른 원본이거나 이 도구의 쓰기 정지 lock — 이전 대상이 아니다
            parts = rel_parts + [name]
            rel = "/".join(parts)
            if _is_link(full):
                entries.append(FileEntry(source, rel, "link"))
                continue
            entries.append(
                FileEntry(
                    source,
                    rel,
                    "file",
                    size=os.path.getsize(full),
                    sha256=sha256_file(Path(full)),
                    admin_only=admin_dir or _admin_name(name),
                    unsafe=any(_unsafe_part(p) for p in parts),
                )
            )
    return entries


__all__ = [
    "SQLITE_SOURCES",
    "JSON_SOURCES",
    "Sources",
    "resolve_sources",
    "sources_from_manifest",
    "check_cross_use",
    "fingerprint",
    "snapshot_sqlite",
    "snapshot_auth_db",
    "table_names",
    "read_table",
    "read_legacy_users",
    "read_json_source",
    "FileEntry",
    "walk_files",
]
