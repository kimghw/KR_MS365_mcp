"""
동기 OneDrive 클라이언트 → 비동기 토큰 공급자 다리 (spec/spec_멀티유저.md ②-5.2).

예전 `OneDriveClient._get_access_token()` 은 이벤트 루프가 돌고 있으면
`ThreadPoolExecutor().submit(asyncio.run, coro)` 로 **새 이벤트 루프를 다른 스레드에 만들어**
인증 코루틴을 돌렸다. 그 스레드에는 요청 컨텍스트(principal)가 없고, 공급자가 가진 루프
종속 자원(lock·세션)이 엉뚱한 루프에서 쓰인다. 이 모듈이 그 브리지를 대체한다.

규칙:
    - 공급자 코루틴은 **요청을 처리 중인 이벤트 루프**(`FileRequestScope.loop`)에서 돈다
      (`asyncio.run_coroutine_threadsafe`). 작업 스레드는 결과만 기다린다.
    - 이벤트 루프 스레드에서 동기 토큰 요청은 교착이므로 오류다 — 동기 작업은
      `FileHandlerService` 가 작업 스레드로 넘긴 뒤 실행해야 한다.
    - 루프가 전혀 없는 순수 동기 진입(mode 0 CLI·단위 테스트)만 `asyncio.run` 을 쓴다.
    - mode 1 은 사용자 고정 `BoundTokenProvider.get_graph_token()` 만 쓴다. 공급자가 없으면
      생성 시점에 거부하고, AuthManager 를 만들거나 빌리지 않는다(②-2.2).
    - mode 0 은 주입된 auth manager, 없으면 첫 토큰 요청 때 공유 AuthManager
      (`mcp_common.auth.get_shared_auth_manager`)를 쓴다 — 별도 `AuthManager()` 생성 금지.
"""

import asyncio
import concurrent.futures
from typing import Any, Optional

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

from .request_scope import current_scope

#: 작업 스레드가 토큰을 기다리는 최대 시간(초). refresh 가 느려도 무한 대기하지 않는다.
DEFAULT_TOKEN_TIMEOUT = 60.0


class SyncTokenBridge:
    """동기 코드가 토큰을 얻는 유일한 창구."""

    def __init__(
        self,
        *,
        token_provider: Any = None,
        auth_manager: Any = None,
        timeout: float = DEFAULT_TOKEN_TIMEOUT,
    ):
        if multi_user_enabled() and token_provider is None:
            raise SecurityError(
                ErrorCode.CONFIG_ERROR,
                "멀티유저 모드의 OneDrive 클라이언트에는 사용자 고정 토큰 공급자가 필요합니다.",
            )
        self._provider = token_provider
        self._auth_manager = auth_manager
        self._timeout = timeout

    @property
    def provider(self) -> Any:
        return self._provider

    # ------------------------------------------------------------------
    async def get_token_async(self) -> Optional[str]:
        """비동기 경로 — 이벤트 루프에서 직접 부를 때."""
        if self._provider is not None:
            token = await self._provider.get_graph_token()
            return token.value
        return await self._legacy_manager().validate_and_refresh_token()

    def _legacy_manager(self) -> Any:
        if multi_user_enabled():  # 생성자가 막지만, 모드가 바뀐 테스트 등에 대비한 이중 잠금
            raise SecurityError(ErrorCode.CONFIG_ERROR)
        if self._auth_manager is None:
            from mcp_common.auth import get_shared_auth_manager

            self._auth_manager = get_shared_auth_manager()
        return self._auth_manager

    # ------------------------------------------------------------------
    def get_token(self) -> Optional[str]:
        """동기 경로 — 작업 스레드(또는 루프 없는 CLI)에서 부른다."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "이벤트 루프 스레드에서 동기 토큰 요청은 지원하지 않습니다 — "
                "FileHandlerService 로 작업 스레드에서 실행하세요."
            )

        scope = current_scope()
        loop = scope.loop if scope is not None else None
        if loop is not None and loop.is_running() and not loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(self.get_token_async(), loop)
            try:
                return future.result(timeout=self._timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise TimeoutError("토큰 공급자 응답 시간 초과") from None

        if multi_user_enabled():
            # 요청 루프 없이 도는 작업 — 요청 컨텍스트 밖이다. 대체 경로를 만들지 않는다.
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
        return asyncio.run(self.get_token_async())


__all__ = ["DEFAULT_TOKEN_TIMEOUT", "SyncTokenBridge"]
