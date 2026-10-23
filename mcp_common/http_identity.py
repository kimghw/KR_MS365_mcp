"""
멀티유저 HTTP 인증 관문 — `/mcp` 앞단 bearer ASGI 미들웨어 (spec/spec_멀티유저.md ②-4.4, WP1).

mode 1(`MS365_MULTI_USER=1`)에서 `mcp_common.http_transport.build_starlette_app()` 이
SDK `StreamableHTTPSessionManager` 를 이 미들웨어로 감싼다. 검사 순서는 고정이다.

1. Host/Origin 허용 목록 — `transport_security()` 와 **같은 목록·같은 SDK 검사기**
2. 요청 크기 — `Content-Length` 상한(`MS365_MAX_REQUEST_BYTES`, 기본 4 MiB). 스트리밍
   본문 상한은 인증 뒤 SDK 의 `RequestBodyLimitMiddleware` 가 같은 값으로 다시 건다.
3. `Authorization: Bearer <key>` 헤더 **정확히 1개**
4. `await authenticator(header, domain=server_name)` → `Principal` (WP2 registry)
5. 도메인 scope 재확인 (registry 결과를 한 번 더 믿지 않고 확인)
6. 서버가 만든 `request_id` 로 `RequestIdentity` 생성 → `scope["state"]["ms365_identity"]`
7. stateless 정책 — POST 외 메서드 405, `Mcp-Session-Id` 헤더 400
8. `bind_identity()` 로 감싸 SDK 에 전달

인증되지 않은 요청은 **SDK 에 닿지 않는다**(initialize·tools/list·tools/call·notification·
GET·DELETE 모두). 쿠키·`user_email` 인자·`Mcp-Session-Id`·`X-User-*` 헤더는 인증 근거가
아니며 이 모듈은 그것들을 읽지 않는다.

| 상황 | 응답 |
|---|---|
| 키 없음·형식 오류·만료·폐기·미지 키 | 401 + `WWW-Authenticate: Bearer` |
| scope 부족 / 계정 비활성 | 403 |
| registry 과부하 | 503 |
| registry 내부 오류 | 500 `internal_error` |

본문은 `{"error": <code>, "message": <고정 공개 메시지>}` 뿐이다 — registry 가 올린 예외
문구·키·내부 상세를 싣지 않는다.

감사(`auth.bearer`): registry 가 내린 판정(성공·401·403)은 registry 가 기록한다. 이 관문은
registry 에 **닿기 전에** 끝난 거부(헤더 없음·중복·형식 오류)와 registry 장애·반환값 이상,
scope 재확인 거부만 기록한다. 어느 쪽도 키 원문을 남기지 않는다(형식이 맞으면 kid 만).
"""

import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from mcp_common.mcp_identity_bridge import (
    IDENTITY_STATE_KEY,
    Authenticator,
    default_authenticate_bearer,
)
from mcp_common.principal import Principal, RequestIdentity, bind_identity
from mcp_common.security_contracts import (
    DEFAULT_MESSAGES,
    ErrorCode,
    SecurityError,
    StartupConfigError,
)

logger = logging.getLogger(__name__)

ENV_MAX_REQUEST_BYTES = "MS365_MAX_REQUEST_BYTES"
#: SDK `DEFAULT_MAX_REQUEST_BODY_SIZE` 와 같은 값.
DEFAULT_MAX_REQUEST_BYTES = 4 * 1024 * 1024
#: Authorization 헤더 길이 상한. `m365v1.<kid32>.<secret43>` 은 90자 안팎이다.
MAX_AUTHORIZATION_LENGTH = 1024

_BEARER_RE = re.compile(r"^Bearer[ ]+([A-Za-z0-9._~+/=-]+)[ ]*$", re.IGNORECASE)
#: 감사용 kid 추출 (②-4.3 형식). kid 는 비밀이 아니다 — secret 부분은 절대 남기지 않는다.
_KID_RE = re.compile(r"^m365v1\.([0-9a-f]{32})\.")

#: registry 가 올린 코드 → (HTTP 상태, 응답 코드). 그 밖의 코드는 401 로 일반화한다.
_AUTH_FAILURES: Dict[str, int] = {
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN_SCOPE: 403,
    ErrorCode.ACCOUNT_INACTIVE: 403,
    ErrorCode.OVERLOADED: 503,
    ErrorCode.CONFIG_ERROR: 500,
    ErrorCode.INTERNAL_ERROR: 500,
}


def max_request_bytes() -> int:
    """`MS365_MAX_REQUEST_BYTES` (양의 정수, 바이트). 잘못된 값은 기동 거부."""
    raw = os.environ.get(ENV_MAX_REQUEST_BYTES, "").strip()
    if not raw:
        return DEFAULT_MAX_REQUEST_BYTES
    try:
        value = int(raw)
    except ValueError:
        raise StartupConfigError(f"{ENV_MAX_REQUEST_BYTES} 는 양의 정수(바이트)여야 합니다: {raw!r}") from None
    if value <= 0:
        raise StartupConfigError(f"{ENV_MAX_REQUEST_BYTES} 는 양의 정수(바이트)여야 합니다: {raw!r}")
    return value


def new_request_id() -> str:
    """서버가 생성하는 요청 ID (128비트 hex). 외부 correlation ID 를 쓰지 않는다."""
    return secrets.token_hex(16)


def _error_body(code: str) -> Dict[str, str]:
    return {"error": code, "message": DEFAULT_MESSAGES.get(code, code)}


def _audit(**fields: Any) -> None:
    """감사 실패가 요청 처리를 바꾸지 않게 감싼다."""
    try:
        from mcp_common.audit import audit

        audit("auth.bearer", **fields)
    except Exception as exc:  # pragma: no cover - 감사 sink 장애
        logger.warning("auth audit failed: %s", type(exc).__name__)


class BearerAuthMiddleware:
    """`/mcp` 를 감싸는 ASGI 미들웨어. 모듈 docstring 의 순서를 그대로 따른다.

    Args:
        app: 인증 뒤에 부를 ASGI 앱 (SDK session manager 래퍼)
        server_name: 도메인 이름 = bearer scope (`mcp:<server_name>`)
        authenticator: `async (authorization, *, domain) -> Principal`. 없으면
            `session.identity_registry.authenticate_bearer` (호출 시점 import)
        security_settings: SDK `TransportSecuritySettings`. 없으면 `transport_security()`
        max_body_bytes: Content-Length 상한
    """

    def __init__(
        self,
        app: Any,
        *,
        server_name: str,
        authenticator: Optional[Authenticator] = None,
        security_settings: Any = None,
        max_body_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    ) -> None:
        from mcp.server.transport_security import TransportSecurityMiddleware

        if security_settings is None:
            from mcp_common.http_transport import transport_security

            security_settings = transport_security()
        self.app = app
        self.server_name = server_name
        self._authenticate = authenticator or default_authenticate_bearer
        self._host_check = TransportSecurityMiddleware(security_settings)
        self.max_body_bytes = max_body_bytes

    # ------------------------------------------------------------------
    async def _respond(
        self,
        scope: Any,
        receive: Any,
        send: Any,
        status: int,
        code: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        from starlette.responses import JSONResponse

        response = JSONResponse(_error_body(code), status_code=status, headers=headers)
        await response(scope, receive, send)

    async def _deny_auth(self, scope: Any, receive: Any, send: Any, code: str) -> None:
        status = _AUTH_FAILURES.get(code, 401)
        if status == 401:
            code = ErrorCode.UNAUTHENTICATED
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        await self._respond(scope, receive, send, status, code, headers)

    def _content_length_problem(self, headers: Any) -> Optional[tuple]:
        values = headers.getlist("content-length")
        if not values:
            return None
        if len(values) > 1 or not values[0].strip().isdigit():
            return (400, "bad_request")
        if int(values[0]) > self.max_body_bytes:
            return (413, "request_too_large")
        return None

    # ------------------------------------------------------------------
    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            # Route 는 http 만 넘긴다. 다른 형식은 인증 없이 통과시키지 않는다.
            if scope.get("type") == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return

        from starlette.requests import HTTPConnection

        connection = HTTPConnection(scope)
        headers = connection.headers
        request_id = new_request_id()
        started = time.monotonic()

        # 1) Host/Origin — DNS rebinding 방어. 인증보다 먼저다.
        rejection = await self._host_check.validate_request(connection, is_post=False)
        if rejection is not None:
            await rejection(scope, receive, send)
            return

        # 2) 요청 크기
        problem = self._content_length_problem(headers)
        if problem is not None:
            await self._respond(scope, receive, send, problem[0], problem[1])
            return

        # 3) Authorization 헤더 개수·형식
        values = headers.getlist("authorization")
        if (
            len(values) != 1
            or len(values[0]) > MAX_AUTHORIZATION_LENGTH
            or not _BEARER_RE.match(values[0])
        ):
            _audit(outcome="failure", request_id=request_id, domain=self.server_name,
                   error_code=ErrorCode.UNAUTHENTICATED)
            await self._deny_auth(scope, receive, send, ErrorCode.UNAUTHENTICATED)
            return
        authorization = values[0]
        kid_match = _KID_RE.match(_BEARER_RE.match(authorization).group(1))
        kid = kid_match.group(1) if kid_match else None

        # 4) registry 인증
        try:
            principal = await self._authenticate(authorization, domain=self.server_name)
        except SecurityError as exc:
            # registry 판정(성공·실패·scope 거부)의 감사는 registry 가 남긴다 — 중복 기록하지 않는다
            code = exc.code if exc.code in _AUTH_FAILURES else ErrorCode.UNAUTHENTICATED
            if _AUTH_FAILURES.get(code) == 500:
                code = ErrorCode.INTERNAL_ERROR
            await self._deny_auth(scope, receive, send, code)
            return
        except Exception as exc:
            # registry 장애는 인증 실패로 위장하지 않되, 원문은 응답·감사에 싣지 않는다.
            logger.error("[%s] bearer authenticator failed: %s (request_id=%s)",
                         self.server_name, type(exc).__name__, request_id)
            _audit(outcome="failure", request_id=request_id, domain=self.server_name,
                   error_code=ErrorCode.INTERNAL_ERROR, credential_id=kid)
            await self._deny_auth(scope, receive, send, ErrorCode.INTERNAL_ERROR)
            return

        if not isinstance(principal, Principal):
            logger.error("[%s] authenticator returned %s, not Principal",
                         self.server_name, type(principal).__name__)
            _audit(outcome="failure", request_id=request_id, domain=self.server_name,
                   error_code=ErrorCode.INTERNAL_ERROR, credential_id=kid)
            await self._deny_auth(scope, receive, send, ErrorCode.INTERNAL_ERROR)
            return

        # 5) scope 재확인
        if not principal.has_scope(self.server_name):
            _audit(outcome="denied", principal=principal, request_id=request_id,
                   domain=self.server_name, error_code=ErrorCode.FORBIDDEN_SCOPE)
            await self._deny_auth(scope, receive, send, ErrorCode.FORBIDDEN_SCOPE)
            return

        # 6) 요청 identity — 서버 생성 request_id
        identity = RequestIdentity(
            principal=principal,
            request_id=request_id,
            transport="http",
            authenticated_at=datetime.now(timezone.utc),
        )
        logger.debug("[%s] bearer ok (request_id=%s, %d ms)", self.server_name, request_id,
                     int((time.monotonic() - started) * 1000))

        # 7) stateless 정책 — 인증 뒤에 판정한다(무인증 호출자에게 지원 여부를 알려주지 않음)
        if scope.get("method") != "POST":
            await self._respond(scope, receive, send, 405, "method_not_allowed", {"Allow": "POST"})
            return
        if headers.get("mcp-session-id") is not None:
            await self._respond(scope, receive, send, 400, "session_not_supported")
            return

        # 8) SDK 로 전달. state 는 복사본에 싣는다(서버 lifespan state 를 오염시키지 않음).
        state = dict(scope.get("state") or {})
        state[IDENTITY_STATE_KEY] = identity
        downstream = dict(scope)
        downstream["state"] = state
        with bind_identity(identity):
            await self.app(downstream, receive, send)


__all__ = [
    "ENV_MAX_REQUEST_BYTES",
    "DEFAULT_MAX_REQUEST_BYTES",
    "BearerAuthMiddleware",
    "max_request_bytes",
    "new_request_id",
]
