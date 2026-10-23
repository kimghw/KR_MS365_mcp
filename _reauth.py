"""임시 재인증 스크립트 (단일 운영자 mode 0 전용).

멀티유저 모드에서는 서버가 브라우저 인증을 대신하지 않는다 — `python -m session.auth_gateway` 와
사용자별 연결 링크를 쓴다. 결과에서 토큰은 출력하지 않는다.
"""
import asyncio
import sys


async def main():
    from mcp_common.security_policy import multi_user_enabled

    if multi_user_enabled():
        print("멀티유저 모드(MS365_MULTI_USER=1)에서는 _reauth.py 를 쓸 수 없습니다. "
              "python -m session.auth_gateway 의 연결 링크를 사용하세요.", file=sys.stderr)
        return 2
    from session.auth_manager import AuthManager

    am = AuthManager()
    try:
        result = await am.authenticate_with_browser(timeout=300, port=5000)
        print({k: v for k, v in result.items() if k in ("status", "email", "error")})
    finally:
        await am.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
