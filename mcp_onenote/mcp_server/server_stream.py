"""
Streamable HTTP MCP Server for OneNote MCP Server
Exposes OneNoteService router tools (read/write/delete) + sync_db (port 5005).
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

server_module_dir = os.path.join(grandparent_dir, "mcp_onenote")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

from mcp_onenote.onenote_service import OneNoteService
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

SERVER_NAME = "onenote"
DEFAULT_PORT = 5005


MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "read_onenote",
        "description": "OneNote 조회 라우터. action에 따라 페이지/섹션 목록, 검색, 본문 조회, 요약 수행",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_email": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["list_pages", "list_sections", "search", "get_content", "get_summary"],
                    "description": "수행할 액션",
                },
                "keyword": {"type": "string", "description": "search 액션의 검색어"},
                "page_id": {"type": "string", "description": "get_content/get_summary용"},
                "section_id": {"type": "string"},
                "notebook_id": {"type": "string"},
                "date_from": {"type": "string", "description": "ISO 8601 시작 날짜 (포함)"},
                "date_to": {"type": "string", "description": "ISO 8601 종료 날짜 (포함)"},
                "top": {"type": "integer", "default": 50},
            },
            "required": ["action"],
        },
    },
    {
        "name": "write_onenote",
        "description": "OneNote 생성/수정 라우터. action: append, create_page, create_section",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_email": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["append", "create_page", "create_section"],
                },
                "content": {"type": "string", "description": "append/create_page용 본문"},
                "page_id": {"type": "string", "description": "append용 (없으면 최근 페이지)"},
                "section_id": {"type": "string", "description": "create_page용"},
                "notebook_id": {"type": "string", "description": "create_section용"},
                "title": {"type": "string", "description": "create_page/create_section용"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "delete_onenote",
        "description": "OneNote 페이지 삭제",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_email": {"type": "string"},
                "page_id": {"type": "string"},
            },
            "required": ["page_id"],
        },
    },
    {
        "name": "sync_onenote_db",
        "description": "OneNote 전체 페이지를 DB에 동기화 (/me/onenote/pages 전체 조회)",
        "inputSchema": {
            "type": "object",
            "properties": {"user_email": {"type": "string"}},
        },
    },
]


onenote_service = OneNoteService()


def _resolve_user_email(args: Dict[str, Any]) -> str:
    """사용자 선택은 mcp_common 정책(SSOT)에 위임. 없으면 ToolExecutionError."""
    return resolve_user_email(args.get("user_email"), required=True)


async def handle_read_onenote(args):
    return await onenote_service.read_onenote(
        user_email=_resolve_user_email(args),
        action=args["action"],
        keyword=args.get("keyword"),
        page_id=args.get("page_id"),
        section_id=args.get("section_id"),
        notebook_id=args.get("notebook_id"),
        date_from=args.get("date_from"),
        date_to=args.get("date_to"),
        top=args.get("top", 50),
    )


async def handle_write_onenote(args):
    return await onenote_service.write_onenote(
        user_email=_resolve_user_email(args),
        action=args["action"],
        content=args.get("content"),
        page_id=args.get("page_id"),
        section_id=args.get("section_id"),
        notebook_id=args.get("notebook_id"),
        title=args.get("title"),
    )


async def handle_delete_onenote(args):
    return await onenote_service.delete_onenote(
        user_email=_resolve_user_email(args), page_id=args["page_id"]
    )


async def handle_sync_onenote_db(args):
    return await onenote_service.writer.sync_db(user_email=_resolve_user_email(args))


TOOL_HANDLERS = {
    "read_onenote": handle_read_onenote,
    "write_onenote": handle_write_onenote,
    "delete_onenote": handle_delete_onenote,
    "sync_onenote_db": handle_sync_onenote_db,
}


# 기본값 주입 + 스키마 검증 + 오류 정규화는 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [onenote_service])


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
                f"OneNote MCP Streamable HTTP server ready with {len(runtime.tools)} tools"
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
    logger.info(f"Starting OneNote MCP Streamable HTTP server on {bind_host}:{port}")
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT))
    run(port=port)
