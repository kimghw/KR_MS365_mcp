"""
바인드 주소 정책 (SSOT).

기본값은 loopback(127.0.0.1)이다. MCP 서버들은 호출자 인증 계층이 없어서
0.0.0.0 으로 열리면 네트워크 상의 누구나 사용자 메일/파일에 접근할 수 있다.
외부 노출이 정말 필요하면 명시적으로 옵트인해야 한다:

    MCP_BIND_HOST=0.0.0.0        # 또는 특정 인터페이스 IP
    MCP_ALLOW_PUBLIC_BIND=1      # 0.0.0.0 / :: 를 쓰려면 함께 필요

옵트인 없이 public 주소를 요청하면 loopback으로 강등하고 경고를 남긴다.
"""

import ipaddress
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_BIND_HOST = "127.0.0.1"

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: Optional[str]) -> bool:
    return bool(value) and value.strip().lower() in _TRUTHY


def is_public_bind(host: str) -> bool:
    """host 가 모든 인터페이스/외부에 노출되는 주소인지 판정."""
    if not host or not host.strip():
        # 빈 문자열은 소켓 계층에서 INADDR_ANY(= 0.0.0.0)로 해석된다.
        # 안전한 값으로 오판하면 안 되므로 fail-closed 로 public 취급한다.
        return True
    candidate = host.strip().strip("[]")
    if candidate in ("0.0.0.0", "::", "*"):
        return True
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        # 호스트명(localhost 등)은 loopback 이름만 안전한 것으로 취급
        return candidate.lower() not in ("localhost", "localhost.localdomain")
    return not addr.is_loopback


def resolve_bind_host(requested: Optional[str] = None, *, server_name: str = "mcp") -> str:
    """
    실제로 바인드할 호스트를 결정한다.

    우선순위: 명시 인자 > MCP_BIND_HOST 환경변수 > 127.0.0.1.
    public 주소는 MCP_ALLOW_PUBLIC_BIND 옵트인이 없으면 loopback으로 강등된다.
    """
    host = requested or os.environ.get("MCP_BIND_HOST") or DEFAULT_BIND_HOST
    host = host.strip()
    if not host:
        # `MCP_BIND_HOST=" "` 처럼 공백만 있는 값은 truthy 라서 위 폴백을 그냥 지나간다.
        # 그대로 두면 uvicorn 이 빈 문자열을 INADDR_ANY 로 해석해 전 인터페이스에 열린다.
        logger.warning(
            "[%s] blank bind host requested; falling back to %s", server_name, DEFAULT_BIND_HOST
        )
        return DEFAULT_BIND_HOST

    if is_public_bind(host) and not _is_truthy(os.environ.get("MCP_ALLOW_PUBLIC_BIND")):
        logger.warning(
            "[%s] refusing to bind on %s without MCP_ALLOW_PUBLIC_BIND=1; "
            "falling back to %s (MCP servers have no caller authentication)",
            server_name,
            host,
            DEFAULT_BIND_HOST,
        )
        return DEFAULT_BIND_HOST

    if is_public_bind(host):
        logger.warning(
            "[%s] binding on %s — externally reachable and there is NO caller "
            "authentication. Restrict access at the firewall.",
            server_name,
            host,
        )
    return host
