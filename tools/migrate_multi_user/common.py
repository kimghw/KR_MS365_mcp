"""
이전 도구 공용 — 오류·저장 위치·hash·JSON 입출력 (tools.migrate_multi_user 내부 전용).

`Layout` 이 `<MS365_DATA_ROOT>/system/migration/` 아래 산출물 위치를 한 곳에서 정한다.

    manifests/<run_id>.json (+ .sha256)   plan 결과 (관리자 전용 — legacy 이메일 매핑 포함)
    snapshots/<run_id>/*.db               SQLite backup API snapshot (auth.db 는 토큰 제외본)
    staging/run.json                      staging 이 어느 run 의 것인지
    staging/users/<user_key>/...          사용자별 저장소 (activate 전까지 서버가 보지 않는다)
    quarantine/<run_id>/                  소유자 불명·모호 데이터
    checkpoints/<run_id>.{apply,activate}.json
    reports/<run_id>.verify.json

산출물 쓰기는 `mcp_common.secure_files` 를 거친다(링크·reparse point 거부, 임시파일 + replace).
"""

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from mcp_common.user_paths import UserPaths, paths_for

MANIFEST_FORMAT = "ms365-migration-manifest"
MANIFEST_VERSION = 1
#: 사용자 DB 안의 이전 표식 테이블 — 행 삽입과 같은 트랜잭션으로 기록해 재실행 중복을 막는다.
MARKER_TABLE = "_ms365_migration"
#: legacy writer 대상 디렉터리마다 두는 쓰기 정지 lock 파일 이름 (`freeze.py`). 이전 대상 파일이 아니다.
LOCK_NAME = ".migration_lock"
#: 파일 원본 이름표. 매핑 파일 `owners.paths[].path` 의 첫 성분이다.
FILE_SOURCES = ("downloads", "output")
#: legacy 원본 이름표 → `UserPaths.files` 아래 대상 디렉터리 (posix).
FILE_DEST_PREFIX = {"downloads": "downloads/outlook", "output": "output"}

_CHUNK = 1024 * 1024


class MigrationError(Exception):
    """이전을 멈추는 오류. 메시지에 이메일·토큰을 넣지 않는다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Layout:
    data_root: Path
    deployment_id: str

    @property
    def migration(self) -> Path:
        return self.data_root / "system" / "migration"

    @property
    def manifests(self) -> Path:
        return self.migration / "manifests"

    @property
    def staging(self) -> Path:
        return self.migration / "staging"

    @property
    def staging_users(self) -> Path:
        return self.staging / "users"

    @property
    def staging_marker(self) -> Path:
        return self.staging / "run.json"

    @property
    def checkpoints(self) -> Path:
        return self.migration / "checkpoints"

    @property
    def reports(self) -> Path:
        return self.migration / "reports"

    @property
    def live_users(self) -> Path:
        return self.data_root / "users"

    def manifest_path(self, run_id: str) -> Path:
        return self.manifests / f"{run_id}.json"

    def snapshot_dir(self, run_id: str) -> Path:
        return self.migration / "snapshots" / run_id

    def quarantine_dir(self, run_id: str) -> Path:
        return self.migration / "quarantine" / run_id

    def staging_paths(self, user_key: str) -> UserPaths:
        return paths_for(user_key, root=self.staging)

    def live_paths(self, user_key: str) -> UserPaths:
        return paths_for(user_key, root=self.data_root)


def current_layout() -> Layout:
    """멀티유저 모드 + 초기화된 데이터 루트(deployment marker)를 요구한다."""
    from mcp_common.security_contracts import StartupConfigError
    from mcp_common.security_policy import (
        data_root,
        ensure_deployment,
        is_multi_user_data_root,
        multi_user_enabled,
    )

    try:
        if not multi_user_enabled():
            raise MigrationError(
                "mode", "이전 도구는 멀티유저 환경(MS365_MULTI_USER=1, MS365_DATA_ROOT)에서 실행합니다."
            )
        root = data_root()
    except StartupConfigError as exc:
        raise MigrationError("mode", str(exc)) from None
    if not is_multi_user_data_root(root):
        # mode 0 저장소나 빈 디렉터리를 멀티유저 루트로 쓰지 않는다 (②-8.1)
        raise MigrationError(
            "not_initialized",
            "MS365_DATA_ROOT 에 멀티유저 deployment marker 가 없습니다 — 먼저 `python -m session.admin_cli init`.",
        )
    try:
        marker = ensure_deployment(root)
    except StartupConfigError as exc:
        raise MigrationError("not_initialized", str(exc)) from None
    return Layout(data_root=root, deployment_id=marker["deployment_id"])


# ----------------------------------------------------------------------
# 시각·ID
# ----------------------------------------------------------------------
def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)


# ----------------------------------------------------------------------
# hash
# ----------------------------------------------------------------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_of(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj))


# ----------------------------------------------------------------------
# 경로
# ----------------------------------------------------------------------
def norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_within(child: Path, parent: Path) -> bool:
    """`child` 가 `parent` 와 같거나 그 아래인가 (대소문자는 OS 규칙)."""
    c, p = norm(child), norm(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def has_files(directory: Path) -> bool:
    """디렉터리 트리에 일반 파일(또는 링크)이 하나라도 있는가. 빈 디렉터리만 있으면 False."""
    if not directory.exists():
        return False
    for _root, dirs, files in os.walk(directory, followlinks=False):
        if files:
            return True
        for name in dirs:
            if os.path.islink(os.path.join(_root, name)):
                return True
    return False


# ----------------------------------------------------------------------
# JSON 입출력 (산출물)
# ----------------------------------------------------------------------
def write_json(path: Path, obj: Any, *, root: Path) -> bytes:
    """`root` 경계 안에 원자적으로 쓴다. 쓴 바이트를 돌려준다(sidecar hash 용)."""
    from mcp_common.secure_files import atomic_write_bytes

    data = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    atomic_write_bytes(Path(path), data, root=root)
    return data


def write_text(path: Path, text: str, *, root: Path) -> None:
    from mcp_common.secure_files import atomic_write_bytes

    atomic_write_bytes(Path(path), text.encode("utf-8"), root=root)


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_json_optional(path: Path) -> Optional[Any]:
    try:
        return read_json(path)
    except FileNotFoundError:
        return None


# ----------------------------------------------------------------------
# manifest
# ----------------------------------------------------------------------
def latest_manifest(layout: Layout) -> Path:
    candidates = sorted(layout.manifests.glob("*.json")) if layout.manifests.is_dir() else []
    if not candidates:
        raise MigrationError("no_manifest", "manifest 가 없습니다 — 먼저 `plan` 을 실행하세요.")
    return candidates[-1]


def load_manifest(layout: Layout, path: Optional[Path]) -> Dict[str, Any]:
    """manifest 를 읽고 sidecar hash·형식·배포 ID 를 확인한다."""
    path = Path(path) if path else latest_manifest(layout)
    try:
        data = path.read_bytes()
        sidecar = Path(str(path) + ".sha256").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise MigrationError("no_manifest", "manifest 또는 그 .sha256 파일이 없습니다.") from None
    if sha256_bytes(data) != sidecar:
        raise MigrationError("manifest_tampered", "manifest 가 plan 이후 바뀌었습니다(.sha256 불일치) — plan 을 다시 실행하세요.")
    manifest = json.loads(data.decode("utf-8"))
    if manifest.get("format") != MANIFEST_FORMAT or manifest.get("version") != MANIFEST_VERSION:
        raise MigrationError("manifest_format", "manifest 형식이 이 도구와 다릅니다.")
    if manifest.get("deployment_id") != layout.deployment_id or norm(Path(manifest.get("data_root", ""))) != norm(
        layout.data_root
    ):
        raise MigrationError("manifest_foreign", "다른 데이터 루트(배포)의 manifest 입니다.")
    manifest["_path"] = str(path)
    manifest["_sha256"] = sidecar
    return manifest


def require_no_conflicts(manifest: Dict[str, Any]) -> None:
    if manifest.get("conflicts"):
        raise MigrationError(
            "conflicts",
            f"manifest 에 해결되지 않은 충돌 {len(manifest['conflicts'])}건이 있습니다 — 매핑을 고친 뒤 plan 을 다시 실행하세요.",
        )


def audit_event(command: str, outcome: str, *, user_key: Optional[str] = None, error_code: Optional[str] = None) -> None:
    """감사 sink 에 이전 사건을 남긴다(허용 필드만). 실패해도 이전을 멈추지 않는다."""
    try:
        from mcp_common.audit import audit

        audit("migration", outcome=outcome, tool=f"migrate.{command}", user_key=user_key, error_code=error_code)
    except Exception:
        pass


__all__ = [
    "MANIFEST_FORMAT",
    "MANIFEST_VERSION",
    "MARKER_TABLE",
    "FILE_SOURCES",
    "FILE_DEST_PREFIX",
    "MigrationError",
    "Layout",
    "current_layout",
    "utcnow_iso",
    "new_run_id",
    "sha256_bytes",
    "sha256_file",
    "canonical_json",
    "digest_of",
    "norm",
    "is_within",
    "has_files",
    "write_json",
    "write_text",
    "read_json",
    "read_json_optional",
    "latest_manifest",
    "load_manifest",
    "require_no_conflicts",
    "audit_event",
]
