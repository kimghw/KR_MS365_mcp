"""임시 재인증 스크립트"""
import asyncio
from session.auth_manager import AuthManager

async def main():
    am = AuthManager()
    try:
        result = await am.authenticate_with_browser(timeout=300, port=5000)
        print(result)
    finally:
        await am.close()

asyncio.run(main())
