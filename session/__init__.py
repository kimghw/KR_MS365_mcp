"""
Azure Authentication Module
Azure AD OAuth 2.0 인증을 처리하는 모듈입니다.

- mode 0 (단일 운영자): `AuthManager`·`AuthService`·`AzureConfig`·`AuthDatabase` (legacy)
- mode 1 (멀티유저, `MS365_MULTI_USER=1`): `identity_registry`(bearer 인증·사용자 관리),
  `token_store`(사용자별 암호화 토큰·refresh), `graph_connect`/`auth_gateway`(중앙 OAuth 연결),
  `admin_cli`(관리 CLI). legacy 클래스는 mode 1 에서 생성 자체를 거부한다(`mode_guard`).

legacy 클래스는 **처음 접근할 때** import 한다 — 멀티유저 모듈만 쓰는 프로세스가 legacy 모듈의
import 부작용(.env 로드·logging 설정)을 끌어오지 않게 한다. `from session import AuthManager` 는
그대로 동작한다.
"""

from importlib import import_module
from typing import Any

_LAZY = {
    "AuthService": ".auth_service",
    "AuthManager": ".auth_manager",
    "AzureConfig": ".azure_config",
    "AuthDatabase": ".auth_database",
}

# 메인 인터페이스
__all__ = [
    # 클래스
    'AuthManager',           # 메인 매니저 - 다중 사용자 관리 (mode 0)
    'AuthService',           # 인증 서비스 - OAuth 플로우 (mode 0)
    'AzureConfig',           # Azure 설정 관리 (mode 0)
    'AuthDatabase',          # 인증 데이터베이스 관리 (mode 0)
]

__version__ = '1.1.0'


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'session' has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
