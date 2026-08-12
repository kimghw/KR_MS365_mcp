"""
FileHandler MCP Streamable HTTP 서버 (표준 MCP SDK transport, port 5008)

보안 주의:
    - 이 서버에는 **호출자 인증이 없다**. 기본 바인드는 loopback(127.0.0.1) 전용이며,
      외부 노출은 `MCP_BIND_HOST` + `MCP_ALLOW_PUBLIC_BIND=1` 옵트인이 필요하다.
    - 도구가 여는 모든 파일/디렉터리는 `mcp_common.paths` 허용 루트로 제한된다
      (기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장).

엔드포인트:
    /mcp     — 표준 Streamable HTTP 단일 엔드포인트 (SDK 가 프로토콜 버전을 협상)
    /health  — 상태 조회. 초기화 실패 시 degraded + HTTP 503

이전 구현의 `/mcp/v1/initialize|tools/list|tools/call` 독자 경로, 자체 NDJSON 스트리밍,
`protocolVersion: 0.1.0` 하드코딩은 제거됐다(표준 클라이언트는 `/mcp` 만 호출한다).
도구 호출은 `ToolRuntime` 을 경유하므로 동기 핸들러를 `await` 하던 버그도 재발하지 않는다.
"""

import logging
import os
import sys
import contextlib
from collections.abc import AsyncIterator
from typing import Any, Dict, List

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

for _path in (grandparent_dir, parent_dir, current_dir):
    if _path not in sys.path:
        sys.path.insert(0, _path)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

import mcp.types as mcp_types
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_common.net import resolve_bind_host
from mcp_common.runtime import build_health_payload, health_status_code

try:
    from .handlers import (
        DEFAULT_PORT,
        SERVER_NAME,
        SERVER_VERSION,
        build_lifecycle,
        build_runtime,
        security_payload,
    )
except ImportError:  # 스크립트 직접 실행
    from handlers import (  # type: ignore[no-redef]
        DEFAULT_PORT,
        SERVER_NAME,
        SERVER_VERSION,
        build_lifecycle,
        build_runtime,
        security_payload,
    )


runtime = build_runtime()
lifecycle = build_lifecycle()


def build_mcp_server() -> MCPServer:
    """표준 MCP lowlevel 서버. 도구 실행/검증/오류 변환은 ToolRuntime 이 담당한다."""
    server: MCPServer = MCPServer(name=SERVER_NAME, version=SERVER_VERSION)
    tool_objects: List[mcp_types.Tool] = runtime.build_tool_objects()

    @server.list_tools()
    async def _list_tools() -> List[mcp_types.Tool]:
        return tool_objects

    @server.call_tool(validate_input=False)  # 검증은 ToolRuntime 이 수행
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        # 실패는 ToolExecutionError 로 올라가고 SDK 가 isError=True 로 감싼다.
        return await runtime.dispatch(name, arguments or {})

    return server


def build_starlette_app() -> Starlette:
    mcp_server = build_mcp_server()
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server, event_store=None, json_response=False, stateless=False
    )

    class _StreamableHTTPASGI:
        def __init__(self, sm):
            self._sm = sm

        async def __call__(self, scope, receive, send) -> None:
            await self._sm.handle_request(scope, receive, send)

    handle_streamable_http = _StreamableHTTPASGI(session_manager)

    async def health(_request: StarletteRequest) -> JSONResponse:
        payload = build_health_payload(
            SERVER_NAME, runtime, lifecycle,
            version=SERVER_VERSION, protocol="streamable-http",
        )
        payload["security"] = security_payload()
        return JSONResponse(payload, status_code=health_status_code(payload))

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            await lifecycle.startup()
            if lifecycle.errors:
                logger.error("초기화 실패로 degraded 상태입니다: %s", lifecycle.errors)
            logger.info(
                "FileHandler MCP Streamable HTTP 서버 준비 완료 (tools=%d)",
                len(runtime.tools),
            )
            try:
                yield
            finally:
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


def run(host: str = None, port: int = DEFAULT_PORT) -> None:
    """서버 실행. host 기본값은 loopback (resolve_bind_host 정책)."""
    import uvicorn

    bind_host = resolve_bind_host(host, server_name=SERVER_NAME)
    logger.info("Starting FileHandler MCP Streamable HTTP server on %s:%s", bind_host, port)
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


if __name__ == "__main__":
    run(port=int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT)))
