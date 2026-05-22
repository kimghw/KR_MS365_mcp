"""
OneNote Service Tests
새 CRUD 구조 반영:
- svc.reader  → OneNoteReader (list_pages, list_sections, search, get_content, get_summary + DB 조회)
- svc.writer  → OneNoteWriter (append, create_page, create_section, edit_page, sync_db)
- svc.deleter → OneNoteDeleter (delete_page)
- svc.agent   → OneNoteAgent (AI 요약/검색)

MCP 툴 라우팅:
- svc.read_onenote()   → Reader 위임
- svc.write_onenote()  → Writer 위임
- svc.delete_onenote() → Deleter 위임
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_onenote.onenote_service import OneNoteService
from mcp_onenote.onenote_read import OneNoteReader
from mcp_onenote.onenote_write import OneNoteWriter
from mcp_onenote.onenote_delete import OneNoteDeleter
from mcp_onenote.onenote_types import PageAction, ReadAction, WriteAction


class TestOneNoteService:
    """OneNoteService Facade 테스트"""

    @pytest.fixture
    def service(self):
        """서비스 인스턴스 생성"""
        return OneNoteService()

    @pytest.fixture
    def mock_client(self):
        """Mock GraphOneNoteClient"""
        return AsyncMock()

    @pytest.fixture
    def mock_db_service(self):
        """Mock OneNoteDBService"""
        return MagicMock()

    @pytest.fixture
    def mock_agent(self):
        """Mock OneNoteAgent"""
        return AsyncMock()

    @pytest.fixture
    def initialized_service(self, service, mock_client, mock_db_service, mock_agent):
        """초기화된 서비스 (reader, writer, deleter 접근자 포함)"""
        service._client = mock_client
        service._db_service = mock_db_service
        service._agent = mock_agent
        service._initialized = True

        service._writer = OneNoteWriter(mock_client, mock_db_service, mock_agent)
        service._deleter = OneNoteDeleter(mock_client, mock_db_service)
        service._reader = OneNoteReader(
            mock_client, mock_db_service, mock_agent, service._writer
        )

        return service

    # ========================================================================
    # 초기화 테스트
    # ========================================================================

    @pytest.mark.asyncio
    async def test_initialize(self, service):
        """서비스 초기화 테스트"""
        service._initialized = True
        assert service._initialized is True

    def test_not_initialized_error(self, service):
        """초기화되지 않은 상태에서 호출 시 에러 테스트"""
        with pytest.raises(RuntimeError, match="not initialized"):
            service._ensure_initialized()

    # ========================================================================
    # MCP 툴 라우팅: read_onenote 테스트
    # ========================================================================

    @pytest.mark.asyncio
    async def test_read_onenote_list_pages(self, initialized_service, mock_db_service):
        """read_onenote - list_pages 라우팅 테스트"""
        mock_db_service.list_items = MagicMock(return_value=[
            {
                "item_id": "p1", "item_name": "Page 1",
                "section_id": "s1", "section_name": "Sec 1",
                "notebook_name": "NB 1", "last_accessed": "2026-01-01T00:00:00Z",
            },
        ])

        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="list_pages",
        )

        assert result["success"] is True
        assert result["count"] == 1
        assert result["pages"][0]["page_id"] == "p1"

    @pytest.mark.asyncio
    async def test_read_onenote_list_pages_with_date_filter(self, initialized_service, mock_db_service):
        """read_onenote - list_pages 날짜 필터 테스트"""
        mock_db_service.list_items = MagicMock(return_value=[
            {
                "item_id": "p1", "item_name": "Page 1",
                "section_id": "s1", "section_name": "Sec 1",
                "notebook_name": "NB 1", "last_accessed": "2026-01-15T00:00:00Z",
            },
            {
                "item_id": "p2", "item_name": "Page 2",
                "section_id": "s1", "section_name": "Sec 1",
                "notebook_name": "NB 1", "last_accessed": "2025-12-01T00:00:00Z",
            },
        ])

        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="list_pages",
            date_from="2026-01-01T00:00:00Z",
            date_to="2026-01-31T23:59:59Z",
        )

        assert result["success"] is True
        assert result["count"] == 1
        assert result["pages"][0]["page_id"] == "p1"

    @pytest.mark.asyncio
    async def test_read_onenote_list_sections(self, initialized_service, mock_client):
        """read_onenote - list_sections 라우팅 테스트"""
        mock_client.list_sections = AsyncMock(return_value={
            "success": True,
            "sections": [{"id": "s1", "display_name": "Section 1"}],
            "count": 1,
        })

        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="list_sections",
            notebook_id="nb1",
        )

        assert result["success"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_read_onenote_search(self, initialized_service, mock_agent):
        """read_onenote - search 라우팅 테스트"""
        mock_agent.search_pages = AsyncMock(return_value={
            "success": True,
            "results": [
                {"page_id": "p1", "title": "Found Page", "score": 0.9},
            ],
            "count": 1,
        })

        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="search",
            keyword="테스트",
        )

        assert result["success"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_read_onenote_search_no_keyword(self, initialized_service):
        """read_onenote - search에 keyword 없으면 에러"""
        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="search",
        )

        assert result["success"] is False
        assert "keyword" in result["error"]

    @pytest.mark.asyncio
    async def test_read_onenote_get_content(self, initialized_service, mock_client):
        """read_onenote - get_content 라우팅 테스트"""
        mock_client.get_page_content = AsyncMock(return_value={
            "success": True,
            "page_id": "p1",
            "content": "<html><body>Test</body></html>",
        })

        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="get_content",
            page_id="p1",
        )

        assert result["success"] is True
        assert "content" in result

    @pytest.mark.asyncio
    async def test_read_onenote_get_content_no_page_id(self, initialized_service):
        """read_onenote - get_content에 page_id 없으면 에러"""
        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="get_content",
        )

        assert result["success"] is False
        assert "page_id" in result["error"]

    @pytest.mark.asyncio
    async def test_read_onenote_get_summary(self, initialized_service, mock_agent):
        """read_onenote - get_summary 라우팅 테스트"""
        mock_agent.get_page_summary = AsyncMock(return_value={
            "success": True,
            "summary": "페이지 요약 내용",
        })

        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="get_summary",
            page_id="p1",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_read_onenote_invalid_action(self, initialized_service):
        """read_onenote - 잘못된 action"""
        result = await initialized_service.read_onenote(
            user_email="test@example.com",
            action="invalid_action",
        )

        assert result["success"] is False
        assert "알 수 없는 action" in result["error"]

    # ========================================================================
    # MCP 툴 라우팅: write_onenote 테스트
    # ========================================================================

    @pytest.mark.asyncio
    async def test_write_onenote_append(self, initialized_service, mock_client, mock_db_service):
        """write_onenote - append 라우팅 테스트"""
        mock_client.update_page = AsyncMock(return_value={"success": True})
        mock_db_service.get_summary = MagicMock(return_value=None)
        mock_db_service.list_items = MagicMock(return_value=[
            {"item_id": "p1", "item_name": "Test Page", "web_url": "http://example.com"}
        ])
        mock_db_service.save_page_change = MagicMock()

        result = await initialized_service.write_onenote(
            user_email="test@example.com",
            action="append",
            content="<p>New content</p>",
            page_id="p1",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_write_onenote_append_no_content(self, initialized_service):
        """write_onenote - append에 content 없으면 에러"""
        result = await initialized_service.write_onenote(
            user_email="test@example.com",
            action="append",
        )

        assert result["success"] is False
        assert "content" in result["error"]

    @pytest.mark.asyncio
    async def test_write_onenote_create_page(self, initialized_service, mock_client, mock_db_service):
        """write_onenote - create_page 라우팅 테스트"""
        mock_client.create_page = AsyncMock(return_value={
            "success": True,
            "page": {
                "id": "p_new", "title": "New Page",
                "parent_section_id": "s1",
            },
        })

        result = await initialized_service.write_onenote(
            user_email="test@example.com",
            action="create_page",
            section_id="s1",
            title="New Page",
            content="<p>Content</p>",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_write_onenote_create_page_missing_params(self, initialized_service):
        """write_onenote - create_page에 필수 파라미터 누락 시 에러"""
        result = await initialized_service.write_onenote(
            user_email="test@example.com",
            action="create_page",
            title="Title Only",
        )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_write_onenote_create_section(self, initialized_service, mock_client):
        """write_onenote - create_section 라우팅 테스트"""
        mock_client.create_section = AsyncMock(return_value={
            "success": True,
            "section": {"id": "s_new", "display_name": "New Section"},
        })

        result = await initialized_service.write_onenote(
            user_email="test@example.com",
            action="create_section",
            notebook_id="nb1",
            title="New Section",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_write_onenote_invalid_action(self, initialized_service):
        """write_onenote - 잘못된 action"""
        result = await initialized_service.write_onenote(
            user_email="test@example.com",
            action="invalid_action",
        )

        assert result["success"] is False
        assert "알 수 없는 action" in result["error"]

    # ========================================================================
    # MCP 툴 라우팅: delete_onenote 테스트
    # ========================================================================

    @pytest.mark.asyncio
    async def test_delete_onenote(self, initialized_service, mock_client, mock_db_service):
        """delete_onenote 라우팅 테스트"""
        mock_client.delete_page = AsyncMock(return_value={"success": True})

        result = await initialized_service.delete_onenote(
            user_email="test@example.com",
            page_id="p1",
        )

        assert result["success"] is True
        assert result["deleted_page_id"] == "p1"

    @pytest.mark.asyncio
    async def test_delete_onenote_no_page_id(self, initialized_service):
        """delete_onenote - page_id 없으면 에러"""
        result = await initialized_service.delete_onenote(
            user_email="test@example.com",
            page_id="",
        )

        assert result["success"] is False
        assert "page_id" in result["error"]

    # ========================================================================
    # OneNoteReader 직접 테스트
    # ========================================================================

    @pytest.mark.asyncio
    async def test_reader_list_pages_empty_triggers_sync(
        self, initialized_service, mock_client, mock_db_service
    ):
        """Reader: DB 비어있으면 sync_db 호출 후 재조회"""
        # 첫 호출: 빈 목록, 두 번째 호출(sync 후): 데이터 있음
        mock_db_service.list_items = MagicMock(side_effect=[
            [],  # 첫 조회
            [{"item_id": "p1", "item_name": "Page 1",
              "section_id": "s1", "section_name": "Sec 1",
              "notebook_name": "NB 1", "last_accessed": "2026-01-01T00:00:00Z"}],
        ])
        mock_client.list_pages = AsyncMock(return_value={
            "success": True,
            "pages": [{"id": "p1", "title": "Page 1"}],
        })
        mock_db_service.sync_pages_to_db = AsyncMock(return_value={"synced": 1})

        result = await initialized_service.reader.list_pages("test@example.com")

        assert result["success"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_reader_list_pages_notebook_filter(
        self, initialized_service, mock_db_service
    ):
        """Reader: notebook_id 필터링"""
        mock_db_service.list_items = MagicMock(return_value=[
            {"item_id": "p1", "item_name": "Page 1", "notebook_id": "nb1",
             "section_id": "s1", "section_name": "Sec 1",
             "notebook_name": "NB 1", "last_accessed": "2026-01-01T00:00:00Z"},
            {"item_id": "p2", "item_name": "Page 2", "notebook_id": "nb2",
             "section_id": "s2", "section_name": "Sec 2",
             "notebook_name": "NB 2", "last_accessed": "2026-01-01T00:00:00Z"},
        ])

        result = await initialized_service.reader.list_pages(
            "test@example.com", notebook_id="nb1"
        )

        assert result["count"] == 1
        assert result["pages"][0]["page_id"] == "p1"

    def test_reader_get_recent_items(self, initialized_service, mock_db_service):
        """Reader: 최근 섹션 조회"""
        mock_db_service.get_recent_items = MagicMock(return_value=[
            {"item_id": "s1", "item_name": "Section 1", "item_type": "section"},
            {"item_id": "s2", "item_name": "Section 2", "item_type": "section"},
        ])

        result = initialized_service.reader.get_recent_items(
            "test@example.com", "section", 5
        )

        assert result["success"] is True
        assert result["count"] == 2
        mock_db_service.get_recent_items.assert_called_once_with(
            "test@example.com", "section", 5
        )

    def test_reader_get_recent_items_invalid_type(self, initialized_service):
        """Reader: 잘못된 item_type"""
        result = initialized_service.reader.get_recent_items(
            "test@example.com", "notebook", 5
        )

        assert result["success"] is False

    def test_reader_find_section_by_name(self, initialized_service, mock_db_service):
        """Reader: 이름으로 섹션 검색"""
        mock_db_service.get_section = MagicMock(return_value={
            "section_id": "s1",
            "section_name": "My Section",
            "notebook_id": "nb1",
        })

        result = initialized_service.reader.find_section_by_name(
            "test@example.com", "My Section"
        )

        assert result["success"] is True
        assert result["section"]["section_id"] == "s1"

    def test_reader_find_section_not_found(self, initialized_service, mock_db_service):
        """Reader: 섹션 검색 실패"""
        mock_db_service.get_section = MagicMock(return_value=None)

        result = initialized_service.reader.find_section_by_name(
            "test@example.com", "Unknown"
        )

        assert result["success"] is False

    def test_reader_find_page_by_name(self, initialized_service, mock_db_service):
        """Reader: 이름으로 페이지 검색"""
        mock_db_service.get_page = MagicMock(return_value={
            "page_id": "p1",
            "page_title": "My Page",
            "section_id": "s1",
        })

        result = initialized_service.reader.find_page_by_name(
            "test@example.com", "My Page"
        )

        assert result["success"] is True
        assert result["page"]["page_id"] == "p1"

    def test_reader_get_page_history(self, initialized_service, mock_db_service):
        """Reader: 페이지 변경 이력 조회"""
        mock_db_service.get_page_changes = MagicMock(return_value=[
            {
                "id": 1, "page_id": "p1", "user_id": "test@example.com",
                "action": "append", "change_summary": "새 단락 추가",
                "change_keywords": ["단락", "추가"],
                "created_at": "2026-02-09T12:00:00",
            },
            {
                "id": 2, "page_id": "p1", "user_id": "test@example.com",
                "action": "replace", "change_summary": "제목 수정",
                "change_keywords": ["제목", "수정"],
                "created_at": "2026-02-09T11:00:00",
            },
        ])

        result = initialized_service.reader.get_page_history("p1")

        assert result["success"] is True
        assert result["count"] == 2
        assert result["changes"][0]["action"] == "append"
        assert result["changes"][1]["change_summary"] == "제목 수정"

    def test_reader_get_user_history(self, initialized_service, mock_db_service):
        """Reader: 사용자별 변경 이력 조회"""
        mock_db_service.get_user_changes = MagicMock(return_value=[
            {"page_id": "p1", "action": "append", "change_summary": "내용 추가"},
        ])

        result = initialized_service.reader.get_user_history("test@example.com")

        assert result["success"] is True
        assert result["count"] == 1

    # ========================================================================
    # OneNoteWriter 직접 테스트
    # ========================================================================

    @pytest.mark.asyncio
    async def test_writer_create_page(self, initialized_service, mock_client, mock_db_service):
        """Writer: 페이지 생성 + DB 저장"""
        mock_client.create_page = AsyncMock(return_value={
            "success": True,
            "page": {"id": "p_new", "title": "New Page"},
        })

        result = await initialized_service.writer.create_page(
            user_email="test@example.com",
            section_id="s1",
            title="New Page",
            content="<p>Hello World</p>",
        )

        assert result["success"] is True
        assert result["page"]["title"] == "New Page"
        mock_db_service.save_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_writer_edit_page_append(self, initialized_service, mock_client, mock_db_service):
        """Writer: 페이지 편집(append)"""
        mock_client.update_page = AsyncMock(return_value={"success": True})
        mock_db_service.get_summary = MagicMock(return_value=None)
        mock_db_service.list_items = MagicMock(return_value=[
            {"item_id": "p1", "item_name": "Test Page"}
        ])
        mock_db_service.save_page_change = MagicMock()

        result = await initialized_service.writer.edit_page(
            user_email="test@example.com",
            page_id="p1",
            action=PageAction.APPEND,
            content="<p>Appended content</p>",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_writer_edit_page_saves_change_history(
        self, initialized_service, mock_client, mock_db_service, mock_agent
    ):
        """Writer: 편집 시 변경 이력 저장 확인"""
        mock_client.update_page = AsyncMock(return_value={"success": True})
        mock_db_service.get_summary = MagicMock(return_value=None)
        mock_db_service.list_items = MagicMock(return_value=[
            {"item_id": "p1", "item_name": "Test Page"}
        ])
        mock_db_service.save_page_change = MagicMock()

        mock_agent.summarize_change = AsyncMock(return_value={
            "change_summary": "테스트 내용 추가",
            "change_keywords": ["테스트", "추가"],
        })

        result = await initialized_service.writer.edit_page(
            user_email="test@example.com",
            page_id="p1",
            action=PageAction.APPEND,
            content="<p>새 내용</p>",
        )

        assert result["success"] is True
        mock_db_service.save_page_change.assert_called_once()

        call_kwargs = mock_db_service.save_page_change.call_args
        assert call_kwargs[1]["page_id"] == "p1"
        assert call_kwargs[1]["action"] == "append"
        assert call_kwargs[1]["change_summary"] == "테스트 내용 추가"
        assert call_kwargs[1]["change_keywords"] == ["테스트", "추가"]

    @pytest.mark.asyncio
    async def test_writer_append_auto_select_recent_page(
        self, initialized_service, mock_client, mock_db_service
    ):
        """Writer: append에 page_id 없으면 최근 페이지 자동 선택"""
        mock_db_service.get_recent_items = MagicMock(return_value=[
            {"item_id": "p_recent", "item_name": "Recent Page"}
        ])
        mock_client.update_page = AsyncMock(return_value={"success": True})
        mock_db_service.get_summary = MagicMock(return_value=None)
        mock_db_service.list_items = MagicMock(return_value=[
            {"item_id": "p_recent", "item_name": "Recent Page", "web_url": "http://example.com"}
        ])
        mock_db_service.save_page_change = MagicMock()

        result = await initialized_service.writer.append(
            user_email="test@example.com",
            content="<p>Auto appended</p>",
        )

        assert result["success"] is True
        assert result["page_id"] == "p_recent"

    @pytest.mark.asyncio
    async def test_writer_append_no_recent_page(self, initialized_service, mock_db_service):
        """Writer: append에 page_id 없고 최근 페이지도 없으면 에러"""
        mock_db_service.get_recent_items = MagicMock(return_value=[])

        result = await initialized_service.writer.append(
            user_email="test@example.com",
            content="<p>Content</p>",
        )

        assert result["success"] is False
        assert "page_id" in result["error"]

    @pytest.mark.asyncio
    async def test_writer_sync_db(self, initialized_service, mock_client, mock_db_service):
        """Writer: DB 동기화"""
        mock_client.list_pages = AsyncMock(return_value={
            "success": True,
            "pages": [{"id": "p1", "title": "Page 1"}],
        })
        mock_db_service.sync_pages_to_db = AsyncMock(return_value={"synced": 1})

        result = await initialized_service.writer.sync_db(
            user_email="test@example.com",
        )

        assert result["success"] is True
        assert result["pages_synced"] == 1

    @pytest.mark.asyncio
    async def test_writer_create_section(self, initialized_service, mock_client):
        """Writer: 섹션 생성"""
        mock_client.create_section = AsyncMock(return_value={
            "success": True,
            "section": {"id": "s_new", "display_name": "New Section"},
        })

        result = await initialized_service.writer.create_section(
            user_email="test@example.com",
            notebook_id="nb1",
            title="New Section",
        )

        assert result["success"] is True

    # ========================================================================
    # OneNoteDeleter 직접 테스트
    # ========================================================================

    @pytest.mark.asyncio
    async def test_deleter_delete_page(self, initialized_service, mock_client, mock_db_service):
        """Deleter: 페이지 삭제 + DB/요약 삭제"""
        mock_client.delete_page = AsyncMock(return_value={"success": True})

        result = await initialized_service.deleter.delete_page(
            "test@example.com", "p1"
        )

        assert result["success"] is True
        assert result["deleted_page_id"] == "p1"
        mock_db_service.delete_item.assert_called_once_with(
            user_id="test@example.com", item_id="p1"
        )
        mock_db_service.delete_summary.assert_called_once_with(page_id="p1")

    # ========================================================================
    # 접근자 테스트
    # ========================================================================

    def test_reader_property_not_initialized(self, service):
        """초기화 전 reader 접근 시 에러"""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = service.reader

    def test_writer_property_not_initialized(self, service):
        """초기화 전 writer 접근 시 에러"""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = service.writer

    def test_deleter_property_not_initialized(self, service):
        """초기화 전 deleter 접근 시 에러"""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = service.deleter

    def test_agent_property_not_initialized(self, service):
        """초기화 전 agent 접근 시 에러"""
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = service.agent


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
