"""
Streamable HTTP MCP Server for OneNote MCP Server
Exposes OneNoteService router tools (read/write/delete) + sync_db (port 5005).
Inline tool definitions (no YAML dependency).
"""
import json
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
from session.auth_database import AuthDatabase

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def get_default_user_email() -> Optional[str]:
    try:
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email') or users[0].get('email')
        return None
    except Exception as e:
        logger.warning(f"Failed to get default user email from auth.db: {e}")
        return None


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


def _resolve_user_email(args: Dict[str, Any]) -> Optional[str]:
    user_email = args.get("user_email")
    if user_email:
        return user_email
    return get_default_user_email()


def _require_user_email(args: Dict[str, Any]):
    user_email = _resolve_user_email(args)
    if not user_email:
        return None, {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
    return user_email, None


async def handle_read_onenote(args):
    user_email, err = _require_user_email(args)
    if err:
        return err
    return await onenote_service.read_onenote(
        user_email=user_email,
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
    user_email, err = _require_user_email(args)
    if err:
        return err
    return await onenote_service.write_onenote(
        user_email=user_email,
        action=args["action"],
        content=args.get("content"),
        page_id=args.get("page_id"),
        section_id=args.get("section_id"),
        notebook_id=args.get("notebook_id"),
        title=args.get("title"),
    )


async def handle_delete_onenote(args):
    user_email, err = _require_user_email(args)
    if err:
        return err
    return await onenote_service.delete_onenote(user_email=user_email, page_id=args["page_id"])


async def handle_sync_onenote_db(args):
    user_email, err = _require_user_email(args)
    if err:
        return err
    return await onenote_service.writer.sync_db(user_email=user_email)


TOOL_HANDLERS = {
    "read_onenote": handle_read_onenote,
    "write_onenote": handle_write_onenote,
    "delete_onenote": handle_delete_onenote,
    "sync_onenote_db": handle_sync_onenote_db,
}


def get_tool_config(tool_name: str) -> Optional[dict]:
    for tool in MCP_TOOLS:
        if tool.get("name") == tool_name:
            return tool
    return None


def apply_schema_defaults(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    tool_config = get_tool_config(tool_name)
    if not tool_config:
        return arguments
    properties = tool_config.get("inputSchema", {}).get("properties", {})
    merged_args = dict(arguments) if arguments else {}
    for prop_name, prop_def in properties.items():
        if prop_name not in merged_args and "default" in prop_def:
            merged_args[prop_name] = prop_def["default"]
    return merged_args


import mcp.types as mcp_types
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.requests import Request as StarletteRequest


def _build_tool_objects() -> List[mcp_types.Tool]:
    tools: List[mcp_types.Tool] = []
    for raw in MCP_TOOLS:
        name = raw.get("name")
        if not name:
            continue
        input_schema = raw.get("inputSchema") or {"type": "object", "properties": {}}
        if "type" not in input_schema:
            input_schema = {"type": "object", **input_schema}
        tools.append(mcp_types.Tool(name=name, description=raw.get("description") or "", inputSchema=input_schema))
    return tools


def build_mcp_server() -> MCPServer:
    server: MCPServer = MCPServer(name="onenote", version="1.0.0")
    tool_objects = _build_tool_objects()

    @server.list_tools()
    async def _list_tools() -> List[mcp_types.Tool]:
        return tool_objects

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")
        merged_args = apply_schema_defaults(name, arguments or {})
        try:
            result = await handler(merged_args)
        except Exception as e:
            logger.exception(f"Error executing tool {name}: {e}")
            return [mcp_types.TextContent(type="text", text=json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))]

        if isinstance(result, dict) and result.get("status") == "auth_required":
            return [mcp_types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        if isinstance(result, str):
            return [mcp_types.TextContent(type="text", text=result)]
        return [mcp_types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2, default=str))]

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
        return JSONResponse({
            "status": "healthy", "server": "onenote", "protocol": "streamable-http",
            "version": "1.0.0", "tool_count": len(MCP_TOOLS),
        })

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            try:
                await onenote_service.initialize()
                logger.info("OneNoteService initialized")
            except Exception as e:
                logger.warning(f"OneNoteService initialize() failed: {e}")
            logger.info(f"OneNote MCP Streamable HTTP server ready with {len(MCP_TOOLS)} tools")
            try:
                yield
            finally:
                try:
                    await onenote_service.close()
                except Exception:
                    pass

    return Starlette(debug=False, routes=[
        Route("/mcp", endpoint=handle_streamable_http),
        Route("/health", endpoint=health, methods=["GET"]),
    ], lifespan=lifespan)


app = build_starlette_app()


def run(host: str = "0.0.0.0", port: int = 5005) -> None:
    import uvicorn
    logger.info(f"Starting OneNote MCP Streamable HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", 5005))
    run(host="0.0.0.0", port=port)
