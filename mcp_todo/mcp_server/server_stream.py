"""
Streamable HTTP MCP Server for Todo MCP Server

Uses the official MCP Python SDK's Streamable HTTP transport (spec: MCP 2025-03-26)
mounted on a Starlette app served by uvicorn.
"""
import json
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
from session.auth_database import AuthDatabase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def get_default_user_email() -> Optional[str]:
    """Get default user email from auth.db when not provided."""
    try:
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email') or users[0].get('email')
        return None
    except Exception as e:
        logger.warning(f"Failed to get default user email from auth.db: {e}")
        return None


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


def get_tool_config(tool_name: str) -> Optional[dict]:
    for tool in MCP_TOOLS:
        if tool.get("name") == tool_name:
            return tool
    return None


def apply_schema_defaults(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Apply default values from inputSchema to arguments if not provided."""
    tool_config = get_tool_config(tool_name)
    if not tool_config:
        return arguments
    input_schema = tool_config.get("inputSchema", {})
    properties = input_schema.get("properties", {})
    merged = dict(arguments) if arguments else {}
    for prop_name, prop_def in properties.items():
        if prop_name not in merged and "default" in prop_def:
            merged[prop_name] = prop_def["default"]
    return merged


# ============================================================
# Tool handlers
# ============================================================

async def handle_todo_lists_view(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    top = args.get("top") if args.get("top") is not None else 50
    return await todo_service.todo_lists_view(user_email=user_email, top=top)


async def handle_todo_list_create(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    display_name = args.get("display_name", "")
    return await todo_service.todo_list_create(user_email=user_email, display_name=display_name)


async def handle_todo_list_delete(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    list_id_or_name = args.get("list_id_or_name", "")
    return await todo_service.todo_list_delete(
        user_email=user_email, list_id_or_name=list_id_or_name
    )


async def handle_todo_tasks_view(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    list_id_or_name = args.get("list_id_or_name")
    status_filter = args.get("status_filter")
    top = args.get("top") if args.get("top") is not None else 50
    orderby = args.get("orderby")
    return await todo_service.todo_tasks_view(
        user_email=user_email,
        list_id_or_name=list_id_or_name,
        status_filter=status_filter,
        top=top,
        orderby=orderby,
    )


async def handle_todo_task_get(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    list_id_or_name = args.get("list_id_or_name")
    task_id = args.get("task_id", "")
    return await todo_service.todo_task_get(
        user_email=user_email, list_id_or_name=list_id_or_name, task_id=task_id
    )


async def handle_todo_task_create(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    return await todo_service.todo_task_create(
        user_email=user_email,
        list_id_or_name=args.get("list_id_or_name"),
        title=args.get("title", ""),
        body=args.get("body"),
        importance=args.get("importance"),
        due_datetime=args.get("due_datetime"),
        reminder_datetime=args.get("reminder_datetime"),
        categories=args.get("categories"),
    )


async def handle_todo_task_update(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    return await todo_service.todo_task_update(
        user_email=user_email,
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
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    return await todo_service.todo_task_delete(
        user_email=user_email,
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


def _build_tool_objects() -> List[mcp_types.Tool]:
    """Convert YAML-loaded tool dicts to mcp.types.Tool objects."""
    tools: List[mcp_types.Tool] = []
    for raw in MCP_TOOLS:
        name = raw.get("name")
        if not name:
            continue
        input_schema = raw.get("inputSchema") or {"type": "object", "properties": {}}
        if "type" not in input_schema:
            input_schema = {"type": "object", **input_schema}
        description = raw.get("description") or ""
        tools.append(
            mcp_types.Tool(
                name=name,
                description=description,
                inputSchema=input_schema,
            )
        )
    return tools


def build_mcp_server() -> MCPServer:
    """Construct an MCP lowlevel Server with tools registered."""
    server: MCPServer = MCPServer(name="todo", version="1.0.0")
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
            return [mcp_types.TextContent(
                type="text",
                text=json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False),
            )]

        if isinstance(result, dict) and result.get("status") == "auth_required":
            return [mcp_types.TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )]

        if isinstance(result, str):
            return [mcp_types.TextContent(type="text", text=result)]

        return [mcp_types.TextContent(
            type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
        )]

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
        return JSONResponse({
            "status": "healthy",
            "server": "todo",
            "protocol": "streamable-http",
            "version": "1.0.0",
            "tool_count": len(MCP_TOOLS),
        })

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            try:
                await todo_service.initialize()
                logger.info("TodoService initialized")
            except Exception as e:
                logger.warning(f"TodoService initialize() failed: {e}")
            logger.info(f"Todo MCP Streamable HTTP server ready with {len(MCP_TOOLS)} tools")
            yield

    return Starlette(
        debug=False,
        routes=[
            Route("/mcp", endpoint=handle_streamable_http),
            Route("/health", endpoint=health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


app = build_starlette_app()


def run(host: str = "0.0.0.0", port: int = 8093) -> None:
    import uvicorn
    logger.info(f"Starting Todo MCP Streamable HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", 8093))
    run(host="0.0.0.0", port=port)
