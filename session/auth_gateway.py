"""
중앙 Graph 연결 서비스 (spec/spec_멀티유저.md ②-6.4, ②-12.7) — `python -m session.auth_gateway`.

멀티유저 모드에서는 도메인별 CallbackServer 를 띄우지 않는다. 이 프로세스 하나가
`AZURE_REDIRECT_URI` 포트(또는 `MS365_AUTH_GATEWAY_PORT`)에서 `/auth/*` 를 담당한다.

| 엔드포인트 | 인증 | 용도 |
|------------|------|------|
| `POST /auth/graph/start` | bearer (그 사용자의 어떤 scope 키든) | 본인 연결 시도 + 1회용 연결 링크(300초) |
| `GET /auth/graph/connect?ticket=` | ticket 1회 소비 | 시도별 쿠키 발급 후 Entra authorize 로 302 |
| `GET /auth/callback` (및 redirect URI 경로) | state + 쿠키 | PKCE·OIDC 검증, 암호화 토큰 저장 |
| `GET /auth/attempts/{attempt_id}` | bearer | 본인 시도 상태만 |
| `DELETE /auth/graph/connection` | bearer | 본인 Graph 연결 해제 |
| `GET /health` | 없음 | `status`·`server`·`version` 만 |

- 응답에 access/refresh token·state·ticket·오류 원문을 싣지 않는다. 브라우저 페이지에는 상태와
  연결된 계정 표시만.
- 접근 로그는 메서드·경로·상태코드만 남긴다(query string 비기록). uvicorn access log 는 끈다.
- client secret 은 환경변수에서만 읽는다(어떤 DB 에도 저장하지 않음).
"""

import asyncio
import html
import logging
import os
import sys
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from mcp_common.security_contracts import ErrorCode, SecurityError

from . import graph_connect
from .app_settings import DEFAULT_CALLBACK_PATH, load_app_settings
from .identity_registry import authenticate_bearer

logger = logging.getLogger("session.auth_gateway")

SERVER_NAME = "auth_gateway"
VERSION = "1.0.0"

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
}

_CALLBACK_MESSAGES = {
    "connected": "Microsoft 365 계정이 연결되었습니다. 이 창을 닫고 에이전트로 돌아가세요.",
    "invalid_state": "알 수 없거나 만료된 연결 요청입니다. 새 연결 링크를 요청하세요.",
    "replayed": "이미 처리된 연결 요청입니다. 필요하면 새 연결 링크를 요청하세요.",
    "expired": "연결 시간이 지났습니다. 새 연결 링크를 요청하세요.",
    "browser_mismatch": "연결을 시작한 브라우저가 아닙니다. 같은 브라우저에서 새 연결 링크를 여세요.",
    "oauth_error": "Microsoft 로그인이 취소되었거나 실패했습니다. 새 연결 링크를 요청하세요.",
    "account_mismatch": "등록된 사용자와 다른 Microsoft 계정으로 로그인했습니다. 연결하지 않았습니다.",
    "tenant_not_allowed": "허용되지 않은 조직(tenant)의 계정입니다. 연결하지 않았습니다.",
    "account_changed": "계정 상태가 바뀌어 연결을 중단했습니다. 새 연결 링크를 요청하세요.",
}
_DEFAULT_FAIL = "연결에 실패했습니다. 새 연결 링크를 요청하세요."

_CONNECT_MESSAGES = {
    "invalid_ticket": "연결 링크가 올바르지 않거나 이미 사용되었습니다. 새 연결 링크를 요청하세요.",
    "ticket_expired": "연결 링크가 만료되었습니다(5분). 새 연결 링크를 요청하세요.",
    "account_inactive": "계정이 비활성 상태입니다. 관리자에게 문의하세요.",
    "account_changed": "계정 상태가 바뀌었습니다. 새 연결 링크를 요청하세요.",
}


def _page(title: str, message: str, *, status: int = 200, account: Optional[str] = None) -> HTMLResponse:
    extra = f"<p>계정: <strong>{html.escape(account)}</strong></p>" if account else ""
    body = (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:sans-serif;margin:40px;max-width:640px}</style></head>"
        f"<body><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{extra}</body></html>"
    )
    return HTMLResponse(body, status_code=status, headers=_SECURITY_HEADERS)


def _json(data: Dict[str, Any], status: int = 200, headers: Optional[Dict[str, str]] = None) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={**_SECURITY_HEADERS, **(headers or {})})


def _security_error(exc: SecurityError) -> JSONResponse:
    status = 500 if exc.code == ErrorCode.INTERNAL_ERROR else exc.http_status
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return _json({"error": exc.code, "message": exc.public_message}, status, headers)


async def _principal(request: Request):
    values = request.headers.getlist("authorization")
    if len(values) > 1:  # 여러 개면 어느 것도 믿지 않는다
        raise SecurityError(ErrorCode.UNAUTHENTICATED)
    return await authenticate_bearer(values[0] if values else None, domain=None)


def create_app(*, entra: Any = None, jwks_client: Any = None) -> Starlette:
    """테스트는 `entra`(exchange_code/get_me 가짜)·`jwks_client` 를 주입한다."""
    settings = load_app_settings()

    async def start(request: Request) -> Response:
        try:
            principal = await _principal(request)
            link = await asyncio.to_thread(graph_connect.create_connect_attempt, principal)
        except SecurityError as exc:
            return _security_error(exc)
        return _json({"attempt_id": link.attempt_id, "connect_url": link.connect_url,
                      "expires_in": link.expires_in}, 201)

    async def connect(request: Request) -> Response:
        try:
            redirect = await asyncio.to_thread(graph_connect.begin_browser_flow,
                                               request.query_params.get("ticket"), settings=settings)
        except graph_connect.ConnectError as exc:
            status = 403 if exc.code == "account_inactive" else 400
            return _page("연결할 수 없습니다", _CONNECT_MESSAGES.get(exc.code, _DEFAULT_FAIL), status=status)
        response = RedirectResponse(redirect.authorize_url, status_code=302, headers=_SECURITY_HEADERS)
        response.set_cookie(redirect.cookie_name, redirect.cookie_value, max_age=redirect.max_age,
                            path=redirect.cookie_path, secure=redirect.secure, httponly=True, samesite="lax")
        return response

    async def callback(request: Request) -> Response:
        result = await graph_connect.complete_callback(
            dict(request.query_params), dict(request.cookies), settings=settings, entra=entra, jwks_client=jwks_client
        )
        if result.ok:
            response = _page("연결 완료", _CALLBACK_MESSAGES["connected"], account=result.account)
        else:
            response = _page("연결 실패", _CALLBACK_MESSAGES.get(result.code, _DEFAULT_FAIL), status=400)
        if result.cookie_name:
            response.delete_cookie(result.cookie_name, path=settings.callback_path,
                                   secure=settings.uses_https, httponly=True, samesite="lax")
        return response

    async def attempt(request: Request) -> Response:
        try:
            principal = await _principal(request)
            status = await asyncio.to_thread(graph_connect.attempt_status, principal,
                                             request.path_params.get("attempt_id", ""))
        except SecurityError as exc:
            return _security_error(exc)
        if status is None:
            return _json({"error": ErrorCode.NOT_FOUND, "message": "대상을 찾을 수 없습니다."}, 404)
        return _json(status)

    async def disconnect(request: Request) -> Response:
        try:
            principal = await _principal(request)
            await asyncio.to_thread(graph_connect.disconnect, principal)
        except SecurityError as exc:
            return _security_error(exc)
        return _json({"status": "disconnected"})

    async def health(request: Request) -> Response:
        return _json({"status": "ok", "server": SERVER_NAME, "version": VERSION})

    routes = [
        Route("/auth/graph/start", start, methods=["POST"]),
        Route("/auth/graph/connect", connect, methods=["GET"]),
        Route(DEFAULT_CALLBACK_PATH, callback, methods=["GET"]),
        Route("/auth/attempts/{attempt_id}", attempt, methods=["GET"]),
        Route("/auth/graph/connection", disconnect, methods=["DELETE"]),
        Route("/health", health, methods=["GET"]),
    ]
    if settings.callback_path != DEFAULT_CALLBACK_PATH:
        routes.append(Route(settings.callback_path, callback, methods=["GET"]))
    app = Starlette(routes=routes)
    return _AccessLog(app)


class _AccessLog:
    """메서드·경로·상태코드만 기록하는 ASGI 래퍼 (query string·헤더·쿠키 비기록)."""

    def __init__(self, app):
        self.app = app

    def __getattr__(self, name):  # TestClient 등이 원래 앱 속성을 볼 수 있게
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        status_holder = {"status": 0}

        async def _send(message):
            if message.get("type") == "http.response.start":
                status_holder["status"] = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            logger.info("%s %s -> %s", scope.get("method"), scope.get("path"), status_holder["status"])


# ----------------------------------------------------------------------
# 실행
# ----------------------------------------------------------------------
def _gateway_port(redirect_uri: str) -> int:
    explicit = os.environ.get("MS365_AUTH_GATEWAY_PORT", "").strip()
    if explicit:
        return int(explicit)
    parts = urlsplit(redirect_uri)
    if parts.port:
        return parts.port
    raise SystemExit("AZURE_REDIRECT_URI 에 포트가 없습니다. MS365_AUTH_GATEWAY_PORT 를 지정하세요.")


def main(argv: Optional[list] = None) -> int:
    from dotenv import load_dotenv

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(root, ".env"), encoding="utf-8-sig", override=False)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), stream=sys.stderr,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from mcp_common.net import resolve_bind_host
    from mcp_common.security_policy import multi_user_enabled, validate_startup

    from .app_settings import auth_startup_problems

    if not multi_user_enabled():
        print("auth gateway 는 멀티유저 모드(MS365_MULTI_USER=1) 전용입니다.", file=sys.stderr)
        return 2
    validate_startup(SERVER_NAME, "http")
    problems = auth_startup_problems()
    if problems:
        print("auth gateway 기동 거부:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 2
    settings = load_app_settings()
    host = resolve_bind_host(os.environ.get("MS365_AUTH_GATEWAY_HOST"), server_name=SERVER_NAME)
    port = _gateway_port(settings.redirect_uri)

    import uvicorn

    logger.info("auth gateway listening on %s:%s", host, port)
    uvicorn.run(create_app(), host=host, port=port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

