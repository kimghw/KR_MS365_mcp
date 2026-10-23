"""
Outlook 멀티유저 — Graph URL 정책 (spec/spec_멀티유저.md ②-7.5, G01/G02).

- `mail_query_url`: https Graph 호스트 + `/me/<메일 리소스>` 또는 본인 `/users/{oid|email}/<메일 리소스>`
  만. 위반은 `PATH_NOT_ALLOWED` 이고 **토큰을 얻기 전·HTTP 세션을 열기 전에** 거부된다.
- Authorization 을 단 요청은 redirect 를 따라가지 않는다.
- 사전 서명 URL(업로드 세션)에는 Graph bearer 를 붙이지 않는다.
- 공급자의 `graph_not_connected` 는 오류 dict 로 삼키지 않고 그대로 올라간다.
"""

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_context import bind_service
from mcp_common.testing import FakeTokenProvider, bound

from mcp_outlook.graph_mail_query import GraphMailQuery
from mcp_outlook.mail_attachment_storage import OneDriveStorageBackend
from mcp_outlook.mcp_server import handlers
from mcp_outlook.outlook_security import check_mail_query_url
from mcp_outlook.tests.multiuser_fakes import *  # noqa: F401,F403 - fixtures

G = "https://graph.microsoft.com"


def _deny_urls(bob):
    return [
        f"{G}/v1.0/users/other@fabrikam.com/messages",
        f"{G}/v1.0/users/{BOB_EMAIL}/mailFolders/inbox/messages",
        f"{G}/v1.0/users/{bob.object_id}/messages",
        f"{G}/v1.0/users('{ALICE_EMAIL}')/messages",
        f"{G}/v1.0/me/../users/other@fabrikam.com/messages",
        f"{G}/v1.0/me/messages/..%2F..%2F..%2Fusers%2Fother@fabrikam.com%2Fmessages",
        f"{G}/v1.0/me/%2E%2E/drive",
        f"{G}/v1.0/me/drive/root/children",
        f"{G}/v1.0/me/events",
        f"{G}/v1.0/$batch",
        f"{G}/v2.0/me/messages",
        f"{G}/beta/me/messages",
        f"{G}/v1.0/me//messages",
        "https://evil.example/v1.0/me/messages",
        "http://graph.microsoft.com/v1.0/me/messages",
        "https://graph.microsoft.com.evil.example/v1.0/me/messages",
        "https://user:pw@graph.microsoft.com/v1.0/me/messages",
        "https://graph.microsoft.com:8443/v1.0/me/messages",
        "https://graph.microsoft.com\\@evil.example/v1.0/me/messages",
        "",
    ]


def _allow_urls(alice):
    return [
        f"{G}/v1.0/me/messages",
        f"{G}/v1.0/me/mailFolders/junkemail/messages?",
        f"{G}/v1.0/me/mailFolders('Inbox')/messages?$top=5",
        f"{G}/v1.0/users/ALICE@contoso.com/messages",
        f"{G}/v1.0/users/alice%40contoso.com/messages",
        f"{G}/v1.0/users/{alice.object_id}/messages/abc/attachments",
    ]


def test_policy_table(mu, alice, bob):
    with bound(alice):
        for url in _deny_urls(bob):
            with pytest.raises(SecurityError) as err:
                check_mail_query_url(url)
            assert err.value.code == ErrorCode.PATH_NOT_ALLOWED, url
        for url in _allow_urls(alice):
            check_mail_query_url(url)
        with pytest.raises(SecurityError):
            check_mail_query_url(f"{G}/v1.0/me/messages", method="POST")


async def test_g01_rejected_before_token_or_http(mu, alice, bob, alice_paths, monkeypatch):
    http = install_http(monkeypatch, lambda call: FakeResponse(200, {"value": []}))
    for url in _deny_urls(bob):
        tokens = FakeTokenProvider(alice)
        query = GraphMailQuery(token_provider=tokens, paths=alice_paths)
        with bound(alice), pytest.raises(SecurityError) as err:
            await query.query_url(user_email=ALICE_EMAIL, url=url, top=10)
        assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
        assert tokens.calls == []  # 토큰을 얻지도 않았다
    assert http.sessions == 0 and http.calls == []


async def test_g01_tool_path_raises_not_swallowed(mu, alice, alice_paths, alice_tokens, monkeypatch):
    http = install_http(monkeypatch, lambda call: FakeResponse(200, {"value": []}))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice), bind_service(handlers.SERVER_NAME, svc):
        with pytest.raises(SecurityError) as err:
            await handlers.handle_mail_query_url(
                {"user_email": ALICE_EMAIL, "url": f"{G}/v1.0/users/other@fabrikam.com/messages"}
            )
    assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
    assert alice_tokens.calls == [] and http.calls == []


async def test_allowed_url_sends_own_token_without_redirects(mu, alice, alice_paths, alice_tokens, monkeypatch):
    http = install_http(monkeypatch, lambda call: FakeResponse(200, {"value": [{"id": "m1"}]}))
    query = GraphMailQuery(token_provider=alice_tokens, paths=alice_paths)
    with bound(alice):
        result = await query.query_url(user_email=ALICE_EMAIL, url=f"{G}/v1.0/me/mailFolders/inbox/messages?", top=300)
    assert [e["id"] for e in result["value"]] == ["m1"]
    assert len(http.calls) == 2  # 150개씩 2페이지 — 다음 페이지 URL 도 같은 정책
    for call in http.calls:
        assert call.url.startswith(f"{G}/v1.0/me/mailFolders/inbox/messages?")
        assert call.authorization == f"Bearer {alice_tokens.token}"
        assert call.kwargs.get("allow_redirects") is False


async def test_redirect_is_not_followed(mu, alice, alice_paths, alice_tokens, monkeypatch):
    def _route(call):
        resp = FakeResponse(302)
        resp.headers["Location"] = "https://evil.example/steal"
        return resp

    http = install_http(monkeypatch, _route)
    query = GraphMailQuery(token_provider=alice_tokens, paths=alice_paths)
    with bound(alice):
        result = await query.query_url(user_email=ALICE_EMAIL, url=f"{G}/v1.0/me/messages", top=10)
    assert result["status"] == "error"
    assert len(http.calls) == 1
    assert all("evil.example" not in c.url for c in http.calls)
    assert http.calls[0].kwargs.get("allow_redirects") is False


async def test_g02_presigned_upload_url_gets_no_bearer(mu, alice, alice_tokens, monkeypatch):
    presigned = "https://contoso-my.sharepoint.com/personal/alice/_api/v2.0/drive/upload?tempauth=abc"

    def _route(call):
        if call.url.endswith(":/createUploadSession"):
            return FakeResponse(200, {"uploadUrl": presigned})
        if call.url == presigned:
            return FakeResponse(201, {"webUrl": "https://contoso-my.sharepoint.com/x"})
        return FakeResponse(404)

    http = install_http(monkeypatch, _route)
    storage = OneDriveStorageBackend(auth_manager=alice_tokens, user_email=ALICE_EMAIL)
    with bound(alice):
        session = __import__("aiohttp").ClientSession()
        web_url = await storage._upload_large(session, "Attachments/a.bin", b"x" * 1024, "a.bin")

    assert web_url == "https://contoso-my.sharepoint.com/x"
    create, upload = http.calls
    assert create.authorization == f"Bearer {alice_tokens.token}"
    assert create.kwargs.get("allow_redirects") is False
    assert upload.url == presigned and upload.method == "PUT"
    assert upload.authorization is None  # 사전 서명 URL 에 Graph bearer 미부착
    assert upload.kwargs.get("allow_redirects") is False


async def test_g02_non_https_upload_url_rejected(mu, alice, alice_tokens, monkeypatch):
    def _route(call):
        if call.url.endswith(":/createUploadSession"):
            return FakeResponse(200, {"uploadUrl": "http://evil.example/upload"})
        return FakeResponse(201, {})

    http = install_http(monkeypatch, _route)
    storage = OneDriveStorageBackend(auth_manager=alice_tokens, user_email=ALICE_EMAIL)
    session = __import__("aiohttp").ClientSession()
    with pytest.raises(SecurityError) as err:  # 공용 사전 서명 정책 위반은 조용히 None 이 아니라 거부 (N05)
        await storage._upload_large(session, "A/a.bin", b"x", "a.bin")
    assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
    assert [c.method for c in http.calls] == ["POST"]  # 업로드 PUT 없음


async def test_graph_not_connected_propagates(mu, alice, alice_paths, monkeypatch):
    install_http(monkeypatch, lambda call: FakeResponse(200, {"value": []}))
    svc = await handlers.create_service(alice, alice_paths, FakeTokenProvider(alice, connected=False))
    await svc.initialize()
    with bound(alice):
        with pytest.raises(SecurityError) as err:
            await svc.fetch_search(user_email=ALICE_EMAIL, search_term="x")
        assert err.value.code == ErrorCode.GRAPH_NOT_CONNECTED
        with pytest.raises(SecurityError):
            await svc.download_attachments(user_email=ALICE_EMAIL, message_attachment_ids=["m1"])


async def test_identity_mismatch_from_provider_propagates(mu, alice, alice_paths, alice_tokens, monkeypatch):
    install_http(monkeypatch, lambda call: FakeResponse(200, {"responses": []}))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice), pytest.raises(SecurityError) as err:
        await svc.batch_and_fetch(user_email=BOB_EMAIL, message_ids=["m1"])
    assert err.value.code == ErrorCode.IDENTITY_MISMATCH
