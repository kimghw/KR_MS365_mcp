#!/usr/bin/env python3
"""
OAuth Callback Server
Azure AD 인증 콜백을 처리하는 웹서버입니다 — **단일 운영자(mode 0) 전용**.
클래스 기반으로 리팩토링하여 AuthManager에서 사용할 수 있습니다.

인증 대기는 **state 별**이다(`expect(state)` → `wait_for_auth(timeout, state=...)`). 공용 Event·
공용 인증 이메일·공용 오류 필드가 없으므로 잘못된 state·다른 인증의 오류 콜백이 진행 중인 다른
인증을 깨우거나 중단시키지 못한다(spec/spec_멀티유저.md ②-2.3). 오류 콜백도 성공 경로와 같은
TTL·1회 소비 규칙(`AuthService.consume_state`)을 따른다.

멀티유저 모드(`MS365_MULTI_USER=1`)에서는 생성 자체를 거부한다 — 중앙 `session.auth_gateway` 를 쓴다.
로그에는 query string·state·토큰·이메일을 남기지 않는다.
"""

import asyncio
import html
import json
import socket
import logging
from aiohttp import web
from urllib.parse import parse_qs
import os
import platform
from dotenv import load_dotenv
from typing import Dict, List, Optional

# Load environment variables (프로젝트 루트 기준)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_env_path, encoding="utf-8-sig")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CallbackServer:
    """OAuth 콜백 서버 클래스"""

    def __init__(self, auth_manager=None, port: int = 5000):
        """
        콜백 서버 초기화

        Args:
            auth_manager: AuthManager 인스턴스 (옵션)
            port: 서버 포트 (기본 5000)
        """
        from session.mode_guard import refuse_in_multi_user

        refuse_in_multi_user("CallbackServer")
        self.auth_manager = auth_manager
        self.port = port
        self.app = None
        self.runner = None
        self.site = None
        # state → 그 인증 하나의 결과 Future (이메일 또는 오류 문자열)
        self._waiters: Dict[str, asyncio.Future] = {}
        # state 를 지정하지 않은 legacy 대기자 — **검증된 state** 의 결과만 전달된다
        self._any_waiters: List[asyncio.Future] = []

        # AuthManager가 없으면 독립 실행 모드
        if not auth_manager:
            from session.auth_manager import AuthManager
            self.auth_manager = AuthManager()
            self.standalone_mode = True
        else:
            self.standalone_mode = False

        # AuthService는 AuthManager에서 가져옴
        self.auth_service = self.auth_manager.auth_service

    def is_running(self) -> bool:
        """서버 실행 상태 확인"""
        return self.site is not None

    def check_port_availability(self) -> bool:
        """
        포트 사용 가능 여부 확인

        Returns:
            포트가 사용 가능하면 True
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('localhost', self.port))
            sock.close()
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # state 별 대기
    # ------------------------------------------------------------------
    def expect(self, state: str) -> None:
        """이 state 의 결과를 기다릴 대기자를 등록한다(브라우저를 열기 전에 부른다)."""
        loop = asyncio.get_running_loop()
        old = self._waiters.get(state)
        if old is None or old.done():
            self._waiters[state] = loop.create_future()

    def _resolve(self, state: str, *, email: Optional[str] = None, error: Optional[str] = None) -> None:
        """검증된 state 의 결과를 그 state 의 대기자(와 legacy 대기자)에게만 전달한다."""
        targets = [f for f in [self._waiters.get(state)] if f is not None]
        targets += self._any_waiters
        self._any_waiters = []
        for fut in targets:
            if not fut.done():
                fut.set_result((email, error))

    async def handle_callback(self, request):
        """OAuth 콜백 처리"""
        # 쿼리 문자열은 authorization code 를 담고 있으므로 로그에 남기지 않는다
        logger.info(f"Callback received - Path: {request.path}")

        query_params = parse_qs(request.query_string)

        # Get authorization code and state
        code = query_params.get('code', [None])[0]
        state = query_params.get('state', [None])[0]
        error = query_params.get('error', [None])[0]
        error_description = query_params.get('error_description', [None])[0]

        if error:
            html_content = f"""
            <html>
            <head>
                <title>Authentication Failed</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f0f0f0; }}
                    .container {{ background: white; padding: 30px; border-radius: 10px; max-width: 600px; margin: auto; }}
                    h1 {{ color: #d73027; }}
                    .error {{ background: #fee; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                    .button {{ background: #4285f4; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 20px; }}
                    .button:hover {{ background: #357ae8; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>[ERROR] Authentication Failed</h1>
                    <div class="error">
                        <strong>Error:</strong> {html.escape(error)}<br>
                        <strong>Description:</strong> {html.escape(error_description or 'No additional information')}
                    </div>
                    <p>Please try again or contact your administrator if the problem persists.</p>
                    <a href="/" class="button">Try Again</a>
                </div>
            </body>
            </html>
            """
            # 진행 중인 인증(state 일치·TTL 이내)의 오류만 **그 인증의** 대기자를 깨운다.
            # state 는 성공 경로와 같이 1회 소비한다 — 다른 인증은 영향받지 않는다.
            if self.auth_service.consume_state(state):
                self._resolve(state, error=f"OAuth error: {error}")
            else:
                logger.warning("Callback error without a pending state ignored")
            return web.Response(text=html_content, content_type='text/html', status=400)

        if not code or not state:
            missing = []
            if not code:
                missing.append("authorization code")
            if not state:
                missing.append("state")
            error_msg = f"Missing required parameter(s): {', '.join(missing)}"
            # state 가 없으면 어느 인증의 응답인지 알 수 없다 — 대기 중인 인증은 건드리지 않는다
            logger.error(f"Callback rejected - {error_msg}")
            return web.Response(text=error_msg, status=400)

        logger.info("Processing callback")

        from session.auth_service import InvalidOAuthStateError

        try:
            # Exchange code for tokens
            auth_result = await self.auth_service.complete_auth_flow(code, state)

            # complete_auth_flow는 성공 시 user_email을 직접 반환 (토큰은 반환하지 않는다)
            user_email = auth_result.get('user_email')

            if user_email:
                logger.info("[OK] Authentication successful")

                # 이 state 의 대기자에게만 완료 전달
                self._resolve(state, email=user_email)

                # Success page with auto-close script
                html_content = f"""
                <html>
                <head>
                    <title>Authentication Successful</title>
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f0f0f0; }}
                        .container {{ background: white; padding: 30px; border-radius: 10px; max-width: 600px; margin: auto; }}
                        h1 {{ color: #27ae60; }}
                        .user-info {{ background: #e8f6ef; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                        .message {{ color: #666; margin-top: 20px; }}
                    </style>
                    <script>
                        setTimeout(function() {{
                            window.close();
                        }}, 3000);
                    </script>
                </head>
                <body>
                    <div class="container">
                        <h1>[OK] Authentication Successful!</h1>
                        <div class="user-info">
                            <strong>Logged in as:</strong> {html.escape(user_email)}
                        </div>
                        <p class="message">This window will close automatically in 3 seconds...</p>
                        <p class="message">You can now return to your application.</p>
                    </div>
                </body>
                </html>
                """
                return web.Response(text=html_content, content_type='text/html')

            else:
                # Authentication failed - user_email이 없는 경우 (응답 내용은 로그에 남기지 않는다)
                error_msg = "Failed to authenticate - no user email returned"
                logger.error("Authentication failed: no user email returned")
                html_content = f"""
                <html>
                <head>
                    <title>Authentication Failed</title>
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 40px; }}
                        .error {{ color: red; }}
                    </style>
                </head>
                <body>
                    <h1>Authentication Failed</h1>
                    <p class="error">{error_msg}</p>
                    <p><a href="/">Try Again</a></p>
                </body>
                </html>
                """
                self._resolve(state, error=error_msg)
                return web.Response(text=html_content, content_type='text/html', status=401)

        except InvalidOAuthStateError:
            # 진행 중이 아닌 state — 어떤 대기자도 건드리지 않는다
            logger.error("Callback rejected - invalid or expired state")
            return web.Response(text="Invalid or expired authentication request. Please start again.", status=400)
        except Exception as e:
            # state 는 이미 검증·소비됐다 → 그 인증만 실패로 끝낸다. 예외 원문은 응답·로그에 싣지 않는다.
            logger.error("Error during callback processing: %s", type(e).__name__)
            self._resolve(state, error="Authentication failed during token exchange")
            return web.Response(text="Authentication failed. Please try again.", status=500)

    async def handle_root(self, request):
        """Root endpoint - shows server status"""
        html_content = """
        <html>
        <head>
            <title>Azure OAuth Callback Server</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f0f0f0; }
                .container { background: white; padding: 30px; border-radius: 10px; max-width: 600px; margin: auto; }
                h1 { color: #4285f4; }
                .status { background: #e8f5e9; padding: 20px; border-radius: 5px; margin: 20px 0; }
                .info { margin: 10px 0; }
                code { background: #f5f5f5; padding: 2px 5px; border-radius: 3px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>[KEY] Azure OAuth Callback Server</h1>
                <div class="status">
                    <strong>[OK] Server is running</strong>
                </div>
                <div class="info">
                    <strong>Callback URL:</strong> <code>http://localhost:5000/callback</code>
                </div>
                <div class="info">
                    <strong>Status:</strong> Ready to receive authentication callbacks
                </div>
                <p>This server handles OAuth 2.0 callbacks from Azure AD.</p>
            </div>
        </body>
        </html>
        """
        return web.Response(text=html_content, content_type='text/html')

    async def handle_status(self, request):
        """Status endpoint - returns JSON status"""
        status = {
            'status': 'running',
            'port': self.port,
            'callback_url': f'http://localhost:{self.port}/callback',
            'standalone_mode': self.standalone_mode
        }
        return web.json_response(status)

    async def init_app(self):
        """Initialize the web application"""
        self.app = web.Application()

        # Add routes
        self.app.router.add_get('/callback', self.handle_callback)
        self.app.router.add_get('/', self.handle_root)
        self.app.router.add_get('/status', self.handle_status)

        # Add cleanup handler
        self.app.on_cleanup.append(self._cleanup)

        return self.app

    async def _cleanup(self, app):
        """Cleanup on shutdown"""
        if self.standalone_mode:
            await self.auth_manager.close()
        logger.info("Server shutdown complete")

    async def start(self):
        """서버 시작"""
        if self.is_running():
            logger.warning("Server already running")
            return

        # 포트 확인
        if not self.check_port_availability():
            logger.warning(f"Port {self.port} is already in use")
            raise OSError(f"Port {self.port} is already in use")

        # 앱 초기화
        await self.init_app()

        # 서버 시작 - WSL이면 0.0.0.0, 그 외는 localhost
        bind_host = '0.0.0.0' if 'microsoft' in platform.release().lower() else 'localhost'
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, bind_host, self.port)
        await self.site.start()

        logger.info(f"Callback server started on http://{bind_host}:{self.port}")

    async def stop(self):
        """서버 종료"""
        if self.site:
            await self.site.stop()
            self.site = None
            logger.info("Server site stopped")

        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            logger.info("Server runner cleaned up")

    async def wait_for_auth(self, timeout: int = 300, state: Optional[str] = None):
        """
        인증 완료 대기

        Args:
            timeout: 대기 시간 (초)
            state: 기다릴 인증의 state (`expect(state)` 로 먼저 등록). None 이면 다음으로 **검증된**
                콜백 결과를 기다린다(legacy 호환).

        Returns:
            인증된 이메일 또는 None(시간 초과)

        Raises:
            Exception: 그 인증의 콜백에서 에러가 발생한 경우 즉시 raise
        """
        if state is not None:
            fut = self._waiters.get(state)
            if fut is None:
                self.expect(state)
                fut = self._waiters[state]
        else:
            fut = asyncio.get_running_loop().create_future()
            self._any_waiters.append(fut)
        try:
            email, error = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Authentication timeout")
            return None
        finally:
            if state is not None and self._waiters.get(state) is fut:
                del self._waiters[state]
            elif fut in self._any_waiters:
                self._any_waiters.remove(fut)
        if error:
            raise Exception(error)
        return email

    def reset_auth_event(self):
        """호환용 no-op. 대기는 state 별(`expect`)이라 초기화할 공용 상태가 없다."""
        return None


# 독립 실행을 위한 메인 함수
async def run_standalone_server():
    """독립 실행 모드로 서버 실행"""
    port = int(os.getenv('CALLBACK_PORT', '5000'))

    print("\n" + "="*60)
    print(" Azure Authentication Callback Server")
    print("="*60)
    print(f"[START] Starting server on http://localhost:{port}")
    print(f"[INFO] Callback URL: http://localhost:{port}/callback")
    print("="*60)
    print("\nPress Ctrl+C to stop the server\n")

    # 서버 생성 및 시작
    server = CallbackServer(port=port)

    try:
        await server.start()

        # 서버 유지
        while True:
            await asyncio.sleep(3600)

    except KeyboardInterrupt:
        print("\n\nShutting down server...")
    finally:
        await server.stop()
        if server.standalone_mode:
            await server.auth_manager.close()


def main():
    """Main function for standalone execution"""
    try:
        asyncio.run(run_standalone_server())
    except KeyboardInterrupt:
        print("\nServer stopped by user")


if __name__ == '__main__':
    main()