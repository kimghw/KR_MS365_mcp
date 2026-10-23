"""
Outlook 멀티유저 — 서비스 factory 격리·수명 (spec/spec_멀티유저.md ②-7.6, ②-12 2항, L01).

- A·B 의 서비스는 각자의 provider·UserPaths 를 쓰고 공유 AuthManager 를 얻지 않는다.
- 서비스 close 는 주입된 provider 를 닫지 않는다(풀이 차용 해제한다).
"""

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_context import bind_service
from mcp_common.service_pool import UserServicePool, get_service_pool
from mcp_common.testing import FakeTokenProvider, bound
from mcp_common.user_paths import paths_for

from mcp_outlook.graph_mail_query import GraphMailQuery
from mcp_outlook.mail_attachment import BatchAttachmentHandler, SingleAttachmentHandler
from mcp_outlook.mcp_server import handlers
from mcp_outlook.outlook_service import MailService
from mcp_outlook.tests.multiuser_fakes import *  # noqa: F401,F403 - fixtures


def _graph_ok(call):
    return FakeResponse(200, {"value": [{"id": "m1"}]})


async def test_factory_isolates_provider_and_paths(
    mu, alice, bob, alice_paths, bob_paths, alice_tokens, bob_tokens, no_shared_auth
):
    svc_a = await handlers.create_service(alice, alice_paths, alice_tokens)
    svc_b = await handlers.create_service(bob, bob_paths, bob_tokens)
    assert svc_a is not svc_b
    assert await svc_a.initialize() is True
    assert await svc_b.initialize() is True

    for svc, tokens, paths in ((svc_a, alice_tokens, alice_paths), (svc_b, bob_tokens, bob_paths)):
        client = svc._client
        assert client.mail_query.token_provider is tokens
        assert client.mail_batch.token_provider is tokens
        assert client.mail_query.paths is paths
        handler = client._attachment_handler()
        assert handler.token_provider is tokens
        assert handler.paths is paths
        # 사용자별 DB 가 생기고 legacy JSON 은 어디에도 없다
        assert paths.outlook_db.is_file()

    assert alice_paths.outlook_db != bob_paths.outlook_db
    assert not list(mu.rglob("mail_metadata.json"))
    assert no_shared_auth == []


async def test_mode1_refuses_legacy_construction(mu, alice, alice_tokens, no_shared_auth):
    with pytest.raises(RuntimeError):
        MailService()
    with pytest.raises(RuntimeError):
        MailService(token_provider=alice_tokens)  # paths 누락
    with pytest.raises(RuntimeError):
        GraphMailQuery()
    with pytest.raises(RuntimeError):
        BatchAttachmentHandler(token_provider=alice_tokens)  # paths 누락
    with pytest.raises(RuntimeError):
        SingleAttachmentHandler("raw-token")  # 토큰 보유 객체 금지
    assert no_shared_auth == []


async def test_handler_uses_leased_service_only(mu, alice, alice_paths, alice_tokens, monkeypatch):
    assert get_service_pool().has_factory(handlers.SERVER_NAME)

    # lease 된 서비스가 없으면 전역 인스턴스로 대체하지 않는다
    with pytest.raises(SecurityError) as err:
        handlers._service()
    assert err.value.code == ErrorCode.MISSING_PRINCIPAL

    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    http = install_http(monkeypatch, _graph_ok)
    with bound(alice), bind_service(handlers.SERVER_NAME, svc):
        assert handlers._service() is svc
        result = await handlers.handle_mail_fetch_search(
            {"user_email": ALICE_EMAIL, "search_term": "report"}
        )
    assert result["value"] == [{"id": "m1"}]
    assert http.calls and http.calls[0].authorization == f"Bearer {alice_tokens.token}"
    assert alice_tokens.calls  # A 의 공급자만 쓰였다


async def test_l01_closing_service_keeps_provider_and_other_user(
    mu, alice, bob, alice_paths, bob_paths, alice_tokens, bob_tokens, monkeypatch
):
    svc_a = await handlers.create_service(alice, alice_paths, alice_tokens)
    svc_b = await handlers.create_service(bob, bob_paths, bob_tokens)
    await svc_a.initialize()
    await svc_b.initialize()

    await svc_a.close()
    assert alice_tokens.closed is False  # 서비스는 빌린 공급자를 닫지 않는다
    assert bob_tokens.closed is False

    # B 는 영향 없이 계속 동작
    http = install_http(monkeypatch, _graph_ok)
    with bound(bob):
        result = await svc_b.fetch_url(
            user_email=BOB_EMAIL, url="https://graph.microsoft.com/v1.0/me/messages"
        )
    assert result["value"] == [{"id": "m1"}]
    assert http.calls[-1].authorization == f"Bearer {bob_tokens.token}"


async def test_pool_lease_per_user_and_invalidate(mu, alice, bob, no_shared_auth):
    providers = {}

    def _tokens(principal):
        providers[principal.user_key] = FakeTokenProvider(principal)
        return providers[principal.user_key]

    pool = UserServicePool(token_provider_factory=_tokens, paths_factory=paths_for)
    pool.register(handlers.SERVER_NAME, handlers.create_service)

    async with pool.lease(handlers.SERVER_NAME, alice) as svc_a:
        async with pool.lease(handlers.SERVER_NAME, bob) as svc_b:
            assert svc_a is not svc_b
            assert svc_a.token_provider is providers[alice.user_key]
            assert svc_b.token_provider is providers[bob.user_key]
            assert svc_a.paths.user_key == alice.user_key
            assert svc_b.paths.user_key == bob.user_key
            assert svc_a._initialized and svc_b._initialized  # 풀이 initialize() 를 불렀다

    await pool.invalidate(alice.user_key)
    # A 항목은 풀이 닫는다(서비스 close + 공급자 차용 해제). B 는 그대로.
    assert svc_a._initialized is False
    assert providers[alice.user_key].closed is True
    assert providers[bob.user_key].closed is False
    assert svc_b._initialized is True

    await pool.close()
    assert no_shared_auth == []


async def test_mode0_legacy_service_still_owns_shared_provider(monkeypatch):
    """mode 0: 스스로 얻은 공유 AuthManager 는 서버 종료 정리로 1회 닫는다(기존 동작)."""
    closes = []

    class _Shared:
        async def validate_and_refresh_token(self, email=None):
            return "tok"

        async def close(self):
            closes.append(1)

    monkeypatch.setattr("mcp_common.auth.get_shared_auth_manager", lambda: _Shared())
    svc = MailService()
    assert await svc.initialize() is True
    await svc.close()
    assert closes == [1]

    injected = FakeTokenProvider.__new__(FakeTokenProvider)  # 주입 공급자는 닫지 않는다
    injected.closed = False
    svc2 = MailService(token_provider=injected)
    await svc2.initialize()
    await svc2.close()
    assert injected.closed is False
