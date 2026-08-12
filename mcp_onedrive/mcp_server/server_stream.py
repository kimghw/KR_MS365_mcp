"""
Streamable HTTP MCP Server for OneDrive MCP Server
Exposes OneDriveService methods as MCP tools (port 5004).
Inline tool definitions (no YAML dependency).

dispatch/검증/오류계약/lifecycle/bind 주소는 mcp_common 으로 수렴한다.
"""
from typing import Dict, Any, List, Optional
import sys
import os
import logging
import contextlib
from collections.abc import AsyncIterator
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

_env_path = os.path.join(grandparent_dir, ".env")
_env_loaded = load_dotenv(_env_path, encoding="utf-8-sig")

for _key in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_REDIRECT_URI", "AZURE_SCOPES"):
    _val = os.environ.get(_key)
    if _val and _val.startswith("﻿"):
        os.environ[_key] = _val.lstrip("﻿")

print(f"[DEBUG] .env path: {_env_path}, exists: {os.path.exists(_env_path)}, loaded: {_env_loaded}", file=sys.stderr)
print(f"[DEBUG] AZURE_CLIENT_ID: {repr(os.getenv('AZURE_CLIENT_ID'))}", file=sys.stderr)

server_module_dir = os.path.join(grandparent_dir, "mcp_onedrive")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

from mcp_onedrive.onedrive_service import OneDriveService
from mcp_common.net import resolve_bind_host
from mcp_common.runtime import (
    ServiceLifecycle,
    ToolRuntime,
    build_health_payload,
    health_status_code,
)
from mcp_common.user_resolver import resolve_user_email

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

SERVER_NAME = "onedrive"
DEFAULT_PORT = 5004


MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "handler_onedrive_get_drive_info",
        "description": "OneDrive 드라이브 정보 조회",
        "inputSchema": {
            "type": "object",
            "properties": {"user_email": {"type": "string"}},
        },
    },
    {
        "name": "handler_onedrive_list_files",
        "description": "OneDrive 파일/폴더 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_email": {"type": "string"},
                "folder_path": {"type": "string", "description": "조회할 폴더 경로 (없으면 루트)"},
                "search": {"type": "string", "description": "이름 검색어"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "handler_onedrive_get_item",
        "description": "OneDrive 파일/폴더 정보 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "user_email": {"type": "string"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "handler_onedrive_read_file",
        "description": "OneDrive 파일 내용 읽기",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "user_email": {"type": "string"},
                "as_text": {"type": "boolean", "default": True, "description": "True면 텍스트로, False면 바이너리 base64로"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "handler_onedrive_write_file",
        "description": "OneDrive 파일 쓰기/업로드",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string", "description": "파일 내용 (텍스트)"},
                "user_email": {"type": "string"},
                "content_type": {"type": "string", "default": "text/plain"},
                "overwrite": {"type": "boolean", "default": True},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "handler_onedrive_delete_file",
        "description": "OneDrive 파일/폴더 삭제",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "user_email": {"type": "string"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "handler_onedrive_create_folder",
        "description": "OneDrive 폴더 생성",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_name": {"type": "string"},
                "user_email": {"type": "string"},
                "parent_path": {"type": "string", "description": "상위 폴더 경로 (없으면 루트)"},
            },
            "required": ["folder_name"],
        },
    },
    {
        "name": "handler_onedrive_copy_file",
        "description": "OneDrive 파일 복사",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string"},
                "dest_path": {"type": "string"},
                "user_email": {"type": "string"},
                "new_name": {"type": "string"},
            },
            "required": ["source_path", "dest_path"],
        },
    },
    {
        "name": "handler_onedrive_move_file",
        "description": "OneDrive 파일 이동",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string"},
                "dest_path": {"type": "string"},
                "user_email": {"type": "string"},
                "new_name": {"type": "string"},
            },
            "required": ["source_path", "dest_path"],
        },
    },
]


onedrive_service = OneDriveService()


def _resolve_user_email(args: Dict[str, Any]) -> str:
    """사용자 선택은 mcp_common 정책(SSOT)에 위임. 없으면 ToolExecutionError."""
    return resolve_user_email(args.get("user_email"), required=True)


async def handle_get_drive_info(args):
    return await onedrive_service.get_drive_info(user_email=_resolve_user_email(args))


async def handle_list_files(args):
    return await onedrive_service.list_files(
        user_email=_resolve_user_email(args),
        folder_path=args.get("folder_path"),
        search=args.get("search"),
        limit=args.get("limit", 50),
    )


async def handle_get_item(args):
    return await onedrive_service.get_item(file_path=args["file_path"], user_email=_resolve_user_email(args))


async def handle_read_file(args):
    return await onedrive_service.read_file(
        file_path=args["file_path"],
        user_email=_resolve_user_email(args),
        as_text=args.get("as_text", True),
    )


async def handle_write_file(args):
    return await onedrive_service.write_file(
        file_path=args["file_path"],
        content=args["content"],
        user_email=_resolve_user_email(args),
        content_type=args.get("content_type", "text/plain"),
        overwrite=args.get("overwrite", True),
    )


async def handle_delete_file(args):
    return await onedrive_service.delete_file(file_path=args["file_path"], user_email=_resolve_user_email(args))


async def handle_create_folder(args):
    return await onedrive_service.create_folder(
        folder_name=args["folder_name"],
        user_email=_resolve_user_email(args),
        parent_path=args.get("parent_path"),
    )


async def handle_copy_file(args):
    return await onedrive_service.copy_file(
        source_path=args["source_path"],
        dest_path=args["dest_path"],
        user_email=_resolve_user_email(args),
        new_name=args.get("new_name"),
    )


async def handle_move_file(args):
    return await onedrive_service.move_file(
        source_path=args["source_path"],
        dest_path=args["dest_path"],
        user_email=_resolve_user_email(args),
        new_name=args.get("new_name"),
    )


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


import mcp.types as mcp_types
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.requests import Request as StarletteRequest


def _build_tool_objects() -> List[mcp_types.Tool]:
    return runtime.build_tool_objects()


def build_mcp_server() -> MCPServer:
    server: MCPServer = MCPServer(name=SERVER_NAME, version="1.0.0")
    tool_objects = _build_tool_objects()

    @server.list_tools()
    async def _list_tools() -> List[mcp_types.Tool]:
        return tool_objects

    # SDK 검증은 끄고(validate_input=False) ToolRuntime 이 검증한다.
    # 실패는 예외로 올라가 SDK 가 CallToolResult(isError=True) 로 감싼다.
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        return await runtime.dispatch(name, arguments)

    return server


def build_starlette_app() -> Starlette:
    mcp_server = build_mcp_server()
    session_manager = StreamableHTTPSessionManager(app=mcp_server, event_store=None, json_response=False, stateless=False)

    class _StreamableHTTPASGI:
        def __init__(self, sm):
            self._sm = sm

        async def __call__(self, scope, receive, send) -> None:
            await self._sm.handle_request(scope, receive, send)

    handle_streamable_http = _StreamableHTTPASGI(session_manager)

    async def health(_request: StarletteRequest) -> JSONResponse:
        payload = build_health_payload(SERVER_NAME, runtime, lifecycle)
        return JSONResponse(payload, status_code=health_status_code(payload))

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            await lifecycle.startup()
            logger.info(
                f"OneDrive MCP Streamable HTTP server ready with {len(runtime.tools)} tools"
            )
            try:
                yield
            finally:
                await lifecycle.shutdown()

    return Starlette(debug=False, routes=[
        Route("/mcp", endpoint=handle_streamable_http),
        Route("/health", endpoint=health, methods=["GET"]),
    ], lifespan=lifespan)


app = build_starlette_app()


def run(host: Optional[str] = None, port: int = DEFAULT_PORT) -> None:
    import uvicorn
    # 기본 loopback. 외부 노출은 MCP_BIND_HOST + MCP_ALLOW_PUBLIC_BIND 옵트인 필요.
    bind_host = resolve_bind_host(host, server_name=SERVER_NAME)
    logger.info(f"Starting OneDrive MCP Streamable HTTP server on {bind_host}:{port}")
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT))
    run(port=port)
