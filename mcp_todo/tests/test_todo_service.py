"""TodoService 기본 동작 (mode 0). 네트워크 없음 — 가짜 Graph 세션(`_fake_graph`).

Todo 는 그동안 테스트가 없었다. 도구 응답 형태, 리스트 이름 해석(wellknownListName →
displayName → defaultList), soft not_found, 요청 본문 조립, URL 인코딩을 고정한다.
"""

import pytest

from mcp_common.testing import FakeTokenProvider, make_principal, single_user_mode

from mcp_todo.graph_todo_query import GraphTodoQuery, GraphTodoUrlBuilder
from mcp_todo.mcp_server import handlers
from mcp_todo.todo_service import TodoService, _to_datetime_timezone, _to_item_body
from mcp_todo.tests._fake_graph import FakeGraph, FakeResponse

GRAPH = "https://graph.microsoft.com/v1.0"
USER = "solo@contoso.com"
ROOT = f"{GRAPH}/users/{USER}/todo"
LONG_LIST_ID = "AAMkAGI2" + "x" * 40 + "=="

LISTS = [
    {"id": "L-default", "displayName": "Tasks", "wellknownListName": "defaultList"},
    {"id": "L-work", "displayName": "Work", "wellknownListName": "none"},
    {"id": "L-flag", "displayName": "Flagged", "wellknownListName": "flaggedEmails"},
]


def _router(method, url, token, body):
    path = url.split("?", 1)[0]
    if method == "GET" and path.endswith("/todo/lists"):
        return FakeResponse(200, {"value": LISTS})
    if method == "POST" and path.endswith("/todo/lists"):
        return FakeResponse(201, {"id": "L-new", **body})
    if method == "GET" and path.endswith("/tasks"):
        return FakeResponse(200, {"value": [{"id": "T1", "title": "first"}]})
    if method == "POST" and path.endswith("/tasks"):
        return FakeResponse(201, {"id": "T-new", **body})
    if method == "GET" and "/tasks/" in path:
        return FakeResponse(200, {"id": path.rsplit("/", 1)[1], "title": "one"})
    if method == "PATCH":
        return FakeResponse(200, {"id": path.rsplit("/", 1)[1], **body})
    if method == "DELETE":
        return FakeResponse(204)
    return FakeResponse(404, {"error": {"code": "notFound", "message": "no"}})


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph(_router)
    monkeypatch.setattr(GraphTodoQuery, "_http_session", lambda self: fake.session_factory())
    return fake


@pytest.fixture
async def service(graph):
    with single_user_mode():
        svc = TodoService(token_provider=FakeTokenProvider(make_principal(USER), "tok-solo"))
        assert await svc.initialize()
        yield svc
        await svc.close()


async def test_not_initialized_raises():
    with pytest.raises(RuntimeError, match="not initialized"):
        await TodoService().todo_lists_view(USER)


async def test_lists_view_shapes_response(service, graph):
    res = await service.todo_lists_view(USER, top=10)
    assert res["status"] == "success"
    assert res["user"] == USER
    assert [x["id"] for x in res["lists"]] == ["L-default", "L-work", "L-flag"]
    assert "value" not in res
    req = graph.requests[0]
    assert req["url"] == f"{ROOT}/lists?$top=10"
    assert req["token"] == "tok-solo"


async def test_list_create_requires_name_and_posts_display_name(service, graph):
    assert (await service.todo_list_create(USER, display_name=""))["status"] == "error"
    assert graph.requests == []
    res = await service.todo_list_create(USER, display_name="Groceries")
    assert res["status"] == "success" and res["list"]["displayName"] == "Groceries"
    assert graph.requests[0]["body"] == {"displayName": "Groceries"}


@pytest.mark.parametrize(
    "name, expected",
    [(None, "L-default"), ("", "L-default"), ("flaggedEmails", "L-flag"), ("Work", "L-work")],
)
async def test_tasks_view_resolves_list(service, graph, name, expected):
    res = await service.todo_tasks_view(USER, list_id_or_name=name, status_filter="notStarted", top=5)
    assert res["status"] == "success"
    assert res["list_id"] == expected
    assert res["tasks"] == [{"id": "T1", "title": "first"}]
    url = graph.requests[-1]["url"]
    assert url.startswith(f"{ROOT}/lists/{expected}/tasks?")
    assert "$filter=status eq 'notStarted'" in url
    assert "$orderby=createdDateTime desc" in url and "$top=5" in url


async def test_long_list_id_skips_lookup(service, graph):
    res = await service.todo_task_get(USER, list_id_or_name=LONG_LIST_ID, task_id="T 9/x")
    assert res["status"] == "success"
    assert len(graph.requests) == 1  # 목록 조회 없이 바로 task 조회
    # list_id / task_id 는 경로 조각으로 인코딩된다
    assert graph.requests[0]["url"] == f"{ROOT}/lists/AAMkAGI2{'x' * 40}%3D%3D/tasks/T%209%2Fx"


async def test_unknown_list_is_soft_not_found(service, graph):
    res = await service.todo_task_create(USER, list_id_or_name="Nope", title="x")
    assert res["success"] is True and res["found"] is False
    assert res["requested"] == "Nope"
    assert {x["displayName"] for x in res["available_lists"]} == {"Tasks", "Work", "Flagged"}
    assert all(r["method"] == "GET" for r in graph.requests)  # 생성 요청은 나가지 않았다


async def test_task_create_builds_graph_body(service, graph):
    res = await service.todo_task_create(
        USER,
        list_id_or_name="Work",
        title="report",
        body="draft",
        importance="high",
        due_datetime="2026-10-30T09:00:00",
        reminder_datetime={"dateTime": "2026-10-29T09:00:00", "timeZone": "UTC"},
        categories=["Blue"],
    )
    assert res["status"] == "success" and res["list_id"] == "L-work"
    body = graph.requests[-1]["body"]
    assert body == {
        "title": "report",
        "body": {"content": "draft", "contentType": "text"},
        "importance": "high",
        "dueDateTime": {"dateTime": "2026-10-30T09:00:00", "timeZone": "Korea Standard Time"},
        "reminderDateTime": {"dateTime": "2026-10-29T09:00:00", "timeZone": "UTC"},
        "isReminderOn": True,
        "categories": ["Blue"],
    }


async def test_task_update_without_fields_is_noop(service, graph):
    res = await service.todo_task_update(USER, list_id_or_name="L" * 41 + "=", task_id="T1")
    assert res == {"status": "success", "updated": False, "reason": "no_fields", "user": USER, "list_id": "L" * 41 + "="}
    assert graph.requests == []


async def test_task_update_patches_only_given_fields(service, graph):
    res = await service.todo_task_update(USER, list_id_or_name="Work", task_id="T1", status="completed")
    assert res["status"] == "success"
    patch = graph.requests[-1]
    assert patch["method"] == "PATCH" and patch["body"] == {"status": "completed"}


async def test_required_ids_are_checked_before_graph(service, graph):
    assert (await service.todo_task_get(USER, task_id=""))["status"] == "error"
    assert (await service.todo_task_delete(USER, task_id=""))["status"] == "error"
    assert (await service.todo_list_delete(USER, list_id_or_name=""))["status"] == "error"
    assert graph.requests == []


async def test_task_delete(service, graph):
    res = await service.todo_task_delete(USER, list_id_or_name="Work", task_id="T1")
    assert res["status"] == "success" and res["task_id"] == "T1" and res["list_id"] == "L-work"
    assert graph.requests[-1]["method"] == "DELETE"


def test_value_converters():
    assert _to_datetime_timezone(None) is None
    assert _to_datetime_timezone("2026-01-01T00:00:00").timeZone == "Korea Standard Time"
    assert _to_datetime_timezone({"date_time": "d", "time_zone": "UTC"}).timeZone == "UTC"
    assert _to_item_body(None) is None
    assert _to_item_body({"content": "c", "content_type": "html"}).contentType == "html"


def test_url_builder_roots():
    assert GraphTodoUrlBuilder(USER).lists_url == f"{ROOT}/lists"
    assert GraphTodoUrlBuilder("me").lists_url == f"{GRAPH}/me/todo/lists"


def test_handlers_cover_every_spec_tool():
    assert set(handlers.TOOL_HANDLERS) == {t["name"] for t in handlers.MCP_TOOLS}
    for tool in handlers.MCP_TOOLS:
        assert "user_email" in tool["inputSchema"]["properties"]
        assert "user_email" not in tool["inputSchema"].get("required", [])


# ----------------------------------------------------------------------
# G01 — list_id/task_id 가 경로 구조를 못 바꾼다 (mode 0 에서도) / ②-9 — 오류 원문 비노출
@pytest.mark.parametrize("task_id", ["..", ".", "%2E%2E"])
async def test_dot_segment_ids_rejected_before_graph(service, graph, task_id):
    from mcp_common.security_contracts import ErrorCode, SecurityError

    with pytest.raises(SecurityError) as err:
        await service.todo_task_get(USER, list_id_or_name=LONG_LIST_ID, task_id=task_id)
    assert err.value.code == ErrorCode.NOT_FOUND
    assert graph.requests == []


async def test_failure_payload_has_only_status_and_code(service, graph):
    graph.router = lambda *a: FakeResponse(500, {"error": {"code": "InternalServerError", "message": "CANARY-BODY"}})
    res = await service.todo_lists_view(USER)
    assert res["status"] == "error"
    assert res["status_code"] == 500 and res["graph_error_code"] == "InternalServerError"
    assert "CANARY-BODY" not in repr(res) and "error_detail" not in res


async def test_transport_exception_text_not_returned(service, graph):
    def _boom(*args):
        raise OSError(r"D:\ms365-data\users\secret CANARY-EXC")

    graph.router = _boom
    res = await service.todo_lists_view(USER)
    assert res["status"] == "error"
    assert "CANARY-EXC" not in repr(res) and "ms365-data" not in repr(res)
