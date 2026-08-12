"""
Streamable HTTP 트랜스포트 구동부 — 한 벌.

8개 도메인의 `server_stream.py` 가 `StreamableHTTPSessionManager` 마운트, `/mcp` 라우트,
`/health`, lifespan 을 100% 동일하게 반복하고 있었다(spec/spec_MCP트랜스포트.md ③-3).
그 배선을 여기로 모은다. 도메인 파일에는 포트와 `handlers` import 만 남는다.

MCP Streamable HTTP 스펙(2025-03-26 이후)의 단일 엔드포인트 `/mcp` 를 제공한다.
`json_response=False` 라 Accept 헤더에 따라 JSON 또는 SSE 프레이밍으로 응답한다 —
이때의 SSE 는 폐기된 HTTP+SSE 트랜스포트가 아니라 Streamable HTTP **안쪽의 응답 형식**
이다(②-4).
"""

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any, Optional

from mcp_common.runtime import build_health_payload, health_status_code

logger = logging.getLogger(__name__)


def build_starlette_app(
    server_name: str,
    mcp_server: Any,
    runtime: Any,
    lifecycle: Any,
    *,
    version: str = "1.0.0",
):
    """`/mcp` + `/health` 두 라우트를 가진 Starlette ASGI 앱을 만든다."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=False,  # Accept 헤더에 따라 JSON/SSE 협상
        stateless=False,
    )

    class _StreamableHTTPASGI:
        """SessionManager 를 ASGI 콜러블로 감싼다."""

        def __init__(self, sm: Any) -> None:
            self._sm = sm

        async def __call__(self, scope, receive, send) -> None:
            await self._sm.handle_request(scope, receive, send)

    handle_streamable_http = _StreamableHTTPASGI(session_manager)

    async def health(_request: "StarletteRequest") -> "JSONResponse":
        payload = build_health_payload(server_name, runtime, lifecycle, version=version)
        return JSONResponse(payload, status_code=health_status_code(payload))

    @contextlib.asynccontextmanager
    async def lifespan(_app: "Starlette") -> AsyncIterator[None]:
        async with session_manager.run():
            await lifecycle.startup()
            logger.info(
                "[%s] Streamable HTTP server ready with %d tools",
                server_name,
                len(runtime.tools),
            )
            try:
                yield
            finally:
                await lifecycle.shutdown()

    # Mount 대신 Route 를 쓴다 — Mount 는 `/mcp` 를 `/mcp/` 로 리다이렉트해 클라이언트가
    # 307 을 따라가지 못하는 경우가 있다.
    return Starlette(
        debug=False,
        routes=[
            Route("/mcp", endpoint=handle_streamable_http),
            Route("/health", endpoint=health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


def run_http(app: Any, server_name: str, port: int, host: Optional[str] = None) -> None:
    """uvicorn 으로 앱을 띄운다.

    바인드 주소는 `resolve_bind_host` 가 결정한다(기본 127.0.0.1). 외부 노출은
    `MCP_BIND_HOST` + `MCP_ALLOW_PUBLIC_BIND=1` 로 명시적 옵트인해야 한다.
    """
    import uvicorn

    from mcp_common.net import resolve_bind_host

    bind_host = resolve_bind_host(host, server_name=server_name)
    logger.info("[%s] starting Streamable HTTP server on %s:%s", server_name, bind_host, port)
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


__all__ = ["build_starlette_app", "run_http"]
