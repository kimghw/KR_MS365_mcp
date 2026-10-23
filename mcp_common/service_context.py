"""
요청 범위 서비스 바인딩 (spec/spec_멀티유저.md ②-7.6, WP0).

멀티유저에서 도메인 핸들러는 전역 서비스 인스턴스를 쓰지 않는다. `ToolRuntime.call()`
(WP1)이 서비스 풀에서 **현재 principal 의 서비스**를 lease 해 `bind_service()` 로 묶고,
핸들러는 `service_for()` 로 꺼낸다.

도메인 핸들러 사용 패턴 (WP4~WP9 공통):

    from mcp_common.security_policy import multi_user_enabled
    from mcp_common.service_context import service_for
    from mcp_common.service_pool import register_service_factory

    async def create_service(principal, paths, tokens) -> MailService:
        # 생성만 한다. initialize()/close() 는 풀이 부른다.
        return MailService(token_provider=tokens, paths=paths)

    register_service_factory(SERVER_NAME, create_service)

    # mode 0 전용 전역 인스턴스. mode 1 에서는 만들지 않는다(공용 AuthManager 를 끌어오므로).
    mail_service = None if multi_user_enabled() else MailService()

    def _service() -> MailService:
        return service_for(SERVER_NAME, legacy=mail_service)

    async def handle_mail_send(args):
        return await _service().send_mail(**_call_args("mail_send", args))
"""

import contextvars
from contextlib import contextmanager
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Optional

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

_EMPTY: Mapping[str, Any] = MappingProxyType({})

_services_var: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar(
    "ms365_bound_services", default=_EMPTY
)


@contextmanager
def bind_service(domain: str, service: Any) -> Iterator[Any]:
    """현재 요청 범위에 `domain` 서비스를 묶는다. `finally` 에서 반드시 되돌린다."""
    current = dict(_services_var.get())
    current[domain] = service
    token = _services_var.set(MappingProxyType(current))
    try:
        yield service
    finally:
        _services_var.reset(token)


def current_service(domain: str) -> Any:
    """lease 된 서비스. 없으면 `missing_principal` — 전역 인스턴스로 대체하지 않는다."""
    service = _services_var.get().get(domain)
    if service is None:
        raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
    return service


def service_for(domain: str, legacy: Optional[Any] = None) -> Any:
    """mode 1 → lease 된 사용자 서비스, mode 0 → `legacy` 전역 인스턴스."""
    if multi_user_enabled():
        return current_service(domain)
    if legacy is None:
        raise RuntimeError(f"[{domain}] legacy 서비스 인스턴스가 없습니다 (mode 0)")
    return legacy


__all__ = ["bind_service", "current_service", "service_for"]
