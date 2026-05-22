"""
OneNote DB Query - 아이템 조회/저장 (외부 호출용)
섹션/페이지 검색, 최근 아이템 조회, 수동 저장 등
"""

import logging
from typing import Dict, Any, Optional

from .onenote_db_service import OneNoteDBService

logger = logging.getLogger(__name__)


class OneNoteDBQuery:
    """
    OneNote DB 조회/저장 서비스 (외부 호출용)

    - 이름으로 섹션/페이지 검색
    - 최근 접근 아이템 조회
    - 섹션/페이지 수동 DB 저장
    """

    def __init__(self, db_service: OneNoteDBService):
        self._db_service = db_service

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

    def save_section(
        self,
        user_email: str,
        notebook_id: str,
        section_id: str,
        section_name: str,
        notebook_name: Optional[str] = None,
        mark_as_recent: bool = True,
    ) -> Dict[str, Any]:
        """섹션 정보를 DB에 저장"""
        success = self._db_service.save_section(
            user_id=user_email,
            notebook_id=notebook_id,
            section_id=section_id,
            section_name=section_name,
            notebook_name=notebook_name,
            update_accessed=mark_as_recent,
        )

        if success:
            return {"success": True, "message": f"섹션 '{section_name}' 저장 완료"}
        return {"success": False, "message": "섹션 저장 실패"}

    def save_page(
        self,
        user_email: str,
        section_id: str,
        page_id: str,
        page_title: str,
        mark_as_recent: bool = True,
    ) -> Dict[str, Any]:
        """페이지 정보를 DB에 저장"""
        success = self._db_service.save_page(
            user_id=user_email,
            section_id=section_id,
            page_id=page_id,
            page_title=page_title,
            update_accessed=mark_as_recent,
        )

        if success:
            return {"success": True, "message": f"페이지 '{page_title}' 저장 완료"}
        return {"success": False, "message": "페이지 저장 실패"}

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
