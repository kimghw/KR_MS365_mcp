"""이전 도구 테스트 fixture — 멀티유저 임시 데이터 루트(memory KEK) + legacy 저장소."""

from types import SimpleNamespace

import pytest

from mcp_common.testing import TEST_AUTH_ENV, multi_user_mode

_CLEARED_ENV = (
    "MS365_DEFAULT_USER_EMAIL", "MCP_ALLOWED_PATHS", "MCP_DATA_DIR", "DB_PATH", "MCP_PARAM_SPEC_DIR",
    "MS365_AUTH_GATEWAY_PORT", "MS365_AUTH_GATEWAY_HOST", "MCP_SERVER_PORT", "MCP_BIND_HOST",
    "MS365_KEK_B64", "MS365_KEK_KEY_ID", "AZURE_CLIENT_SECRET", "AZURE_CLIENT_SECRET_FILE",
)


@pytest.fixture
def mu_env(tmp_path, monkeypatch):
    """초기화된 멀티유저 데이터 루트 + 서버 포트 검사 무력화(실제 PC 의 서버와 무관하게)."""
    from mcp_common.security_policy import ensure_deployment
    from mcp_common.user_paths import ensure_system_dirs
    from session.identity_registry import ensure_registry
    from session.key_provider import set_key_provider_for_tests
    from tools.migrate_multi_user import ports

    for key in _CLEARED_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in TEST_AUTH_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ports, "running_server_ports", lambda: [])
    with multi_user_mode(tmp_path / "data") as root:
        ensure_system_dirs()
        ensure_deployment()
        ensure_registry()
        try:
            yield SimpleNamespace(root=root, tmp=tmp_path, legacy_root=tmp_path / "legacy")
        finally:
            set_key_provider_for_tests(None)


@pytest.fixture
def registered(mu_env):
    """ALICE·BOB 을 registry 에 등록한다 (`admin_cli user add` 와 같은 함수)."""
    from session.identity_registry import register_user
    from tools.tests.migration_support import ALICE, BOB

    for principal in (ALICE, BOB):
        register_user(principal.tenant_id, principal.object_id)
    return mu_env
