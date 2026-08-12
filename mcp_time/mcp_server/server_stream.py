"""Streamable HTTP MCP Server for mcp_time (port 5007). 인증 불필요.

dispatch/검증/오류계약/lifecycle/bind 주소는 mcp_common 으로 수렴한다.
"""
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
from mcp_common.net import resolve_bind_host
from mcp_common.runtime import (
    ServiceLifecycle,
    ToolRuntime,
    build_health_payload,
    health_status_code,
)

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)

SERVER_NAME = "time"
DEFAULT_PORT = 5007


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


# 기본값 주입 + 스키마 검증 + 오류 정규화는 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [time_service])


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


def _build_tool_objects():
    return runtime.build_tool_objects()


def build_mcp_server() -> MCPServer:
    server = MCPServer(name=SERVER_NAME, version="1.0.0")
    tool_objects = _build_tool_objects()

    @server.list_tools()
    async def _list_tools():
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
                f"Time MCP Streamable HTTP server ready with {len(runtime.tools)} tools"
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
    logger.info(f"Starting Time MCP Streamable HTTP server on {bind_host}:{port}")
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT))
    run(port=port)
