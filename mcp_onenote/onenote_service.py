"""
OneNote Service - Facade
MCP 툴 3개 (read_onenote, write_onenote, delete_onenote) 라우팅
+ 하위 모듈 접근자
"""

import logging
from typing import Dict, Any, Optional

from .graph_onenote_client import GraphOneNoteClient
from .onenote_db_service import OneNoteDBService
from .onenote_types import ReadAction, WriteAction

logger = logging.getLogger(__name__)


class OneNoteService:
    """
    OneNote Facade — MCP 툴 라우팅 + 하위 모듈 접근자

    MCP 툴 진입점:
    - read_onenote()   → OneNoteReader (조회)
    - write_onenote()  → OneNoteWriter (생성/수정)
    - delete_onenote() → OneNoteDeleter (삭제)

    하위 모듈 접근:
    - svc.reader → OneNoteReader
    - svc.writer → OneNoteWriter
    - svc.deleter → OneNoteDeleter
    - svc.agent  → OneNoteAgent (AI 요약/검색)
    """

    def __init__(self):
        self._client: Optional[GraphOneNoteClient] = None
        self._db_service: Optional[OneNoteDBService] = None
        self._agent = None
        self._reader = None
        self._writer = None
        self._deleter = None
        self._initialized = False

    async def initialize(self) -> bool:
        """서비스 초기화"""
        if self._initialized:
            return True

        self._client = GraphOneNoteClient()
        self._db_service = OneNoteDBService()

        if await self._client.initialize():
            from .onenote_agent import OneNoteAgent
            from .onenote_read import OneNoteReader
            from .onenote_write import OneNoteWriter
            from .onenote_delete import OneNoteDeleter

            self._agent = OneNoteAgent(self._client, self._db_service)

            self._writer = OneNoteWriter(
                self._client, self._db_service, self._agent
            )
            self._deleter = OneNoteDeleter(
                self._client, self._db_service
            )
            self._reader = OneNoteReader(
                self._client, self._db_service, self._agent, self._writer
            )

            self._initialized = True
            return True
        return False

    def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized or not self._client:
            raise RuntimeError("OneNoteService not initialized. Call initialize() first.")

    async def close(self):
        """리소스 정리"""
        if self._client:
            await self._client.close()
            self._client = None
        self._initialized = False

    # ========================================================================
    # MCP 툴 진입점 (read / write / delete)
    # ========================================================================

    async def read_onenote(
        self,
        user_email: str,
        action: str,
        keyword: Optional[str] = None,
        page_id: Optional[str] = None,
        section_id: Optional[str] = None,
        notebook_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        top: int = 50,
    ) -> Dict[str, Any]:
        """
        조회 라우터 — action에 따라 Reader 메서드 위임

        Actions:
            list_pages: 페이지 목록 조회
            list_sections: 섹션 목록 조회
            search: 키워드 기반 페이지 검색
            get_content: 페이지 본문 조회
            get_summary: 페이지 요약 조회

        날짜 필터 (ISO 8601 형식, Outlook과 동일):
            date_from: 시작 날짜 (포함, >= 이 값) 예: "2024-12-01T00:00:00Z"
            date_to: 종료 날짜 (포함, <= 이 값) 예: "2024-12-31T23:59:59Z"
        """
        self._ensure_initialized()

        try:
            act = ReadAction(action)
        except ValueError:
            return {"success": False, "error": f"알 수 없는 action: {action}. "
                    f"사용 가능: {[a.value for a in ReadAction]}"}

        if act == ReadAction.LIST_PAGES:
            return await self._reader.list_pages(
                user_email, section_id, notebook_id, date_from, date_to, top
            )

        elif act == ReadAction.LIST_SECTIONS:
            return await self._reader.list_sections(user_email, notebook_id, top)

        elif act == ReadAction.SEARCH:
            if not keyword:
                return {"success": False, "error": "search action에는 keyword가 필요합니다."}
            return await self._reader.search(
                user_email, keyword, section_id, date_from, date_to, top
            )

        elif act == ReadAction.GET_CONTENT:
            if not page_id:
                return {"success": False, "error": "get_content action에는 page_id가 필요합니다."}
            return await self._reader.get_content(user_email, page_id)

        elif act == ReadAction.GET_SUMMARY:
            if not page_id:
                return {"success": False, "error": "get_summary action에는 page_id가 필요합니다."}
            return await self._reader.get_summary(user_email, page_id)

    async def write_onenote(
        self,
        user_email: str,
        action: str,
        content: Optional[str] = None,
        page_id: Optional[str] = None,
        section_id: Optional[str] = None,
        notebook_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        생성/수정 라우터 — action에 따라 Writer 메서드 위임

        Actions:
            append: 기존 페이지에 내용 추가 (page_id 없으면 최근 페이지)
            create_page: 새 페이지 생성
            create_section: 새 섹션 생성
        """
        self._ensure_initialized()

        try:
            act = WriteAction(action)
        except ValueError:
            return {"success": False, "error": f"알 수 없는 action: {action}. "
                    f"사용 가능: {[a.value for a in WriteAction]}"}

        if act == WriteAction.APPEND:
            if not content:
                return {"success": False, "error": "append action에는 content가 필요합니다."}
            return await self._writer.append(user_email, content, page_id)

        elif act == WriteAction.CREATE_PAGE:
            if not section_id or not title or not content:
                return {"success": False, "error": "create_page action에는 section_id, title, content가 필요합니다."}
            return await self._writer.create_page(user_email, section_id, title, content)

        elif act == WriteAction.CREATE_SECTION:
            if not notebook_id or not title:
                return {"success": False, "error": "create_section action에는 notebook_id, title이 필요합니다."}
            return await self._writer.create_section(user_email, notebook_id, title)

    async def delete_onenote(
        self,
        user_email: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """
        삭제 라우터 — Deleter에 위임
        """
        self._ensure_initialized()

        if not page_id:
            return {"success": False, "error": "page_id가 필요합니다."}

        return await self._deleter.delete_page(user_email, page_id)

    # ========================================================================
    # 접근자
    # ========================================================================

    @property
    def reader(self):
        """OneNoteReader 인스턴스 반환"""
        if not self._reader:
            raise RuntimeError("OneNoteService not initialized. Call initialize() first.")
        return self._reader

    @property
    def writer(self):
        """OneNoteWriter 인스턴스 반환"""
        if not self._writer:
            raise RuntimeError("OneNoteService not initialized. Call initialize() first.")
        return self._writer

    @property
    def deleter(self):
        """OneNoteDeleter 인스턴스 반환"""
        if not self._deleter:
            raise RuntimeError("OneNoteService not initialized. Call initialize() first.")
        return self._deleter

    @property
    def agent(self):
        """OneNoteAgent 인스턴스 반환"""
        if not self._agent:
            raise RuntimeError("OneNoteService not initialized. Call initialize() first.")
        return self._agent
