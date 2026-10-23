"""Calendar 멀티유저 격리 (spec/spec_멀티유저.md ②-2.4·②-7.6·②-10 C01·L01, WP8).

네트워크 없음 — `FakeTokenProvider` + 가짜 Graph 세션(`_fake_graph`). 공용 AuthManager
(`get_shared_auth_manager`)와 legacy 기본 사용자 선택은 호출되면 실패하도록 막아 둔다.
"""

import asyncio
import importlib
import inspect
import logging

import pytest

import mcp_common.auth as common_auth
from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError
from mcp_common.service_context import bind_service
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode
from mcp_common.user_resolver import UserResolver

from mcp_calendar.calendar_service import CalendarService

# `import mcp_calendar.calendar_service as x` 는 패키지 속성(= legacy 싱글톤)을 돌려주므로 모듈은 importlib 로
service_mod = importlib.import_module("mcp_calendar.calendar_service")
assert inspect.ismodule(service_mod)
from mcp_calendar.graph_calendar_client import GraphCalendarClient
from mcp_calendar.graph_calendar_query import GraphCalendarQuery, GraphCalendarUrlBuilder
from mcp_calendar.mcp_server import handlers
from mcp_calendar.tests._fake_graph import FakeGraph, FakeResponse, Rendezvous

GRAPH = "https://graph.microsoft.com/v1.0"
ALICE = "alice@contoso.com"
BOB = "bob@fabrikam.com"
DOMAIN = handlers.SERVER_NAME
VIEW_ARGS = {"start_datetime": "2026-10-01T00:00:00", "end_datetime": "2026-10-02T00:00:00"}


def _router(method, url, token, body):
    if method == "GET" and ("/calendar/calendarView?" in url or "/events?" in url):
        return FakeResponse(200, {"value": [{"id": f"evt-{token}", "subject": f"meeting of {token}"}]})
    if method == "DELETE" and "/events/" in url:
        return FakeResponse(204)
    return FakeResponse(404, {"error": {"code": "ErrorItemNotFound", "message": "CANARY-BODY board meeting"}})


def _forbidden(*args, **kwargs):
    raise AssertionError("mode 1 경로가 공용 AuthManager·legacy 기본 사용자를 불렀다")


@pytest.fixture
def mu(tmp_path, monkeypatch):
    monkeypatch.setattr(common_auth, "get_shared_auth_manager", _forbidden)
    monkeypatch.setattr(service_mod, "_resolve_user_email", _forbidden)
    monkeypatch.setattr(UserResolver, "default_email", _forbidden)
    with multi_user_mode(tmp_path) as root:
        yield root


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph(_router)
    monkeypatch.setattr(GraphCalendarQuery, "_http_session", lambda self: fake.session_factory())
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

    res_a = await _call(pool, alice, handlers.handle_calendar_view, {"user_email": ALICE, **VIEW_ARGS})
    assert res_a["success"] and res_a["events"][0]["id"] == "evt-tok-alice"
    assert a_tok.calls and b_tok.calls == []

    used_by_alice = len(a_tok.calls)
    res_b = await _call(pool, bob, handlers.handle_list_events, {"user_email": BOB})
    assert res_b["events"][0]["id"] == "evt-tok-bob"
    assert len(a_tok.calls) == used_by_alice
    assert [r["token"] for r in graph.requests] == ["tok-alice", "tok-bob"]


async def test_interleaved_calls_keep_token_and_me_paths(pool, users, graph):
    alice, _ = users["alice"]
    bob, _ = users["bob"]
    graph.gate = Rendezvous(6)

    calls = []
    for _ in range(3):
        calls.append(_call(pool, alice, handlers.handle_calendar_view, {"user_email": ALICE, **VIEW_ARGS}))
        calls.append(_call(pool, bob, handlers.handle_calendar_view, {"user_email": BOB, **VIEW_ARGS}))
    results = await asyncio.gather(*calls)

    for i, res in enumerate(results):
        owner = "tok-alice" if i % 2 == 0 else "tok-bob"
        assert res["events"][0]["id"] == f"evt-{owner}"
        assert res["user"] == (ALICE if i % 2 == 0 else BOB)

    expected = {alice.user_key: "tok-alice", bob.user_key: "tok-bob"}
    assert len(graph.requests) == 6
    for req in graph.requests:
        assert req["token"] == expected[req["principal_key"]]
        assert req["url"].startswith(f"{GRAPH}/me/calendar/calendarView?")
        assert "/users/" not in req["url"]


async def test_service_close_does_not_close_injected_provider(mu, users):
    alice, a_tok = users["alice"]
    svc = await handlers.create_service(alice, None, a_tok)
    assert await svc.initialize()
    await svc.close()
    assert a_tok.closed is False


async def test_query_close_never_closes_provider_in_either_mode(users):
    # 전에는 graph_calendar_query.close() 가 공급자 close() 까지 불렀다 (②-2.4)
    alice, a_tok = users["alice"]
    query = GraphCalendarQuery(token_provider=a_tok)  # mode 0
    await query.close()
    assert a_tok.closed is False


async def test_evicting_alice_leaves_bob_untouched(pool, users, graph):
    alice, a_tok = users["alice"]
    bob, b_tok = users["bob"]
    await _call(pool, alice, handlers.handle_list_events, {"user_email": ALICE})
    await _call(pool, bob, handlers.handle_list_events, {"user_email": BOB})

    await pool.invalidate(alice.user_key)

    assert a_tok.closed is True  # 풀이 A 의 차용만 해제했다
    assert b_tok.closed is False
    res = await _call(pool, bob, handlers.handle_delete_event, {"user_email": BOB, "event_id": "e1"})
    assert res["success"] is True
    assert graph.requests[-1]["url"] == f"{GRAPH}/me/events/e1"


async def test_mode1_never_falls_back_to_shared_auth_manager(mu):
    with pytest.raises(RuntimeError, match="token_provider"):
        GraphCalendarQuery()
    # 서비스 초기화는 False 로 실패를 알린다(공용 AuthManager 로 대체하지 않는다)
    assert await CalendarService().initialize() is False


async def test_other_account_email_is_rejected_before_graph(pool, users, graph):
    alice, _ = users["alice"]
    _, b_tok = users["bob"]
    with pytest.raises(SecurityError) as err:
        await _call(pool, alice, handlers.handle_list_events, {"user_email": BOB})
    assert err.value.code == ErrorCode.IDENTITY_MISMATCH
    assert graph.requests == []
    assert b_tok.calls == []


async def test_omitted_email_means_caller(pool, users, graph):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            res = await svc.list_events()
    assert res["user"] == ALICE
    assert graph.requests[0]["token"] == "tok-alice"


async def test_service_leased_for_another_user_refuses_request(pool, users, graph):
    alice, _ = users["alice"]
    twin = make_principal(ALICE, object_id="00000000-0000-0000-0000-0000000000aa")
    async with pool.lease(DOMAIN, alice) as svc:
        with bound(twin):
            with pytest.raises(SecurityError) as err:
                await svc.list_events()
    assert err.value.code == ErrorCode.IDENTITY_MISMATCH
    assert graph.requests == []


async def test_not_connected_is_raised_not_swallowed(mu, graph):
    carol = make_principal("carol@contoso.com")
    svc = await handlers.create_service(carol, None, FakeTokenProvider(carol, connected=False))
    assert await svc.initialize()
    with bound(carol):
        with pytest.raises(SecurityError) as err:
            await svc.calendar_view(**VIEW_ARGS)
    assert err.value.code == ErrorCode.GRAPH_NOT_CONNECTED
    assert graph.requests == []


async def test_client_wrappers_do_not_swallow_security_errors(mu):
    carol = make_principal("carol@contoso.com")
    client = GraphCalendarClient(token_provider=FakeTokenProvider(carol, connected=False))
    assert await client.initialize()
    with bound(carol):
        with pytest.raises(SecurityError):
            await client.delete_event(user_email="carol@contoso.com", event_id="x")


async def test_logs_omit_error_body_and_email(pool, users, graph, caplog):
    alice, _ = users["alice"]
    caplog.set_level(logging.DEBUG)
    res = await _call(pool, alice, handlers.handle_get_event, {"user_email": ALICE, "event_id": "evt-1"})
    assert res.get("status") == "error"
    for secret in ("CANARY-BODY", ALICE, "tok-alice"):
        assert secret not in caplog.text


def test_url_builder_has_no_shared_email_state(users):
    _, a_tok = users["alice"]
    query = GraphCalendarQuery(token_provider=a_tok)  # mode 0
    first = query._get_url_builder("a@x")
    second = query._get_url_builder("b@x")
    assert first is not second
    assert first.events_url == f"{GRAPH}/users/a@x/events"  # 다른 이메일 호출이 앞 builder 를 바꾸지 않는다
    assert second.events_url == f"{GRAPH}/users/b@x/events"
    assert not hasattr(query, "_url_builder")


def test_me_builder_targets_me_root():
    builder = GraphCalendarUrlBuilder("me")
    assert builder.events_url == f"{GRAPH}/me/events"
    assert builder.get_schedule_url == f"{GRAPH}/me/calendar/getSchedule"


def test_mode1_query_pins_me_builder(mu, users):
    _, a_tok = users["alice"]
    query = GraphCalendarQuery(token_provider=a_tok)
    assert query._get_url_builder(ALICE) is query._get_url_builder(BOB)
    assert query._get_url_builder(ALICE).events_url == f"{GRAPH}/me/events"


def test_handler_without_lease_fails_closed(mu):
    with pytest.raises(SecurityError) as err:
        handlers._service()
    assert err.value.code == ErrorCode.MISSING_PRINCIPAL


def test_mode0_keeps_legacy_global_service():
    assert isinstance(handlers.calendar_service, CalendarService)
    assert handlers._service() is handlers.calendar_service


# ----------------------------------------------------------------------
# G01 — event_id 가 경로 구조를 못 바꾼다 / ②-9 — 오류 원문 비노출
@pytest.mark.parametrize("bad", ["..", "%2E%2E", "../../../users/bob@fabrikam.com/events", ""])
async def test_traversal_event_id_cannot_leave_me_events(pool, users, graph, bad):
    alice, _ = users["alice"]
    for handler in (handlers.handle_get_event, handlers.handle_delete_event):
        try:
            await _call(pool, alice, handler, {"user_email": ALICE, "event_id": bad})
        except SecurityError as err:
            assert err.code == ErrorCode.NOT_FOUND
    for req in graph.requests:  # 단일 성분으로 인코딩돼 나갔다면 /me/events/<하나> 아래다
        assert req["url"].startswith(f"{GRAPH}/me/events/")
        assert "/../" not in req["url"] and not req["url"].endswith("/..")


def test_event_url_encodes_single_segment():
    builder = GraphCalendarUrlBuilder("me")
    assert builder.event_url("a/../b") == f"{GRAPH}/me/events/a%2F..%2Fb"
    for bad in ("..", ".", "%2e%2E", "", "a\x00b"):
        with pytest.raises(SecurityError):
            builder.event_url(bad)


async def test_failure_payload_has_only_status_and_code(pool, users, graph):
    alice, _ = users["alice"]
    res = await _call(pool, alice, handlers.handle_get_event, {"user_email": ALICE, "event_id": "evt-1"})
    assert res["status"] == "error"
    assert res["status_code"] == 404 and res["graph_error_code"] == "ErrorItemNotFound"
    assert "CANARY-BODY" not in repr(res) and "error_detail" not in res


async def test_transport_exception_text_not_returned(pool, users, graph):
    alice, _ = users["alice"]

    def _boom(*args):
        raise OSError(r"D:\ms365-data\users\secret CANARY-EXC")

    graph.router = _boom
    res = await _call(pool, alice, handlers.handle_list_events, {"user_email": ALICE})
    assert res["status"] == "error"
    assert "CANARY-EXC" not in repr(res) and "ms365-data" not in repr(res)


# ----------------------------------------------------------------------
# R08 — bearer 요청은 redirect 를 따라가지 않는다 / nextLink 는 본인 캘린더 범위만
REDIRECT_TARGET = f"{GRAPH}/users/{BOB}/events"


async def test_graph_redirect_is_not_followed_and_sanitized(pool, users, graph):
    alice, _ = users["alice"]
    graph.router = lambda *a: FakeResponse(302, None, text="", headers={"Location": REDIRECT_TARGET})
    res = await _call(pool, alice, handlers.handle_list_events, {"user_email": ALICE})
    assert res["status"] == "error" and res["status_code"] == 302
    assert len(graph.requests) == 1
    assert graph.requests[0]["allow_redirects"] is False
    assert REDIRECT_TARGET not in repr(res) and BOB not in repr(res)


async def test_all_four_http_helpers_disable_redirects(users, graph):
    _, a_tok = users["alice"]
    query = GraphCalendarQuery(token_provider=a_tok)  # mode 0 도 같다
    await query._fetch_data("t", f"{GRAPH}/me/events")
    await query._post_data("t", f"{GRAPH}/me/events", {})
    await query._patch_data("t", f"{GRAPH}/me/events/e1", {})
    await query._delete_data("t", f"{GRAPH}/me/events/e1")
    assert [r["method"] for r in graph.requests] == ["GET", "POST", "PATCH", "DELETE"]
    assert all(r["allow_redirects"] is False for r in graph.requests)


@pytest.mark.parametrize(
    "bad",
    [
        f"{GRAPH}/users/{BOB}/events?$skip=10",
        f"{GRAPH}/me/events/../../users/{BOB}/events",
        f"{GRAPH}/me/events/..%2F..%2Fusers%2F{BOB}",
        f"{GRAPH}/me/messages?$skip=10",  # 캘린더 범위 밖 리소스
        "http://graph.microsoft.com/v1.0/me/events",  # https 아님
        "https://graph.microsoft.com.evil.example/v1.0/me/events",
        "https://graph.microsoft.com/beta/me/events",
    ],
)
async def test_next_link_outside_caller_scope_is_refused(pool, users, graph, bad):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            with pytest.raises(SecurityError) as err:
                await svc._client.calendar_query.fetch_next_link(ALICE, bad)
    assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
    assert graph.requests == []


async def test_next_link_within_me_scope_is_fetched_without_redirects(pool, users, graph):
    alice, _ = users["alice"]
    link = f"{GRAPH}/me/events?$skiptoken=abc"
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            res = await svc._client.calendar_query.fetch_next_link(ALICE, link)
    assert res["status"] == "success" and res["value"][0]["id"] == "evt-tok-alice"
    (req,) = graph.requests
    assert req["url"] == link and req["token"] == "tok-alice" and req["allow_redirects"] is False


async def test_next_link_own_users_segment_allowed_other_refused_in_mode0(users, graph):
    _, a_tok = users["alice"]
    query = GraphCalendarQuery(token_provider=a_tok)  # mode 0 — 호출 이메일로 본인 판정
    await query.fetch_next_link(ALICE, f"{GRAPH}/users/{ALICE}/events?$skip=5")
    with pytest.raises(SecurityError):
        await query.fetch_next_link(ALICE, f"{GRAPH}/users/{BOB}/events?$skip=5")
    assert len(graph.requests) == 1


# ----------------------------------------------------------------------
# R15 — legacy 싱글톤 export 호환 (mode 0 그대로, mode 1 은 기동 오류·인스턴스 생성 없음)
def _no_instantiation(self, *args, **kwargs):
    raise AssertionError("mode 1 에서 CalendarService 가 만들어졌다")


def test_legacy_singleton_export_resolves_to_mode0_instance():
    import mcp_calendar
    from mcp_calendar import calendar_service as via_package
    from mcp_calendar.calendar_service import calendar_service as via_module

    assert via_package is handlers.calendar_service is via_module
    assert isinstance(via_package, CalendarService)
    assert inspect.ismodule(importlib.import_module("mcp_calendar.calendar_service"))
    assert "calendar_service" in dir(mcp_calendar) and "calendar_service" in dir(service_mod)


def test_legacy_singleton_export_refused_in_mode1(mu, monkeypatch):
    import mcp_calendar

    monkeypatch.setattr(CalendarService, "__init__", _no_instantiation)
    with pytest.raises(StartupConfigError):
        getattr(mcp_calendar, "calendar_service")
    with pytest.raises(StartupConfigError):
        getattr(service_mod, "calendar_service")


# ----------------------------------------------------------------------
# R15(2차) — wildcard export: mode 0 은 싱글톤 포함, mode 1 은 미포함·미생성
def test_wildcard_imports_expose_singleton_in_mode0():
    import mcp_calendar

    assert "calendar_service" in mcp_calendar.__all__ and "calendar_service" in service_mod.__all__
    ns = {}
    exec("from mcp_calendar import *", ns)
    assert ns["calendar_service"] is handlers.calendar_service
    ns = {}
    exec("from mcp_calendar.calendar_service import *", ns)
    assert ns["calendar_service"] is handlers.calendar_service
    assert ns["CalendarService"] is CalendarService


def test_wildcard_import_in_mode1_exports_nothing_and_instantiates_nothing(tmp_path, monkeypatch):
    import mcp_calendar

    monkeypatch.setattr(CalendarService, "__init__", _no_instantiation)
    try:
        with multi_user_mode(tmp_path):
            importlib.reload(mcp_calendar)  # 기동 시점(mode 1)의 __all__ 을 재현
            assert "calendar_service" not in mcp_calendar.__all__
            ns = {}
            exec("from mcp_calendar import *", ns)
            assert "calendar_service" not in ns and "CalendarService" in ns
    finally:
        importlib.reload(mcp_calendar)  # mode 0 __all__ 복원
    assert "calendar_service" in mcp_calendar.__all__


# ----------------------------------------------------------------------
# R02 — 결과 수·목록 길이 상한: 스키마와 서비스 경계 둘 다
def _payload(exc):
    return getattr(exc, "payload", None) or exc.args[0]


def test_schema_declares_bounds():
    by_name = {t["name"]: t["inputSchema"]["properties"] for t in handlers.MCP_TOOLS}
    assert by_name["list_events"]["top"]["minimum"] == 1
    assert by_name["list_events"]["top"]["maximum"] == 1000
    assert by_name["get_schedule"]["schedules"]["maxItems"] == 100


@pytest.mark.parametrize("top", [0, -1, 1001, 10**12])
async def test_runtime_rejects_top_outside_schema_bounds_before_handler(graph, top):
    with pytest.raises(ToolExecutionError):
        await handlers.runtime.call("list_events", {"top": top})
    assert graph.requests == []


@pytest.mark.parametrize("top", [0, -1, 1001, 10**12, "many", True])
async def test_service_rejects_top_outside_bounds_before_graph(pool, users, graph, top):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            with pytest.raises(ToolExecutionError) as err:
                await svc.list_events(top=top)
            with pytest.raises(ToolExecutionError):
                await svc.calendar_view(top=top, **VIEW_ARGS)
    assert _payload(err.value)["error"] == "invalid_argument"
    assert graph.requests == []


async def test_service_caps_attendees_categories_and_schedules(pool, users, graph):
    alice, _ = users["alice"]
    when = {"start": "2026-10-01T09:00:00", "end": "2026-10-01T10:00:00"}
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            with pytest.raises(ToolExecutionError) as err:
                await svc.get_schedule(
                    schedules=["u@x"] * 101, start_time=when["start"], end_time=when["end"]
                )
            assert _payload(err.value)["argument"] == "schedules"
            with pytest.raises(ToolExecutionError) as err:
                await svc.create_event(subject="s", attendees=["a@x"] * 501, **when)
            assert _payload(err.value)["argument"] == "attendees"
            with pytest.raises(ToolExecutionError) as err:
                await svc.update_event(event_id="e1", categories=["c"] * 51)
            assert _payload(err.value)["argument"] == "categories"
    assert graph.requests == []


# ----------------------------------------------------------------------
# N01 — 토큰은 요청마다 bound provider 에서 다시 받는다. 페이지 사이 폐기 → 후속 요청 0건
async def test_revocation_between_pages_stops_next_page(pool, users, graph):
    alice, a_tok = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            page1 = await svc.list_events()
            assert page1["success"]
            acquisitions_after_page1 = a_tok.calls.count("validate_and_refresh_token")
            a_tok.connected = False  # 1페이지와 2페이지 사이에 연결 해제·폐기
            with pytest.raises(SecurityError) as err:
                await svc._client.calendar_query.fetch_next_link(ALICE, f"{GRAPH}/me/events?$skiptoken=abc")
    assert err.value.code == ErrorCode.GRAPH_NOT_CONNECTED
    assert acquisitions_after_page1 == 1
    assert len(graph.requests) == 1  # 2페이지 요청은 나가지 않았다
