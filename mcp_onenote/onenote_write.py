"""
OneNote Write - 생성/수정 작업 담당
action에 따라 append, create_page, create_section 분기

통합: onenote_page.py (OneNotePageManager)의 create_page, edit_page, sync_db 로직 포함
"""

import logging
from typing import Dict, Any, Optional

from .graph_onenote_client import GraphOneNoteClient
from .onenote_db_service import OneNoteDBService
from .onenote_types import PageAction, WriteAction

logger = logging.getLogger(__name__)


class OneNoteWriter:
    """
    OneNote 생성/수정 전담

    - append: 기존 페이지에 내용 추가 (page_id 없으면 최근 페이지)
    - create_page: 새 페이지 생성 + DB 저장
    - create_section: 새 섹션 생성
    - sync_db: OneNote 전체 페이지를 DB에 동기화
    """

    def __init__(
        self,
        client: GraphOneNoteClient,
        db_service: OneNoteDBService,
        agent=None,
    ):
        self._client = client
        self._db_service = db_service
        self._agent = agent

    def set_agent(self, agent):
        """Agent 설정 (순환 참조 방지를 위한 후속 설정)"""
        self._agent = agent

    # ========================================================================
    # MCP 툴 action 메서드
    # ========================================================================

    async def append(
        self,
        user_email: str,
        content: str,
        page_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """기존 페이지에 내용 추가 (page_id 없으면 최근 접근 페이지)"""
        # page_id가 없으면 최근 접근 페이지 자동 선택
        if not page_id:
            recent = self._db_service.get_recent_items(user_email, "page", limit=1)
            if not recent:
                return {"success": False, "error": "최근 접근한 페이지가 없습니다. page_id를 지정해주세요."}
            page_id = recent[0].get("item_id")

        result = await self.edit_page(
            user_email=user_email,
            page_id=page_id,
            content=content,
        )

        if result.get("success"):
            # 페이지 정보 조회하여 반환값 보강
            items = self._db_service.list_items(user_email, item_type="page")
            page_info = next((i for i in items if i.get("item_id") == page_id), {})
            result["page_id"] = page_id
            result["title"] = page_info.get("item_name", "")
            result["web_url"] = page_info.get("web_url", "")

        return result

    async def create_page(
        self,
        user_email: str,
        section_id: str,
        title: str,
        content: str,
    ) -> Dict[str, Any]:
        """페이지 생성 + DB 저장"""
        result = await self._client.create_page(section_id, title, content, user_email)

        if result.get("success") and self._db_service:
            page = result.get("page", {})
            self._db_service.save_item(
                user_id=user_email,
                item_type="page",
                item_id=page.get("id"),
                item_name=page.get("title", title),
                notebook_id=page.get("notebook_id"),
                notebook_name=page.get("notebook_name"),
                section_id=page.get("parent_section_id") or section_id,
                section_name=page.get("parent_section_name"),
                web_url=page.get("web_url"),
                update_accessed=True,
            )

        return result

    async def create_section(
        self,
        user_email: str,
        notebook_id: str,
        title: str,
    ) -> Dict[str, Any]:
        """새 섹션 생성"""
        return await self._client.create_section(
            notebook_id=notebook_id,
            section_name=title,
            user_email=user_email,
        )

    # ========================================================================
    # 내부 로직 (구 OneNotePageManager에서 통합)
    # ========================================================================

    async def edit_page(
        self,
        user_email: str,
        page_id: str,
        action: PageAction = PageAction.APPEND,
        content: Optional[str] = None,
        target: Optional[str] = None,
        position: str = "after",
    ) -> Dict[str, Any]:
        """페이지 편집 + DB 업데이트 + 변경 이력 기록 + 요약 자동 갱신"""
        if not content and action != PageAction.CLEAN:
            return {"success": False, "error": "content가 필요합니다."}

        # 1. 편집 전 content_hash 조회
        previous_hash = None
        existing_summary = None
        if self._db_service:
            existing_summary = self._db_service.get_summary(page_id)
            if existing_summary:
                previous_hash = existing_summary.get("content_hash")

        # 2. Graph API 편집 실행
        result = await self._client.update_page(
            page_id=page_id,
            action=action,
            content=content or "",
            target=target,
            position=position,
            user_email=user_email,
        )

        if result.get("success") and self._db_service:
            self._db_service.save_item(
                user_id=user_email,
                item_type="page",
                item_id=page_id,
                item_name="",
                update_accessed=True,
            )

            # 3. AI 변경 요약 생성 + 변경 이력 저장
            change_summary = ""
            change_keywords = []
            if self._agent:
                try:
                    # 페이지 제목 조회 (item_id로 직접 조회)
                    page_title = ""
                    items = self._db_service.list_items(user_email, item_type="page")
                    for item in items:
                        if item.get("item_id") == page_id:
                            page_title = item.get("item_name", "")
                            break

                    change_result = await self._agent.summarize_change(
                        page_title=page_title,
                        action=action.value,
                        content=content or "",
                    )
                    change_summary = change_result.get("change_summary", "")
                    change_keywords = change_result.get("change_keywords", [])
                except Exception as e:
                    logger.warning(f"변경 요약 생성 실패 (무시): {e}")
                    change_summary = f"{action.value} 작업 수행"

            self._db_service.save_page_change(
                page_id=page_id,
                user_id=user_email,
                action=action.value,
                content_snippet=content,
                target=target,
                previous_hash=previous_hash,
                change_summary=change_summary,
                change_keywords=change_keywords,
            )

            # 4. 기존 요약 자동 갱신 (기존 요약이 있는 경우만)
            if existing_summary and self._agent:
                try:
                    await self._agent.summarize_page(user_email, page_id, force_refresh=True)
                    logger.info(f"페이지 편집 후 요약 자동 갱신: {page_id}")
                except Exception as e:
                    logger.warning(f"페이지 편집 후 요약 갱신 실패 (무시): {e}")

        return result

    async def sync_db(
        self,
        user_email: str,
    ) -> Dict[str, Any]:
        """
        OneNote 전체 페이지를 DB에 동기화
        /me/onenote/pages로 전체 페이지를 조회하여 DB에 저장
        """
        result = {"success": True, "pages_synced": 0}

        pages_result = await self._client.list_pages(user_email)
        if pages_result.get("success"):
            pages = pages_result.get("pages", [])
            sync_result = await self._db_service.sync_pages_to_db(
                user_id=user_email,
                pages=pages,
            )
            result["pages_synced"] = sync_result.get("synced", 0)
        else:
            result["success"] = False
            result["error"] = pages_result.get("error", "페이지 조회 실패")

        return result
