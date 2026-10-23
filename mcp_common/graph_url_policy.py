"""
Graph URL 정책 — redirect 차단·nextLink 범위·사전 서명 URL 검사 (spec/spec_멀티유저.md ②-7.5, R08).

Calendar·Todo·OneDrive 가 각자 바이트 단위 사본으로 갖고 있던 것을 여기로 올렸다(2026-10-23).
정책 의미는 `mcp_outlook/outlook_security.py` 와 같다. OneNote·Teams 는 자기 클라이언트에
같은 규칙을 두고 있다 — 새 도메인은 이 모듈을 쓴다.

| 검사 | 적용 |
|------|------|
| Authorization 을 단 요청은 redirect 를 따라가지 않는다 (`BEARER_KW`) | 두 모드 |
| `@odata.nextLink`: https + `graph.microsoft.com` + `/v1.0/me/<리소스>...` 또는 본인 `/users/{id}/<리소스>...`, dot-segment 없음, GET 만 | 두 모드 (mode 1 은 principal, mode 0 은 호출 이메일로 본인 판정) |
| 사전 서명 다운로드 URL: https, userinfo 없음, 기본 포트, 사설·loopback·link-local IP·`localhost`·단일 라벨 호스트 거부, bearer 미부착, 후속 redirect 금지 | 두 모드 |

위반은 `SecurityError(PATH_NOT_ALLOWED)` 다 — 토큰 획득·HTTP 요청보다 먼저 판정한다.
사설 호스트 검사는 리터럴 IP·이름 기준이다(DNS 를 풀지 않으므로 rebinding 은 막지 못한다).
"""

import ipaddress
import uuid
from typing import Any, Dict, FrozenSet, Optional
from urllib.parse import unquote

from mcp_common.principal import current_principal, normalize_email_for_compare
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

GRAPH_HOST = "graph.microsoft.com"
GRAPH_VERSION = "v1.0"

#: Authorization 헤더를 단 aiohttp 요청에 항상 넘기는 키워드 — redirect 로 토큰이 새지 않게.
BEARER_KW: Dict[str, Any] = {"allow_redirects": False}

_NEXT_LINK_MESSAGE = "허용되지 않은 Graph 페이지 URL 입니다. 본인 리소스(/me 또는 본인 /users/{id})만 이어서 조회할 수 있습니다."
_PRESIGNED_MESSAGE = "허용되지 않은 다운로드 URL 입니다."


def _deny(message: str) -> SecurityError:
    return SecurityError(ErrorCode.PATH_NOT_ALLOWED, message)


def _parse(url: Any):
    """aiohttp 와 같은 파서(yarl)로 해석한다. 절대 URL 이 아니거나 역슬래시·제어문자가 있으면 None."""
    import yarl

    if not isinstance(url, str) or not url or "\\" in url or any(ord(c) < 0x20 for c in url):
        return None
    try:
        parsed = yarl.URL(url)
    except (ValueError, TypeError):
        return None
    if not parsed.is_absolute():
        return None
    return parsed


def _is_plain_https(parsed) -> bool:
    return (
        parsed is not None
        and parsed.scheme == "https"
        and bool(parsed.host)
        and parsed.user is None
        and parsed.password is None
        and parsed.port in (None, 443)
    )


def is_graph_https(url: Any) -> bool:
    """https + Graph 호스트 + userinfo 없음 + 기본 포트."""
    parsed = _parse(url)
    return _is_plain_https(parsed) and (parsed.host or "").lower() == GRAPH_HOST


def _is_own_user_segment(value: str, user_email: Optional[str]) -> bool:
    """`/users/{id}` 의 id 가 호출자 본인인지. mode 1 은 principal(이메일·oid), mode 0 은 호출 이메일."""
    principal = current_principal() if multi_user_enabled() else None
    if principal is not None:
        if "@" in value:
            return bool(principal.graph_email) and (
                normalize_email_for_compare(value) == normalize_email_for_compare(principal.graph_email)
            )
        try:
            return str(uuid.UUID(value)).lower() == str(uuid.UUID(principal.object_id)).lower()
        except (ValueError, TypeError, AttributeError):
            return False
    if not user_email or "@" not in value:
        return False
    return normalize_email_for_compare(value) == normalize_email_for_compare(user_email)


def check_next_link(url: Any, user_email: Optional[str], *, resources: FrozenSet[str]) -> str:
    """`@odata.nextLink` 를 따라가도 되는지. 통과하면 URL 문자열을 돌려준다.

    yarl 이 정규화한 경로로 판정한다 — `..` 는 이미 접혀 있고, 인코딩된 `%2F`·`%2E%2E` 는
    성분 단위로 풀어서 다시 거부한다. `resources` 는 소문자 리소스 이름 집합
    (예: calendar → {"events", "calendar", "calendars", "calendarview"}).
    """
    parsed = _parse(url)
    if not is_graph_https(url):
        raise _deny(_NEXT_LINK_MESSAGE)
    segments = [unquote(s) for s in parsed.raw_parts[1:]]  # 첫 원소는 "/"
    for part in segments[:-1]:
        if part == "":
            raise _deny(_NEXT_LINK_MESSAGE)
    for part in segments:
        if part in (".", "..") or "/" in part or "\\" in part or any(ord(c) < 0x20 for c in part):
            raise _deny(_NEXT_LINK_MESSAGE)
    if len(segments) < 3 or segments[0] != GRAPH_VERSION:
        raise _deny(_NEXT_LINK_MESSAGE)
    owner = segments[1].lower()
    if owner == "me":
        resource_index = 2
    elif owner == "users":
        if len(segments) < 4 or not _is_own_user_segment(segments[2], user_email):
            raise _deny(_NEXT_LINK_MESSAGE)
        resource_index = 3
    else:
        raise _deny(_NEXT_LINK_MESSAGE)
    if segments[resource_index].lower() not in resources:
        raise _deny(_NEXT_LINK_MESSAGE)
    return str(url)


def _is_disallowed_address(addr: "ipaddress.IPv4Address | ipaddress.IPv6Address") -> bool:
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _is_private_host(host: str) -> bool:
    """리터럴 IP 는 사설·loopback·link-local·멀티캐스트·예약·미지정 대역, 이름은 localhost·단일 라벨·`.local`·`.internal`.

    끝의 `.`(FQDN 표기)은 떼고 본다 — `localhost.` 가 이름 검사를 비켜 가지 못하게 (astra 2차 N05).
    """
    candidate = host.strip("[]").lower().rstrip(".")
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return (
            candidate in ("localhost", "localhost.localdomain")
            or candidate.endswith(".localhost")
            or candidate.endswith(".local")
            or candidate.endswith(".internal")
            or "." not in candidate
        )
    return _is_disallowed_address(addr)


def _resolved_addresses(host: str) -> list:
    """이름을 지금 해석한 주소 목록. 해석 실패는 빈 목록 — 호출자가 거부한다."""
    import socket

    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    addresses = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return addresses


def check_presigned_url(url: Any, *, resolve_dns: bool = True) -> str:
    """Graph 가 302 로 준 사전 서명 다운로드 URL. bearer 없이, https 로, 공개 호스트에만 간다.

    이름 호스트는 지금 해석해 **모든** 주소가 공개 대역이어야 한다(해석 실패도 거부). 해석 시점과
    연결 시점의 주소가 다를 수 있는 rebinding 은 막지 못한다(④) — 연결 주소 고정은 후속.
    `resolve_dns=False` 는 테스트 전용.
    """
    parsed = _parse(url)
    if not _is_plain_https(parsed) or _is_private_host(parsed.host):
        raise _deny(_PRESIGNED_MESSAGE)
    host = parsed.host.strip("[]").rstrip(".")
    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False
    if resolve_dns and not is_literal:
        addresses = _resolved_addresses(host)
        if not addresses or any(_is_disallowed_address(a) for a in addresses):
            raise _deny(_PRESIGNED_MESSAGE)
    return str(url)


def is_redirect(status: Any) -> bool:
    return isinstance(status, int) and 300 <= status < 400


__all__ = [
    "GRAPH_HOST",
    "GRAPH_VERSION",
    "BEARER_KW",
    "is_graph_https",
    "check_next_link",
    "check_presigned_url",
    "is_redirect",
]
