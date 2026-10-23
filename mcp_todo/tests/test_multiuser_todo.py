"""Todo 멀티유저 격리 (spec/spec_멀티유저.md ②-2.4·②-7.6·②-10 C01·L01, WP8).

네트워크 없음 — `FakeTokenProvider` + 가짜 Graph 세션(`_fake_graph`). 공용 AuthManager
(`get_shared_auth_manager`)와 legacy 기본 사용자 선택은 호출되면 실패하도록 막아 둔다.
"""

import asyncio
import importlib
import inspect

import pytest

import mcp_common.auth as common_auth
from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError
from mcp_common.service_context import bind_service
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode
from mcp_common.user_resolver import UserResolver

import mcp_todo.todo_service as service_mod
from mcp_todo.graph_todo_query import GraphTodoQuery
from mcp_todo.mcp_server import handlers
from mcp_todo.todo_service import TodoService
from mcp_todo.tests._fake_graph import FakeGraph, FakeResponse, Rendezvous

GRAPH = "https://graph.microsoft.com/v1.0"
ALICE = "alice@contoso.com"
BOB = "bob@fabrikam.com"
DOMAIN = handlers.SERVER_NAME


def _router(method, url, token, body):
    path = url.split("?", 1)[0]
    if method == "GET" and path.endswith("/todo/lists"):
        # 사용자마다 다른 list id — 응답이 섞이면 바로 드러난다
        return FakeResponse(
            200,
            {"value": [{"id": f"L-{token}", "displayName": "Tasks", "wellknownListName": "defaultList"}]},
        )
    if method == "GET" and path.endswith("/tasks"):
        return FakeResponse(200, {"value": [{"id": f"T-{token}", "title": f"task of {token}"}]})
    if method == "DELETE":
        return FakeResponse(204)
    return FakeResponse(404, {"error": {"code": "notFound", "message": "CANARY-BODY"}})


def _forbidden(*args, **kwargs):
    raise AssertionError("mode 1 경로가 공용 AuthManager·legacy 기본 사용자를 불렀다")


@pytest.fixture
def mu(tmp_path, monkeypatch):
    monkeypatch.setattr(common_auth, "get_shared_auth_manager", _forbidden)
    monkeypatch.setattr(service_mod, "get_default_user_email", _forbidden)
    monkeypatch.setattr(UserResolver, "default_email", _forbidden)
    with multi_user_mode(tmp_path) as root:
        yield root


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph(_router)
    monkeypatch.setattr(GraphTodoQuery, "_http_session", lambda self: fake.session_factory())
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

    res_a = await _call(pool, alice, handlers.handle_todo_lists_view, {"user_email": ALICE})
    assert res_a["lists"][0]["id"] == "L-tok-alice"
    assert a_tok.calls and b_tok.calls == []

    used_by_alice = len(a_tok.calls)
    res_b = await _call(pool, bob, handlers.handle_todo_lists_view, {"user_email": BOB})
    assert res_b["lists"][0]["id"] == "L-tok-bob"
    assert len(a_tok.calls) == used_by_alice


async def test_interleaved_multi_step_calls_stay_per_user(pool, users, graph):
    """todo_tasks_view 는 (목록 조회 → task 조회) 2단계다. 단계 사이에서 A/B 가 교차해도
    두 번째 요청이 자기 list id·토큰·`/me` 경로를 쓴다(전에는 공유 URL builder 가 마지막
    이메일로 바뀌었다)."""
    alice, _ = users["alice"]
    bob, _ = users["bob"]
    graph.gate = Rendezvous(4)  # 첫 단계 4개가 모두 진행 중이어야 응답한다

    calls = []
    for _ in range(2):
        calls.append(_call(pool, alice, handlers.handle_todo_tasks_view, {"user_email": ALICE}))
        calls.append(_call(pool, bob, handlers.handle_todo_tasks_view, {"user_email": BOB}))
    results = await asyncio.gather(*calls)

    for i, res in enumerate(results):
        owner = "tok-alice" if i % 2 == 0 else "tok-bob"
        assert res["list_id"] == f"L-{owner}"
        assert res["tasks"][0]["id"] == f"T-{owner}"
        assert res["user"] == (ALICE if i % 2 == 0 else BOB)

    expected = {alice.user_key: "tok-alice", bob.user_key: "tok-bob"}
    assert len(graph.requests) == 8
    for req in graph.requests:
        assert req["token"] == expected[req["principal_key"]]
        assert req["url"].startswith(f"{GRAPH}/me/todo/lists")
        assert "/users/" not in req["url"]
        if "/tasks" in req["url"]:
            assert f"/lists/L-{req['token']}/tasks" in req["url"]


async def test_service_and_query_close_keep_provider_open(mu, users):
    alice, a_tok = users["alice"]
    svc = await handlers.create_service(alice, None, a_tok)
    assert await svc.initialize()
    await svc.close()
    assert a_tok.closed is False
    # 전에는 graph_todo_query.close() 가 공급자 close() 까지 불렀다 (②-2.4)
    query = GraphTodoQuery(token_provider=a_tok)
    await query.close()
    assert a_tok.closed is False


async def test_evicting_alice_leaves_bob_untouched(pool, users, graph):
    alice, a_tok = users["alice"]
    bob, b_tok = users["bob"]
    await _call(pool, alice, handlers.handle_todo_lists_view, {"user_email": ALICE})
    await _call(pool, bob, handlers.handle_todo_lists_view, {"user_email": BOB})

    await pool.invalidate(alice.user_key)

    assert a_tok.closed is True
    assert b_tok.closed is False
    res = await _call(pool, bob, handlers.handle_todo_lists_view, {"user_email": BOB})
    assert res["lists"][0]["id"] == "L-tok-bob"


async def test_mode1_never_falls_back_to_shared_auth_manager(mu):
    with pytest.raises(RuntimeError, match="token_provider"):
        GraphTodoQuery()
    with pytest.raises(RuntimeError, match="token_provider"):
        await TodoService().initialize()


async def test_other_account_email_is_rejected_before_graph(pool, users, graph):
    alice, _ = users["alice"]
    _, b_tok = users["bob"]
    with pytest.raises(SecurityError) as err:
        await _call(pool, alice, handlers.handle_todo_lists_view, {"user_email": BOB})
    assert err.value.code == ErrorCode.IDENTITY_MISMATCH
    assert graph.requests == []
    assert b_tok.calls == []


async def test_omitted_and_empty_email(pool, users, graph):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            res = await svc.todo_lists_view()
            assert res["user"] == ALICE
            with pytest.raises(SecurityError) as err:
                await svc.todo_lists_view(user_email="")
    assert err.value.code == ErrorCode.INVALID_USER_EMAIL


async def test_service_leased_for_another_user_refuses_request(pool, users, graph):
    alice, _ = users["alice"]
    twin = make_principal(ALICE, object_id="00000000-0000-0000-0000-0000000000aa")
    async with pool.lease(DOMAIN, alice) as svc:
        with bound(twin):
            with pytest.raises(SecurityError) as err:
                await svc.todo_tasks_view()
    assert err.value.code == ErrorCode.IDENTITY_MISMATCH
    assert graph.requests == []


async def test_not_connected_is_raised_not_swallowed(mu, graph):
    carol = make_principal("carol@contoso.com")
    svc = await handlers.create_service(carol, None, FakeTokenProvider(carol, connected=False))
    assert await svc.initialize()
    with bound(carol):
        with pytest.raises(SecurityError) as err:
            await svc.todo_tasks_view()
    assert err.value.code == ErrorCode.GRAPH_NOT_CONNECTED
    assert graph.requests == []


def test_handler_without_lease_fails_closed(mu):
    with pytest.raises(SecurityError) as err:
        handlers._service()
    assert err.value.code == ErrorCode.MISSING_PRINCIPAL


def test_mode0_keeps_legacy_global_service():
    assert isinstance(handlers.todo_service, TodoService)
    assert handlers._service() is handlers.todo_service


# ----------------------------------------------------------------------
# R08 — bearer 요청은 redirect 를 따라가지 않는다 / nextLink 는 본인 To Do 범위만
REDIRECT_TARGET = f"{GRAPH}/users/{BOB}/todo/lists"


async def test_graph_redirect_is_not_followed_and_sanitized(pool, users, graph):
    alice, _ = users["alice"]
    graph.router = lambda *a: FakeResponse(302, None, text="", headers={"Location": REDIRECT_TARGET})
    res = await _call(pool, alice, handlers.handle_todo_lists_view, {"user_email": ALICE})
    assert res["status"] == "error" and res["status_code"] == 302
    assert len(graph.requests) == 1
    assert graph.requests[0]["allow_redirects"] is False
    assert REDIRECT_TARGET not in repr(res) and BOB not in repr(res)


async def test_all_four_http_helpers_disable_redirects(users, graph):
    _, a_tok = users["alice"]
    query = GraphTodoQuery(token_provider=a_tok)  # mode 0 도 같다
    await query._fetch("t", f"{GRAPH}/me/todo/lists")
    await query._post("t", f"{GRAPH}/me/todo/lists", {})
    await query._patch("t", f"{GRAPH}/me/todo/lists/L1/tasks/T1", {})
    await query._delete("t", f"{GRAPH}/me/todo/lists/L1")
    assert [r["method"] for r in graph.requests] == ["GET", "POST", "PATCH", "DELETE"]
    assert all(r["allow_redirects"] is False for r in graph.requests)


@pytest.mark.parametrize(
    "bad",
    [
        f"{GRAPH}/users/{BOB}/todo/lists?$skip=10",
        f"{GRAPH}/me/todo/lists/../../../users/{BOB}/todo/lists",
        f"{GRAPH}/me/todo/lists/..%2F..%2Fusers%2F{BOB}",
        f"{GRAPH}/me/events?$skip=10",  # To Do 범위 밖 리소스
        "http://graph.microsoft.com/v1.0/me/todo/lists",
        "https://graph.microsoft.com.evil.example/v1.0/me/todo/lists",
    ],
)
async def test_next_link_outside_caller_scope_is_refused(pool, users, graph, bad):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            with pytest.raises(SecurityError) as err:
                await svc._client.todo_query.fetch_next_link(ALICE, bad)
    assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
    assert graph.requests == []


async def test_next_link_within_me_scope_is_fetched_without_redirects(pool, users, graph):
    alice, _ = users["alice"]
    link = f"{GRAPH}/me/todo/lists?$skiptoken=abc"
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            res = await svc._client.todo_query.fetch_next_link(ALICE, link)
    assert res["status"] == "success" and res["value"][0]["id"] == "L-tok-alice"
    (req,) = graph.requests
    assert req["url"] == link and req["token"] == "tok-alice" and req["allow_redirects"] is False


# ----------------------------------------------------------------------
# R15 — legacy 싱글톤 export 호환 (mode 0 그대로, mode 1 은 기동 오류·인스턴스 생성 없음)
def _no_instantiation(self, *args, **kwargs):
    raise AssertionError("mode 1 에서 TodoService 가 만들어졌다")


def test_legacy_singleton_export_resolves_to_mode0_instance():
    from mcp_todo.todo_service import todo_service as via_module

    assert via_module is handlers.todo_service
    assert isinstance(via_module, TodoService)
    assert inspect.ismodule(service_mod) and inspect.ismodule(importlib.import_module("mcp_todo.todo_service"))
    assert "todo_service" in dir(service_mod)


def test_legacy_singleton_export_refused_in_mode1(mu, monkeypatch):
    monkeypatch.setattr(TodoService, "__init__", _no_instantiation)
    with pytest.raises(StartupConfigError):
        getattr(service_mod, "todo_service")


def test_wildcard_import_exposes_singleton_in_mode0():
    assert "todo_service" in service_mod.__all__
    ns = {}
    exec("from mcp_todo.todo_service import *", ns)
    assert ns["todo_service"] is handlers.todo_service
    assert ns["TodoService"] is TodoService


# ----------------------------------------------------------------------
# R02 — 결과 수·목록 길이 상한: 스키마와 서비스 경계 둘 다
def _payload(exc):
    return getattr(exc, "payload", None) or exc.args[0]


def test_schema_declares_bounds():
    by_name = {t["name"]: t["inputSchema"]["properties"] for t in handlers.MCP_TOOLS}
    for tool in ("todo_lists_view", "todo_tasks_view"):
        assert by_name[tool]["top"]["minimum"] == 1 and by_name[tool]["top"]["maximum"] == 1000
    for tool in ("todo_task_create", "todo_task_update"):
        assert by_name[tool]["categories"]["maxItems"] == 50


@pytest.mark.parametrize("top", [0, -1, 1001, 10**12])
async def test_runtime_rejects_top_outside_schema_bounds_before_handler(graph, top):
    with pytest.raises(ToolExecutionError):
        await handlers.runtime.call("todo_lists_view", {"top": top})
    assert graph.requests == []


@pytest.mark.parametrize("top", [0, -1, 1001, 10**12, "many", True])
async def test_service_rejects_top_outside_bounds_before_graph(pool, users, graph, top):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            with pytest.raises(ToolExecutionError) as err:
                await svc.todo_lists_view(top=top)
            with pytest.raises(ToolExecutionError):
                await svc.todo_tasks_view(top=top)
    assert _payload(err.value)["error"] == "invalid_argument"
    assert graph.requests == []


async def test_service_caps_categories(pool, users, graph):
    alice, _ = users["alice"]
    with bound(alice):
        async with pool.lease(DOMAIN, alice) as svc:
            with pytest.raises(ToolExecutionError) as err:
                await svc.todo_task_create(title="t", categories=["c"] * 51)
            assert _payload(err.value)["argument"] == "categories"
            with pytest.raises(ToolExecutionError):
                await svc.todo_task_update(task_id="T1", categories=["c"] * 51)
    assert graph.requests == []


# ----------------------------------------------------------------------
# N01 — 2단계 도구(목록 해석 → task 조회)는 요청마다 토큰을 다시 받는다
async def test_two_step_tool_reacquires_token_per_request(pool, users, graph):
    alice, a_tok = users["alice"]
    res = await _call(pool, alice, handlers.handle_todo_tasks_view, {"user_email": ALICE})
    assert res["status"] == "success"
    assert len(graph.requests) == 2
    assert a_tok.calls.count("validate_and_refresh_token") == 2


async def test_revocation_between_steps_stops_second_request(pool, users, graph):
    alice, a_tok = users["alice"]
    base = graph.router

    def router(method, url, token, body):
        a_tok.connected = False  # 1단계(목록 조회) 응답 시점에 연결 해제·폐기
        return base(method, url, token, body)

    graph.router = router
    with pytest.raises(SecurityError) as err:
        await _call(pool, alice, handlers.handle_todo_tasks_view, {"user_email": ALICE})
    assert err.value.code == ErrorCode.GRAPH_NOT_CONNECTED
    assert len(graph.requests) == 1  # task 조회 요청은 나가지 않았다
