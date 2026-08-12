"""Streamable HTTP MCP Server for mcp_file_handler (port 5008). 인증 불필요(로컬 파일 처리).

도구 정의·핸들러·`Server` 구성은 `handlers.py` 한 벌을 쓰고, ASGI 배선은
`mcp_common.http_transport` 를 쓴다. 이 파일에는 **HTTP 고유의 것만** 남는다
(spec/spec_MCP트랜스포트.md ②-3-1, ②-4).

엔드포인트:
    /mcp     — 표준 Streamable HTTP 단일 엔드포인트 (SDK 가 프로토콜 버전을 협상)
    /health  — 상태 조회. 초기화 실패 시 degraded + HTTP 503. 이 도메인은 보안 고지
               (인증 없음·바인드 정책·허용 루트)를 추가로 싣는다.

보안 주의:
    - 이 서버에는 **호출자 인증이 없다**. 기본 바인드는 loopback(127.0.0.1) 전용이며,
      외부 노출은 `MCP_BIND_HOST` + `MCP_ALLOW_PUBLIC_BIND=1` 옵트인이 필요하다.
    - 도구가 여는 모든 파일/디렉터리는 `mcp_common.paths` 허용 루트로 제한된다.
"""

import os
import sys

# mcp_common 을 import 하려면 프로젝트 루트가 먼저 sys.path 에 있어야 한다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_common.bootstrap import bootstrap_http

BOOT = bootstrap_http(__file__, package_name="mcp_file_handler")

# ↓ 서비스 모듈을 끌어오는 import 는 반드시 bootstrap 뒤에
from mcp_common.http_transport import build_starlette_app, run_http
from mcp_common.runtime import build_health_payload, health_status_code

from mcp_file_handler.mcp_server.handlers import (
    DEFAULT_PORT,
    SERVER_NAME,
    SERVER_VERSION,
    build_mcp_server,
    lifecycle,
    runtime,
    security_payload,
)

# 모듈 수준 ASGI 앱 (`uvicorn server_stream:app` 도 동작한다)
app = build_starlette_app(
    SERVER_NAME,
    build_mcp_server(),
    runtime,
    lifecycle,
    version=SERVER_VERSION,
)


def _install_security_health(starlette_app) -> None:
    """공통 `/health` 에 이 도메인만의 보안 고지를 덧붙인다.

    인증 없는 파일 서버라 운영자가 허용 루트·바인드 정책을 확인할 창구가 필요하다.
    공통 빌더는 도메인 고유 필드를 모르므로 라우트만 교체한다(배선은 그대로 재사용).
    """
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(_request):
        payload = build_health_payload(
            SERVER_NAME, runtime, lifecycle, version=SERVER_VERSION
        )
        payload["security"] = security_payload()
        return JSONResponse(payload, status_code=health_status_code(payload))

    routes = starlette_app.router.routes
    for index, route in enumerate(routes):
        if getattr(route, "path", None) == "/health":
            routes[index] = Route("/health", endpoint=health, methods=["GET"])
            return


_install_security_health(app)


def run(host=None, port: int = DEFAULT_PORT) -> None:
    run_http(app, SERVER_NAME, port, host)


if __name__ == "__main__":
    run(port=int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT)))
