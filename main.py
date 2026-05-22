"""
Azure Authentication Module - Main Entry Point
Azure AD 인증 모듈의 메인 실행 파일입니다.
"""

import asyncio
import os
from dotenv import load_dotenv
from session import AuthManager
import logging

# Load environment variables (프로젝트 루트 기준)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_env_path, encoding="utf-8-sig")

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """메인 함수 - 통합된 인증 플로우"""

    # Initialize auth manager
    auth_manager = AuthManager()

    try:
        # 기존 인증된 사용자 확인
        users = auth_manager.list_users()
        if users:
            print("\n" + "="*60)
            print("Authenticated Users")
            print("="*60)
            for user in users:
                status = "[OK] Active" if not user.get('token_expired', True) else "[FAIL] Expired"
                print(f"{user['email']}: {status}")
            print("="*60)

            response = input("\nAdd another account? (y/n): ").lower()
            if response != 'y':
                print("Using existing authentication.")
                return

        # 통합된 인증 플로우 실행 (콜백 서버 포함)
        print("\n" + "="*60)
        print("Azure AD Authentication")
        print("="*60)
        print("\nStarting authentication flow with integrated callback server...")
        print("Browser will open automatically.")
        print("This window will close after successful authentication.")
        print("="*60)

        # AuthManager가 모든 것을 처리
        result = await auth_manager.authenticate_with_browser()

        if result['status'] == 'success':
            print("\n" + "="*60)
            print("[OK] Authentication Successful!")
            print("="*60)
            print(f"Authenticated as: {result['email']}")
            user = result.get('user', {})
            if user.get('display_name'):
                print(f"Name: {user['display_name']}")
            if user.get('job_title'):
                print(f"Job Title: {user['job_title']}")
            print("="*60)
        elif result['status'] == 'timeout':
            print("\n[WARN] Authentication timeout. Please try again.")
        else:
            print(f"\n[ERROR] Authentication failed: {result.get('error', 'Unknown error')}")

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        print(f"\n[ERROR] Error: {str(e)}")

    finally:
        # Close the auth manager (콜백 서버도 자동 정리)
        await auth_manager.close()


if __name__ == "__main__":
    asyncio.run(main())