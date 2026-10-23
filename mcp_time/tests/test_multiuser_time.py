"""Time 멀티유저 (spec/spec_멀티유저.md ②-2.4 Time 행·②-7.3, WP8).

Time 은 개인 토큰·DB·사용자 상태가 없다. 서비스 factory 를 등록하지 않으며, 멀티유저에서
principal 이 묶여 있든 없든 핸들러가 사용자 자원(토큰 공급자·사용자 디렉터리)에 손대지 않는다.
"""

import pytest

import mcp_common.auth as common_auth
from mcp_common.service_pool import get_service_pool
from mcp_common.testing import bound, make_principal, multi_user_mode

from mcp_time.mcp_server import handlers
from mcp_time.time_service import TimeService


def _forbidden(*args, **kwargs):
    raise AssertionError("Time 이 공용 AuthManager 를 불렀다")


@pytest.fixture
def mu(tmp_path, monkeypatch):
    monkeypatch.setattr(common_auth, "get_shared_auth_manager", _forbidden)
    with multi_user_mode(tmp_path) as root:
        yield root


async def test_time_handler_needs_no_user_service(mu):
    assert not get_service_pool().has_factory(handlers.SERVER_NAME)
    with bound(make_principal("alice@contoso.com")):
        res = await handlers.handle_get_current_time({"timezone": "UTC"})
    assert res["timezone"] == "UTC"
    # 사용자 디렉터리·DB 를 만들지 않는다
    assert not (mu / "users").exists()


def test_time_contract_has_no_user_arguments():
    (tool,) = handlers.MCP_TOOLS
    assert set(tool["inputSchema"]["properties"]) == {"timezone"}
    assert tool["inputSchema"].get("required", []) == []
    assert [type(s) for s in handlers.lifecycle.services] == [TimeService]
