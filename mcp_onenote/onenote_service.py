"""
OneNote Service - Facade
MCP 툴 3개 (read_onenote, write_onenote, delete_onenote) 라우팅
+ 하위 모듈 접근자
"""

import logging
import os
from typing import Dict, Any, Optional, Union

from mcp_common.principal import MISSING, Principal, assert_owner, assert_user_email
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

from .graph_onenote_client import GraphOneNoteClient
from .onenote_db_service import OneNoteDBService
from .onenote_types import ReadAction, WriteAction, check_top

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

    모드 (spec/spec_멀티유저.md ②-7.6):
    - mode 0: `OneNoteService()` — 공용 AuthManager·`database/onenote.db`, 소유자 = user_email.
    - mode 1: `OneNoteService(principal=..., token_provider=..., db_path=paths.onenote_db)` —
      한 사용자에 고정. 생성자는 아무 I/O 도 하지 않고 `initialize()` 가 DB·세션을 연다.
      MCP 진입점은 호출 principal 이 이 서비스의 소유자인지, user_email 이 연결 계정과
      같은지 먼저 확인한다(서비스 직접 호출 포함, ②-5.4).
    """

    def __init__(
        self,
        *,
        principal: Optional[Principal] = None,
        token_provider: Any = None,
        db_path: Optional[Union[str, "os.PathLike[str]"]] = None,
    ):
        self._principal = principal
        self._token_provider = token_provider
        self._db_path = db_path
        self._client: Optional[GraphOneNoteClient] = None
        self._db_service: Optional[OneNoteDBService] = None
        self._agent = None
        self._reader = None
        self._writer = None
        self._deleter = None
        self._initialized = False

    def _make_db_service(self) -> OneNoteDBService:
        if self._principal is not None:
            if self._db_path is None:
                raise RuntimeError("사용자 전용 OneNote DB 경로가 없습니다")
            return OneNoteDBService(self._db_path, owner_key=self._principal.user_key)
        if multi_user_enabled():
            # 공용 DB·공용 인증으로 되돌아가지 않는다
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
        return OneNoteDBService(self._db_path) if self._db_path is not None else OneNoteDBService()

    async def initialize(self) -> bool:
        """서비스 초기화"""
        if self._initialized:
            return True

        self._db_service = self._make_db_service()
        self._client = GraphOneNoteClient(token_provider=self._token_provider)

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

    def _caller(self, user_email: Optional[str]) -> Optional[str]:
        """MCP 진입점의 사용자 확정.

        mode 0: 핸들러가 해석한 값을 그대로 쓴다.
        mode 1: 요청 principal 이 이 서비스의 소유자여야 하고(아니면 not_found),
        user_email 은 연결 계정과 같아야 한다(아니면 identity_mismatch). 반환값은
        연결 계정 이메일 — 다른 계정을 고를 수 없다.
        """
        if self._principal is None:
            return user_email
        assert_owner(self._principal.user_key)
        return assert_user_email(MISSING if user_email is None else user_email)

    async def close(self):
        """리소스 정리 — 자기 HTTP 세션만 닫는다(토큰 공급자는 서비스 풀이 닫는다)."""
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
        include_ids: bool = False,
    ) -> Dict[str, Any]:
        """
        조회 라우터 — action에 따라 Reader 메서드 위임

        Actions:
            list_pages: 페이지 목록 조회
            list_sections: 섹션 목록 조회
            search: 키워드 기반 페이지 검색
            get_content: 페이지 본문 조회 (include_ids=True 면 요소 id·data-id 포함 — replace target 용)
            get_summary: 페이지 요약 조회

        날짜 필터 (ISO 8601 형식, Outlook과 동일):
            date_from: 시작 날짜 (포함, >= 이 값) 예: "2024-12-01T00:00:00Z"
            date_to: 종료 날짜 (포함, <= 이 값) 예: "2024-12-31T23:59:59Z"
        """
        self._ensure_initialized()
        user_email = self._caller(user_email)
        top = check_top(top)  # 1~500 — 조회·분석 작업량의 상한 (R02)

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
            return await self._reader.get_content(user_email, page_id, include_ids)

        elif act == ReadAction.GET_SUMMARY:
            if not page_id:
                return {"success": False, "error": "get_summary action에는 page_id가 필요합니다."}
            return await self._reader.get_summary(user_email, page_id)

        # ReadAction 이 추가됐는데 분기가 누락된 경우 — None 이 성공처럼 나가지 않도록 방어
        return {"success": False, "error": f"처리되지 않은 action: {action}"}

    async def write_onenote(
        self,
        user_email: str,
        action: str,
        content: Optional[str] = None,
        page_id: Optional[str] = None,
        section_id: Optional[str] = None,
        notebook_id: Optional[str] = None,
        title: Optional[str] = None,
        target: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        생성/수정 라우터 — action에 따라 Writer 메서드 위임

        Actions:
            append: 기존 페이지에 내용 추가 (page_id 없으면 최근 페이지)
            create_page: 새 페이지 생성
            create_section: 새 섹션 생성
            replace: page_id 의 target 요소('#data-id' 또는 생성 id)를 content 로 교체
        """
        self._ensure_initialized()
        user_email = self._caller(user_email)

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

        elif act == WriteAction.REPLACE:
            if not page_id or not target or not content:
                return {"success": False, "error": "replace action에는 page_id, target, content가 필요합니다."}
            return await self._writer.replace(user_email, page_id, target, content)

        # WriteAction 이 추가됐는데 분기가 누락된 경우 — None 이 성공처럼 나가지 않도록 방어
        return {"success": False, "error": f"처리되지 않은 action: {action}"}

    async def delete_onenote(
        self,
        user_email: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """
        삭제 라우터 — Deleter에 위임
        """
        self._ensure_initialized()
        user_email = self._caller(user_email)

        if not page_id:
            return {"success": False, "error": "page_id가 필요합니다."}

        return await self._deleter.delete_page(user_email, page_id)

    async def sync_db(self, user_email: str) -> Dict[str, Any]:
        """전체 페이지 DB 동기화 (MCP `sync_onenote_db`) — Writer.sync_db 에 위임"""
        self._ensure_initialized()
        user_email = self._caller(user_email)
        return await self._writer.sync_db(user_email)

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
