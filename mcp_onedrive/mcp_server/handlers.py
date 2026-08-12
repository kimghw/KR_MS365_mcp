"""
OneDrive MCP — 도구 정의와 핸들러. **두 트랜스포트가 공유하는 유일한 원본이다.**

`server_stdio.py` 와 `server_stream.py` 는 이 모듈을 import 해 `build_mcp_server()` 가
만든 같은 `Server` 객체를 받아 구동만 한다. 도구 정의나 핸들러가 트랜스포트 파일에
다시 나타나면 사양 위반이다(spec/spec_MCP트랜스포트.md ②-3-1). 전에는 `MCP_TOOLS`
리터럴이 stdio·stream 에 각각 복사돼 있었고 실제로 드리프트했다(stdio 사본에
folder_path·search·as_text·content·parent_path 의 description 이 빠져 있었다).

이 모듈은 트랜스포트를 import 하지 않는다(단방향 의존). 또한 프로세스 부트스트랩을
수행하지 않는다 — 호출자가 `mcp_common.bootstrap` 을 먼저 돌린 뒤 import 해야 한다.
"""

from typing import Any, Dict, List, Optional

from mcp_common.param_spec import load_param_spec
from mcp_common.runtime import ServiceLifecycle, ToolRuntime
from mcp_common.user_resolver import resolve_user_email

from mcp_onedrive.onedrive_service import OneDriveService

# 도구 계약의 단일 원본. 이 파일에는 도구 정의를 적지 않는다.
SPEC = load_param_spec("onedrive")

SERVER_NAME = SPEC.name
SERVER_VERSION = SPEC.version
DEFAULT_PORT = SPEC.port or 5004

MCP_TOOLS: List[Dict[str, Any]] = SPEC.mcp_tools()


onedrive_service = OneDriveService()


def _call_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """spec 에서 호출 인자를 파생시키고 user_email 만 정책(SSOT)으로 해석한다.

    OneDrive 도구는 9개 모두 `user_email` 을 받는다. 스키마상으로는 선택이지만
    실제 값 결정은 `mcp_common.user_resolver` 가 하고(명시값 → 환경변수 → auth.db),
    끝내 없으면 `ToolExecutionError` 를 올린다.
    """
    call = SPEC.call_args(tool_name, args)
    call["user_email"] = resolve_user_email(call.get("user_email"), required=True)
    return call


async def handle_get_drive_info(args: Dict[str, Any]) -> Any:
    return await onedrive_service.get_drive_info(
        **_call_args("handler_onedrive_get_drive_info", args)
    )


async def handle_list_files(args: Dict[str, Any]) -> Any:
    return await onedrive_service.list_files(**_call_args("handler_onedrive_list_files", args))


async def handle_get_item(args: Dict[str, Any]) -> Any:
    return await onedrive_service.get_item(**_call_args("handler_onedrive_get_item", args))


async def handle_read_file(args: Dict[str, Any]) -> Any:
    return await onedrive_service.read_file(**_call_args("handler_onedrive_read_file", args))


async def handle_write_file(args: Dict[str, Any]) -> Any:
    return await onedrive_service.write_file(**_call_args("handler_onedrive_write_file", args))


async def handle_delete_file(args: Dict[str, Any]) -> Any:
    return await onedrive_service.delete_file(**_call_args("handler_onedrive_delete_file", args))


async def handle_create_folder(args: Dict[str, Any]) -> Any:
    return await onedrive_service.create_folder(
        **_call_args("handler_onedrive_create_folder", args)
    )


async def handle_copy_file(args: Dict[str, Any]) -> Any:
    return await onedrive_service.copy_file(**_call_args("handler_onedrive_copy_file", args))


async def handle_move_file(args: Dict[str, Any]) -> Any:
    return await onedrive_service.move_file(**_call_args("handler_onedrive_move_file", args))


TOOL_HANDLERS = {
    "handler_onedrive_get_drive_info": handle_get_drive_info,
    "handler_onedrive_list_files": handle_list_files,
    "handler_onedrive_get_item": handle_get_item,
    "handler_onedrive_read_file": handle_read_file,
    "handler_onedrive_write_file": handle_write_file,
    "handler_onedrive_delete_file": handle_delete_file,
    "handler_onedrive_create_folder": handle_create_folder,
    "handler_onedrive_copy_file": handle_copy_file,
    "handler_onedrive_move_file": handle_move_file,
}


# 기본값 주입 + 스키마 검증 + 오류 정규화는 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [onedrive_service])


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
        # 진짜 bool -> enabled/disabled 보정은 ToolRuntime 이 검증 전에 처리한다.
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
