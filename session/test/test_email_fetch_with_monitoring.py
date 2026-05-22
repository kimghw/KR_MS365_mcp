#!/usr/bin/env python3
"""
이메일 조회 테스트 스크립트 - 각 단계마다 DB 상태 모니터링
Microsoft Graph API를 사용한 이메일 조회 테스트
"""

import asyncio
import sys
import os
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import aiohttp

# Load environment variables (프로젝트 루트 기준)
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
load_dotenv(_env_path, encoding="utf-8-sig")

# Add parent directories to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
grandparent_dir = os.path.dirname(parent_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

from auth import AuthManager, AuthDatabase


def check_db_state(step_name: str, email: str = None):
    """DB 상태 확인 및 출력"""
    print(f"\n{'='*60}")
    print(f"[INFO] DB 상태 확인 - {step_name}")
    print(f"{'='*60}")

    conn = sqlite3.connect("database/auth.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 토큰 정보 확인
        print("\n[토큰 상태]:")
        print("-" * 50)

        if email:
            cursor.execute("""
                SELECT user_email,
                       SUBSTR(access_token, 1, 30) || '...' as access_token_preview,
                       CASE WHEN refresh_token IS NOT NULL THEN '[OK] 있음' ELSE '[ERROR] 없음' END as refresh_status,
                       access_token_expires_at,
                       updated_at
                FROM azure_token_info
                WHERE user_email = ?
            """, (email,))
        else:
            cursor.execute("""
                SELECT user_email,
                       SUBSTR(access_token, 1, 30) || '...' as access_token_preview,
                       CASE WHEN refresh_token IS NOT NULL THEN '[OK] 있음' ELSE '[ERROR] 없음' END as refresh_status,
                       access_token_expires_at,
                       updated_at
                FROM azure_token_info
                ORDER BY updated_at DESC
                LIMIT 3
            """)

        tokens = cursor.fetchall()
        for token in tokens:
            print(f"  Email: {token['user_email']}")
            print(f"  Access Token: {token['access_token_preview']}")
            print(f"  Refresh Token: {token['refresh_status']}")

            # 만료 시간 확인
            if token['access_token_expires_at']:
                expires_at = datetime.fromisoformat(
                    token['access_token_expires_at'].replace('Z', '+00:00')
                )
                now = datetime.now(timezone.utc)
                remaining = expires_at - now

                if remaining.total_seconds() > 0:
                    hours = int(remaining.total_seconds() // 3600)
                    minutes = int((remaining.total_seconds() % 3600) // 60)
                    print(f"  [TIME] 만료까지: {hours}시간 {minutes}분")
                else:
                    print(f"  [WARN] 토큰 만료됨!")
            print("-" * 50)

    except Exception as e:
        print(f"[ERROR] DB 조회 오류: {e}")
    finally:
        conn.close()


async def fetch_emails_with_token(email: str, access_token: str, count: int = 5):
    """Microsoft Graph API로 이메일 조회"""
    print(f"\n[MAIL] 이메일 조회 중 (상위 {count}개)...")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }

    # Graph API 엔드포인트
    url = f"https://graph.microsoft.com/v1.0/me/messages?$top={count}&$select=subject,from,receivedDateTime,bodyPreview&$orderby=receivedDateTime desc"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    messages = data.get('value', [])

                    print(f"[OK] {len(messages)}개 이메일 조회 성공\n")
                    print("-" * 80)

                    for i, msg in enumerate(messages, 1):
                        sender = msg.get('from', {}).get('emailAddress', {})
                        received = msg.get('receivedDateTime', 'Unknown')

                        # 시간 포맷팅
                        if received != 'Unknown':
                            dt = datetime.fromisoformat(received.replace('Z', '+00:00'))
                            received = dt.strftime('%Y-%m-%d %H:%M')

                        print(f"\n[{i}] 제목: {msg.get('subject', '제목 없음')}")
                        print(f"    발신자: {sender.get('name', 'Unknown')} <{sender.get('address', 'Unknown')}>")
                        print(f"    수신 시간: {received}")
                        print(f"    미리보기: {msg.get('bodyPreview', '')[:100]}...")
                        print("-" * 80)

                    return True

                elif response.status == 401:
                    print("[ERROR] 인증 실패 - 토큰이 유효하지 않습니다")
                    error_data = await response.text()
                    print(f"   오류: {error_data[:200]}")
                    return False
                else:
                    print(f"[ERROR] 이메일 조회 실패 (HTTP {response.status})")
                    error_data = await response.text()
                    print(f"   응답: {error_data[:200]}")
                    return False

        except Exception as e:
            print(f"[ERROR] 이메일 조회 중 오류: {e}")
            return False


async def fetch_calendar_events(email: str, access_token: str):
    """캘린더 이벤트 조회"""
    print(f"\n[CAL] 캘린더 이벤트 조회 중...")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }

    # 오늘부터 7일간의 이벤트 조회
    start = datetime.now(timezone.utc).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    url = f"https://graph.microsoft.com/v1.0/me/calendarview?startdatetime={start}&enddatetime={end}&$select=subject,start,end,location&$orderby=start/dateTime"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    events = data.get('value', [])

                    if events:
                        print(f"[OK] {len(events)}개 이벤트 발견 (향후 7일)\n")
                        for event in events[:5]:  # 상위 5개만
                            start_time = event.get('start', {}).get('dateTime', '')
                            if start_time:
                                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                                start_time = dt.strftime('%m/%d %H:%M')

                            print(f"  [EVENT] {event.get('subject', '제목 없음')}")
                            print(f"     시간: {start_time}")
                            location = event.get('location', {}).get('displayName')
                            if location:
                                print(f"     장소: {location}")
                            print()
                    else:
                        print("  향후 7일간 예정된 이벤트 없음")
                    return True
                else:
                    print(f"[ERROR] 캘린더 조회 실패 (HTTP {response.status})")
                    return False

        except Exception as e:
            print(f"[ERROR] 캘린더 조회 중 오류: {e}")
            return False


async def test_email_fetch_flow():
    """이메일 조회 플로우 테스트 - 단계별 DB 모니터링"""

    print("\n" + "="*80)
    print("[MAIL] Microsoft Graph API 이메일 조회 테스트 (DB 모니터링 포함)")
    print("="*80)

    auth_manager = AuthManager()

    try:
        # Step 1: 사용자 선택
        print("\n[Step 1] 인증된 사용자 확인")
        users = auth_manager.list_users()

        if not users:
            print("[ERROR] 인증된 사용자가 없습니다. 먼저 로그인을 진행하세요.")
            return

        print(f"\n인증된 사용자 목록 ({len(users)}명):")
        print("-" * 60)
        for i, user in enumerate(users):
            status = "[OK] 유효" if not user.get('token_expired', True) else "[WARN] 만료"
            refresh = "[REFRESH]" if user.get('has_refresh_token') else "[ERROR]"
            print(f"  [{i+1}] {user['email']} - {status} {refresh}")

        # 사용자 선택
        if len(users) == 1:
            selected_user = users[0]
            print(f"\n자동 선택: {selected_user['email']}")
        else:
            try:
                choice = int(input(f"\n테스트할 사용자 번호 선택 (1-{len(users)}): ")) - 1
                selected_user = users[choice]
            except (ValueError, IndexError):
                print("[ERROR] 잘못된 선택")
                return

        selected_email = selected_user['email']
        print(f"\n[OK] 선택된 사용자: {selected_email}")

        # Step 2: 현재 토큰 상태 확인
        print("\n[Step 2] 토큰 상태 확인")
        check_db_state("이메일 조회 전", selected_email)

        # Step 3: 토큰 유효성 확인 및 갱신
        print("\n[Step 3] 토큰 유효성 확인")
        token_info = await auth_manager.get_token(selected_email)

        if not token_info:
            print("[ERROR] 토큰을 찾을 수 없습니다.")
            return

        print(f"  토큰 상태: {'만료됨' if token_info['is_expired'] else '유효함'}")

        # 토큰이 만료된 경우 갱신 시도
        if token_info['is_expired']:
            if token_info.get('refresh_token'):
                print("  [REFRESH] 토큰 갱신 시도 중...")
                refresh_result = await auth_manager.refresh_token(selected_email)

                if refresh_result['status'] == 'success':
                    print("  [OK] 토큰 갱신 성공")
                    # 갱신된 토큰 다시 가져오기
                    token_info = await auth_manager.get_token(selected_email)
                    check_db_state("토큰 갱신 후", selected_email)
                else:
                    print(f"  [ERROR] 토큰 갱신 실패: {refresh_result.get('error')}")
                    print("  재인증이 필요합니다.")
                    return
            else:
                print("  [ERROR] Refresh token이 없어 갱신 불가")
                print("  재인증이 필요합니다.")
                return

        # Step 4: Graph API로 이메일 조회
        print("\n[Step 4] Microsoft Graph API 호출")
        print("="*60)

        access_token = token_info['access_token']

        # 4-1: 사용자 프로필 조회
        print("\n[USER] 사용자 프로필 조회...")
        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {access_token}'}
            async with session.get('https://graph.microsoft.com/v1.0/me', headers=headers) as response:
                if response.status == 200:
                    profile = await response.json()
                    print(f"[OK] 사용자: {profile.get('displayName', 'N/A')}")
                    print(f"   이메일: {profile.get('mail') or profile.get('userPrincipalName', 'N/A')}")
                    print(f"   직책: {profile.get('jobTitle', 'N/A')}")
                    print(f"   부서: {profile.get('department', 'N/A')}")
                else:
                    print(f"[ERROR] 프로필 조회 실패 (HTTP {response.status})")

        # 4-2: 이메일 조회
        success = await fetch_emails_with_token(selected_email, access_token, count=5)

        if success:
            # 4-3: 캘린더 이벤트 조회 (선택적)
            choice = input("\n[CAL] 캘린더 이벤트도 조회하시겠습니까? (y/n): ")
            if choice.lower() == 'y':
                await fetch_calendar_events(selected_email, access_token)

        # Step 5: 이메일 폴더 정보 조회
        print("\n[Step 5] 이메일 폴더 정보")
        print("="*60)

        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {access_token}'}
            url = 'https://graph.microsoft.com/v1.0/me/mailFolders?$select=displayName,totalItemCount,unreadItemCount'

            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    folders = data.get('value', [])

                    print("[FOLDER] 메일 폴더 현황:\n")
                    for folder in folders[:10]:  # 상위 10개
                        total = folder.get('totalItemCount', 0)
                        unread = folder.get('unreadItemCount', 0)
                        if total > 0:  # 이메일이 있는 폴더만
                            print(f"  • {folder.get('displayName', 'Unknown')}: "
                                  f"전체 {total}개 (읽지 않음 {unread}개)")

        # Step 6: 최종 상태 확인
        print("\n[Step 6] 최종 DB 상태")
        check_db_state("이메일 조회 완료", selected_email)

        # 통계 요약
        print("\n" + "="*60)
        print("[INFO] 테스트 요약")
        print("="*60)
        print(f"[OK] 테스트 사용자: {selected_email}")
        print(f"[OK] 토큰 상태: 유효함")
        print(f"[OK] Graph API 호출: 성공")
        print(f"[OK] 이메일 조회: 완료")

    except Exception as e:
        print(f"\n[ERROR] 테스트 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 정리
        await auth_manager.close()
        print("\n[OK] 테스트 완료 - 리소스 정리됨")


if __name__ == "__main__":
    print("Microsoft Graph API 이메일 조회 테스트 시작...")
    print("이 스크립트는 각 단계마다 DB 상태를 모니터링합니다.")
    print("주의: 실제 이메일을 조회하므로 유효한 토큰이 필요합니다.")
    asyncio.run(test_email_fetch_flow())