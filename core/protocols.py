"""
Core Protocols - 모듈 간 의존성 추상화를 위한 Protocol 정의

현재 정의:
    - TokenProviderProtocol: mcp_outlook이 session.AuthManager를 직접 알지 않아도 되게 함

사용 예시:
    # 테스트용 Mock 주입
    mock_provider = MockTokenProvider()
    query = GraphMailQuery(token_provider=mock_provider)

    # 기본 사용 (하위 호환)
    query = GraphMailQuery()  # 내부에서 AuthManager 사용
"""

from typing import Protocol, Optional, Dict, Any, runtime_checkable


@runtime_checkable
class TokenProviderProtocol(Protocol):
    """
    토큰 제공자 프로토콜 - AuthManager 추상화

    OAuth 토큰의 획득, 갱신, 검증을 담당하는 인터페이스.
    session.AuthManager가 이 Protocol을 구현합니다.
    """

    async def validate_and_refresh_token(self, user_email: Optional[str] = None) -> Optional[str]:
        """
        유효한 액세스 토큰 반환 (필요시 자동 갱신)

        Args:
            user_email: 사용자 이메일. None이면 auth.db에서 첫 번째 사용자를 자동으로 가져옴

        Returns:
            유효한 액세스 토큰 또는 None
        """
        ...

    async def get_token(self, email: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        특정 사용자의 전체 토큰 정보 조회

        Args:
            email: 사용자 이메일. None이면 auth.db에서 첫 번째 사용자를 자동으로 가져옴

        Returns:
            토큰 정보 딕셔너리 또는 None
        """
        ...

    async def close(self) -> None:
        """리소스 정리"""
        ...
