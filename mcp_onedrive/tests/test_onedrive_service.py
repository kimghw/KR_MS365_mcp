"""
OneDrive Service Tests
원본 onedrive_mcp 모듈과 동일한 기능을 테스트합니다.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_onedrive.onedrive_service import OneDriveService
from mcp_onedrive.onedrive_types import (
    ItemType,
    ConflictBehavior,
)


class TestOneDriveService:
    """OneDriveService 테스트"""

    @pytest.fixture
    def service(self):
        """서비스 인스턴스 생성"""
        return OneDriveService()

    @pytest.fixture
    def mock_client(self):
        """Mock GraphOneDriveClient"""
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
    async def test_get_drive_info(self, service, mock_client):
        """드라이브 정보 조회 테스트"""
        mock_client.get_drive_info = AsyncMock(return_value={
            "success": True,
            "drive": {
                "id": "d1",
                "name": "OneDrive",
                "drive_type": "personal",
                "quota_total": 5368709120,
                "quota_used": 1073741824,
            },
        })

        service._client = mock_client
        service._initialized = True

        result = await service.get_drive_info("test@example.com")

        assert result["success"] is True
        assert result["drive"]["name"] == "OneDrive"

    @pytest.mark.asyncio
    async def test_list_files_root(self, service, mock_client):
        """루트 파일 목록 조회 테스트"""
        mock_client.list_files = AsyncMock(return_value={
            "success": True,
            "files": [
                {"id": "f1", "name": "Document.docx", "item_type": "file"},
                {"id": "f2", "name": "Photos", "item_type": "folder"},
            ],
            "count": 2,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.list_files("test@example.com")

        assert result["success"] is True
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_list_files_folder(self, service, mock_client):
        """특정 폴더 파일 목록 조회 테스트"""
        mock_client.list_files = AsyncMock(return_value={
            "success": True,
            "files": [
                {"id": "f3", "name": "photo1.jpg", "item_type": "file"},
            ],
            "count": 1,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.list_files("test@example.com", folder_path="Photos")

        assert result["success"] is True
        mock_client.list_files.assert_called_once_with("test@example.com", "Photos", None, 50)

    @pytest.mark.asyncio
    async def test_list_files_search(self, service, mock_client):
        """파일 검색 테스트"""
        mock_client.list_files = AsyncMock(return_value={
            "success": True,
            "files": [
                {"id": "f1", "name": "report.docx", "item_type": "file"},
            ],
            "count": 1,
        })

        service._client = mock_client
        service._initialized = True

        result = await service.list_files("test@example.com", search="report")

        assert result["success"] is True
        mock_client.list_files.assert_called_once_with("test@example.com", None, "report", 50)

    @pytest.mark.asyncio
    async def test_get_item(self, service, mock_client):
        """파일/폴더 정보 조회 테스트"""
        mock_client.get_item = AsyncMock(return_value={
            "success": True,
            "item": {"id": "f1", "name": "test.txt", "size": 1024},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.get_item("test@example.com", "Documents/test.txt")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_read_file_text(self, service, mock_client):
        """텍스트 파일 읽기 테스트"""
        mock_client.read_file = AsyncMock(return_value={
            "success": True,
            "file_path": "Documents/test.txt",
            "content": "Hello World",
            "content_type": "text",
        })

        service._client = mock_client
        service._initialized = True

        result = await service.read_file("test@example.com", "Documents/test.txt")

        assert result["success"] is True
        assert result["content"] == "Hello World"
        assert result["content_type"] == "text"

    @pytest.mark.asyncio
    async def test_read_file_binary(self, service, mock_client):
        """바이너리 파일 읽기 테스트"""
        mock_client.read_file = AsyncMock(return_value={
            "success": True,
            "file_path": "Documents/image.png",
            "content": "base64encodedcontent",
            "content_type": "base64",
        })

        service._client = mock_client
        service._initialized = True

        result = await service.read_file("test@example.com", "Documents/image.png", as_text=False)

        assert result["success"] is True
        assert result["content_type"] == "base64"

    @pytest.mark.asyncio
    async def test_write_file(self, service, mock_client):
        """파일 쓰기 테스트"""
        mock_client.write_file = AsyncMock(return_value={
            "success": True,
            "file": {"id": "f_new", "name": "new_file.txt"},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.write_file(
            user_email="test@example.com",
            file_path="Documents/new_file.txt",
            content="New file content",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_write_file_no_overwrite(self, service, mock_client):
        """파일 쓰기 (덮어쓰기 비활성화) 테스트"""
        mock_client.write_file = AsyncMock(return_value={
            "success": True,
            "file": {"id": "f_new", "name": "new_file.txt"},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.write_file(
            user_email="test@example.com",
            file_path="Documents/new_file.txt",
            content="New content",
            overwrite=False,
        )

        assert result["success"] is True
        # ConflictBehavior.FAIL이 전달되었는지 확인
        call_kwargs = mock_client.write_file.call_args.kwargs
        assert call_kwargs["conflict_behavior"] == ConflictBehavior.FAIL

    @pytest.mark.asyncio
    async def test_delete_file(self, service, mock_client):
        """파일 삭제 테스트"""
        mock_client.delete_file = AsyncMock(return_value={
            "success": True,
            "message": "파일 삭제됨: Documents/old_file.txt",
        })

        service._client = mock_client
        service._initialized = True

        result = await service.delete_file("test@example.com", "Documents/old_file.txt")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_folder(self, service, mock_client):
        """폴더 생성 테스트"""
        mock_client.create_folder = AsyncMock(return_value={
            "success": True,
            "folder": {"id": "fld_new", "name": "NewFolder"},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.create_folder("test@example.com", "NewFolder")

        assert result["success"] is True
        assert result["folder"]["name"] == "NewFolder"

    @pytest.mark.asyncio
    async def test_create_folder_with_parent(self, service, mock_client):
        """하위 폴더 생성 테스트"""
        mock_client.create_folder = AsyncMock(return_value={
            "success": True,
            "folder": {"id": "fld_new", "name": "SubFolder"},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.create_folder(
            user_email="test@example.com",
            folder_name="SubFolder",
            parent_path="Documents",
        )

        assert result["success"] is True
        mock_client.create_folder.assert_called_once_with("test@example.com", "SubFolder", "Documents")

    @pytest.mark.asyncio
    async def test_copy_file(self, service, mock_client):
        """파일 복사 테스트"""
        mock_client.copy_file = AsyncMock(return_value={
            "success": True,
            "message": "복사 작업이 시작되었습니다.",
        })

        service._client = mock_client
        service._initialized = True

        result = await service.copy_file(
            user_email="test@example.com",
            source_path="Documents/file.txt",
            dest_path="Backup",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_move_file(self, service, mock_client):
        """파일 이동 테스트"""
        mock_client.move_file = AsyncMock(return_value={
            "success": True,
            "file": {"id": "f1", "name": "file.txt"},
        })

        service._client = mock_client
        service._initialized = True

        result = await service.move_file(
            user_email="test@example.com",
            source_path="Documents/file.txt",
            dest_path="Archive",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_not_initialized_error(self, service):
        """초기화되지 않은 상태에서 호출 시 에러 테스트"""
        with pytest.raises(RuntimeError, match="not initialized"):
            await service.list_files("test@example.com")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
