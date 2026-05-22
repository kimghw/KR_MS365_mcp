"""
Teams Service Tests
원본 teams_mcp 모듈과 동일한 기능을 테스트합니다.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_teams.teams_service import TeamsService
from mcp_teams.teams_types import (
    ChatType,
    MessageImportance,
)


class TestTeamsService:
    """TeamsService 테스트"""

    @pytest.fixture
    def service(self):
        """서비스 인스턴스 생성"""
        return TeamsService()

    @pytest.fixture
    def mock_client(self):
        """Mock GraphTeamsClient"""
        mock = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_initialize(self, service):
        """서비스 초기화 테스트"""
        with patch.object(service, '_client', new_callable=AsyncMock) as mock_client:
            mock_client.initialize = AsyncMock(return_value=True)
            service._client = mock_client
            service._initialized = True

            assert service._initialized is True

    @pytest.mark.asyncio
    async def test_list_chats(self, service, mock_client):
        """채팅 목록 조회 테스트"""
        mock_client.list_chats = AsyncMock(return_value={
            "success": True,
            "chats": [
                {"id": "c1", "topic": "Chat 1", "chat_type": "oneOnOne"},
                {"id": "c2", "topic": "Chat 2", "chat_type": "group"},
            ],
            "count": 2,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.list_chats("test@example.com")

        assert result["success"] is True
        assert result["count"] == 2
        mock_client.list_chats.assert_called_once_with("test@example.com", 50)

    @pytest.mark.asyncio
    async def test_get_chat(self, service, mock_client):
        """특정 채팅 정보 조회 테스트"""
        mock_client.get_chat = AsyncMock(return_value={
            "success": True,
            "chat": {"id": "c1", "topic": "Test Chat"},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.get_chat("test@example.com", "c1")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_get_chat_messages(self, service, mock_client):
        """채팅 메시지 목록 조회 테스트"""
        mock_client.get_chat_messages = AsyncMock(return_value={
            "success": True,
            "messages": [
                {"id": "m1", "body_content": "Hello"},
                {"id": "m2", "body_content": "World"},
            ],
            "count": 2,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.get_chat_messages("test@example.com", "c1")

        assert result["success"] is True
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_get_chat_messages_notes(self, service, mock_client):
        """Notes 채팅 메시지 조회 테스트 (chat_id 생략)"""
        mock_client.get_chat_messages = AsyncMock(return_value={
            "success": True,
            "messages": [{"id": "m1", "body_content": "Note"}],
            "count": 1,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.get_chat_messages("test@example.com")

        assert result["success"] is True
        # chat_id가 None으로 전달됨 (클라이언트에서 NOTES_CHAT_ID 사용)
        mock_client.get_chat_messages.assert_called_once_with("test@example.com", None, 50)

    @pytest.mark.asyncio
    async def test_send_chat_message(self, service, mock_client):
        """채팅 메시지 전송 테스트"""
        mock_client.send_chat_message = AsyncMock(return_value={
            "success": True,
            "message_id": "m_new",
            "message": {"id": "m_new", "body_content": "[claude] Test message"},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.send_chat_message(
            user_email="test@example.com",
            content="Test message",
            chat_id="c1",
        )

        assert result["success"] is True
        assert result["message_id"] == "m_new"

    @pytest.mark.asyncio
    async def test_list_teams(self, service, mock_client):
        """팀 목록 조회 테스트"""
        mock_client.list_teams = AsyncMock(return_value={
            "success": True,
            "teams": [
                {"id": "t1", "display_name": "Team 1"},
                {"id": "t2", "display_name": "Team 2"},
            ],
            "count": 2,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.list_teams("test@example.com")

        assert result["success"] is True
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_list_channels(self, service, mock_client):
        """채널 목록 조회 테스트"""
        mock_client.list_channels = AsyncMock(return_value={
            "success": True,
            "channels": [
                {"id": "ch1", "display_name": "General"},
            ],
            "count": 1,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.list_channels("test@example.com", "t1")

        assert result["success"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_get_channel_messages(self, service, mock_client):
        """채널 메시지 목록 조회 테스트"""
        mock_client.get_channel_messages = AsyncMock(return_value={
            "success": True,
            "messages": [
                {"id": "m1", "body_content": "Channel message"},
            ],
            "count": 1,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.get_channel_messages("test@example.com", "t1", "ch1")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_send_channel_message(self, service, mock_client):
        """채널 메시지 전송 테스트"""
        mock_client.send_channel_message = AsyncMock(return_value={
            "success": True,
            "message_id": "m_new",
            "message": {"id": "m_new", "body_content": "New channel message"},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.send_channel_message(
            user_email="test@example.com",
            team_id="t1",
            channel_id="ch1",
            content="New channel message",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_get_message_replies(self, service, mock_client):
        """메시지 답글 목록 조회 테스트"""
        mock_client.get_message_replies = AsyncMock(return_value={
            "success": True,
            "replies": [
                {"id": "r1", "body_content": "Reply 1"},
            ],
            "count": 1,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.get_message_replies("test@example.com", "t1", "ch1", "m1")

        assert result["success"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_not_initialized_error(self, service):
        """초기화되지 않은 상태에서 호출 시 에러 테스트"""
        with pytest.raises(RuntimeError, match="not initialized"):
            await service.list_chats("test@example.com")

    # ========================================================================
    # 한글 이름 관련 테스트
    # ========================================================================

    @pytest.fixture
    def mock_db_manager(self):
        """Mock TeamsDBManager"""
        mock = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_save_korean_name(self, service, mock_client, mock_db_manager):
        """한글 이름 저장 테스트"""
        mock_db_manager.save_korean_name = AsyncMock(return_value={
            "success": True,
            "message": "한글 이름 '한그로' 저장 완료",
            "chat_id": "c1"
        })

        service._client = mock_client
        service._db_manager = mock_db_manager
        service._initialized = True

        result = await service.save_korean_name(
            user_email="test@example.com",
            topic_kr="한그로",
            topic_en="Hangro"
        )

        assert result["success"] is True
        mock_db_manager.save_korean_name.assert_called_once_with(
            user_id="test@example.com",
            topic_kr="한그로",
            chat_id=None,
            topic_en="Hangro"
        )

    @pytest.mark.asyncio
    async def test_save_korean_names_batch(self, service, mock_client, mock_db_manager):
        """한글 이름 배치 저장 테스트"""
        mock_db_manager.save_korean_names_batch = AsyncMock(return_value={
            "success": True,
            "saved": 2,
            "failed": 0,
            "total": 2,
            "results": [
                {"topic_en": "Hangro", "topic_kr": "한그로", "success": True},
                {"topic_en": "Test User", "topic_kr": "테스트", "success": True},
            ]
        })

        service._client = mock_client
        service._db_manager = mock_db_manager
        service._initialized = True

        result = await service.save_korean_names_batch(
            user_email="test@example.com",
            names=[
                {"topic_en": "Hangro", "topic_kr": "한그로"},
                {"topic_en": "Test User", "topic_kr": "테스트"},
            ]
        )

        assert result["success"] is True
        assert result["saved"] == 2
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_find_chat_by_name(self, service, mock_client, mock_db_manager):
        """이름으로 채팅 검색 테스트"""
        mock_db_manager.find_chat_by_name = AsyncMock(return_value="c1")

        service._client = mock_client
        service._db_manager = mock_db_manager
        service._initialized = True

        result = await service.find_chat_by_name(
            user_email="test@example.com",
            recipient_name="한그로"
        )

        assert result["success"] is True
        assert result["chat_id"] == "c1"

    @pytest.mark.asyncio
    async def test_find_chat_by_name_not_found(self, service, mock_client, mock_db_manager):
        """채팅 검색 실패 테스트"""
        mock_db_manager.find_chat_by_name = AsyncMock(return_value=None)

        service._client = mock_client
        service._db_manager = mock_db_manager
        service._initialized = True

        result = await service.find_chat_by_name(
            user_email="test@example.com",
            recipient_name="존재하지않는사용자"
        )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_sync_chats(self, service, mock_client, mock_db_manager):
        """채팅 동기화 테스트"""
        mock_client.list_chats = AsyncMock(return_value={
            "success": True,
            "chats": [
                {"id": "c1", "topic": "Chat 1", "chat_type": "oneOnOne"},
                {"id": "c2", "topic": "Chat 2", "chat_type": "group"},
            ],
            "count": 2,
        })
        mock_db_manager.sync_chats_to_db = AsyncMock(return_value={
            "success": True,
            "synced": 2,
            "deactivated": 0,
        })

        service._client = mock_client
        service._db_manager = mock_db_manager
        service._initialized = True

        result = await service.sync_chats(user_email="test@example.com")

        assert result["success"] is True
        assert result["chats_count"] == 2
        assert result["synced"] == 2

    @pytest.mark.asyncio
    async def test_get_chats_without_korean(self, service, mock_client, mock_db_manager):
        """한글 이름이 없는 채팅 조회 테스트"""
        mock_db_manager.get_chats_without_korean_names = AsyncMock(return_value=[
            {"chat_id": "c1", "peer_user_name": "John Doe"},
            {"chat_id": "c2", "peer_user_name": "Jane Smith"},
        ])

        service._client = mock_client
        service._db_manager = mock_db_manager
        service._initialized = True

        result = await service.get_chats_without_korean(user_email="test@example.com")

        assert result["success"] is True
        assert result["count"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
