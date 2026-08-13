"""
OneNote Delete - 삭제 작업 담당

통합: onenote_page.py (OneNotePageManager)의 delete_page 로직 포함
"""

import logging
from typing import Dict, Any

from .graph_onenote_client import GraphOneNoteClient
from .onenote_db_service import OneNoteDBService

logger = logging.getLogger(__name__)


class OneNoteDeleter:
    """
    OneNote 삭제 전담

    - delete_page: 페이지 삭제 (Graph API + DB + 요약 캐시)
    """

    def __init__(
        self,
        client: GraphOneNoteClient,
        db_service: OneNoteDBService,
    ):
        self._client = client
        self._db_service = db_service

    async def delete_page(
        self,
        user_email: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """페이지 삭제 + DB/요약 삭제

        Graph 가 404 를 주면 그 페이지는 이미 없는 것이므로 실패로 두지 않고
        DB 행만 걷어낸다. 그렇게 하지 않으면 삭제된 페이지가 목록에는 계속
        뜨면서 개별 조회·삭제만 404 인 상태로 영구히 남는다(실제 발생함).
        """
        result = await self._client.delete_page(page_id, user_email)

        if not self._db_service:
            return result

        if result.get("success"):
            self._db_service.delete_item(user_id=user_email, item_id=page_id)
            self._db_service.delete_summary(page_id=page_id)
            result["deleted_page_id"] = page_id
            return result

        if result.get("status_code") == 404:
            purged = self._db_service.delete_item(user_id=user_email, item_id=page_id)
            self._db_service.delete_summary(page_id=page_id)
            logger.info(f"이미 삭제된 페이지의 DB 잔재 정리: {page_id} (행 삭제={purged})")
            return {
                "success": True,
                "already_deleted": True,
                "deleted_page_id": page_id,
                "db_row_purged": purged,
                "message": "페이지가 이미 존재하지 않아 DB 기록만 정리했습니다.",
            }

        return result
