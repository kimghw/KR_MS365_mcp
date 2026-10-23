"""
Calendar MCP — 도구 정의와 핸들러. **두 트랜스포트가 공유하는 유일한 원본이다.**

`server_stdio.py` 와 `server_stream.py` 는 이 모듈을 import 해 `build_mcp_server()` 가
만든 같은 `Server` 객체를 받아 구동만 한다. 도구 정의나 핸들러가 트랜스포트 파일에
다시 나타나면 사양 위반이다(spec/spec_MCP트랜스포트.md ②-3-1). 전에는 stdio 가 자체
JSON-RPC 루프(1002줄)를, stream 이 별도 YAML 로더와 boolean 변환 사본을 각각 갖고 있었고
`top=50`·`availability_view_interval=30` 같은 기본값이 핸들러 코드에 하드코딩돼
`spec/param_spec/calendar.yaml` 의 `default` 와 두 벌로 존재했다.

이 모듈은 트랜스포트를 import 하지 않는다(단방향 의존). 또한 프로세스 부트스트랩을
수행하지 않는다 — 호출자가 `mcp_common.bootstrap` 을 먼저 돌린 뒤 import 해야 한다.

서비스 배선(spec/spec_멀티유저.md ②-12 항목 2): 멀티유저(mode 1)에서는 서비스 풀이
`create_service()` 로 사용자별 서비스를 만들고 요청마다 lease 해 묶는다. 핸들러는
`_service()` 로 꺼내 쓴다. 전역 `calendar_service` 는 mode 0 에서만 만든다.
"""

from typing import Any, Dict, List, Optional

from mcp_common.param_spec import load_param_spec
from mcp_common.runtime import ServiceLifecycle, ToolRuntime
from mcp_common.security_policy import multi_user_enabled
from mcp_common.service_context import service_for
from mcp_common.service_pool import register_service_factory
from mcp_common.user_resolver import resolve_user_email

from mcp_calendar.calendar_service import CalendarService

# 도구 계약의 단일 원본. 이 파일에는 도구 정의를 적지 않는다.
SPEC = load_param_spec("calendar")

SERVER_NAME = SPEC.name
SERVER_VERSION = SPEC.version
DEFAULT_PORT = SPEC.port or 5002

MCP_TOOLS: List[Dict[str, Any]] = SPEC.mcp_tools()


async def create_service(principal, paths, tokens) -> CalendarService:
    """사용자별 서비스 factory — **생성만** 한다. initialize()/close() 는 풀이 부른다."""
    return CalendarService(token_provider=tokens, paths=paths)


register_service_factory(SERVER_NAME, create_service)

# mode 0 전용 전역 인스턴스. mode 1 에서는 만들지 않는다(공용 AuthManager 를 끌어오므로).
calendar_service: Optional[CalendarService] = None if multi_user_enabled() else CalendarService()


def _service() -> CalendarService:
    """mode 1 → 현재 요청에 lease 된 사용자 서비스, mode 0 → 전역 인스턴스."""
    return service_for(SERVER_NAME, legacy=calendar_service)


def _call_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """spec 에서 호출 인자를 파생시키고 user_email 만 정책(SSOT)으로 해석한다.

    Calendar 도구 7개 모두 `user_email` 을 받는다. 스키마상으로는 선택이지만 실제 값
    결정은 `mcp_common.user_resolver` 가 한다 — mode 0 은 명시값 → 환경변수 → auth.db
    (끝내 없으면 `ToolExecutionError`), mode 1 은 인증된 호출자의 연결 계정만.
    """
    call = SPEC.call_args(tool_name, args)
    call["user_email"] = resolve_user_email(call.get("user_email"), required=True)
    return call


async def handle_calendar_view(args: Dict[str, Any]) -> Any:
    return await _service().calendar_view(**_call_args("calendar_view", args))


async def handle_get_event(args: Dict[str, Any]) -> Any:
    return await _service().get_event(**_call_args("get_event", args))


async def handle_create_event(args: Dict[str, Any]) -> Any:
    return await _service().create_event(**_call_args("create_event", args))


async def handle_list_events(args: Dict[str, Any]) -> Any:
    return await _service().list_events(**_call_args("list_events", args))


async def handle_update_event(args: Dict[str, Any]) -> Any:
    return await _service().update_event(**_call_args("update_event", args))


async def handle_get_schedule(args: Dict[str, Any]) -> Any:
    return await _service().get_schedule(**_call_args("get_schedule", args))


async def handle_delete_event(args: Dict[str, Any]) -> Any:
    return await _service().delete_event(**_call_args("delete_event", args))


TOOL_HANDLERS = {
    "calendar_view": handle_calendar_view,
    "get_event": handle_get_event,
    "create_event": handle_create_event,
    "list_events": handle_list_events,
    "update_event": handle_update_event,
    "get_schedule": handle_get_schedule,
    "delete_event": handle_delete_event,
}


# 기본값 주입 + 스키마 검증 + 오류 정규화는 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [calendar_service])


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
    "create_service",
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
