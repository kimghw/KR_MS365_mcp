"""
배포 모드 정책 — 단일 운영자(mode 0) / 멀티유저(mode 1) (spec/spec_멀티유저.md ②-8.1, WP0).

모드는 **프로세스 기동 시 한 번** 확정하고, 요청·사용자 입력으로 바꿀 수 없다.
`get_policy()` 가 첫 호출 때 환경변수를 읽어 동결한다. 테스트만 `reset_policy_cache()` 로
다시 읽힌다.

| 설정 | 동작 |
|------|------|
| `MS365_MULTI_USER` 미설정·`0` | 기존 단일 운영자 구조 그대로 (mode 0) |
| `MS365_MULTI_USER=1` + HTTP | 멀티유저. `MS365_DATA_ROOT`(절대경로) 필수 |
| `MS365_MULTI_USER=1` + stdio | 기동 실패 |

`validate_startup()` 은 멀티유저와 **충돌하는 공용 설정을 조용히 무시하지 않고** 기동을
막는다(②-7.4). 개별 WP 가 추가 검사를 붙일 때는 이 함수에 항목을 더한다 — 검사 진입점을
도메인마다 따로 만들지 않는다.
"""

import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from mcp_common.security_contracts import StartupConfigError

ENV_MULTI_USER = "MS365_MULTI_USER"
ENV_DATA_ROOT = "MS365_DATA_ROOT"

#: 멀티유저에서 설정돼 있으면 기동을 막는 공용 설정 (범위를 넓히거나 폴백을 만드는 것들).
CONFLICTING_ENV = (
    "MS365_DEFAULT_USER_EMAIL",  # 기본 사용자 폴백 (②-5.5)
    "MCP_ALLOWED_PATHS",         # 파일 허용 루트 확장 (②-7.4)
    "MCP_DATA_DIR",
    "DB_PATH",                   # 공용 auth.db 경로
    # FileHandler 공용 경로 (mcp_file_handler/config/settings.py). 도메인 검사와 별개로
    # 여기서도 막아 어느 도메인 프로세스든 같은 설정으로 기동을 거부한다.
    "MCP_ATTACHMENT_TEMP_DIR",
    "MCP_ATTACHMENT_OUTPUT_DIR",
    "MCP_ATTACHMENT_METADATA_PATH",
    "MCP_ATTACHMENT_LOG_FILE",
)

DEPLOYMENT_FILE = "deployment.json"
STORAGE_FORMAT = "ms365-multi-user"
SCHEMA_VERSION = 1

_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SecurityPolicy:
    multi_user: bool
    data_root: Optional[Path]  # mode 1 에서만 값이 있다


_policy: Optional[SecurityPolicy] = None
_lock = threading.Lock()


def _read_policy() -> SecurityPolicy:
    raw = os.environ.get(ENV_MULTI_USER, "").strip().lower()
    multi = raw in _TRUE
    if raw and not multi and raw not in {"0", "false", "no", "off"}:
        raise StartupConfigError(f"{ENV_MULTI_USER} 값이 올바르지 않습니다: {raw!r} (0 또는 1)")
    if not multi:
        return SecurityPolicy(multi_user=False, data_root=None)

    root_raw = os.environ.get(ENV_DATA_ROOT, "").strip().strip('"')
    if not root_raw:
        raise StartupConfigError(f"멀티유저 모드에는 {ENV_DATA_ROOT}(절대경로)가 필요합니다.")
    root = Path(root_raw).expanduser()
    if not root.is_absolute():
        # CWD·프로젝트 루트로 자동 결정하지 않는다 (②-7.2)
        raise StartupConfigError(f"{ENV_DATA_ROOT} 는 절대경로여야 합니다: {root_raw!r}")
    return SecurityPolicy(multi_user=True, data_root=root.resolve())


def get_policy() -> SecurityPolicy:
    """프로세스 모드. 첫 호출에 동결된다."""
    global _policy
    with _lock:
        if _policy is None:
            _policy = _read_policy()
        return _policy


def reset_policy_cache() -> None:
    """**테스트 전용.** 다음 `get_policy()` 가 환경변수를 다시 읽는다."""
    global _policy
    with _lock:
        _policy = None


def multi_user_enabled() -> bool:
    return get_policy().multi_user


def data_root() -> Path:
    """멀티유저 데이터 루트. mode 0 에서 부르면 오류 — legacy 경로와 섞지 않는다."""
    policy = get_policy()
    if not policy.multi_user or policy.data_root is None:
        raise StartupConfigError("data_root() 는 멀티유저 모드에서만 쓸 수 있습니다.")
    return policy.data_root


def assert_transport_allowed(transport: str) -> None:
    """`transport` 는 "stdio" | "http". 멀티유저 + stdio 는 기동 실패."""
    if transport == "stdio" and multi_user_enabled():
        raise StartupConfigError(
            "멀티유저 모드(MS365_MULTI_USER=1)는 stdio 를 지원하지 않습니다. "
            "Streamable HTTP 서버로 기동하세요."
        )


# ----------------------------------------------------------------------
# deployment marker
# ----------------------------------------------------------------------
def _deployment_path(root: Path) -> Path:
    return root / "system" / DEPLOYMENT_FILE


def ensure_deployment(root: Optional[Path] = None) -> dict:
    """`<root>/system/deployment.json` 을 읽고, 없으면 배타 생성한다.

    배포 ID 는 토큰 암호화 AAD·키 digest 의 도메인 분리에 쓰인다. 다른 형식의 marker 가
    있으면(legacy 저장소를 가리킨 경우 등) 기동을 막는다.
    """
    root = root or data_root()
    path = _deployment_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        marker = {
            "storage_format": STORAGE_FORMAT,
            "schema_version": SCHEMA_VERSION,
            "deployment_id": secrets.token_hex(16),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # 'x' — 동시에 뜬 다른 도메인 프로세스와 경합해도 한 쪽만 만든다.
            with open(path, "x", encoding="utf-8") as fh:
                json.dump(marker, fh, ensure_ascii=False, indent=2)
        except FileExistsError:
            pass
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StartupConfigError(f"deployment marker 를 읽을 수 없습니다: {exc}") from exc
    if marker.get("storage_format") != STORAGE_FORMAT:
        raise StartupConfigError("데이터 루트의 저장 형식이 멀티유저 형식이 아닙니다.")
    if int(marker.get("schema_version", 0)) > SCHEMA_VERSION:
        raise StartupConfigError("데이터 루트의 스키마가 이 코드보다 새 버전입니다.")
    if not isinstance(marker.get("deployment_id"), str) or len(marker["deployment_id"]) < 16:
        raise StartupConfigError("deployment_id 가 올바르지 않습니다.")
    return marker


def deployment_id() -> str:
    return ensure_deployment()["deployment_id"]


MIGRATION_LOCK_NAME = ".migration_lock"
ENV_MIGRATION_OVERRIDE = "MS365_MIGRATION_OVERRIDE"


def assert_legacy_store_not_frozen(db_path: "os.PathLike[str] | str") -> None:
    """mode 0 전용 — legacy 저장소가 멀티유저 이전으로 잠겨 있으면 열지 않는다 (astra 재검토 R10).

    `tools.migrate_multi_user plan` 이 legacy SQLite 가 있는 디렉터리마다 `.migration_lock` 을
    둔다. 이전 구간(plan→activate) 동안 legacy writer 가 데이터를 추가하면 mode 1 데이터가
    불완전해지므로, 잠금이 있으면 mode 0 기동을 거부한다. 운영자가 알고 여는 경우만
    `MS365_MIGRATION_OVERRIDE=1` 로 통과시키며 감사에 남긴다.
    """
    if multi_user_enabled():
        return
    lock = Path(os.path.abspath(os.fspath(db_path))).parent / MIGRATION_LOCK_NAME
    if not lock.exists():
        return
    if os.environ.get(ENV_MIGRATION_OVERRIDE, "").strip() == "1":
        try:
            from mcp_common.audit import audit

            audit("admin.config", outcome="success", tool="migration_override")
        except Exception:
            pass
        return
    raise StartupConfigError(
        "legacy 저장소가 멀티유저 이전 중/완료로 잠겨 있습니다 — mode 1 로 기동하거나 "
        "`python -m tools.migrate_multi_user unlock --yes` 또는 MS365_MIGRATION_OVERRIDE=1 "
        "(운영자 확인 후)로 여세요."
    )


def is_multi_user_data_root(path: Path) -> bool:
    """legacy 코드가 멀티유저 저장 루트를 열려는지 판별할 때 쓴다 (②-8.1)."""
    try:
        marker = json.loads(_deployment_path(Path(path)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return marker.get("storage_format") == STORAGE_FORMAT


# ----------------------------------------------------------------------
# startup validation
# ----------------------------------------------------------------------
def startup_problems(transport: str) -> List[str]:
    """멀티유저 기동을 막아야 하는 설정 문제 목록 (mode 0 이면 빈 목록)."""
    if not multi_user_enabled():
        return []
    problems: List[str] = []
    if transport == "stdio":
        problems.append("멀티유저 모드는 stdio 를 지원하지 않습니다.")
    for key in CONFLICTING_ENV:
        if os.environ.get(key, "").strip():
            problems.append(f"{key} 는 멀티유저 모드와 함께 쓸 수 없습니다 (설정 해제 필요).")
    if os.environ.get("MCP_VALIDATE_INPUT", "").strip().lower() in {"0", "false", "no", "off"}:
        problems.append("멀티유저 모드에서는 MCP_VALIDATE_INPUT=0 을 쓸 수 없습니다.")
    # 인증 계층(앱 설정·KEK provider) 점검은 session 이 소유한다. 여기서 모아야 KEK 미설정이
    # 첫 토큰 접근이 아니라 기동 시점에 드러난다.
    try:
        from session.app_settings import auth_startup_problems
    except ImportError:
        problems.append("멀티유저 모드에는 session 패키지(인증 계층)가 필요합니다.")
    else:
        problems.extend(auth_startup_problems())
    return problems


def validate_startup(server_name: str, transport: str) -> None:
    """기동 직후 1회. 문제가 있으면 `StartupConfigError` — 서버를 띄우지 않는다."""
    problems = startup_problems(transport)
    if problems:
        raise StartupConfigError(
            f"[{server_name}] 멀티유저 기동 거부:\n- " + "\n- ".join(problems)
        )
    if multi_user_enabled():
        ensure_deployment()


__all__ = [
    "ENV_MULTI_USER",
    "ENV_DATA_ROOT",
    "CONFLICTING_ENV",
    "SecurityPolicy",
    "get_policy",
    "reset_policy_cache",
    "multi_user_enabled",
    "data_root",
    "assert_transport_allowed",
    "ensure_deployment",
    "deployment_id",
    "is_multi_user_data_root",
    "MIGRATION_LOCK_NAME",
    "ENV_MIGRATION_OVERRIDE",
    "assert_legacy_store_not_frozen",
    "startup_problems",
    "validate_startup",
]
