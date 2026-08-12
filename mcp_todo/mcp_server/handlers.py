"""
Todo MCP — 도구 정의와 핸들러. **두 트랜스포트가 공유하는 유일한 원본이다.**

`server_stdio.py` 와 `server_stream.py` 는 이 모듈을 import 해 `build_mcp_server()` 가
만든 같은 `Server` 객체를 받아 구동만 한다. 도구 정의나 핸들러가 트랜스포트 파일에
다시 나타나면 사양 위반이다(spec/spec_MCP트랜스포트.md ②-3-1).

도구 계약(이름·설명·파라미터·enum·기본값)은 `spec/param_spec/todo.yaml` 한 곳에만 있다.
이 파일에는 도구 정의를 적지 않고, 생성기·에디터 산출물도 참조하지 않는다.

이 모듈은 트랜스포트를 import 하지 않는다(단방향 의존). 또한 프로세스 부트스트랩을
수행하지 않는다 — 호출자가 `mcp_common.bootstrap` 을 먼저 돌린 뒤 import 해야 한다.
"""

from typing import Any, Dict, List, Optional

from mcp_common.param_spec import load_param_spec
from mcp_common.runtime import ServiceLifecycle, ToolRuntime
from mcp_common.user_resolver import resolve_user_email

from mcp_todo.todo_service import TodoService

# 도구 계약의 단일 원본. 이 파일에는 도구 정의를 적지 않는다.
SPEC = load_param_spec("todo")

SERVER_NAME = SPEC.name
SERVER_VERSION = SPEC.version
DEFAULT_PORT = SPEC.port or 5006

MCP_TOOLS: List[Dict[str, Any]] = SPEC.mcp_tools()


todo_service = TodoService()


def _call_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """spec 파생 호출 인자 + 사용자 선택 정책.

    `user_email` 은 스키마상 선택이지만 서비스에는 항상 확정된 값이 가야 한다.
    선택 정책은 `mcp_common.user_resolver`(SSOT)에 위임하고, 없으면
    `ToolExecutionError` 가 올라간다.
    """
    kwargs = SPEC.call_args(tool_name, args)
    kwargs["user_email"] = resolve_user_email(kwargs.get("user_email"), required=True)
    return kwargs


async def handle_todo_lists_view(args: Dict[str, Any]) -> Any:
    return await todo_service.todo_lists_view(**_call_args("todo_lists_view", args))


async def handle_todo_list_create(args: Dict[str, Any]) -> Any:
    return await todo_service.todo_list_create(**_call_args("todo_list_create", args))


async def handle_todo_list_delete(args: Dict[str, Any]) -> Any:
    return await todo_service.todo_list_delete(**_call_args("todo_list_delete", args))


async def handle_todo_tasks_view(args: Dict[str, Any]) -> Any:
    return await todo_service.todo_tasks_view(**_call_args("todo_tasks_view", args))


async def handle_todo_task_get(args: Dict[str, Any]) -> Any:
    return await todo_service.todo_task_get(**_call_args("todo_task_get", args))


async def handle_todo_task_create(args: Dict[str, Any]) -> Any:
    return await todo_service.todo_task_create(**_call_args("todo_task_create", args))


async def handle_todo_task_update(args: Dict[str, Any]) -> Any:
    return await todo_service.todo_task_update(**_call_args("todo_task_update", args))


async def handle_todo_task_delete(args: Dict[str, Any]) -> Any:
    return await todo_service.todo_task_delete(**_call_args("todo_task_delete", args))


TOOL_HANDLERS = {
    "todo_lists_view": handle_todo_lists_view,
    "todo_list_create": handle_todo_list_create,
    "todo_list_delete": handle_todo_list_delete,
    "todo_tasks_view": handle_todo_tasks_view,
    "todo_task_get": handle_todo_task_get,
    "todo_task_create": handle_todo_task_create,
    "todo_task_update": handle_todo_task_update,
    "todo_task_delete": handle_todo_task_delete,
}


# 기본값 주입 + 스키마 검증 + 오류 정규화는 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [todo_service])


def get_tool_config(tool_name: str) -> Optional[dict]:
    """하위 호환용 조회 헬퍼."""
    return runtime.tool_config(tool_name)


def build_mcp_server():
    """stdio·stream 이 공유하는 `Server` 를 만든다. 도구 등록은 여기서 1회만 한다."""
    from mcp.server.lowlevel import Server as MCPServer

    server = MCPServer(name=SERVER_NAME, version=SERVER_VERSION)
    tool_objects = runtime.build_tool_objects()

    @server.list_tools()
    async def _list_tools():
        return tool_objects

    # SDK 검증은 끄고(validate_input=False) ToolRuntime 이 검증한다.
    # 실패는 예외로 올라가 SDK 가 CallToolResult(isError=True) 로 감싼다.
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        return await runtime.dispatch(name, arguments)

    return server


__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "DEFAULT_PORT",
    "MCP_TOOLS",
    "TOOL_HANDLERS",
    "runtime",
    "lifecycle",
    "build_mcp_server",
    "get_tool_config",
]
