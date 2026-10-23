"""WP2 — legacy(mode 0) 인증 경로: 멀티유저 모드 차단 가드 + 콜백 state 별 대기(다른 인증 간섭 금지)."""

import asyncio
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from mcp_common.testing import multi_user_mode, single_user_mode
from session.mode_guard import LegacyAuthDisabledError


# ----------------------------------------------------------------------
# mode 1 에서 legacy 경로 거부
# ----------------------------------------------------------------------
def test_legacy_constructors_refuse_in_multi_user(tmp_path):
    from callback_server import CallbackServer
    from session.auth_database import AuthDatabase
    from session.auth_manager import AuthManager, get_default_auth_manager, get_default_user_email
    from session.auth_service import AuthService
    from session.azure_config import AzureConfig
    from session.session_manager import Session

    with multi_user_mode(tmp_path / "data") as root:
        for make in (
            AuthManager,
            get_default_auth_manager,
            get_default_user_email,
            AuthDatabase,
            lambda: AuthDatabase("database/auth.db"),
            lambda: AuthDatabase(str(root / "system" / "legacy.db")),
            lambda: AuthService(auth_db=object(), config=object()),
            lambda: AzureConfig(auth_db=object()),
            lambda: Session("alice@contoso.com"),
            lambda: CallbackServer(auth_manager=SimpleNamespace(auth_service=None)),
        ):
            with pytest.raises(LegacyAuthDisabledError):
                make()
        # 이전 도구가 읽을 명시 legacy 경로(데이터 루트 밖)는 열 수 있다
        AuthDatabase(str(tmp_path / "legacy" / "auth.db"))


async def test_session_manager_refuses_in_multi_user(tmp_path):
    from session.session_manager import SessionManager

    manager = SessionManager()
    with multi_user_mode(tmp_path / "data"):
        with pytest.raises(LegacyAuthDisabledError):
            await manager.get_or_create_session("alice@contoso.com")
        with pytest.raises(LegacyAuthDisabledError):
            await manager.get_session(None)


def test_shared_auth_manager_refuses_in_multi_user(tmp_path):
    from mcp_common.auth import get_shared_auth_manager

    with multi_user_mode(tmp_path / "data"):
        with pytest.raises(LegacyAuthDisabledError):
            get_shared_auth_manager()


async def test_main_and_reauth_refuse_in_multi_user(tmp_path, capsys):
    import _reauth
    import main as legacy_main

    with multi_user_mode(tmp_path / "data"):
        assert await _reauth.main() == 2
        await legacy_main.main()
    out = capsys.readouterr()
    assert "session.admin_cli" in out.out and "auth_gateway" in out.err


def test_azure_config_listing_excludes_secret(tmp_path, monkeypatch):
    from session.auth_database import AuthDatabase
    from session.azure_config import AzureConfig

    monkeypatch.setenv("AZURE_CLIENT_ID", "app-1")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "SECRET-CANARY")
    with single_user_mode():
        config = AzureConfig(AuthDatabase(str(tmp_path / "auth.db")))
        apps = config.list_all_apps()
    assert apps and all("client_secret" not in app for app in apps)


# ----------------------------------------------------------------------
# mode 0 콜백: state 별 대기
# ----------------------------------------------------------------------
class _FakeService:
    def __init__(self, states):
        self.auth_states = {s: {} for s in states}
        self.completed = []

    def consume_state(self, state):
        if state and state in self.auth_states:
            del self.auth_states[state]
            return True
        return False

    async def complete_auth_flow(self, code, state):
        from session.auth_service import InvalidOAuthStateError

        if not self.consume_state(state):
            raise InvalidOAuthStateError("bad")
        if code == "boom":
            raise RuntimeError("SECRET-DETAIL token endpoint said no")
        self.completed.append(state)
        return {"user_email": f"user-{state}@contoso.com"}


def _request(**params):
    return SimpleNamespace(path="/callback", query_string=urlencode(params))


async def _server(states):
    from callback_server import CallbackServer

    with single_user_mode():
        server = CallbackServer(auth_manager=SimpleNamespace(auth_service=_FakeService(states)))
    for state in states:
        server.expect(state)
    return server


async def test_bad_state_does_not_wake_or_fail_other_flows(caplog):
    server = await _server(["s1", "s2"])
    w1 = asyncio.create_task(server.wait_for_auth(5, state="s1"))
    w2 = asyncio.create_task(server.wait_for_auth(5, state="s2"))
    await asyncio.sleep(0)

    # 알 수 없는 state 의 오류·코드 → 아무도 깨우지 않는다
    assert (await server.handle_callback(_request(error="access_denied", state="nope"))).status == 400
    assert (await server.handle_callback(_request(code="c", state="nope"))).status == 400
    assert (await server.handle_callback(_request(error="access_denied"))).status == 400
    await asyncio.sleep(0.05)
    assert not w1.done() and not w2.done()

    # s1 의 오류 콜백 → s1 만 실패
    assert (await server.handle_callback(_request(error="access_denied", state="s1"))).status == 400
    with pytest.raises(Exception) as e:
        await w1
    assert "access_denied" in str(e.value)
    assert not w2.done()

    # s2 성공 → s2 만 완료
    resp = await server.handle_callback(_request(code="c", state="s2"))
    assert resp.status == 200
    assert await w2 == "user-s2@contoso.com"
    # 같은 state 재사용(replay) → 거부
    assert (await server.handle_callback(_request(code="c", state="s2"))).status == 400
    assert "s2" not in caplog.text and "user-s2" not in caplog.text


async def test_token_exchange_failure_only_fails_its_state_without_leaking_detail():
    server = await _server(["s1", "s2"])
    w1 = asyncio.create_task(server.wait_for_auth(5, state="s1"))
    w2 = asyncio.create_task(server.wait_for_auth(5, state="s2"))
    await asyncio.sleep(0)
    resp = await server.handle_callback(_request(code="boom", state="s1"))
    assert resp.status == 500 and "SECRET-DETAIL" not in resp.text
    with pytest.raises(Exception) as e:
        await w1
    assert "SECRET-DETAIL" not in str(e.value)
    assert not w2.done()
    w2.cancel()


async def test_wait_without_state_only_gets_validated_results():
    server = await _server(["s1"])
    waiter = asyncio.create_task(server.wait_for_auth(5))
    await asyncio.sleep(0)
    await server.handle_callback(_request(code="c", state="forged"))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await server.handle_callback(_request(code="c", state="s1"))
    assert await waiter == "user-s1@contoso.com"


async def test_wait_for_auth_timeout_returns_none():
    server = await _server(["s1"])
    assert await server.wait_for_auth(0.05, state="s1") is None
