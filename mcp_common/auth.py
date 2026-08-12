"""
공유 AuthManager 접근점.

GraphClient 마다 `AuthManager()` 를 새로 만들면 per-email refresh lock dict 이
인스턴스별로 분리돼 lock 이 무의미해지고, callback server / aiohttp 세션도 중복된다.
모든 도메인 클라이언트는 이 함수를 통해 프로세스 단일 인스턴스를 공유한다.
"""

from typing import Any


def get_shared_auth_manager() -> Any:
    """session.auth_manager 의 프로세스 단일 AuthManager 를 반환."""
    from session.auth_manager import get_default_auth_manager

    return get_default_auth_manager()
