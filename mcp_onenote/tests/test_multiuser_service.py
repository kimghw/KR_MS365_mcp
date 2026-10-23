"""
OneNote 멀티유저 서비스 격리 (spec/spec_멀티유저.md ②-7.6, ②-10 D01–D03·L01).

- factory(`create_service`)가 사용자별 DB 파일·토큰 공급자로 서비스를 만든다.
- MCP 진입점은 호출 principal = 서비스 소유자, user_email = 연결 계정을 확인한다.
- A 가 B 의 page_id 로 요약 조회·삭제(Graph 404)해도 B 의 요약·이력은 그대로다.
- mode 0 핸들러 경로의 요약 조회·삭제도 호출자 범위다(IDOR 회귀).

Graph 는 부르지 않는다 — 클라이언트 메서드를 가짜로 바꾼다.
"""

import logging
from unittest.mock import AsyncMock

import pytest

import mcp_onenote.graph_onenote_client as graph_mod
import mcp_onenote.onenote_agent as agent_mod
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_context import bind_service
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode
from mcp_common.user_paths import ensure_user_dirs, paths_for
from mcp_onenote.graph_onenote_client import GraphOneNoteClient
from mcp_onenote.mcp_server import handlers
from mcp_onenote.onenote_service import OneNoteService

A = "alice@contoso.com"
B = "bob@contoso.com"


@pytest.fixture(autouse=True)
def _no_sdk(monkeypatch):
    # 요약 SDK 를 실제로 부르지 않는다
    monkeypatch.setattr(agent_mod, "is_sdk_available", lambda: False)


@pytest.fixture
def mu(tmp_path):
    with multi_user_mode(tmp_path / "root") as root:
        yield root


async def _user_service(principal):
    paths = ensure_user_dirs(paths_for(principal))
    tokens = FakeTokenProvider(principal)
    svc = await handlers.create_service(principal, paths, tokens)
    assert await svc.initialize()
    return svc, tokens


def _summary(svc, email, page_id, text):
    assert svc._db_service.save_summary(
        page_id=page_id, user_id=email, page_title="t", summary=text,
        paragraph_summaries=[], keywords=[], content_hash="h",
    )


@pytest.fixture
async def users(mu):
    alice, bob = make_principal(A), make_principal(B)
    a_svc, a_tok = await _user_service(alice)
    b_svc, b_tok = await _user_service(bob)
    yield {"alice": alice, "bob": bob, "a": a_svc, "b": b_svc, "a_tok": a_tok, "b_tok": b_tok}
    await a_svc.close()
    await b_svc.close()


class TestFactoryIsolation:
    async def test_factory_constructs_only(self, mu):
        alice = make_principal(A)
        paths = paths_for(alice)  # 디렉터리를 만들지 않는다
        svc = await handlers.create_service(alice, paths, FakeTokenProvider(alice))
        assert isinstance(svc, OneNoteService)
        assert svc._db_service is None and svc._client is None
        assert not paths.onenote_db.exists()

    async def test_users_get_separate_db_files_and_providers(self, users):
        a, b = users["a"], users["b"]
        assert a._db_service.db_path != b._db_service.db_path
        assert a._db_service.db_path == str(paths_for(users["alice"]).onenote_db)
        assert b._db_service.db_path == str(paths_for(users["bob"]).onenote_db)
        assert a._client.token_provider is users["a_tok"]
        assert b._client.token_provider is users["b_tok"]
        assert a._agent is not b._agent  # 요약 에이전트도 사용자별

    async def test_close_does_not_close_token_provider(self, users):
        await users["a"].close()
        assert users["a_tok"].closed is False  # 공급자는 풀이 닫는다
        assert users["b"]._client is not None  # 다른 사용자 서비스는 영향 없음

    async def test_pool_lease_isolates_and_releases(self, mu):
        pool = UserServicePool(token_provider_factory=FakeTokenProvider)
        pool.register(handlers.SERVER_NAME, handlers.create_service)
        alice, bob = make_principal(A), make_principal(B)
        async with pool.lease(handlers.SERVER_NAME, alice) as a_svc:
            async with pool.lease(handlers.SERVER_NAME, bob) as b_svc:
                assert a_svc is not b_svc
                assert a_svc._db_service.db_path != b_svc._db_service.db_path
                a_tok = a_svc._client.token_provider
                assert a_tok.principal == alice
        await pool.close()
        assert a_tok.closed is True

    def test_graph_client_without_provider_fails_in_mode1(self, mu):
        with pytest.raises(SecurityError) as exc:
            GraphOneNoteClient()
        assert exc.value.code == ErrorCode.MISSING_PRINCIPAL


class TestCallerChecks:
    async def test_other_users_email_is_identity_mismatch(self, users):
        with bound(users["alice"]):
            with pytest.raises(SecurityError) as exc:
                await users["a"].read_onenote(user_email=B, action="get_summary", page_id="P1")
        assert exc.value.code == ErrorCode.IDENTITY_MISMATCH

    async def test_service_of_other_principal_is_not_found(self, users):
        with bound(users["bob"]):
            with pytest.raises(SecurityError) as exc:
                await users["a"].read_onenote(user_email=B, action="get_summary", page_id="P1")
        assert exc.value.code == ErrorCode.NOT_FOUND

    async def test_omitted_email_uses_callers_own_account(self, users):
        _summary(users["a"], A, "P1", "alice")
        with bound(users["alice"]):
            result = await users["a"].read_onenote(user_email=None, action="get_summary", page_id="P1")
        assert result["has_summary"] is True and result["summary"] == "alice"

    async def test_token_request_never_looks_up_default_user(self, users, monkeypatch):
        def _forbidden():
            raise AssertionError("mode 1 에서 기본 사용자 조회 금지")

        monkeypatch.setattr(graph_mod, "get_default_user_email", _forbidden)
        token = await users["a"]._client._get_access_token(None)
        assert token == users["a_tok"].token

    async def test_token_mismatch_propagates(self, users):
        with pytest.raises(SecurityError) as exc:
            await users["a"]._client._get_access_token(B)
        assert exc.value.code == ErrorCode.IDENTITY_MISMATCH

    async def test_next_link_off_graph_host_gets_no_token(self, users):
        before = list(users["a_tok"].calls)
        with pytest.raises(SecurityError) as exc:
            await users["a"]._client._make_request_full_url("https://evil.example/v1.0/me/onenote/pages")
        assert exc.value.code == ErrorCode.PATH_NOT_ALLOWED
        assert users["a_tok"].calls == before


class TestDataIsolation:
    async def test_d01_reading_other_users_page_summary_gets_nothing(self, users):
        _summary(users["b"], B, "P-B", "bob-secret")
        with bound(users["alice"]):
            result = await users["a"].read_onenote(user_email=A, action="get_summary", page_id="P-B")
        assert result["has_summary"] is False
        assert "bob-secret" not in str(result)
        with bound(users["bob"]):
            mine = await users["b"].read_onenote(user_email=B, action="get_summary", page_id="P-B")
        assert mine["summary"] == "bob-secret"

    async def test_d02_delete_with_graph_404_keeps_other_users_rows(self, users):
        b = users["b"]
        _summary(b, B, "P1", "bob")
        b._db_service.save_item(B, "page", "P1", "Bob page")
        b._db_service.save_page_change(page_id="P1", user_id=B, action="append")
        _summary(users["a"], A, "P1", "alice")  # A 자신의 같은 page_id 행

        users["a"]._client.delete_page = AsyncMock(
            return_value={"success": False, "status_code": 404, "error": "API 요청 실패: 404"}
        )
        with bound(users["alice"]):
            result = await users["a"].delete_onenote(user_email=A, page_id="P1")

        assert result["already_deleted"] is True
        assert users["a"]._db_service.get_summary("P1", user_id=A) is None  # 자기 것만 정리
        assert b._db_service.get_summary("P1", user_id=B)["summary"] == "bob"
        assert [i["item_id"] for i in b._db_service.list_items(B)] == ["P1"]
        assert len(b._db_service.get_page_changes("P1", user_id=B)) == 1

    async def test_d03_same_page_id_keeps_independent_summary_and_history(self, users):
        for key, email in (("a", A), ("b", B)):
            svc = users[key]
            svc._client.update_page = AsyncMock(return_value={"success": True})
            with bound(users["alice" if key == "a" else "bob"]):
                result = await svc.write_onenote(
                    user_email=email, action="append", page_id="P1", content=f"<p>{key}</p>"
                )
            assert result["success"] is True
            _summary(svc, email, "P1", f"summary-{key}")

        a_hist = users["a"].reader.get_page_history(A, "P1")
        b_hist = users["b"].reader.get_page_history(B, "P1")
        assert a_hist["count"] == 1 and b_hist["count"] == 1
        assert a_hist["changes"][0]["content_snippet"] == "<p>a</p>"
        assert b_hist["changes"][0]["content_snippet"] == "<p>b</p>"
        with bound(users["alice"]):
            a_sum = await users["a"].read_onenote(user_email=A, action="get_summary", page_id="P1")
        with bound(users["bob"]):
            b_sum = await users["b"].read_onenote(user_email=B, action="get_summary", page_id="P1")
        assert (a_sum["summary"], b_sum["summary"]) == ("summary-a", "summary-b")


class TestHandlerWiring:
    async def test_handler_uses_leased_service(self, users):
        _summary(users["a"], A, "P1", "alice")
        with bound(users["alice"]), bind_service(handlers.SERVER_NAME, users["a"]):
            result = await handlers.handle_read_onenote(
                {"user_email": A, "action": "get_summary", "page_id": "P1"}
            )
        assert result["summary"] == "alice"

    async def test_handler_without_lease_never_falls_back(self, users):
        with bound(users["alice"]):
            with pytest.raises(SecurityError) as exc:
                await handlers.handle_sync_onenote_db({"user_email": A})
        assert exc.value.code == ErrorCode.MISSING_PRINCIPAL

    def test_sync_tool_binds_facade(self):
        tool = next(t for t in handlers.SPEC.tools if t.name == "sync_onenote_db")
        assert tool.service == "OneNoteService.sync_db"
        assert hasattr(OneNoteService, "sync_db")

    def test_user_email_contract_unchanged(self):
        for tool in handlers.MCP_TOOLS:
            schema = tool["inputSchema"]
            prop = schema["properties"]["user_email"]
            assert prop["type"] == "string"
            assert "user_email" not in schema.get("required", [])
            assert "다른 계정은 선택할 수 없다" in prop["description"]


class TestMode0Regression:
    """mode 0 (단일 운영자) 공용 DB 에서도 요약 조회·삭제·이력은 호출자 범위다."""

    @pytest.fixture
    async def legacy(self, tmp_path):
        svc = OneNoteService(db_path=str(tmp_path / "onenote.db"), token_provider=AsyncMock())
        assert await svc.initialize()
        yield svc
        await svc.close()

    async def test_summary_read_idor_fixed(self, legacy):
        _summary(legacy, B, "P-B", "bob-secret")
        result = await legacy.read_onenote(user_email=A, action="get_summary", page_id="P-B")
        assert result["has_summary"] is False

    async def test_summary_delete_idor_fixed(self, legacy):
        _summary(legacy, B, "P-B", "bob-secret")
        legacy._db_service.save_page_change(page_id="P-B", user_id=B, action="append")
        legacy._client.delete_page = AsyncMock(return_value={"success": False, "status_code": 404})
        result = await legacy.delete_onenote(user_email=A, page_id="P-B")
        assert result["already_deleted"] is True
        assert legacy._db_service.get_summary("P-B", user_id=B)["summary"] == "bob-secret"
        assert len(legacy._db_service.get_page_changes("P-B", user_id=B)) == 1

    async def test_successful_delete_only_removes_callers_summary(self, legacy):
        _summary(legacy, A, "P1", "alice")
        _summary(legacy, B, "P1", "bob")
        legacy._client.delete_page = AsyncMock(return_value={"success": True})
        await legacy.delete_onenote(user_email=A, page_id="P1")
        assert legacy._db_service.get_summary("P1", user_id=A) is None
        assert legacy._db_service.get_summary("P1", user_id=B)["summary"] == "bob"

    async def test_page_history_is_owner_scoped(self, legacy):
        legacy._db_service.save_page_change(page_id="P1", user_id=B, action="append")
        assert legacy.reader.get_page_history(A, "P1")["count"] == 0
        assert legacy.reader.get_page_history(B, "P1")["count"] == 1


class _FakeResponse:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def json(self):
        return {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, response):
        self._response = response

    def request(self, *args, **kwargs):
        return self._response

    get = post = request

    async def close(self):
        pass


async def test_graph_error_log_has_code_but_not_body_or_ids(caplog):
    body = '{"error":{"code":"itemNotFound","message":"SECRET-BODY about SECRET-PAGE"}}'
    client = GraphOneNoteClient(token_provider=AsyncMock(validate_and_refresh_token=AsyncMock(return_value="t")))
    client._session = _FakeSession(_FakeResponse(404, body))
    client._initialized = True
    caplog.set_level(logging.DEBUG, logger="mcp_onenote")

    result = await client.delete_page("0-SECRET-PAGE", A)
    await client.get_page_content("0-SECRET-PAGE", A)

    assert result["status_code"] == 404
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "itemNotFound" in text
    for secret in ("SECRET-BODY", "SECRET-PAGE", A):
        assert secret not in text


# ----------------------------------------------------------------------
# 런타임 경유 (WP1 ToolRuntime → 서비스 풀 lease → 핸들러)
# ----------------------------------------------------------------------
@pytest.fixture
async def runtime_pool(mu, monkeypatch):
    from mcp_common.service_pool import get_service_pool, reset_service_pool_for_tests

    async def _active(principal):
        return None

    monkeypatch.setattr(handlers.runtime, "active_checker", _active)
    reset_service_pool_for_tests(UserServicePool(token_provider_factory=FakeTokenProvider))
    pool = get_service_pool()
    yield pool
    await pool.close()
    reset_service_pool_for_tests()


def _payload(blocks):
    import json

    return json.loads(blocks[0]["text"])


class TestRuntimeEndToEnd:
    async def test_d01_through_runtime_dispatch(self, runtime_pool):
        alice, bob = make_principal(A), make_principal(B)
        async with runtime_pool.lease(handlers.SERVER_NAME, bob) as b_svc:
            _summary(b_svc, B, "P-B", "bob-secret")

        with bound(alice):  # user_email 생략 → 호출자 본인
            out = _payload(await handlers.runtime.call(
                "read_onenote", {"action": "get_summary", "page_id": "P-B"}
            ))
        assert out["has_summary"] is False and "bob-secret" not in str(out)

        with bound(bob):
            out = _payload(await handlers.runtime.call(
                "read_onenote", {"user_email": B, "action": "get_summary", "page_id": "P-B"}
            ))
        assert out["summary"] == "bob-secret"

    async def test_other_account_email_rejected_through_runtime(self, runtime_pool):
        with bound(make_principal(A)):
            with pytest.raises(SecurityError) as exc:
                await handlers.runtime.call(
                    "read_onenote", {"user_email": B, "action": "get_summary", "page_id": "P"}
                )
        assert exc.value.code == ErrorCode.IDENTITY_MISMATCH


# ----------------------------------------------------------------------
# G01 — 호출자 ID 가 Graph 경로 구조를 바꾸지 못한다 / ②-9 오류 본문 비노출 (두 모드 공통)
# ----------------------------------------------------------------------
class _RecordingSession(_FakeSession):
    def __init__(self, response):
        super().__init__(response)
        self.urls = []
        self.kwargs = []

    def request(self, method, url, *args, **kwargs):
        self.urls.append(url)
        self.kwargs.append(kwargs)
        return self._response

    def get(self, url, *args, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, *args, **kwargs):
        return self.request("POST", url, **kwargs)


def _recording_client(status=404, body='{"error":{"code":"itemNotFound","message":"x"}}'):
    provider = AsyncMock(validate_and_refresh_token=AsyncMock(return_value="t"))
    client = GraphOneNoteClient(token_provider=provider)
    client._session = _RecordingSession(_FakeResponse(status, body))
    client._initialized = True
    return client, provider


def _id_calls(client, value):
    from mcp_onenote.onenote_types import PageAction

    return [
        lambda: client.get_page_content(value, A),
        lambda: client.delete_page(value, A),
        lambda: client.update_page(value, PageAction.APPEND, "<p>x</p>", user_email=A),
        lambda: client.list_pages(A, section_id=value),
        lambda: client.list_sections(A, notebook_id=value),
        lambda: client.create_section(value, "name", A),
        lambda: client.create_page(value, "title", "<p>x</p>", A),
    ]


@pytest.mark.parametrize("value", ["..", ".", "%2E%2E", "a\x00b"])
async def test_dot_segment_ids_are_rejected_before_any_token(value):
    client, provider = _recording_client()
    for call in _id_calls(client, value):
        with pytest.raises(SecurityError) as exc:
            await call()
        assert exc.value.code == ErrorCode.NOT_FOUND
    provider.validate_and_refresh_token.assert_not_awaited()
    assert client._session.urls == []


@pytest.mark.parametrize("value", [f"../../users/{B}", "..\\..\\users\\" + B, "../../../../$batch"])
async def test_slash_ids_stay_one_segment_under_me(value):
    from yarl import URL

    client, _ = _recording_client()
    for call in _id_calls(client, value):
        await call()
    assert client._session.urls
    for url in client._session.urls:
        raw = URL(url).raw_path  # aiohttp 가 실제로 보내는 (dot-segment 정규화 후) 경로
        assert raw.startswith("/v1.0/me/onenote/"), url
        assert ".." not in raw.split("/"), url
        assert "/users/" not in raw  # %2F 로 인코딩돼 한 성분 안에 남는다


async def test_next_link_with_dot_segments_is_not_followed():
    client, provider = _recording_client()
    for link in (
        f"https://graph.microsoft.com/v1.0/me/../users/{B}/onenote/pages",
        f"https://graph.microsoft.com/v1.0/me/%2E%2E/users/{B}/onenote/pages",
        "https://graph.microsoft.com/beta/me/onenote/pages",
    ):
        with pytest.raises(SecurityError):
            await client._make_request_full_url(link, A)
    provider.validate_and_refresh_token.assert_not_awaited()


async def test_graph_error_body_is_not_returned():
    body = '{"error":{"code":"InternalServerError","message":"CANARY-BODY"}}'
    client, _ = _recording_client(500, body)
    results = [
        await client.list_sections(A),
        await client.get_page_content("0-p", A),
        await client.create_page("0-s", "t", "<p>x</p>", A),
        await client._make_request_full_url("https://graph.microsoft.com/v1.0/me/onenote/pages?$skip=1", A),
    ]
    for result in results:
        assert result["success"] is False
        assert "CANARY-BODY" not in str(result) and "details" not in result
        assert result["status_code"] == 500 and result["graph_error_code"] == "InternalServerError"


# ----------------------------------------------------------------------
# R08 — bearer 요청은 redirect 를 따라가지 않고, nextLink 는 호출자의 OneNote 경로(GET)만 따라간다
# ----------------------------------------------------------------------
from mcp_common.graph_url_policy import check_next_link  # noqa: E402


async def test_redirects_are_not_followed_and_not_leaked():
    client, _ = _recording_client(302, "")
    calls = _id_calls(client, "0-p") + [
        lambda: client.list_sections(A),
        lambda: client._make_request_full_url("https://graph.microsoft.com/v1.0/me/onenote/pages?$skip=1", A),
    ]
    for call in calls:
        result = await call()
        assert result["success"] is False and result["status_code"] == 302, result
        assert "Location" not in str(result) and "details" not in result
    assert len(client._session.kwargs) == len(calls)
    assert all(k.get("allow_redirects") is False for k in client._session.kwargs)


@pytest.mark.parametrize("link", [
    f"https://graph.microsoft.com/v1.0/users/{B}/onenote/pages?$skip=10",   # 다른 사용자
    "https://graph.microsoft.com/v1.0/me/messages?$skip=10",               # 다른 도메인
    "https://graph.microsoft.com/v1.0/users/onenote/pages",
    "http://graph.microsoft.com/v1.0/me/onenote/pages",
    "https://graph.microsoft.com.evil.example/v1.0/me/onenote/pages",
    "https://graph.microsoft.com/beta/me/onenote/pages",
    f"https://graph.microsoft.com/v1.0/me/onenote/../../users/{B}/onenote/pages",
    # 공용 정책이 더 엄격한 것들 (N05): userinfo·비표준 포트·디코딩하면 slash 가 되는 성분
    "https://user@graph.microsoft.com/v1.0/me/onenote/pages",
    "https://graph.microsoft.com:8443/v1.0/me/onenote/pages",
    f"https://graph.microsoft.com/v1.0/me/onenote%2F..%2Fusers%2F{B}%2Fonenote/pages",
    f"https://graph.microsoft.com/v1.0/me/%2E%2E/users/{B}/onenote/pages",
])
async def test_next_link_outside_callers_onenote_is_refused(link):
    client, provider = _recording_client()
    with pytest.raises(SecurityError) as exc:
        await client._make_request_full_url(link, A)
    assert exc.value.code == ErrorCode.PATH_NOT_ALLOWED
    provider.validate_and_refresh_token.assert_not_awaited()
    assert client._session.urls == []


@pytest.mark.parametrize("link", [
    "https://graph.microsoft.com/v1.0/me/onenote/pages?$skip=10",
    f"https://graph.microsoft.com/v1.0/users/{A}/onenote/sections?$skip=5",
    "https://graph.microsoft.com/v1.0/users/ALICE%40contoso.com/onenote/pages",
])
async def test_next_link_within_callers_onenote_is_followed(link):
    client, provider = _recording_client()
    await client._make_request_full_url(link, A)
    provider.validate_and_refresh_token.assert_awaited_once()
    assert client._session.urls == [link]


def test_next_link_accepts_callers_own_oid_form_in_mode1(tmp_path):
    """mode 1 에서는 principal 의 oid 형식 `/users/{oid}/onenote/...` 도 본인으로 본다; 남의 oid 는 거부."""
    alice, bob = make_principal(A), make_principal(B)
    onenote = frozenset({"onenote"})
    with multi_user_mode(tmp_path / "root"), bound(alice):
        own = f"https://graph.microsoft.com/v1.0/users/{alice.object_id}/onenote/pages?$skip=1"
        assert check_next_link(own, None, resources=onenote) == own
        with pytest.raises(SecurityError):
            check_next_link(f"https://graph.microsoft.com/v1.0/users/{bob.object_id}/onenote/pages", None, resources=onenote)
        with pytest.raises(SecurityError):
            check_next_link(f"https://graph.microsoft.com/v1.0/users/{B}/onenote/pages", None, resources=onenote)
    # 호출자를 모르면(mode 0, 이메일 없음) /users/{id} 형식은 받지 않는다
    with pytest.raises(SecurityError):
        check_next_link(f"https://graph.microsoft.com/v1.0/users/{A}/onenote/pages", None, resources=onenote)


# ----------------------------------------------------------------------
# R02 — top 은 결과 슬라이스가 아니라 작업량(DB 행·Graph 페이지·LLM 판정)을 묶는다
# N01 — 토큰은 요청 직전에 매번 공급자에서 받는다: 페이징 사이에 폐기되면 다음 요청이 나가지 않는다
# ----------------------------------------------------------------------
import json as _json  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from mcp_common.errors import ToolExecutionError  # noqa: E402
from mcp_onenote.onenote_db_service import OneNoteDBService  # noqa: E402
from mcp_onenote.onenote_read import OneNoteReader  # noqa: E402
from mcp_onenote.onenote_types import check_top  # noqa: E402


def _invalid(exc_info):
    payload = exc_info.value.payload
    assert payload["error"] == "invalid_argument", payload
    return payload


@pytest.mark.parametrize("bad", [0, -1, 501, "abc", True, None, 2.5])
def test_check_top_rejects_out_of_range(bad):
    with pytest.raises(ToolExecutionError) as exc:
        check_top(bad)
    _invalid(exc)


def test_check_top_accepts_range_and_numeric_strings():
    assert check_top(1) == 1 and check_top(500) == 500 and check_top(" 42 ") == 42


async def test_read_onenote_rejects_bad_top_before_any_work(tmp_path):
    svc = OneNoteService(db_path=str(tmp_path / "onenote.db"), token_provider=AsyncMock())
    assert await svc.initialize()
    svc._db_service.list_items = MagicMock(return_value=[])
    for bad in (0, 501):
        with pytest.raises(ToolExecutionError) as exc:
            await svc.read_onenote(user_email=A, action="list_pages", top=bad)
        _invalid(exc)
    svc._db_service.list_items.assert_not_called()
    await svc.close()


def test_db_list_items_pushes_filters_and_limit_into_sql(tmp_path):
    db = OneNoteDBService(str(tmp_path / "onenote.db"))
    for i in range(6):
        db.save_item(A, "page", f"P{i}", f"t{i}", notebook_id="nb1" if i % 2 else "nb2", update_accessed=True)
    assert len(db.list_items(A, "page")) == 6
    assert len(db.list_items(A, "page", limit=2)) == 2
    assert {r["notebook_id"] for r in db.list_items(A, "page", notebook_id="nb1")} == {"nb1"}
    stamps = sorted(r["last_accessed"] for r in db.list_items(A, "page"))
    since = db.list_items(A, "page", date_from=stamps[-1])
    assert since and all(r["last_accessed"] >= stamps[-1] for r in since)
    assert db.list_items(A, "page", date_to="2000-01-01T00:00:00Z") == []
    # NULL last_accessed 는 '' 로 본다 — date_to 만 주면 포함, date_from 을 주면 제외 (기존 Python 필터와 같다)
    db.save_item(A, "page", "P-null", "n")
    assert "P-null" in {r["item_id"] for r in db.list_items(A, "page", date_to="2999-01-01")}
    assert "P-null" not in {r["item_id"] for r in db.list_items(A, "page", date_from="2000-01-01")}


async def test_reader_bounds_db_rows_and_search_pages_by_top():
    db = MagicMock()
    db.list_items = MagicMock(return_value=[])
    agent = AsyncMock()
    agent.search_pages = AsyncMock(return_value={"success": True, "results": [], "count": 0})
    reader = OneNoteReader(AsyncMock(), db, agent, writer=None)

    await reader.list_pages(A, section_id="s1", notebook_id="nb", date_from="2026-01-01", top=7)
    db.list_items.assert_called_once_with(
        user_id=A, item_type="page", section_id="s1", notebook_id="nb",
        date_from="2026-01-01", date_to=None, limit=7,
    )
    await reader.search(A, "q", top=3)
    assert agent.search_pages.await_args.kwargs["max_pages"] == 3
    with pytest.raises(ToolExecutionError):
        await reader.list_pages(A, top=0)
    with pytest.raises(ToolExecutionError):
        await reader.search(A, "q", top=501)


class _JsonResponse(_FakeResponse):
    def __init__(self, status, payload):
        super().__init__(status, _json.dumps(payload))
        self._payload = payload

    async def json(self):
        return self._payload


class _SeqSession(_FakeSession):
    """응답을 차례대로 돌려주고 요청을 기록한다."""

    def __init__(self, responses):
        super().__init__(None)
        self._responses = list(responses)
        self.urls = []
        self.kwargs = []

    def request(self, method, url, *args, **kwargs):
        self.urls.append(url)
        self.kwargs.append(kwargs)
        return self._responses.pop(0)

    def get(self, url, *args, **kwargs):
        return self.request("GET", url, **kwargs)


_NEXT = "https://graph.microsoft.com/v1.0/me/onenote/pages?$skip={}"


def _page(ids, next_skip=None):
    payload = {"value": [{"id": f"0-{i}", "title": f"t{i}"} for i in ids]}
    if next_skip is not None:
        payload["@odata.nextLink"] = _NEXT.format(next_skip)
    return _JsonResponse(200, payload)


async def test_client_list_pages_stops_paging_at_max_pages():
    provider = AsyncMock(validate_and_refresh_token=AsyncMock(return_value="t"))
    client = GraphOneNoteClient(token_provider=provider)
    client._session = _SeqSession([_page([1, 2], 2), _page([3, 4], 4), _page([5, 6])])
    client._initialized = True

    result = await client.list_pages(A, max_pages=3)

    assert result["count"] == 3 and result["capped"] is True
    assert [p["id"] for p in result["pages"]] == ["0-1", "0-2", "0-3"]
    assert len(client._session.urls) == 2          # 세 번째 페이지는 가져오지 않았다
    assert "$top=3" in client._session.urls[0]      # 페이지 크기도 상한 이하


async def test_client_list_pages_without_cap_follows_all_pages():
    provider = AsyncMock(validate_and_refresh_token=AsyncMock(return_value="t"))
    client = GraphOneNoteClient(token_provider=provider)
    client._session = _SeqSession([_page([1, 2], 2), _page([3, 4], 4), _page([5, 6])])
    client._initialized = True
    result = await client.list_pages(A)
    assert result["count"] == 6 and "capped" not in result
    assert len(client._session.urls) == 3


class _RevokingProvider(FakeTokenProvider):
    """n 번째 토큰 발급 직후 연결이 폐기된 공급자 — 이후 발급은 graph_not_connected."""

    def __init__(self, principal, *, revoke_after: int):
        super().__init__(principal)
        self._revoke_after = revoke_after

    async def validate_and_refresh_token(self, email=None, auto_reauth=False):
        token = await super().validate_and_refresh_token(email, auto_reauth)
        if self.calls.count("validate_and_refresh_token") >= self._revoke_after:
            self.connected = False
        return token


async def test_n01_revocation_between_pages_stops_further_requests():
    provider = _RevokingProvider(make_principal(A), revoke_after=1)
    client = GraphOneNoteClient(token_provider=provider)
    client._session = _SeqSession([_page([1, 2], 2), _page([3, 4])])
    client._initialized = True

    with pytest.raises(SecurityError) as exc:
        await client.list_pages(A)

    assert exc.value.code == ErrorCode.GRAPH_NOT_CONNECTED
    assert len(client._session.urls) == 1  # 두 번째 페이지 요청은 나가지 않았다
