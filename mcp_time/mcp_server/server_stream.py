"""Streamable HTTP MCP Server for mcp_time (port 5007). 인증 불필요."""
import json
from typing import Dict, Any, List, Optional
import sys
import os
import logging
import contextlib
from collections.abc import AsyncIterator

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

from mcp_time.time_service import TimeService

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)


MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_current_time",
        "description": "현재 시간/날짜를 반환합니다. 어떤 입력이든 무시하고 현재 시간만 반환. 기본 timezone은 Asia/Seoul.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone 이름 (예: Asia/Seoul, UTC, America/New_York). 생략 시 Asia/Seoul.",
                },
            },
        },
    },
]


time_service = TimeService()


async def handle_get_current_time(args):
    return await time_service.get_current_time(timezone=args.get("timezone"))


TOOL_HANDLERS = {"get_current_time": handle_get_current_time}


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
    merged = dict(arguments) if arguments else {}
    for prop_name, prop_def in properties.items():
        if prop_name not in merged and "default" in prop_def:
            merged[prop_name] = prop_def["default"]
    return merged


import mcp.types as mcp_types
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.requests import Request as StarletteRequest


def _build_tool_objects():
    tools = []
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
    server = MCPServer(name="time", version="1.0.0")
    tool_objects = _build_tool_objects()

    @server.list_tools()
    async def _list_tools():
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
            "status": "healthy", "server": "time", "protocol": "streamable-http",
            "version": "1.0.0", "tool_count": len(MCP_TOOLS),
        })

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            logger.info(f"Time MCP Streamable HTTP server ready with {len(MCP_TOOLS)} tools")
            yield

    return Starlette(debug=False, routes=[
        Route("/mcp", endpoint=handle_streamable_http),
        Route("/health", endpoint=health, methods=["GET"]),
    ], lifespan=lifespan)


app = build_starlette_app()


def run(host: str = "0.0.0.0", port: int = 5007) -> None:
    import uvicorn
    logger.info(f"Starting Time MCP Streamable HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", 5007))
    run(host="0.0.0.0", port=port)
