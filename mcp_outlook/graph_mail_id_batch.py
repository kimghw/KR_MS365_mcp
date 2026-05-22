"""
Graph Mail ID Batch - 메일 ID 기반 배치 조회
Microsoft Graph API의 $batch 기능을 활용하여 여러 메일을 효율적으로 조회
"""

import asyncio
import aiohttp
from typing import Dict, Any, List, Optional

import sys
import os
from typing import TYPE_CHECKING

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol

from .outlook_types import SelectParams, build_select_query


class GraphMailIdBatch:
    """
    메일 ID 기반 배치 조회 클래스

    Microsoft Graph API의 $batch 엔드포인트를 사용하여
    여러 메일 ID를 효율적으로 조회
    """

    def __init__(self, token_provider: Optional["TokenProviderProtocol"] = None):
        """
        초기화

        Args:
            token_provider: 토큰 제공자 (None이면 기본 AuthManager 사용)
        """
        if token_provider is None:
            # 공유 AuthManager 싱글톤 사용 (per-email refresh lock 공유)
            from session.auth_manager import get_default_auth_manager
            token_provider = get_default_auth_manager()
        self.token_provider = token_provider
        self.batch_url = "https://graph.microsoft.com/v1.0/$batch"
        self.max_batch_size = 20  # Microsoft Graph API 제한

    async def initialize(self) -> bool:
        """
        초기화 (AuthManager는 이미 초기화됨)

        Returns:
            초기화 성공 여부
        """
        return True

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        """
        액세스 토큰 획득

        Args:
            user_email: 사용자 이메일

        Returns:
            액세스 토큰 또는 None
        """
        try:
            access_token = await self.token_provider.validate_and_refresh_token(user_email)

            if not access_token:
                print(f"Failed to get access token for {user_email}")

            return access_token

        except Exception as e:
            print(f"Token retrieval error for {user_email}: {str(e)}")
            return None

    def _split_into_batches(self, items: List[Any], batch_size: int) -> List[List[Any]]:
        """
        리스트를 배치로 분할

        Args:
            items: 분할할 리스트
            batch_size: 배치 크기

        Returns:
            배치 리스트
        """
        return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    def _build_select_fields(self, select_params: Optional[SelectParams]) -> Optional[str]:
        """
        SelectParams를 $select 쿼리 문자열로 변환

        Args:
            select_params: 선택 필드 파라미터

        Returns:
            $select 쿼리 문자열 또는 None
        """
        if not select_params:
            return None

        # SelectParams가 딕셔너리인 경우
        if isinstance(select_params, dict):
            fields = [field for field, include in select_params.items() if include]
            return ",".join(fields) if fields else None

        # SelectParams가 객체인 경우 (build_select_query 사용)
        return build_select_query(select_params)

    async def fetch_single_by_id(
        self, user_email: str, message_id: str, select_params: Optional[SelectParams] = None
    ) -> Dict[str, Any]:
        """
        단일 메일 ID로 조회

        Args:
            user_email: 사용자 이메일
            message_id: 메일 ID
            select_params: 선택할 필드

        Returns:
            메일 데이터 또는 에러
        """
        # 액세스 토큰 획득
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": f"Failed to get access token for {user_email}"}

        # URL 구성
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages/{message_id}"

        # 선택 필드 추가
        select_fields = self._build_select_fields(select_params)
        if select_fields:
            url += f"?$select={select_fields}"

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {"success": True, "mail": data}
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Failed to fetch mail: {response.status}",
                            "details": error_text[:500],
                        }

        except Exception as e:
            return {"success": False, "error": f"Request failed: {str(e)}"}

    async def batch_fetch_by_ids(
        self, user_email: str, message_ids: List[str], select_params: Optional[SelectParams] = None
    ) -> Dict[str, Any]:
        """
        여러 메일 ID로 배치 조회

        Args:
            user_email: 사용자 이메일
            message_ids: 메일 ID 리스트
            select_params: 선택할 필드

        Returns:
            배치 조회 결과
        """
        if not message_ids:
            return {"success": True, "value": [], "total": 0, "message": "No message IDs provided"}

        # 액세스 토큰 획득
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": f"Failed to get access token for {user_email}", "value": []}

        # 20개씩 배치로 분할
        batches = self._split_into_batches(message_ids, self.max_batch_size)

        print(f"Processing {len(message_ids)} mail IDs in {len(batches)} batch(es)")

        # 선택 필드 준비
        select_fields = self._build_select_fields(select_params)
        select_query = f"?$select={select_fields}" if select_fields else ""

        all_results = []
        errors = []

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        # 각 배치 처리
        async with aiohttp.ClientSession() as session:
            for batch_num, batch_ids in enumerate(batches, 1):
                print(f"  Processing batch {batch_num}/{len(batches)} ({len(batch_ids)} mails)...")

                # 배치 요청 본문 생성
                requests = []
                for i, mail_id in enumerate(batch_ids):
                    requests.append(
                        {
                            "id": str(i + 1),
                            "method": "GET",
                            "url": f"/users/{user_email}/messages/{mail_id}{select_query}",
                        }
                    )

                batch_body = {"requests": requests}

                try:
                    # $batch API 호출
                    async with session.post(self.batch_url, headers=headers, json=batch_body) as response:
                        if response.status == 200:
                            batch_data = await response.json()
                            responses = batch_data.get("responses", [])

                            # 각 응답 처리
                            for resp in responses:
                                if resp.get("status") == 200:
                                    mail_data = resp.get("body", {})
                                    all_results.append(mail_data)
                                else:
                                    # 에러 처리
                                    req_id = resp.get("id")
                                    mail_id = batch_ids[int(req_id) - 1] if req_id else "unknown"
                                    errors.append(
                                        {
                                            "mail_id": mail_id,
                                            "status": resp.get("status"),
                                            "error": resp.get("body", {})
                                            .get("error", {})
                                            .get("message", "Unknown error"),
                                        }
                                    )

                            success_count = len([r for r in responses if r.get("status") == 200])
                            fail_count = len([r for r in responses if r.get("status") != 200])
                            print(f"    Batch {batch_num}: {success_count} successful, {fail_count} failed")
                        else:
                            error_text = await response.text()
                            print(f"    Batch {batch_num}: Request failed with status {response.status}")
                            errors.append({"batch": batch_num, "status": response.status, "error": error_text[:500]})

                except Exception as e:
                    print(f"    Batch {batch_num}: Exception - {str(e)}")
                    errors.append({"batch": batch_num, "error": str(e)})

        # 결과 정리
        success_count = len(all_results)
        total_count = len(message_ids)

        print(f"Fetched {success_count}/{total_count} mails successfully")

        return {
            "success": success_count > 0,
            "value": all_results,
            "total": success_count,
            "requested": total_count,
            "errors": errors if errors else None,
            "query_method": "batch_id",
            "batches_processed": len(batches),
        }

    async def batch_fetch_with_details(
        self, user_email: str, message_ids: List[str], include_attachments: bool = False, include_headers: bool = False
    ) -> Dict[str, Any]:
        """
        상세 정보를 포함한 배치 조회

        Args:
            user_email: 사용자 이메일
            message_ids: 메일 ID 리스트
            include_attachments: 첨부파일 정보 포함 여부
            include_headers: 헤더 정보 포함 여부

        Returns:
            상세 메일 데이터
        """
        # 기본 필드 + 추가 필드
        select_params = SelectParams(
            id=True,
            subject=True,
            from_=True,
            to=True,
            cc=True,
            bcc=True,
            receivedDateTime=True,
            sentDateTime=True,
            body=True,
            bodyPreview=True,
            hasAttachments=True,
            importance=True,
            isRead=True,
            isDraft=True,
            conversationId=True,
            categories=True,
        )

        # 추가 필드
        if include_headers:
            select_params.internetMessageHeaders = True

        # 기본 조회
        result = await self.batch_fetch_by_ids(user_email, message_ids, select_params)

        # 첨부파일 정보 추가 조회 (필요시)
        if include_attachments and result.get("success"):
            mails = result.get("value", [])

            for mail in mails:
                if mail.get("hasAttachments"):
                    # 첨부파일 정보는 별도 조회 필요
                    mail["attachments_info"] = "Use attachment handler for details"

        return result

    async def batch_delete_by_ids(
        self, user_email: str, message_ids: List[str]
    ) -> Dict[str, Any]:
        """
        여러 메일을 휴지통(Deleted Items)으로 이동

        Graph API DELETE /users/{email}/messages/{id} 를 $batch로 실행.
        DELETE는 메일을 Deleted Items 폴더로 이동시킨다 (영구 삭제 아님).

        Args:
            user_email: 사용자 이메일
            message_ids: 삭제할 메일 ID 리스트

        Returns:
            삭제 결과 (성공/실패 건수 포함)
        """
        if not message_ids:
            return {"success": True, "deleted": 0, "failed": 0, "total": 0, "message": "No message IDs provided"}

        # 액세스 토큰 획득
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": f"Failed to get access token for {user_email}"}

        # 20개씩 배치로 분할
        batches = self._split_into_batches(message_ids, self.max_batch_size)

        print(f"[DELETE] Deleting {len(message_ids)} mail(s) in {len(batches)} batch(es)")

        deleted_ids = []
        failed_items = []

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            for batch_num, batch_ids in enumerate(batches, 1):
                print(f"  Processing batch {batch_num}/{len(batches)} ({len(batch_ids)} mails)...")

                # DELETE 배치 요청 생성
                requests = []
                for i, mail_id in enumerate(batch_ids):
                    requests.append(
                        {
                            "id": str(i + 1),
                            "method": "DELETE",
                            "url": f"/users/{user_email}/messages/{mail_id}",
                        }
                    )

                batch_body = {"requests": requests}

                try:
                    async with session.post(self.batch_url, headers=headers, json=batch_body) as response:
                        if response.status == 200:
                            batch_data = await response.json()
                            responses = batch_data.get("responses", [])

                            for resp in responses:
                                req_id = resp.get("id")
                                mail_id = batch_ids[int(req_id) - 1] if req_id else "unknown"

                                if resp.get("status") == 204:
                                    deleted_ids.append(mail_id)
                                else:
                                    error_msg = (
                                        resp.get("body", {})
                                        .get("error", {})
                                        .get("message", "Unknown error")
                                    )
                                    failed_items.append(
                                        {"mail_id": mail_id, "status": resp.get("status"), "error": error_msg}
                                    )

                            success_count = len([r for r in responses if r.get("status") == 204])
                            fail_count = len(responses) - success_count
                            print(f"    Batch {batch_num}: {success_count} deleted, {fail_count} failed")
                        else:
                            error_text = await response.text()
                            print(f"    Batch {batch_num}: Request failed with status {response.status}")
                            for mail_id in batch_ids:
                                failed_items.append(
                                    {"mail_id": mail_id, "status": response.status, "error": error_text[:200]}
                                )

                except Exception as e:
                    print(f"    Batch {batch_num}: Exception - {str(e)}")
                    for mail_id in batch_ids:
                        failed_items.append({"mail_id": mail_id, "error": str(e)})

        print(f"[DONE] Deleted {len(deleted_ids)}/{len(message_ids)} mails")

        return {
            "success": len(deleted_ids) > 0,
            "deleted": len(deleted_ids),
            "failed": len(failed_items),
            "total": len(message_ids),
            "deleted_ids": deleted_ids,
            "failed_items": failed_items if failed_items else None,
            "batches_processed": len(batches),
        }

    async def batch_report_not_junk_by_ids(
        self, user_email: str, message_ids: List[str]
    ) -> Dict[str, Any]:
        """
        여러 메일을 '정크 아님'으로 신고하여 Safe Senders에 등록

        Graph API POST /users/{email}/messages/{id}/reportMessage (beta)
        body: {"reportAction": "notJunk"}

        Beta API를 사용하므로 batch URL이 beta 엔드포인트로 전환됨.

        Args:
            user_email: 사용자 이메일
            message_ids: 신고할 메일 ID 리스트

        Returns:
            신고 결과 (성공/실패 건수 포함)
        """
        if not message_ids:
            return {"success": True, "reported": 0, "failed": 0, "total": 0, "message": "No message IDs provided"}

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": f"Failed to get access token for {user_email}"}

        batches = self._split_into_batches(message_ids, self.max_batch_size)
        beta_batch_url = "https://graph.microsoft.com/beta/$batch"

        print(f"[REPORT] Reporting {len(message_ids)} mail(s) as notJunk in {len(batches)} batch(es)")

        reported_ids = []
        failed_items = []

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            for batch_num, batch_ids in enumerate(batches, 1):
                print(f"  Processing batch {batch_num}/{len(batches)} ({len(batch_ids)} mails)...")

                requests = []
                for i, mail_id in enumerate(batch_ids):
                    requests.append(
                        {
                            "id": str(i + 1),
                            "method": "POST",
                            "url": f"/users/{user_email}/messages/{mail_id}/reportMessage",
                            "headers": {"Content-Type": "application/json"},
                            "body": {"reportAction": "notJunk"},
                        }
                    )

                batch_body = {"requests": requests}

                try:
                    async with session.post(beta_batch_url, headers=headers, json=batch_body) as response:
                        if response.status == 200:
                            batch_data = await response.json()
                            responses = batch_data.get("responses", [])

                            for resp in responses:
                                req_id = resp.get("id")
                                mail_id = batch_ids[int(req_id) - 1] if req_id else "unknown"
                                status_code = resp.get("status")

                                # reportMessage 성공: 202 (Accepted) 또는 204 (No Content)
                                if status_code in (200, 202, 204):
                                    reported_ids.append(mail_id)
                                else:
                                    error_msg = (
                                        resp.get("body", {})
                                        .get("error", {})
                                        .get("message", "Unknown error")
                                    )
                                    failed_items.append(
                                        {"mail_id": mail_id, "status": status_code, "error": error_msg}
                                    )

                            success_count = len([r for r in responses if r.get("status") in (200, 202, 204)])
                            fail_count = len(responses) - success_count
                            print(f"    Batch {batch_num}: {success_count} reported, {fail_count} failed")
                        else:
                            error_text = await response.text()
                            print(f"    Batch {batch_num}: Request failed with status {response.status}")
                            for mail_id in batch_ids:
                                failed_items.append(
                                    {"mail_id": mail_id, "status": response.status, "error": error_text[:200]}
                                )

                except Exception as e:
                    print(f"    Batch {batch_num}: Exception - {str(e)}")
                    for mail_id in batch_ids:
                        failed_items.append({"mail_id": mail_id, "error": str(e)})

        print(f"[DONE] Reported {len(reported_ids)}/{len(message_ids)} mails as notJunk")

        return {
            "success": len(reported_ids) > 0,
            "reported": len(reported_ids),
            "failed": len(failed_items),
            "total": len(message_ids),
            "reported_ids": reported_ids,
            "failed_items": failed_items if failed_items else None,
            "batches_processed": len(batches),
        }

    async def batch_move_by_ids(
        self, user_email: str, message_ids: List[str], destination_id: str = "inbox"
    ) -> Dict[str, Any]:
        """
        여러 메일을 지정 폴더로 이동

        Graph API POST /users/{email}/messages/{id}/move 를 $batch로 실행.
        well-known folder name 사용 가능: inbox, junkemail, deleteditems, drafts, sentitems 등.

        Args:
            user_email: 사용자 이메일
            message_ids: 이동할 메일 ID 리스트
            destination_id: 이동할 폴더 ID 또는 well-known name (기본 "inbox")

        Returns:
            이동 결과 (성공/실패 건수 포함)
        """
        if not message_ids:
            return {"success": True, "moved": 0, "failed": 0, "total": 0, "message": "No message IDs provided"}

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": f"Failed to get access token for {user_email}"}

        batches = self._split_into_batches(message_ids, self.max_batch_size)

        print(f"[MOVE] Moving {len(message_ids)} mail(s) to '{destination_id}' in {len(batches)} batch(es)")

        moved_ids = []
        failed_items = []

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            for batch_num, batch_ids in enumerate(batches, 1):
                print(f"  Processing batch {batch_num}/{len(batches)} ({len(batch_ids)} mails)...")

                requests = []
                for i, mail_id in enumerate(batch_ids):
                    requests.append(
                        {
                            "id": str(i + 1),
                            "method": "POST",
                            "url": f"/users/{user_email}/messages/{mail_id}/move",
                            "headers": {"Content-Type": "application/json"},
                            "body": {"destinationId": destination_id},
                        }
                    )

                batch_body = {"requests": requests}

                try:
                    async with session.post(self.batch_url, headers=headers, json=batch_body) as response:
                        if response.status == 200:
                            batch_data = await response.json()
                            responses = batch_data.get("responses", [])

                            for resp in responses:
                                req_id = resp.get("id")
                                mail_id = batch_ids[int(req_id) - 1] if req_id else "unknown"

                                if resp.get("status") == 201:
                                    moved_ids.append(mail_id)
                                else:
                                    error_msg = (
                                        resp.get("body", {})
                                        .get("error", {})
                                        .get("message", "Unknown error")
                                    )
                                    failed_items.append(
                                        {"mail_id": mail_id, "status": resp.get("status"), "error": error_msg}
                                    )

                            success_count = len([r for r in responses if r.get("status") == 201])
                            fail_count = len(responses) - success_count
                            print(f"    Batch {batch_num}: {success_count} moved, {fail_count} failed")
                        else:
                            error_text = await response.text()
                            print(f"    Batch {batch_num}: Request failed with status {response.status}")
                            for mail_id in batch_ids:
                                failed_items.append(
                                    {"mail_id": mail_id, "status": response.status, "error": error_text[:200]}
                                )

                except Exception as e:
                    print(f"    Batch {batch_num}: Exception - {str(e)}")
                    for mail_id in batch_ids:
                        failed_items.append({"mail_id": mail_id, "error": str(e)})

        print(f"[DONE] Moved {len(moved_ids)}/{len(message_ids)} mails to '{destination_id}'")

        return {
            "success": len(moved_ids) > 0,
            "moved": len(moved_ids),
            "failed": len(failed_items),
            "total": len(message_ids),
            "moved_ids": moved_ids,
            "failed_items": failed_items if failed_items else None,
            "batches_processed": len(batches),
            "destination": destination_id,
        }

    async def close(self):
        """리소스 정리"""
        await self.token_provider.close()


# 테스트 코드
if __name__ == "__main__":

    async def test_batch():
        batch_client = GraphMailIdBatch()

        # 초기화
        if not await batch_client.initialize():
            print("Failed to initialize")
            return

        user_email = "kimghw@krs.co.kr"

        # 테스트용 메일 ID (실제 테스트시 실제 ID로 변경 필요)
        test_ids = [
            "AAMkADU2MGM5YzRjLTE4NmItNDE4NC1hMGI3LTk1NDkwZjY2NGY4ZQBGAAAA...",
            "AAMkADU2MGM5YzRjLTE4NmItNDE4NC1hMGI3LTk1NDkwZjY2NGY4ZQBGAAAA...",
        ]

        # 배치 조회 테스트
        print("\n=== Batch Fetch Test ===")
        result = await batch_client.batch_fetch_by_ids(
            user_email=user_email,
            message_ids=test_ids,
            select_params=SelectParams(subject=True, from_=True, receivedDateTime=True),
        )

        if result.get("success"):
            print(f"Success! Fetched {result.get('total')} mails")
            for mail in result.get("value", [])[:3]:
                print(f"  - {mail.get('subject', 'No subject')}")
        else:
            print(f"Failed: {result.get('error')}")

        await batch_client.close()

    # 실행
    asyncio.run(test_batch())
