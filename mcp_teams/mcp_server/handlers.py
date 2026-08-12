"""
Teams MCP — 핸들러와 `Server` 구성. **두 트랜스포트가 공유하는 유일한 원본이다.**

도구 계약(이름·설명·파라미터·기본값)은 `spec/param_spec/teams.yaml` 한 곳에만 있다.
이 파일에는 도구 정의를 적지 않는다 — 적는 순간 사본이 두 벌이 되어 드리프트한다
(spec/spec_도구정의.md, spec/spec_MCP트랜스포트.md ②-3-1).

`server_stdio.py` 와 `server_stream.py` 는 이 모듈을 import 해 `build_mcp_server()` 가
만든 같은 `Server` 객체를 받아 구동만 한다.

이 모듈은 트랜스포트를 import 하지 않는다(단방향 의존). 또한 프로세스 부트스트랩을
수행하지 않는다 — 호출자가 `mcp_common.bootstrap` 을 먼저 돌린 뒤 import 해야 한다.
"""

from typing import Any, Dict, List, Optional

from mcp_common.param_spec import load_param_spec
from mcp_common.runtime import ServiceLifecycle, ToolRuntime
from mcp_common.user_resolver import resolve_user_email

from mcp_teams.teams_service import TeamsService

# 도구 계약의 단일 원본. 이 파일에는 도구 정의를 적지 않는다.
SPEC = load_param_spec("teams")

SERVER_NAME = SPEC.name
SERVER_VERSION = SPEC.version
DEFAULT_PORT = SPEC.port or 5003

MCP_TOOLS: List[Dict[str, Any]] = SPEC.mcp_tools()


teams_service = TeamsService()


def _args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """spec 이 파생시킨 호출 인자 + 사용자 해석.

    `user_email` 만은 spec 으로 표현할 수 없다 — 값이 비면 mcp_common 정책(SSOT)이
    기본 사용자를 고른다. 14개 도구가 모두 같은 규칙을 쓰므로 여기 한 곳에 둔다.
    """
    call_args = SPEC.call_args(tool_name, args)
    call_args["user_email"] = resolve_user_email(call_args.get("user_email"), required=True)
    return call_args


# ============================================================
# Tool handlers — TeamsService 메서드로 가는 얇은 래퍼
# ============================================================


async def handle_list_chats(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.list_chats(**_args("handler_teams_list_chats", args))


async def handle_get_chat(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_chat(**_args("handler_teams_get_chat", args))


async def handle_get_chat_messages(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_chat_messages(
        **_args("handler_teams_get_chat_messages", args)
    )


async def handle_send_chat_message(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.send_chat_message(
        **_args("handler_teams_send_chat_message", args)
    )


async def handle_list_teams(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.list_teams(**_args("handler_teams_list_teams", args))


async def handle_list_channels(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.list_channels(**_args("handler_teams_list_channels", args))


async def handle_get_channel_messages(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_channel_messages(
        **_args("handler_teams_get_channel_messages", args)
    )


async def handle_send_channel_message(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.send_channel_message(
        **_args("handler_teams_send_channel_message", args)
    )


async def handle_get_message_replies(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_message_replies(
        **_args("handler_teams_get_message_replies", args)
    )


async def handle_save_korean_name(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.save_korean_name(
        **_args("handler_teams_save_korean_name", args)
    )


async def handle_save_korean_names_batch(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.save_korean_names_batch(
        **_args("handler_teams_save_korean_names_batch", args)
    )


async def handle_find_chat_by_name(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.find_chat_by_name(
        **_args("handler_teams_find_chat_by_name", args)
    )


async def handle_sync_chats(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.sync_chats(**_args("handler_teams_sync_chats", args))


async def handle_get_chats_without_korean(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_chats_without_korean(
        **_args("handler_teams_get_chats_without_korean", args)
    )


TOOL_HANDLERS = {
    "handler_teams_list_chats": handle_list_chats,
    "handler_teams_get_chat": handle_get_chat,
    "handler_teams_get_chat_messages": handle_get_chat_messages,
    "handler_teams_send_chat_message": handle_send_chat_message,
    "handler_teams_list_teams": handle_list_teams,
    "handler_teams_list_channels": handle_list_channels,
    "handler_teams_get_channel_messages": handle_get_channel_messages,
    "handler_teams_send_channel_message": handle_send_channel_message,
    "handler_teams_get_message_replies": handle_get_message_replies,
    "handler_teams_save_korean_name": handle_save_korean_name,
    "handler_teams_save_korean_names_batch": handle_save_korean_names_batch,
    "handler_teams_find_chat_by_name": handle_find_chat_by_name,
    "handler_teams_sync_chats": handle_sync_chats,
    "handler_teams_get_chats_without_korean": handle_get_chats_without_korean,
}


# 기본값 주입 + 스키마 검증 + 오류 정규화는 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [teams_service])


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
    "SPEC",
    "runtime",
    "lifecycle",
    "build_mcp_server",
    "get_tool_config",
]
