"""
Streamable HTTP 트랜스포트 구동부 — 한 벌.

8개 도메인의 `server_stream.py` 가 `StreamableHTTPSessionManager` 마운트, `/mcp` 라우트,
`/health`, lifespan 을 100% 동일하게 반복하고 있었다(spec/spec_MCP트랜스포트.md ③-3).
그 배선을 여기로 모은다. 도메인 파일에는 포트와 `handlers` import 만 남는다.

MCP Streamable HTTP 스펙(2025-03-26 이후)의 단일 엔드포인트 `/mcp` 를 제공한다.
`json_response=False` 라 Accept 헤더에 따라 JSON 또는 SSE 프레이밍으로 응답한다 —
이때의 SSE 는 폐기된 HTTP+SSE 트랜스포트가 아니라 Streamable HTTP **안쪽의 응답 형식**
이다(②-4).

## 모드별 차이 (spec/spec_멀티유저.md ②-4.4, ②-4.5)

| 항목 | mode 0 (기본) | mode 1 (`MS365_MULTI_USER=1`) |
|------|---------------|-------------------------------|
| `/mcp` 앞단 | Host/Origin 검사(SDK) | `BearerAuthMiddleware` — Host/Origin → 크기 → bearer → scope |
| SDK 세션 | `stateless=False` | `stateless=True`, `event_store=None` — 매 요청 인증 |
| GET·DELETE `/mcp` | SDK 처리 | 인증 뒤 405 |
| `Mcp-Session-Id` | SDK 처리 | 인증 뒤 400 |
| `/health` | 상태·도구 수·초기화 오류 | `status`·`server`·`version` 만 |
| 기동 검사 | 없음 | `validate_startup(server, "http")` + registry 진입점 확인 |
| 종료 | lifecycle.shutdown | + 사용자 서비스 풀 close |
"""

import contextlib
import logging
import os
from collections.abc import AsyncIterator
from typing import Any, Optional

from mcp_common.runtime import build_health_payload, health_status_code

logger = logging.getLogger(__name__)

#: mode 1 `/health` 가 공개하는 필드 (인증 없이 응답하므로 최소한만).
PUBLIC_HEALTH_FIELDS = ("status", "server", "version")


def transport_security():
    """DNS rebinding 방어 — Host/Origin 허용 목록 (MCP 스펙 transports §Security Warning).

    기본은 loopback 이름만 허용한다. `MCP_BIND_HOST` 로 특정 인터페이스에 바인드하면 그 주소를
    자동 포함하고, 그 밖의 값은 `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` (쉼표 구분,
    `host:*` 와일드카드 가능) 로 더한다. 0.0.0.0 바인드 시에는 접속 주소를 직접 적어야 한다.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    origins = ["http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*"]
    bind = os.environ.get("MCP_BIND_HOST", "").strip()
    if bind and bind not in ("0.0.0.0", "::", "*"):
        hosts.append(f"{bind}:*")
    hosts += [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    origins += [o.strip() for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
    )


def _prepare_multi_user(server_name: str, runtime: Any, authenticator: Any, active_checker: Any) -> int:
    """mode 1 기동 검사. 문제가 있으면 `StartupConfigError` — 앱을 만들지 않는다.

    Returns:
        요청 크기 상한(바이트)
    """
    from mcp_common.http_identity import max_request_bytes
    from mcp_common.mcp_identity_bridge import preflight_registry
    from mcp_common.security_policy import validate_startup

    validate_startup(server_name, "http")
    limit = max_request_bytes()

    if active_checker is not None:
        runtime.active_checker = active_checker
    needed = []
    if authenticator is None:
        needed.append("authenticate_bearer")
    if getattr(runtime, "active_checker", None) is None:
        needed.append("assert_active")
    if needed:
        preflight_registry(*needed)
    return limit


def build_starlette_app(
    server_name: str,
    mcp_server: Any,
    runtime: Any,
    lifecycle: Any,
    *,
    version: str = "1.0.0",
    authenticator: Any = None,
    active_checker: Any = None,
):
    """`/mcp` + `/health` 두 라우트를 가진 Starlette ASGI 앱을 만든다.

    Args:
        authenticator: mode 1 bearer 검증 함수 `async (authorization, *, domain) -> Principal`.
            없으면 `session.identity_registry.authenticate_bearer`. mode 0 에서는 쓰지 않는다.
        active_checker: mode 1 계정 상태 재확인 `async (principal) -> None`. 주면
            `runtime.active_checker` 로 설정한다. 없으면 runtime 의 것(기본은 registry).
    """
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from mcp_common.security_policy import multi_user_enabled

    multi_user = multi_user_enabled()
    security_settings = transport_security()
    if multi_user:
        body_limit = _prepare_multi_user(server_name, runtime, authenticator, active_checker)
        session_manager = StreamableHTTPSessionManager(
            app=mcp_server,
            event_store=None,
            json_response=False,
            stateless=True,  # 요청 간 MCP 세션에 인증 주체를 보관하지 않는다 (②-4.4)
            security_settings=security_settings,
            max_request_body_size=body_limit,
        )
    else:
        session_manager = StreamableHTTPSessionManager(
            app=mcp_server,
            event_store=None,
            json_response=False,  # Accept 헤더에 따라 JSON/SSE 협상
            stateless=False,
            security_settings=security_settings,
        )

    class _StreamableHTTPASGI:
        """SessionManager 를 ASGI 콜러블로 감싼다."""

        def __init__(self, sm: Any) -> None:
            self._sm = sm

        async def __call__(self, scope, receive, send) -> None:
            await self._sm.handle_request(scope, receive, send)

    handle_streamable_http: Any = _StreamableHTTPASGI(session_manager)
    if multi_user:
        from mcp_common.http_identity import BearerAuthMiddleware

        handle_streamable_http = BearerAuthMiddleware(
            handle_streamable_http,
            server_name=server_name,
            authenticator=authenticator,
            security_settings=security_settings,
            max_body_bytes=body_limit,
        )

    async def health(_request: "StarletteRequest") -> "JSONResponse":
        payload = build_health_payload(server_name, runtime, lifecycle, version=version)
        status_code = health_status_code(payload)
        if multi_user:
            # 인증 없이 응답하므로 오류 문구·도구 수·경로를 싣지 않는다 (②-4.5)
            payload = {key: payload[key] for key in PUBLIC_HEALTH_FIELDS if key in payload}
        return JSONResponse(payload, status_code=status_code)

    @contextlib.asynccontextmanager
    async def lifespan(_app: "Starlette") -> AsyncIterator[None]:
        async with session_manager.run():
            await lifecycle.startup()
            logger.info(
                "[%s] Streamable HTTP server ready with %d tools%s",
                server_name,
                len(runtime.tools),
                " (multi-user, stateless, bearer)" if multi_user else "",
            )
            try:
                yield
            finally:
                await lifecycle.shutdown()
                if multi_user:
                    from mcp_common import service_pool

                    try:
                        await service_pool.get_service_pool().close()
                    except Exception as exc:
                        logger.warning(
                            "[%s] service pool close failed: %s", server_name, type(exc).__name__
                        )

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


__all__ = ["build_starlette_app", "run_http", "transport_security", "PUBLIC_HEALTH_FIELDS"]
