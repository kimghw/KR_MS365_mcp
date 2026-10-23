"""
사용자별 저장 경로 계약 (spec/spec_멀티유저.md ②-7.2, WP0).

    <MS365_DATA_ROOT>/
      system/   deployment.json  registry.db  app_config.db  locks/  audit/  migration/
      users/<user_key>/
        auth/   auth.db  wrapped_dek.json        ← 파일 도구 접근 금지
        db/     onenote.db teams.db metadata.db outlook.db   ← 파일 도구 접근 금지
        files/  uploads/ downloads/<domain>/ output/ tmp/<request_id>/   ← 도구 허용 루트
        manifest.json

- `paths_for()` 는 **경로 계산·검증만** 한다. 디렉터리를 만들거나 DB 를 열지 않는다.
- `ensure_user_dirs()` 가 디렉터리를 만든다(서비스 풀이 factory 호출 전에 부른다).
- 도구가 읽고 쓸 수 있는 곳은 `UserPaths.files` 아래뿐이다. `auth/`·`db/`·`system/` 은
  자기 것이라도 파일 도구로 열 수 없다(`mcp_common.paths` 가 강제, WP3).
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from mcp_common.principal import Principal, is_valid_user_key
from mcp_common.security_policy import data_root

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class SystemPaths:
    root: Path
    deployment_json: Path
    registry_db: Path
    app_config_db: Path
    locks: Path
    audit: Path
    migration: Path


@dataclass(frozen=True)
class UserPaths:
    user_key: str
    root: Path
    auth_dir: Path
    auth_db: Path
    wrapped_dek: Path
    db_dir: Path
    onenote_db: Path
    teams_db: Path
    metadata_db: Path
    outlook_db: Path
    files: Path
    uploads: Path
    downloads: Path
    output: Path
    tmp: Path
    manifest: Path

    def downloads_for(self, domain: str) -> Path:
        """`files/downloads/<domain>/` — domain 은 소문자 식별자만."""
        if not re.match(r"^[a-z][a-z0-9_]{0,31}$", domain or ""):
            raise ValueError("domain 형식이 올바르지 않습니다")
        return self.downloads / domain

    def request_tmp(self, request_id: str) -> Path:
        """`files/tmp/<request_id>/` — 요청별 임시 디렉터리 경로 (생성하지 않음)."""
        if not _REQUEST_ID_RE.match(request_id or ""):
            raise ValueError("request_id 형식이 올바르지 않습니다")
        return self.tmp / request_id


def system_paths(root: Optional[Path] = None) -> SystemPaths:
    base = (root or data_root()) / "system"
    return SystemPaths(
        root=base,
        deployment_json=base / "deployment.json",
        registry_db=base / "registry.db",
        app_config_db=base / "app_config.db",
        locks=base / "locks",
        audit=base / "audit",
        migration=base / "migration",
    )


def paths_for(who: Union[Principal, str], *, root: Optional[Path] = None) -> UserPaths:
    """Principal 또는 user_key 로 사용자 경로를 계산한다 (I/O 없음)."""
    user_key = who.user_key if isinstance(who, Principal) else who
    if not is_valid_user_key(user_key):
        raise ValueError("user_key 형식이 올바르지 않습니다")
    base = (root or data_root()) / "users" / user_key
    auth_dir = base / "auth"
    db_dir = base / "db"
    files = base / "files"
    return UserPaths(
        user_key=user_key,
        root=base,
        auth_dir=auth_dir,
        auth_db=auth_dir / "auth.db",
        wrapped_dek=auth_dir / "wrapped_dek.json",
        db_dir=db_dir,
        onenote_db=db_dir / "onenote.db",
        teams_db=db_dir / "teams.db",
        metadata_db=db_dir / "metadata.db",
        outlook_db=db_dir / "outlook.db",
        files=files,
        uploads=files / "uploads",
        downloads=files / "downloads",
        output=files / "output",
        tmp=files / "tmp",
        manifest=base / "manifest.json",
    )


def _mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass


def ensure_user_dirs(paths: UserPaths) -> UserPaths:
    """사용자 디렉터리를 만든다. 링크·junction 으로 바꿔치기된 디렉터리는 거부한다."""
    for directory in (
        paths.root,
        paths.auth_dir,
        paths.db_dir,
        paths.files,
        paths.uploads,
        paths.downloads,
        paths.output,
        paths.tmp,
    ):
        _mkdir_private(directory)
        if directory.is_symlink() or _is_junction(directory):
            raise PermissionError("사용자 디렉터리가 링크입니다")
    return paths


def ensure_system_dirs(paths: Optional[SystemPaths] = None) -> SystemPaths:
    paths = paths or system_paths()
    for directory in (paths.root, paths.locks, paths.audit, paths.migration):
        _mkdir_private(directory)
    return paths


def _is_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)  # Python 3.12+
    if is_junction is not None:
        try:
            return bool(is_junction(path))
        except OSError:
            return False
    return False


__all__ = [
    "SystemPaths",
    "UserPaths",
    "system_paths",
    "paths_for",
    "ensure_user_dirs",
    "ensure_system_dirs",
]
