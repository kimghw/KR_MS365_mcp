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
        """페이지 삭제 + DB/요약 삭제"""
        result = await self._client.delete_page(page_id, user_email)

        if result.get("success") and self._db_service:
            self._db_service.delete_item(user_id=user_email, item_id=page_id)
            self._db_service.delete_summary(page_id=page_id)
            result["deleted_page_id"] = page_id

        return result
