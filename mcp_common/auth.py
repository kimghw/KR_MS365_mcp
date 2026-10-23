"""
인증 접근점 — 도메인 코드가 토큰 공급자를 얻는 유일한 관문.

| 모드 | 함수 | 결과 |
|------|------|------|
| mode 0 (단일 운영자) | `get_shared_auth_manager()` | 프로세스 단일 `AuthManager` (이메일 기반, legacy) |
| mode 1 (멀티유저) | `get_bound_token_provider(principal)` | 그 principal 에 고정된 `BoundTokenProvider` |
| mode 1 | `graph_connect_details(principal)` | `{"connect_url", "expires_in"}` — Graph 연결 안내 |

GraphClient 마다 `AuthManager()` 를 새로 만들면 per-email refresh lock dict 이 인스턴스별로
분리돼 lock 이 무의미해지고 callback server / aiohttp 세션도 중복된다 — mode 0 에서는 이 관문의
단일 인스턴스를 공유한다. mode 1 에서 `get_shared_auth_manager()` 를 부르면 명시적 오류다
(spec/spec_멀티유저.md ②-11.1): 기본 계정 선택·공용 auth.db·서버 브라우저 경로를 열지 않는다.
"""

from typing import Any, Dict

from mcp_common.principal import Principal
from mcp_common.security_contracts import BoundTokenProvider


def get_shared_auth_manager() -> Any:
    """session.auth_manager 의 프로세스 단일 AuthManager (mode 0 전용)."""
    from session.mode_guard import refuse_in_multi_user

    refuse_in_multi_user("get_shared_auth_manager()")
    from session.auth_manager import get_default_auth_manager

    return get_default_auth_manager()


def get_bound_token_provider(principal: Principal) -> BoundTokenProvider:
    """principal 에 고정된 토큰 공급자 (mode 1 전용). `close()` 는 no-op 이다."""
    from session.mode_guard import LegacyAuthDisabledError, multi_user_active

    if not multi_user_active():
        raise LegacyAuthDisabledError("get_bound_token_provider() 는 멀티유저 모드(MS365_MULTI_USER=1) 전용입니다.")
    from session.token_store import BoundGraphTokenProvider

    return BoundGraphTokenProvider(principal)


def graph_connect_details(principal: Principal) -> Dict[str, Any]:
    """Graph 미연결·재인증 필요 오류에 붙일 연결 안내. 1회용 링크(300초)를 새로 만든다.

    반환: `{"connect_url": "<공개 origin>/auth/graph/connect?ticket=...", "expires_in": 300}`.
    링크에는 bearer key 가 들어가지 않는다. 같은 브라우저에서 열어야 하며 등록된 계정으로만 연결된다.
    """
    from session.graph_connect import graph_connect_details as _details

    return _details(principal)


__all__ = ["get_shared_auth_manager", "get_bound_token_provider", "graph_connect_details"]
