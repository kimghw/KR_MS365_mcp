"""
MCP SDK ↔ 요청 identity 연결 (spec/spec_멀티유저.md ②-5.2, WP1).

HTTP 인증 관문(`mcp_common.http_identity`)은 검증한 `RequestIdentity` 를 ASGI
`scope["state"]["ms365_identity"]` 에 기록한다. 도구 실행 시점에는 그 값을 **현재 MCP
메시지에 연결된 HTTP request** 에서 다시 읽는다.

    mcp.server.streamable_http   ServerMessageMetadata(request_context=request)
    mcp.server.lowlevel.server   request_ctx.set(RequestContext(..., request=request_data))

미들웨어에서 ContextVar 를 한 번 설정하면 SDK 의 모든 작업으로 전파된다고 가정하지
않는다 — stateless 모드에서 트랜스포트는 session manager 의 task group 안에서 돈다.
그래서 판정 규칙을 다음으로 고정한다.

| SDK HTTP request | scope identity | bound ContextVar | 결과 |
|---|---|---|---|
| 있음 | 있음 | 없음 또는 같음 | scope identity |
| 있음 | 있음 | **다름** | `missing_principal` (컨텍스트 충돌) |
| 있음 | 없음 | (무관) | `missing_principal` (관문을 거치지 않은 HTTP 요청) |
| 없음 | — | 있음 | bound identity (서비스 직접 호출·테스트) |
| 없음 | — | 없음 | `missing_principal` |

bearer 검증·계정 상태 확인의 실제 구현은 `session.identity_registry` (WP2) 가 소유한다.
이 모듈은 그 진입점을 **지연 import** 로만 잡는다 — mode 0 과 단위 테스트가 session
패키지 없이도 돌아야 하기 때문이다.
"""

import importlib
import inspect
import logging
from typing import Any, Awaitable, Callable, Mapping, Optional

from mcp_common.principal import Principal, RequestIdentity, current_identity
from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError

logger = logging.getLogger(__name__)

#: 인증 관문이 identity 를 싣는 ASGI `scope["state"]` 키. 서버 내부 값이다.
IDENTITY_STATE_KEY = "ms365_identity"

#: `async def authenticate_bearer(authorization, *, domain) -> Principal`
Authenticator = Callable[..., Awaitable[Principal]]
#: `async def assert_active(principal) -> None` (비활성이면 `SecurityError`)
ActiveChecker = Callable[[Principal], Awaitable[None]]

_REGISTRY_MODULE = "session.identity_registry"


# ----------------------------------------------------------------------
# SDK request context
# ----------------------------------------------------------------------
def _sdk_http_request() -> Optional[Any]:
    """현재 MCP 메시지에 연결된 HTTP request. SDK 요청 컨텍스트 밖이거나 stdio 면 None."""
    try:
        from mcp.server.lowlevel.server import request_ctx
    except Exception:  # SDK 가 없거나 내부 경로가 바뀐 경우 — 브리지 없음으로 본다
        return None
    try:
        ctx = request_ctx.get()
    except LookupError:
        return None
    return getattr(ctx, "request", None)


def identity_from_scope(scope: Any) -> Optional[RequestIdentity]:
    """ASGI scope 에서 관문이 기록한 identity. 없거나 형식이 다르면 None."""
    if not isinstance(scope, Mapping):
        return None
    state = scope.get("state")
    if not isinstance(state, Mapping):
        return None
    identity = state.get(IDENTITY_STATE_KEY)
    return identity if isinstance(identity, RequestIdentity) else None


def identity_from_request_context() -> Optional[RequestIdentity]:
    """현재 SDK 메시지의 HTTP request scope 에 실린 identity (없으면 None)."""
    request = _sdk_http_request()
    if request is None:
        return None
    return identity_from_scope(getattr(request, "scope", None))


def resolve_request_identity() -> RequestIdentity:
    """도구 실행에 쓸 **권위 있는** identity 를 정한다 (모듈 docstring 의 판정표).

    실패는 전부 `SecurityError(missing_principal)` 다. 다른 사용자로 대체하지 않는다.
    """
    bound = current_identity()
    request = _sdk_http_request()
    if request is not None:
        bridged = identity_from_scope(getattr(request, "scope", None))
        if bridged is None:
            logger.warning("SDK HTTP request carries no authenticated identity; rejecting")
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
        if bound is not None and bound is not bridged and bound != bridged:
            # 이전 요청의 ContextVar 가 남았거나 다른 요청의 컨텍스트가 섞였다.
            logger.warning(
                "identity context conflict (request_id=%s vs %s); rejecting",
                bridged.request_id,
                bound.request_id,
            )
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
        return bridged
    if bound is None:
        raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
    return bound


# ----------------------------------------------------------------------
# registry 진입점 (WP2) — 지연 import
# ----------------------------------------------------------------------
def _registry_attr(name: str) -> Callable[..., Any]:
    module = importlib.import_module(_REGISTRY_MODULE)
    fn = getattr(module, name)
    if not callable(fn):
        raise TypeError(f"{_REGISTRY_MODULE}.{name} is not callable")
    return fn


async def default_authenticate_bearer(authorization: str, *, domain: str) -> Principal:
    """`session.identity_registry.authenticate_bearer` 로 위임한다(호출 시점 import)."""
    fn = _registry_attr("authenticate_bearer")
    return await fn(authorization, domain=domain)


async def default_assert_active(principal: Principal) -> None:
    """`session.identity_registry.assert_active` 로 위임한다(호출 시점 import)."""
    fn = _registry_attr("assert_active")
    result = fn(principal)
    if inspect.isawaitable(result):
        await result


def preflight_registry(*names: str) -> None:
    """mode 1 기동 시 기본 registry 진입점을 실제로 불러 본다. 실패하면 기동 거부.

    요청 시점에 처음 실패하면 모든 호출이 401/내부 오류로 떨어지므로, 설정 누락을
    기동 단계에서 드러낸다.
    """
    for name in names:
        try:
            _registry_attr(name)
        except Exception as exc:
            raise StartupConfigError(
                f"멀티유저 모드에 필요한 {_REGISTRY_MODULE}.{name} 를 불러올 수 없습니다 "
                f"({type(exc).__name__})."
            ) from exc


__all__ = [
    "IDENTITY_STATE_KEY",
    "Authenticator",
    "ActiveChecker",
    "identity_from_scope",
    "identity_from_request_context",
    "resolve_request_identity",
    "default_authenticate_bearer",
    "default_assert_active",
    "preflight_registry",
]
