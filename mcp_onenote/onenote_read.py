"""
OneNote Read - 모든 조회 작업 담당
action에 따라 list_pages, list_sections, search, get_content, get_summary 분기

통합: onenote_db_query.py (OneNoteDBQuery)의 조회 로직 포함
- find_section_by_name, find_page_by_name
- get_recent_items
- get_page_history, get_user_history
"""

import logging
from typing import Dict, Any, Optional

from .graph_onenote_client import GraphOneNoteClient
from .onenote_db_service import OneNoteDBService
from .onenote_types import ReadAction

logger = logging.getLogger(__name__)


class OneNoteReader:
    """
    OneNote 조회 전담

    MCP 툴 action:
    - list_pages: DB에서 페이지 목록 조회 (비어있으면 sync_db 후 재조회)
    - list_sections: Graph API로 섹션 목록 조회
    - search: 키워드 기반 페이지 검색 (AI)
    - get_content: 특정 페이지 본문 조회
    - get_summary: 특정 페이지 요약 조회

    DB 조회 (구 OneNoteDBQuery 통합):
    - get_recent_items: 최근 접근 아이템 조회
    - find_section_by_name / find_page_by_name: 이름 검색
    - get_page_history / get_user_history: 변경 이력 조회
    """

    def __init__(
        self,
        client: GraphOneNoteClient,
        db_service: OneNoteDBService,
        agent=None,
        writer=None,
    ):
        self._client = client
        self._db_service = db_service
        self._agent = agent
        self._writer = writer  # sync_db 호출용

    # ========================================================================
    # MCP 툴 action 메서드
    # ========================================================================

    async def list_pages(
        self,
        user_email: str,
        section_id: Optional[str] = None,
        notebook_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        top: int = 50,
    ) -> Dict[str, Any]:
        """
        페이지 목록 조회 (DB 기반, 비어있으면 sync 후 재조회)

        Args:
            date_from: 시작 날짜 (포함, last_accessed >= 이 값, ISO 8601 형식)
                       예: "2024-12-01T00:00:00Z"
            date_to: 종료 날짜 (포함, last_accessed <= 이 값, ISO 8601 형식)
                     예: "2024-12-31T23:59:59Z"
        """
        items = self._db_service.list_items(
            user_id=user_email,
            item_type="page",
            section_id=section_id,
        )

        # DB가 비어있으면 sync 후 재조회
        if not items and self._writer:
            await self._writer.sync_db(user_email)
            items = self._db_service.list_items(
                user_id=user_email,
                item_type="page",
                section_id=section_id,
            )

        # notebook_id 필터
        if notebook_id:
            items = [i for i in items if i.get("notebook_id") == notebook_id]

        # 날짜 범위 필터 (ISO 8601, Outlook 형식과 동일)
        if date_from:
            items = [
                i for i in items
                if (i.get("last_accessed") or "") >= date_from
            ]
        if date_to:
            items = [
                i for i in items
                if (i.get("last_accessed") or "") <= date_to
            ]

        # top 제한
        items = items[:top]

        pages = [
            {
                "page_id": i.get("item_id"),
                "title": i.get("item_name"),
                "section_id": i.get("section_id"),
                "section_name": i.get("section_name"),
                "notebook_name": i.get("notebook_name"),
                "last_accessed": i.get("last_accessed"),
            }
            for i in items
        ]

        return {"success": True, "pages": pages, "count": len(pages)}

    async def list_sections(
        self,
        user_email: str,
        notebook_id: Optional[str] = None,
        top: int = 50,
    ) -> Dict[str, Any]:
        """섹션 목록 조회 (Graph API)"""
        return await self._client.list_sections(user_email, notebook_id, top)

    async def search(
        self,
        user_email: str,
        keyword: str,
        section_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        top: int = 50,
    ) -> Dict[str, Any]:
        """
        키워드 기반 페이지 검색 (AI)

        Args:
            date_from: 시작 날짜 (포함, ISO 8601 형식) 예: "2024-12-01T00:00:00Z"
            date_to: 종료 날짜 (포함, ISO 8601 형식) 예: "2024-12-31T23:59:59Z"
        """
        if not self._agent:
            return {"success": False, "error": "Agent가 초기화되지 않았습니다."}

        result = await self._agent.search_pages(
            user_email=user_email,
            query=keyword,
            section_id=section_id,
        )

        # top 제한
        if result.get("success") and result.get("results"):
            result["results"] = result["results"][:top]
            result["count"] = len(result["results"])

        return result

    async def get_content(
        self,
        user_email: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """특정 페이지 본문 조회"""
        return await self._client.get_page_content(page_id, user_email)

    async def get_summary(
        self,
        user_email: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """특정 페이지 요약 조회"""
        if not self._agent:
            return {"success": False, "error": "Agent가 초기화되지 않았습니다."}

        return await self._agent.get_page_summary(user_email, page_id)

    # ========================================================================
    # DB 조회 (구 OneNoteDBQuery에서 통합)
    # ========================================================================

    def get_recent_items(
        self,
        user_email: str,
        item_type: str = "section",
        limit: int = 5,
    ) -> Dict[str, Any]:
        """최근 접근한 아이템 조회"""
        if item_type not in ("section", "page"):
            return {"success": False, "error": "item_type은 'section' 또는 'page'여야 합니다."}

        items = self._db_service.get_recent_items(user_email, item_type, limit)
        return {
            "success": True,
            "item_type": item_type,
            "items": items,
            "count": len(items),
        }

    def find_section_by_name(
        self,
        user_email: str,
        section_name: str,
    ) -> Dict[str, Any]:
        """이름으로 섹션 검색"""
        section = self._db_service.get_section(user_email, section_name)
        if section:
            return {"success": True, "section": section}
        return {"success": False, "message": f"섹션 '{section_name}'을 찾을 수 없습니다."}

    def find_page_by_name(
        self,
        user_email: str,
        page_title: str,
    ) -> Dict[str, Any]:
        """이름으로 페이지 검색"""
        page = self._db_service.get_page(user_email, page_title)
        if page:
            return {"success": True, "page": page}
        return {"success": False, "message": f"페이지 '{page_title}'을 찾을 수 없습니다."}

    def get_page_history(
        self,
        page_id: str,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """페이지 변경 이력 조회 (git log 스타일, 최신순)"""
        changes = self._db_service.get_page_changes(page_id, limit)
        return {
            "success": True,
            "page_id": page_id,
            "changes": changes,
            "count": len(changes),
        }

    def get_user_history(
        self,
        user_email: str,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """사용자별 변경 이력 조회 (최신순)"""
        changes = self._db_service.get_user_changes(user_email, limit)
        return {
            "success": True,
            "user_id": user_email,
            "changes": changes,
            "count": len(changes),
        }
