"""OneDrive 멀티유저 격리 (spec/spec_멀티유저.md ②-7.3·②-7.6·②-10 C01·L01, WP7).

네트워크 없음 — `FakeTokenProvider` + 가짜 Graph 세션(`_fake_graph`). 공용 AuthManager
(`get_shared_auth_manager`)와 legacy 기본 사용자 선택은 호출되면 실패하도록 막아 둔다.
"""

import asyncio
import ipaddress
import logging

import pytest

import mcp_common.auth as common_auth
import mcp_common.graph_url_policy as url_policy
from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_context import bind_service
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode
from mcp_common.user_resolver import UserResolver

import mcp_onedrive.graph_onedrive_client as graph_mod
import mcp_onedrive.onedrive_service as service_mod
from mcp_onedrive.graph_onedrive_client import GraphOneDriveClient
from mcp_onedrive.mcp_server import handlers
from mcp_onedrive.onedrive_service import OneDriveService
from mcp_onedrive.tests._fake_graph import FakeGraph, FakeResponse, Rendezvous

GRAPH = "https://graph.microsoft.com/v1.0"
ALICE = "alice@contoso.com"
BOB = "bob@fabrikam.com"
DOMAIN = handlers.SERVER_NAME


def _router(method, url, token, body):
    if url == f"{GRAPH}/me/drive":
        return FakeResponse(200, {"id": f"drive-{token}", "name": f"OneDrive of {token}"})
    if "/children" in url or "/search(" in url:
        return FakeResponse(200, {"value": [{"id": f"item-{token}", "name": f"file-of-{token}"}]})
    if url.endswith(":/content"):
        return FakeResponse(200, body=f"content-of-{token}".encode())
    return FakeResponse(
        404,
        {"error": {"code": "itemNotFound", "message": "CANARY-BODY Secret Plans.docx"}},
    )


def _forbidden(*args, **kwargs):
    raise AssertionError("mode 1 경로가 공용 AuthManager·legacy 기본 사용자를 불렀다")


@pytest.fixture
def mu(tmp_path, monkeypatch):
    monkeypatch.setattr(common_auth, "get_shared_auth_manager", _forbidden)
    monkeypatch.setattr(service_mod, "_get_default_user_email", _forbidden)
    monkeypatch.setattr(UserResolver, "default_email", _forbidden)
    with multi_user_mode(tmp_path) as root:
        yield root


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph(_router)
    monkeypatch.setattr(graph_mod.aiohttp, "ClientSession", fake.session_factory)
    return fake


@pytest.fixture
def users():
    alice = make_principal(ALICE)
    bob = make_principal(BOB)
    return {
        "alice": (alice, FakeTokenProvider(alice, "tok-alice")),
        "bob": (bob, FakeTokenProvider(bob, "tok-bob")),
    }


@pytest.fixture
async def pool(mu, users, graph):
    providers = {p.user_key: t for p, t in users.values()}
    pool = UserServicePool(token_provider_factory=lambda p: providers[p.user_key])
    pool.register(DOMAIN, handlers.create_service)
    yield pool
    await pool.close()


async def _call(pool, principal, handler, args):
    """WP1 런타임이 하는 일(identity 바인딩 → lease → 서비스 바인딩)을 그대로 흉내 낸다."""
    with bound(principal):
        async with pool.lease(DOMAIN, principal) as svc:
            with bind_service(DOMAIN, svc):
                return await handler(args)


# ----------------------------------------------------------------------
async def test_factory_service_uses_only_callers_provider(pool, users, graph):
    alice, a_tok = users["alice"]
    bob, b_tok = users["bob"]

    res_a = await _call(pool, alice, handlers.handle_get_drive_info, {"user_email": ALICE})
    assert res_a["success"] and res_a["drive"]["id"] == "drive-tok-alice"
    assert a_tok.calls and b_tok.calls == []
    assert [r["token"] for r in graph.requests] == ["tok-alice"]

    used_by_alice = len(a_tok.calls)
    res_b = await _call(pool, bob, handlers.handle_get_drive_info, {"user_email": BOB})
    assert res_b["drive"]["id"] == "drive-tok-bob"
    assert len(a_tok.calls) == used_by_alice
    assert [r["token"] for r in graph.requests] == ["tok-alice", "tok-bob"]


async def test_interleaved_calls_keep_token_and_me_paths(pool, users, graph):
    alice, _ = users["alice"]
    bob, _ = users["bob"]
    graph.gate = Rendezvous(6)  # 6개 요청이 모두 진행 중이어야 응답한다 → 확실히 겹친다

    calls = []
    for i in range(3):
        for who, email in ((alice, ALICE), (bob, BOB)):
            calls.append(
                _call(pool, who, handlers.handle_list_files, {"user_email": email, "folder_path": f"Docs{i}"})
            )
    results = await asyncio.gather(*calls)

    for i, res in enumerate(results):
        owner = "tok-alice" if i % 2 == 0 else "tok-bob"
        assert res["files"][0]["name"] == f"file-of-{owner}"

    expected = {alice.user_key: "tok-alice", bob.user_key: "tok-bob"}
    assert len(graph.requests) == 6
    for req in graph.requests:
        assert req["token"] == expected[req["principal_key"]]
        assert req["url"].startswith(f"{GRAPH}/me/drive/")
        assert "/users/" not in req["url"]


async def test_service_close_does_not_close_injected_provider(mu, users, graph):
    alice, a_tok = users["alice"]
    svc = await handlers.create_service(alice, None, a_tok)
    assert await svc.initialize()
    await svc.close()
    assert a_tok.closed is False
    # 자신이 연 HTTP 세션만 닫았다
    assert graph.sessions_opened == graph.sessions_closed == 1


async def test_evicting_alice_leaves_bob_untouched(pool, users, graph):
    alice, a_tok = users["alice"]
    bob, b_tok = users["bob"]
    await _call(pool, alice, handlers.handle_get_drive_info, {"user_email": ALICE})
    await _call(pool, bob, handlers.handle_get_drive_info, {"user_email": BOB})

    await pool.invalidate(alice.user_key)

    assert a_tok.closed is True  # 풀이 A 의 차용만 해제했다
    assert b_tok.closed is False
    assert graph.sessions_closed == 1  # A 서비스의 세션만 닫혔다
    res = await _call(pool, bob, handlers.handle_get_drive_info, {"user_email": BOB})
    assert res["drive"]["id"] == "drive-tok-bob"


async def test_mode1_never_falls_back_to_shared_auth_manager(mu):
    with pytest.raises(RuntimeError, match="token_provider"):
        GraphOneDriveClient()
    with pytest.raises(RuntimeError, match="token_provider"):
        await OneDriveService().initialize()


async def test_other_account_email_is_rejected_before_graph(pool, users, graph):
    alice, _ = users["alice"]
    _, b_tok = users["bob"]
    with pytest.raises(SecurityError) as err:
        await _call(pool, alice, handlers.handle_get_drive_info, {"user_email": BOB})
    assert err.value.code == ErrorCode.IDENTITY_MISMATCH
    assert graph.requests == []
    assert b_tok.calls == []


async def test_omitted_email_means_caller(pool, users, graph):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            res = await svc.get_drive_info()
    assert res["drive"]["id"] == "drive-tok-alice"


async def test_service_leased_for_another_user_refuses_request(pool, users, graph):
    alice, _ = users["alice"]
    # 같은 이메일이라도 (tid, oid) 가 다르면 다른 사용자다 (②-10 I05)
    twin = make_principal(ALICE, object_id="00000000-0000-0000-0000-0000000000aa")
    async with pool.lease(DOMAIN, alice) as svc:
        with bound(twin):
            with pytest.raises(SecurityError) as err:
                await svc.get_drive_info()
    assert err.value.code == ErrorCode.IDENTITY_MISMATCH
    assert graph.requests == []


async def test_not_connected_is_raised_not_swallowed(mu, graph):
    carol = make_principal("carol@contoso.com")
    svc = await handlers.create_service(carol, None, FakeTokenProvider(carol, connected=False))
    await svc.initialize()
    try:
        with bound(carol):
            with pytest.raises(SecurityError) as err:
                await svc.list_files()
        assert err.value.code == ErrorCode.GRAPH_NOT_CONNECTED
        assert graph.requests == []
    finally:
        await svc.close()


async def test_logs_omit_error_body_paths_and_email(pool, users, graph, caplog):
    alice, _ = users["alice"]
    caplog.set_level(logging.DEBUG)
    res = await _call(
        pool,
        alice,
        handlers.handle_get_item,
        {"user_email": ALICE, "file_path": "Secret Plans/canary-name.docx"},
    )
    assert res["success"] is False
    logged = caplog.text
    assert "404" in logged and "itemNotFound" in logged
    for secret in ("CANARY-BODY", "canary-name", "Secret Plans", ALICE, "tok-alice"):
        assert secret not in logged


async def test_reads_write_nothing_to_user_files(pool, users, graph, mu):
    alice, _ = users["alice"]
    res = await _call(
        pool, alice, handlers.handle_read_file, {"user_email": ALICE, "file_path": "a/b.txt"}
    )
    assert res["content"] == "content-of-tok-alice"
    files_root = mu / "users" / alice.user_key / "files"
    assert files_root.is_dir()
    assert [p for p in files_root.rglob("*") if p.is_file()] == []
    # 응답에 로컬 절대경로가 없다
    assert str(mu) not in repr(res)


def test_handler_without_lease_fails_closed(mu):
    with pytest.raises(SecurityError) as err:
        handlers._service()
    assert err.value.code == ErrorCode.MISSING_PRINCIPAL


def test_mode0_keeps_legacy_global_service():
    # 모듈 import(mode 0) 시점에 전역 서비스가 만들어졌고 mode 0 핸들러는 그것을 쓴다
    assert isinstance(handlers.onedrive_service, OneDriveService)
    assert handlers._service() is handlers.onedrive_service


# ----------------------------------------------------------------------
# G01 — 호출자 경로가 /me/drive 밖으로 못 나간다 / ②-9 — 오류 원문 비노출
@pytest.mark.parametrize(
    "bad", ["../../users/bob@fabrikam.com", "Docs/../../../users/x", "..", r"a\b", "%2E%2E/x"]
)
async def test_traversal_paths_rejected_before_graph(pool, users, graph, bad):
    alice, _ = users["alice"]
    with pytest.raises(SecurityError) as err:
        await _call(pool, alice, handlers.handle_get_item, {"user_email": ALICE, "file_path": bad})
    assert err.value.code == ErrorCode.NOT_FOUND
    assert graph.requests == []


async def test_failure_payload_has_only_status_and_code(pool, users, graph):
    alice, _ = users["alice"]
    res = await _call(pool, alice, handlers.handle_get_item, {"user_email": ALICE, "file_path": "x.txt"})
    assert res["success"] is False
    assert res["status_code"] == 404 and res["graph_error_code"] == "itemNotFound"
    assert "CANARY-BODY" not in repr(res) and "details" not in res


async def test_transport_exception_text_not_returned(pool, users, graph):
    alice, _ = users["alice"]

    def _boom(*args):
        raise OSError(r"D:\ms365-data\users\secret CANARY-EXC")

    graph.router = _boom
    res = await _call(pool, alice, handlers.handle_list_files, {"user_email": ALICE})
    assert res["success"] is False
    assert "CANARY-EXC" not in repr(res) and "ms365-data" not in repr(res)


# ----------------------------------------------------------------------
# R08 — bearer 요청 redirect 차단 / /content 의 사전 서명 URL 정책 / nextLink 범위
PRESIGNED = "https://download.sharepoint.example/dl?tempauth=t0k"


def _redirect_router(location):
    def router(method, url, token, body):
        if url.endswith(":/content"):
            return FakeResponse(302, None, text="", headers={"Location": location})
        if url == location:
            return FakeResponse(200, body=b"presigned-bytes")
        return _router(method, url, token, body)

    return router


async def test_graph_redirect_on_api_request_is_refused(pool, users, graph):
    alice, _ = users["alice"]
    target = f"{GRAPH}/users/{BOB}/drive"
    graph.router = lambda *a: FakeResponse(302, None, text="", headers={"Location": target})
    res = await _call(pool, alice, handlers.handle_list_files, {"user_email": ALICE})
    assert res["success"] is False and res["status_code"] == 302
    assert len(graph.requests) == 1 and graph.requests[0]["allow_redirects"] is False
    assert BOB not in repr(res)


async def test_write_request_disables_redirects(pool, users, graph):
    alice, _ = users["alice"]
    await _call(pool, alice, handlers.handle_write_file, {"user_email": ALICE, "file_path": "a.txt", "content": "x"})
    (req,) = graph.requests
    assert req["method"] == "PUT" and req["allow_redirects"] is False


def _public_dns(monkeypatch):
    """가짜 호스트가 DNS 로 해석되지 않으므로 공개 주소로 해석된 것처럼 — 네트워크 무관."""
    monkeypatch.setattr(url_policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("93.184.216.34")])


async def test_content_redirect_goes_to_presigned_url_without_bearer(pool, users, graph, monkeypatch):
    _public_dns(monkeypatch)
    alice, _ = users["alice"]
    graph.router = _redirect_router(PRESIGNED)
    res = await _call(pool, alice, handlers.handle_read_file, {"user_email": ALICE, "file_path": "a.txt"})
    assert res["success"] is True and res["content"] == "presigned-bytes"
    first, second = graph.requests
    assert first["authorization"] == "Bearer tok-alice" and first["allow_redirects"] is False
    assert second["url"] == PRESIGNED
    assert second["authorization"] is None, "사전 서명 URL 에 Graph bearer 가 붙었다"
    assert second["allow_redirects"] is False


@pytest.mark.parametrize(
    "location",
    [
        "http://download.sharepoint.example/dl",  # https 아님
        "https://127.0.0.1/dl",
        "https://10.0.0.5/dl",
        "https://[::1]/dl",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/dl",
        "https://intranet/dl",  # 단일 라벨 호스트
        "https://user:pw@download.sharepoint.example/dl",
        "https://download.sharepoint.example:8443/dl",
        "",
    ],
)
async def test_unsafe_presigned_location_is_not_fetched(pool, users, graph, location):
    alice, _ = users["alice"]
    graph.router = _redirect_router(location)
    res = await _call(pool, alice, handlers.handle_read_file, {"user_email": ALICE, "file_path": "a.txt"})
    assert res["success"] is False and res["status_code"] == 302
    assert len(graph.requests) == 1  # 두 번째 요청이 나가지 않았다
    assert not location or location not in repr(res)


async def test_presigned_url_second_redirect_is_not_followed(pool, users, graph, monkeypatch):
    _public_dns(monkeypatch)
    alice, _ = users["alice"]

    def router(method, url, token, body):
        if url.endswith(":/content"):
            return FakeResponse(302, None, text="", headers={"Location": PRESIGNED})
        return FakeResponse(302, None, text="", headers={"Location": "https://evil.example/x"})

    graph.router = router
    res = await _call(pool, alice, handlers.handle_read_file, {"user_email": ALICE, "file_path": "a.txt"})
    assert res["success"] is False and res["status_code"] == 302
    assert len(graph.requests) == 2 and "evil.example" not in repr(res)


async def test_next_link_scope(pool, users, graph):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            for bad in (
                f"{GRAPH}/users/{BOB}/drive/root/children",
                f"{GRAPH}/me/drive/root/children/../../../../users/{BOB}/drive",
                f"{GRAPH}/me/events",  # 드라이브 범위 밖
                "http://graph.microsoft.com/v1.0/me/drive/root/children",
            ):
                with pytest.raises(SecurityError) as err:
                    await svc._client.fetch_next_link(ALICE, bad)
                assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
            assert graph.requests == []
            ok = await svc._client.fetch_next_link(ALICE, f"{GRAPH}/me/drive/root/children?$skiptoken=x")
    assert ok["success"] and ok["files"][0]["name"] == "file-of-tok-alice"
    (req,) = graph.requests
    assert req["token"] == "tok-alice" and req["allow_redirects"] is False


# ----------------------------------------------------------------------
# R02 — limit 상한: 스키마와 서비스 경계 둘 다
def _payload(exc):
    return getattr(exc, "payload", None) or exc.args[0]


def test_schema_declares_limit_bounds():
    (tool,) = [t for t in handlers.MCP_TOOLS if t["name"] == "handler_onedrive_list_files"]
    limit = tool["inputSchema"]["properties"]["limit"]
    assert limit["minimum"] == 1 and limit["maximum"] == 1000


@pytest.mark.parametrize("limit", [0, -1, 1001, 10**12])
async def test_runtime_rejects_limit_outside_schema_bounds_before_handler(graph, limit):
    with pytest.raises(ToolExecutionError):
        await handlers.runtime.call("handler_onedrive_list_files", {"limit": limit})
    assert graph.requests == []


@pytest.mark.parametrize("limit", [0, -1, 1001, 10**12, "many", True])
async def test_service_rejects_limit_outside_bounds_before_graph(pool, users, graph, limit):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            with pytest.raises(ToolExecutionError) as err:
                await svc.list_files(limit=limit)
    assert _payload(err.value)["error"] == "invalid_argument"
    assert graph.requests == []


# ----------------------------------------------------------------------
# N01 — 2단계 작업(대상 폴더 조회 → 복사 POST)은 요청마다 토큰을 다시 받는다
async def test_revocation_between_lookup_and_copy_stops_the_post(pool, users, graph):
    alice, a_tok = users["alice"]

    def router(method, url, token, body):
        if url.endswith("root:/Backup"):
            a_tok.connected = False  # 폴더 조회 응답 시점에 연결 해제·폐기
            return FakeResponse(200, {"id": "folder-1", "name": "Backup"})
        return FakeResponse(202, None, text="", headers={"Location": f"{GRAPH}/monitor"})

    graph.router = router
    with pytest.raises(SecurityError) as err:
        await _call(
            pool, alice, handlers.handle_copy_file,
            {"user_email": ALICE, "source_path": "a.txt", "dest_path": "Backup"},
        )
    assert err.value.code == ErrorCode.GRAPH_NOT_CONNECTED
    assert [r["method"] for r in graph.requests] == ["GET"]  # 복사 POST 는 나가지 않았다
    assert a_tok.calls.count("validate_and_refresh_token") == 2  # 두 번째 획득 시도에서 거부


async def test_revocation_after_content_redirect_blocks_presigned_get(pool, users, graph, monkeypatch):
    """N01 읽기 경로 — bearer 응답(302) 뒤 폐기되면 사전 서명 GET 은 나가지 않는다."""
    _public_dns(monkeypatch)
    alice, a_tok = users["alice"]

    def router(method, url, token, body):
        if url.endswith(":/content"):
            a_tok.connected = False  # 첫 bearer 응답 시점에 연결 해제·폐기
            return FakeResponse(302, None, text="", headers={"Location": PRESIGNED})
        raise AssertionError("폐기 뒤 사전 서명 GET 이 나갔다")

    graph.router = router
    with pytest.raises(SecurityError) as err:
        await _call(pool, alice, handlers.handle_read_file, {"user_email": ALICE, "file_path": "a.txt"})
    assert err.value.code in (ErrorCode.GRAPH_NOT_CONNECTED, ErrorCode.ACCOUNT_INACTIVE)
    assert [r["url"].endswith(":/content") for r in graph.requests] == [True]
    assert a_tok.calls.count("validate_and_refresh_token") == 2  # 302 뒤 재획득 시도에서 거부
