"""
Streamable HTTP MCP Server for Todo MCP Server

Uses the official MCP Python SDK's Streamable HTTP transport (spec: MCP 2025-03-26)
mounted on a Starlette app served by uvicorn.
"""
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
import sys
import os
import logging
import asyncio
import contextlib
from collections.abc import AsyncIterator
from dotenv import load_dotenv

# Add parent directories to path for module access
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

# Load .env from project root before any imports that need env vars
_env_path = os.path.join(grandparent_dir, ".env")
_env_loaded = load_dotenv(_env_path, encoding="utf-8-sig")

# BOM safety: strip BOM from env vars if present
for _key in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_REDIRECT_URI", "AZURE_SCOPES"):
    _val = os.environ.get(_key)
    if _val and _val.startswith("﻿"):
        os.environ[_key] = _val.lstrip("﻿")

# Add paths for imports
server_module_dir = os.path.join(grandparent_dir, "mcp_todo")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

from mcp_todo.todo_service import TodoService
from mcp_common.net import resolve_bind_host
from mcp_common.runtime import (
    ServiceLifecycle,
    ToolRuntime,
    build_health_payload,
    health_status_code,
)
from mcp_common.user_resolver import resolve_user_email

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

SERVER_NAME = "todo"
SERVER_VERSION = "1.0.0"
DEFAULT_PORT = 5006


# ============================================================
# Tool definitions loading (YAML)
# ============================================================

def _load_mcp_tools() -> List[Dict[str, Any]]:
    """Load MCP tools from tool_definition_templates.yaml."""
    yaml_path_str = os.environ.get("MCP_YAML_PATH")
    if yaml_path_str:
        yaml_path = Path(yaml_path_str)
    else:
        yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_todo" / "tool_definition_templates.yaml"

    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("tools", [])
    raise FileNotFoundError(f"Tool definition YAML not found: {yaml_path}")


MCP_TOOLS = _load_mcp_tools()


# ============================================================
# Service instantiation
# ============================================================

todo_service = TodoService()


# ============================================================
# Tool handlers
# ============================================================

def _resolve_user_email(args: Dict[str, Any]) -> Optional[str]:
    """사용자 선택은 mcp_common 정책(SSOT)에 위임한다."""
    return resolve_user_email(args.get("user_email"), required=True)


async def handle_todo_lists_view(args: Dict[str, Any]) -> Dict[str, Any]:
    top = args.get("top") if args.get("top") is not None else 50
    return await todo_service.todo_lists_view(user_email=_resolve_user_email(args), top=top)


async def handle_todo_list_create(args: Dict[str, Any]) -> Dict[str, Any]:
    return await todo_service.todo_list_create(
        user_email=_resolve_user_email(args),
        display_name=args.get("display_name", ""),
    )


async def handle_todo_list_delete(args: Dict[str, Any]) -> Dict[str, Any]:
    return await todo_service.todo_list_delete(
        user_email=_resolve_user_email(args),
        list_id_or_name=args.get("list_id_or_name", ""),
    )


async def handle_todo_tasks_view(args: Dict[str, Any]) -> Dict[str, Any]:
    top = args.get("top") if args.get("top") is not None else 50
    return await todo_service.todo_tasks_view(
        user_email=_resolve_user_email(args),
        list_id_or_name=args.get("list_id_or_name"),
        status_filter=args.get("status_filter"),
        top=top,
        orderby=args.get("orderby"),
    )


async def handle_todo_task_get(args: Dict[str, Any]) -> Dict[str, Any]:
    return await todo_service.todo_task_get(
        user_email=_resolve_user_email(args),
        list_id_or_name=args.get("list_id_or_name"),
        task_id=args.get("task_id", ""),
    )


async def handle_todo_task_create(args: Dict[str, Any]) -> Dict[str, Any]:
    return await todo_service.todo_task_create(
        user_email=_resolve_user_email(args),
        list_id_or_name=args.get("list_id_or_name"),
        title=args.get("title", ""),
        body=args.get("body"),
        importance=args.get("importance"),
        due_datetime=args.get("due_datetime"),
        reminder_datetime=args.get("reminder_datetime"),
        categories=args.get("categories"),
    )


async def handle_todo_task_update(args: Dict[str, Any]) -> Dict[str, Any]:
    return await todo_service.todo_task_update(
        user_email=_resolve_user_email(args),
        list_id_or_name=args.get("list_id_or_name"),
        task_id=args.get("task_id", ""),
        title=args.get("title"),
        body=args.get("body"),
        importance=args.get("importance"),
        status=args.get("status"),
        due_datetime=args.get("due_datetime"),
        reminder_datetime=args.get("reminder_datetime"),
        categories=args.get("categories"),
    )


async def handle_todo_task_delete(args: Dict[str, Any]) -> Dict[str, Any]:
    return await todo_service.todo_task_delete(
        user_email=_resolve_user_email(args),
        list_id_or_name=args.get("list_id_or_name"),
        task_id=args.get("task_id", ""),
    )


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


# 기본값 주입 / 입력 검증 / 오류 정규화는 모두 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [todo_service])


# ============================================================
# MCP SDK: Server + Streamable HTTP transport
# ============================================================
import mcp.types as mcp_types
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.requests import Request as StarletteRequest


def build_mcp_server() -> MCPServer:
    """Construct an MCP lowlevel Server with tools registered."""
    server: MCPServer = MCPServer(name=SERVER_NAME, version=SERVER_VERSION)
    tool_objects = runtime.build_tool_objects()

    @server.list_tools()
    async def _list_tools() -> List[mcp_types.Tool]:
        return tool_objects

    # SDK 검증은 끄고(validate_input=False) ToolRuntime 이 검증/디스패치를 수행한다.
    # 실패는 ToolExecutionError 로 올라가 SDK 가 CallToolResult(isError=True) 로 감싼다.
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        return await runtime.dispatch(name, arguments)

    return server


def build_starlette_app() -> Starlette:
    """Build the Starlette ASGI app that hosts the StreamableHTTP MCP endpoint at /mcp."""
    mcp_server = build_mcp_server()

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=False,
        stateless=False,
    )

    class _StreamableHTTPASGI:
        def __init__(self, sm: StreamableHTTPSessionManager):
            self._sm = sm

        async def __call__(self, scope, receive, send) -> None:
            await self._sm.handle_request(scope, receive, send)

    handle_streamable_http = _StreamableHTTPASGI(session_manager)

    async def health(_request: StarletteRequest) -> JSONResponse:
        # 초기화 실패 시 degraded/503 을 반환한다 (예전에는 항상 healthy 였다).
        payload = build_health_payload(
            SERVER_NAME, runtime, lifecycle, version=SERVER_VERSION
        )
        return JSONResponse(payload, status_code=health_status_code(payload))

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            await lifecycle.startup()
            logger.info(
                f"Todo MCP Streamable HTTP server ready with {len(runtime.tools)} tools"
            )
            try:
                yield
            finally:
                # 예전에는 close() 가 아예 호출되지 않아 aiohttp 세션이 남았다.
                await lifecycle.shutdown()

    return Starlette(
        debug=False,
        routes=[
            Route("/mcp", endpoint=handle_streamable_http),
            Route("/health", endpoint=health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


app = build_starlette_app()


def run(host: Optional[str] = None, port: int = DEFAULT_PORT) -> None:
    import uvicorn
    # 기본 바인드는 loopback. 외부 노출은 MCP_BIND_HOST/MCP_ALLOW_PUBLIC_BIND 옵트인 필요.
    bind_host = resolve_bind_host(host, server_name=SERVER_NAME)
    logger.info(f"Starting Todo MCP Streamable HTTP server on {bind_host}:{port}")
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT))
    run(port=port)
