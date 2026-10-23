"""
Authentication Manager
다중 사용자 인증 및 토큰 관리 + 콜백 서버 생애주기 관리 — **단일 운영자(mode 0) 전용**.

멀티유저 모드(`MS365_MULTI_USER=1`)에서는 `AuthManager()`·`get_default_auth_manager()`·
`_auto_reauth()`·기본 사용자 선택을 모두 거부한다(spec/spec_멀티유저.md ②-5.5). 멀티유저 경로는
`mcp_common.auth.get_bound_token_provider(principal)` 와 `session.auth_gateway` 다.

로그에는 이메일·state·토큰을 남기지 않는다(②-2.7).
"""

import os
import logging
import asyncio
import webbrowser
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dotenv import load_dotenv

# 환경 변수 로드 (프로젝트 루트 기준)
# Use utf-8-sig encoding to handle Windows BOM (Byte Order Mark)
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(_env_path, encoding="utf-8-sig")

from .auth_service import AuthService, refresh_failure_reason
from .auth_database import AuthDatabase
from .azure_config import AzureConfig
from .mode_guard import refuse_in_multi_user
from . import external_login as _external

logger = logging.getLogger(__name__)


def _get_callback_port_from_env(default: int = 5000) -> int:
    """AZURE_REDIRECT_URI에서 포트를 파싱. 실패 시 default 반환."""
    uri = os.getenv("AZURE_REDIRECT_URI")
    if not uri:
        return default
    try:
        from urllib.parse import urlparse
        return urlparse(uri).port or default
    except Exception:
        return default


def get_default_user_email() -> Optional[str]:
    """
    기본 사용자 이메일을 결정한다.

    이전 구현은 `list_users()[0]` 을 썼는데, 해당 쿼리가 updated_at DESC 정렬이라
    토큰이 갱신될 때마다 대상 사용자가 암묵적으로 바뀌었다. 사용자 선택 정책은
    mcp_common.user_resolver 로 일원화돼 있으므로 여기서는 그쪽에 위임한다
    (MS365_DEFAULT_USER_EMAIL > 유효 토큰 보유자 우선 > 이메일 사전순).

    Returns:
        기본 사용자의 이메일 또는 None
    """
    refuse_in_multi_user("session.auth_manager.get_default_user_email()")
    try:
        from mcp_common.user_resolver import resolve_user_email

        return resolve_user_email()
    except ImportError:
        # mcp_common 없이 session 만 떼어 쓰는 경우를 위한 폴백 (결정적 정렬 유지)
        db = AuthDatabase()
        users = db.list_users() or []
        emails = [
            u.get('user_email') or u.get('email')
            for u in users
            if u.get('user_email') or u.get('email')
        ]
        return sorted(emails, key=str.lower)[0] if emails else None


class AuthManager:
    """인증 매니저 - 다중 사용자 관리 및 콜백 서버 통합"""

    def __init__(self, db_path: Optional[str] = None, app_id: Optional[str] = None):
        """
        인증 매니저 초기화 - 모든 컴포넌트의 중앙 관리자

        Args:
            db_path: 데이터베이스 경로 (None이면 환경변수 또는 기본값 사용)
            app_id: 사용할 Azure AD 앱 ID (선택적)
        """
        refuse_in_multi_user("AuthManager()")
        # DB 경로 결정 (환경변수 > 파라미터 > 기본값)
        import os
        if db_path is None:
            # Use absolute path for database
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.getenv('DB_PATH', os.path.join(base_dir, 'database', 'auth.db'))

        # 1. DB 인스턴스 생성 (단일 인스턴스)
        self.auth_db = AuthDatabase(db_path)

        # 2. Config 인스턴스 생성 (DB 공유)
        self.config = AzureConfig(self.auth_db, app_id)

        # 3. AuthService 생성 (DB와 Config 공유)
        self.auth_service = AuthService(self.auth_db, self.config)

        # 4. 콜백 서버 인스턴스 (필요시 생성)
        self.callback_server = None

        # 5. 사용자별 refresh lock (동일 user_email에 대한 동시 refresh가
        #    같은 refresh_token을 두 번 사용하지 않도록 직렬화)
        self._refresh_locks: Dict[str, asyncio.Lock] = {}
        self._refresh_locks_master = asyncio.Lock()

    async def _get_refresh_lock(self, email: str) -> asyncio.Lock:
        """사용자별 refresh lock 획득. 없으면 생성."""
        async with self._refresh_locks_master:
            lock = self._refresh_locks.get(email)
            if lock is None:
                lock = asyncio.Lock()
                self._refresh_locks[email] = lock
            return lock

    def start_authentication(self) -> Dict[str, str]:
        """
        새 사용자 인증 시작 - URL 생성

        Returns:
            Dict: 인증 정보
                - auth_url: Azure AD 인증 URL
                - state: 보안 검증용 state
        """
        return self.auth_service.start_auth_flow(force_new=True)

    async def get_token(self, email: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        특정 사용자의 토큰 조회

        Args:
            email: 사용자 이메일. None이면 auth.db에서 첫 번째 사용자를 자동으로 가져옴

        Returns:
            토큰 정보 또는 None
        """
        if not email:
            email = get_default_user_email()
            if not email:
                logger.warning("No email provided and no users found in auth.db")
                return None

        token_info = self.auth_db.get_token(email)

        if not token_info:
            logger.warning("No token found for requested user")
            return None

        return {
            'email': email,
            'access_token': token_info['access_token'],
            'refresh_token': token_info.get('refresh_token'),
            'expires_at': token_info['expires_at'],
            'is_expired': self.auth_service.is_token_expired(token_info['expires_at']),
            # 2026-10-23 추가 — 마지막 갱신이 invalid_grant 류로 거부됐으면 'reauth_required'(없으면 None|'ok')
            'refresh_state': token_info.get('refresh_state'),
        }

    async def refresh_token(self, email: Optional[str] = None) -> Dict[str, Any]:
        """
        특정 사용자의 토큰 갱신

        Args:
            email: 사용자 이메일. None이면 auth.db에서 첫 번째 사용자를 자동으로 가져옴

        Returns:
            갱신 결과
        """
        if not email:
            email = get_default_user_email()
            if not email:
                return {
                    'status': 'error',
                    'error': 'No email provided',
                    'message': 'No email provided and no users found in auth.db',
                    'reason': _external.STATE_NOT_CONNECTED,
                }

        try:
            # 기존 토큰 조회
            token_info = self.auth_db.get_token(email)

            if not token_info:
                return {
                    'status': 'error',
                    'error': 'No token found',
                    'message': f'No token found for {email}',
                    'reason': _external.STATE_NOT_CONNECTED,
                }

            if not token_info.get('refresh_token'):
                return {
                    'status': 'error',
                    'error': 'No refresh token',
                    'message': 'Refresh token not available, re-authentication required',
                    'reason': _external.STATE_REAUTH_REQUIRED,
                }

            # 리프레시 토큰 만료 확인 (refresh_token_expires_at 컬럼 직접 비교)
            if self.auth_service.is_refresh_expiry_passed(token_info.get('refresh_token_expires_at')):
                return {
                    'status': 'reauth_required',
                    'error': 'Refresh token expired',
                    'message': 'Refresh token expired, re-authentication required',
                    'reason': _external.STATE_REAUTH_REQUIRED,
                }

            # 토큰 갱신
            new_tokens = await self.auth_service.refresh_tokens(token_info['refresh_token'])

            # DB 업데이트
            success = self.auth_db.update_token(email, new_tokens)

            if success:
                logger.info("Token refreshed")
                return {
                    'status': 'success',
                    'email': email,
                    'access_token': new_tokens['access_token'],
                    'expires_at': new_tokens['expires_at'],
                    'message': 'Token refreshed successfully',
                    'reason': 'ok',
                }
            else:
                raise Exception("Failed to update token in database")

        except Exception as e:
            logger.error("Token refresh failed: %s", type(e).__name__)

            # reason 은 2026-10-23 추가 — 일시 장애 'transient' 와 구분. 토큰 endpoint 가 거부(invalid_grant·interaction_required)한
            # 경우만 영구 표식 — 이후 connection_state 가 reauth_required 를 돌려준다.
            reason = refresh_failure_reason(e)
            if reason == _external.STATE_REAUTH_REQUIRED:
                self.auth_db.mark_refresh_state(email, _external.REFRESH_STATE_REAUTH)

            # refresh token이 revoke된 경우 (종전 문자열 판정은 그대로 유지)
            if reason == _external.STATE_REAUTH_REQUIRED or 'invalid_grant' in str(e).lower() or 'expired' in str(e).lower():
                return {
                    'status': 'reauth_required',
                    'error': str(e),
                    'message': 'Re-authentication required',
                    'reason': _external.STATE_REAUTH_REQUIRED,
                }

            return {
                'status': 'error',
                'error': str(e),
                'reason': reason,
            }

    async def validate_and_refresh_token(self, email: Optional[str] = None, auto_reauth: bool = False) -> Optional[str]:
        """
        토큰 유효성 확인 및 필요시 자동 갱신
        refresh_token 갱신 실패 시 auto_reauth=True이면 브라우저 재인증 시도

        동일 user_email에 대한 동시 호출은 per-email lock으로 직렬화하여
        같은 refresh_token을 두 번 사용해 invalid_grant가 나는 race를 방지한다.
        lock 획득 후 DB를 재조회해, 다른 코루틴이 이미 갱신한 토큰이 유효하면 그대로 사용한다.

        Args:
            email: 사용자 이메일. None이면 auth.db에서 첫 번째 사용자를 자동으로 가져옴
            auto_reauth: refresh 실패 시 브라우저 재인증 자동 시작 여부

        Returns:
            유효한 액세스 토큰 또는 None
        """
        if not email:
            email = get_default_user_email()
            if not email:
                logger.error("No email provided and no users found in auth.db")
                return None

        lock = await self._get_refresh_lock(email)
        async with lock:
            # lock 획득 후 DB 재조회 — 다른 코루틴이 이미 갱신했을 수 있음
            token_info = self.auth_db.get_token(email)

            if not token_info:
                logger.error("No token found for requested user")
                if auto_reauth:
                    return await self._auto_reauth(email)
                return None

            # 토큰이 유효한 경우 (대기 중 다른 코루틴이 갱신했을 수도 있음)
            if not self.auth_service.is_token_expired(token_info['expires_at']):
                return token_info['access_token']

            # 토큰 갱신 시도
            logger.info("Token expired, attempting refresh")
            refresh_result = await self.refresh_token(email)

            if refresh_result['status'] == 'success':
                return refresh_result['access_token']

            # refresh 실패 → 재인증 필요
            logger.warning("Refresh failed (status=%s)", refresh_result.get('status', 'unknown'))
            if auto_reauth:
                return await self._auto_reauth(email)

            logger.error("Failed to get valid token")
            return None

    async def get_auth_url_for_login(self, email: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
        """
        인증이 필요할 때 로그인 URL을 생성하여 반환 (LLM 전달용)
        콜백 서버를 자동으로 시작하고 인증 URL을 반환합니다.

        Args:
            email: 사용자 이메일. None이면 'unknown'으로 처리
            port: 콜백 서버 포트. None이면 AZURE_REDIRECT_URI에서 파싱 (실패 시 5000)

        Returns:
            Dict: auth_url, state, message 포함
        """
        if not email:
            email = 'unknown'
        if port is None:
            port = _get_callback_port_from_env()

        try:
            # 콜백 서버 확인 및 시작
            await self.ensure_callback_server(port)

            # 인증 URL 생성
            auth_info = self.start_authentication()

            return {
                'status': 'auth_required',
                'auth_url': auth_info['auth_url'],
                'state': auth_info['state'],
                'email': email,
                'message': f'인증이 필요합니다. 아래 URL을 브라우저에서 열어 로그인해주세요.\n{auth_info["auth_url"]}'
            }
        except Exception as e:
            logger.error("Failed to generate auth URL: %s", type(e).__name__)
            return {
                'status': 'error',
                'error': str(e),
                'message': f'인증 URL 생성 실패: {str(e)}'
            }

    async def _auto_reauth(self, email: str) -> Optional[str]:
        """
        브라우저 재인증 자동 시작 (mode 0 전용 — 멀티유저에서는 서버가 브라우저를 열지 않는다)

        요청한 계정(`email`)과 실제로 로그인한 계정이 다르면 그 토큰을 돌려주지 않는다 —
        다른 계정의 토큰이 요청 계정 대신 쓰이는 것을 막는다(spec ②-2.2).

        Args:
            email: 재인증을 요청한 사용자 이메일

        Returns:
            새 액세스 토큰 또는 None
        """
        refuse_in_multi_user("AuthManager._auto_reauth()")
        logger.info("Starting automatic re-authentication")
        result = await self.authenticate_with_browser()

        if result['status'] == 'success':
            if (result.get('email') or '').strip().lower() != (email or '').strip().lower():
                logger.error("Re-authentication completed with a different account; token not returned")
                return None
            logger.info("Re-authentication successful")
            new_token_info = self.auth_db.get_token(result['email'])
            if new_token_info:
                return new_token_info['access_token']

        logger.error("Re-authentication failed (status=%s)", result.get('status', 'unknown'))
        return None

    def list_users(self) -> List[Dict[str, Any]]:
        """
        모든 인증된 사용자 목록

        Returns:
            사용자 리스트
        """
        users = self.auth_db.list_users()

        # 각 사용자의 토큰 상태 추가
        for user in users:
            token_info = self.auth_db.get_token(user['email'])
            if token_info:
                user['has_token'] = True
                user['token_expired'] = self.auth_service.is_token_expired(token_info['expires_at'])
                user['has_refresh_token'] = bool(token_info.get('refresh_token'))
            else:
                user['has_token'] = False

        return users


    def remove_user(self, email: Optional[str] = None) -> bool:
        """
        사용자 제거 (토큰 삭제)

        Args:
            email: 사용자 이메일. None이면 auth.db에서 첫 번째 사용자를 자동으로 가져옴

        Returns:
            성공 여부
        """
        if not email:
            email = get_default_user_email()
            if not email:
                logger.error("No email provided and no users found in auth.db")
                return False

        success = self.auth_db.delete_token(email)

        if success:
            logger.info("User token removed")
        else:
            logger.error("Failed to remove user token")

        return success

    def cleanup_expired_tokens(self) -> int:
        """
        만료된 토큰 정리

        Returns:
            정리된 토큰 수
        """
        count = self.auth_db.cleanup_expired_tokens()
        logger.info(f"Cleaned up {count} expired tokens")
        return count

    def get_token_status(self, email: Optional[str] = None) -> Dict[str, Any]:
        """
        사용자 토큰 상태 조회

        Args:
            email: 사용자 이메일. None이면 auth.db에서 첫 번째 사용자를 자동으로 가져옴

        Returns:
            토큰 상태 정보
        """
        if not email:
            email = get_default_user_email()
            if not email:
                return {
                    'status': 'not_found',
                    'email': None,
                    'message': 'No email provided and no users found in auth.db'
                }

        token_info = self.auth_db.get_token(email)

        if not token_info:
            return {
                'status': 'not_found',
                'email': email,
                'message': 'No token found'
            }

        # 액세스 토큰 상태
        access_expired = self.auth_service.is_token_expired(token_info['expires_at'])

        # 리프레시 토큰 상태 (refresh_token_expires_at 컬럼 직접 비교)
        has_refresh = bool(token_info.get('refresh_token'))
        refresh_expired = False
        if has_refresh:
            refresh_expired = self.auth_service.is_refresh_expiry_passed(
                token_info.get('refresh_token_expires_at')
            )

        # 2026-10-23 추가 키(기존 키·의미는 그대로): refresh_state = 마지막 갱신 거부 표식, state = connection_state 의 4상태
        # (거부 표식이 있으면 needs_reauth 가 False 여도 state 는 'reauth_required' — 호출자는 state 를 보는 것이 정확하다).
        refresh_state = token_info.get('refresh_state')
        rejected = refresh_state == _external.REFRESH_STATE_REAUTH
        return {
            'status': 'found',
            'email': email,
            'access_token_expired': access_expired,
            'access_token_expires_at': token_info['expires_at'],
            'has_refresh_token': has_refresh,
            'refresh_token_expired': refresh_expired,
            'needs_refresh': access_expired and has_refresh and not refresh_expired,
            'needs_reauth': not has_refresh or refresh_expired,
            'refresh_state': refresh_state,
            'state': (_external.STATE_REAUTH_REQUIRED if (not has_refresh or refresh_expired or rejected)
                      else _external.STATE_CONNECTED),
        }

    # ------------------------------------------------------------------
    # 외부 로그인 위임 — mode 0 라이브러리 계약 (spec/spec_멀티유저.md ② '모드 0 외부 로그인 위임 계약(AIP)')
    # ------------------------------------------------------------------
    async def complete_external_login(
        self, code: str, redirect_uri: str, scopes: Any = None, save: bool = True, expect_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """외부 웹 앱(AIP)이 자기 콜백에서 받은 Entra 인가 코드를 이 저장소 설정(client_id·secret)으로 교환한다.

        Args:
            code: 인가 코드.
            redirect_uri: 그 코드를 발급받은 외부 앱의 redirect_uri(토큰 교환 때 같은 값이어야 한다).
            scopes: 교환 scope(None = `config.default_scopes`). 문자열(공백 구분) 또는 목록.
            save: True = `save_user` → `save_token`(complete_auth_flow 와 같은 순서, 토큰 응답의 scope 도 저장).
                  False = 신원만(저장 없음 — Graph 동의가 막혔을 때의 `openid profile email User.Read` 폴백).
            expect_email: 기대 계정(로그인 사용자 — 재연결 때). 값이 있으면 `/me` 메일과 **저장 전에** 대소문자 무시로 대조해
                  다르면 아무것도 저장하지 않고 ACCOUNT_MISMATCH. None = 종전(무검증). 2026-10-23 codex 교차 검토 반영.

        Returns:
            {"email"(소문자), "display_name", "user_info"(id·displayName·mail·userPrincipalName), "saved", "has_refresh",
             "granted_scopes", "state"} — access/refresh/id token 은 어떤 키에도 없다.
            save=True 인데 auth.db 저장에 실패하면 예외가 아니라 같은 꼴에 "saved": False · "state"(DB 기준) · **"error": "SAVE_FAILED"**
            가 더 있다(신원은 돌려준다 — 호출자는 로그인을 유지하고 미연결로 표시). 그 밖에는 "error" 키가 없다.

        Raises:
            session.external_login.ExternalLoginError: `code` = EXCHANGE_FAILED | USERINFO_FAILED | ACCOUNT_MISMATCH
                (`expected_email`·`actual_email` 속성), `str(e)` = "CODE|메시지". SAVE_FAILED 는 예외로 쓰지 않는다.
        """
        return await self.auth_service.complete_external_login(
            code, redirect_uri, scopes=scopes, save=save, expect_email=expect_email
        )

    def connection_state(self, email: str) -> Dict[str, Any]:
        """`email` 계정의 연결 상태.

        Returns:
            {"email", "state": connected|reauth_required|not_connected|unavailable,
             "features": {mail, teams, onenote, calendar, todo} → bool (scope 를 모르는 구형 행은 None),
             "granted_scopes": list|None, "access_token_expires_at": ISO|None, "refresh_token_expired": bool}
            unavailable 일 때만 "error"(예외 종류 이름) 키가 더 있다.
        """
        return self.auth_service.connection_state(email)

    def is_callback_server_running(self) -> bool:
        """
        콜백 서버 실행 상태 확인

        Returns:
            서버 실행 중이면 True, 아니면 False
        """
        return self.callback_server is not None and self.callback_server.is_running()

    async def ensure_callback_server(self, port: Optional[int] = None) -> bool:
        """
        콜백 서버가 실행 중인지 확인하고, 필요시 시작

        Args:
            port: 서버 포트. None이면 AZURE_REDIRECT_URI에서 파싱 (실패 시 5000)

        Returns:
            서버가 실행 중이거나 성공적으로 시작되면 True
        """
        if port is None:
            port = _get_callback_port_from_env()
        # CallbackServer 인스턴스가 없으면 생성
        if self.callback_server is None:
            import sys
            import os
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)
            from callback_server import CallbackServer

            self.callback_server = CallbackServer(auth_manager=self, port=port)

        # 이미 실행 중인지 확인
        if self.callback_server.is_running():
            logger.info(f"Callback server already running on port {port}")
            return True

        # 포트가 다른 프로세스에서 사용 중인지 확인
        # 개인용 도구이므로 외부 점유 시 콜백을 받을 수 없어 실패 처리
        if not self.callback_server.check_port_availability():
            logger.error(f"Port {port} is already in use by another process - cannot receive callback")
            return False

        # 서버 시작
        try:
            await self.callback_server.start()
            return True
        except Exception as e:
            logger.error(f"Failed to start callback server: {e}")
            return False

    async def stop_callback_server(self):
        """콜백 서버 종료"""
        if self.callback_server and self.callback_server.is_running():
            await self.callback_server.stop()
            logger.info("Callback server stopped")

    async def authenticate_with_browser(self, timeout: int = 300, port: Optional[int] = None) -> Dict[str, Any]:
        """
        브라우저를 통한 완전한 인증 플로우

        Args:
            timeout: 인증 대기 시간 (초, 기본 5분)
            port: 콜백 서버 포트. None이면 AZURE_REDIRECT_URI에서 파싱 (실패 시 5000)

        Returns:
            인증 결과
        """
        if port is None:
            port = _get_callback_port_from_env()
        server_was_running = self.is_callback_server_running()

        try:
            # 1. 콜백 서버 상태 확인 및 시작
            logger.info("Checking callback server status...")
            if not await self.ensure_callback_server(port):
                return {
                    'status': 'error',
                    'error': 'Failed to start callback server'
                }

            # 2. 인증 URL 생성
            auth_info = self.start_authentication()
            state = auth_info['state']
            logger.info("Authentication URL generated")

            # 브라우저를 열기 전에 **이 state 전용** 대기자를 먼저 등록한다
            # (SSO 세션이 살아있으면 브라우저 열자마자 콜백이 올 수 있음). 다른 state 의 콜백·오류는
            # 이 대기자를 깨우지 않는다.
            if self.callback_server:
                self.callback_server.expect(state)

            # 3. 브라우저 열기
            logger.info("Opening browser for authentication")
            try:
                webbrowser.open(auth_info['auth_url'])
                logger.info("Browser opened successfully")
            except Exception as e:
                logger.warning("Could not open browser: %s", type(e).__name__)
                print(f"\n[WARN] Please manually visit: {auth_info['auth_url']}")

            # 4. 인증 완료 대기
            logger.info(f"Waiting for authentication (timeout: {timeout}s)")

            # CallbackServer 의 state 별 대기 (DB 에 새로 생긴 이메일로 성공을 추정하지 않는다)
            if not self.callback_server:
                raise Exception("Callback server unavailable")
            authenticated_email = await self.callback_server.wait_for_auth(timeout, state=state)

            if authenticated_email:
                # 인증된 사용자 정보 조회
                users = self.list_users()
                user = next((u for u in users if u['email'] == authenticated_email), None)

                if user:
                    logger.info("Authentication successful")
                    return {
                        'status': 'success',
                        'email': authenticated_email,
                        'user': user
                    }
                raise Exception("Authenticated user not found in DB")
            raise asyncio.TimeoutError("Authentication timeout")

        except asyncio.TimeoutError:
            logger.error("Authentication timeout")
            return {
                'status': 'timeout',
                'error': 'Authentication timeout'
            }
        except Exception as e:
            logger.error("Authentication error: %s", type(e).__name__)
            return {
                'status': 'error',
                'error': str(e)
            }
        finally:
            # 6. 서버가 원래 실행 중이지 않았다면 정리
            if not server_was_running and self.is_callback_server_running():
                logger.info("Stopping callback server (was not running before)")
                await self.stop_callback_server()

    async def close(self):
        """리소스 정리"""
        # 콜백 서버 정리
        await self.stop_callback_server()

        # AuthService 정리
        await self.auth_service.close()

        logger.info("Auth manager closed")


_default_auth_manager: Optional[AuthManager] = None


def get_default_auth_manager() -> AuthManager:
    """
    공유 AuthManager 싱글톤 반환.

    Session 등에서 매 호출마다 AuthManager()를 새로 만들면 per-email refresh lock dict이
    각 인스턴스마다 독립적이라 lock이 의미가 없다. 동일 프로세스 내에서는 같은 인스턴스를
    공유해 lock dict, callback_server, aiohttp 세션을 재사용한다. (mode 0 전용)
    """
    refuse_in_multi_user("get_default_auth_manager()")
    global _default_auth_manager
    if _default_auth_manager is None:
        _default_auth_manager = AuthManager()
    return _default_auth_manager


async def main():
    """AuthManager 직접 실행 - 인증 및 토큰 관리"""
    import sys

    manager = AuthManager()

    try:
        # 기존 인증된 사용자 확인
        users = manager.list_users()
        if users:
            print("\n" + "=" * 60)
            print(" Authenticated Users")
            print("=" * 60)
            for user in users:
                status = "Active" if not user.get('token_expired', True) else "Expired"
                has_refresh = "Yes" if user.get('has_refresh_token') else "No"
                print(f"  {user['email']}: [{status}] refresh_token={has_refresh}")
            print("=" * 60)

            # 토큰 갱신 테스트
            print("\n[1] Refresh token  [2] New auth  [3] Exit")
            choice = input("Select: ").strip()

            if choice == '1':
                email = input("Email to refresh: ").strip()
                if not email:
                    email = users[0]['email']
                print(f"\nRefreshing token for {email}...")
                token = await manager.validate_and_refresh_token(email, auto_reauth=True)
                if token:
                    print("Access token acquired.")  # 토큰 값·앞부분은 출력하지 않는다
                else:
                    print("Failed to get token.")
                return

            elif choice == '2':
                pass  # 아래 인증 플로우 진행

            else:
                print("Exiting.")
                return

        # 브라우저 인증 플로우
        print("\n" + "=" * 60)
        print(" Azure AD Authentication")
        print("=" * 60)
        print("Starting authentication flow...")
        print("Browser will open automatically.")
        print("=" * 60)

        result = await manager.authenticate_with_browser()

        if result['status'] == 'success':
            print(f"\nAuthentication Successful!")
            print(f"  Email: {result['email']}")
            user = result.get('user', {})
            if user.get('display_name'):
                print(f"  Name: {user['display_name']}")
        elif result['status'] == 'timeout':
            print("\nAuthentication timeout. Please try again.")
        else:
            print(f"\nAuthentication failed: {result.get('error', 'Unknown error')}")

    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        logger.error("Error: %s", type(e).__name__)
        print(f"\nError: {str(e)}")
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())