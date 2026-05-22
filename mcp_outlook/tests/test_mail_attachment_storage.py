"""
mail_attachment_storage.py 단위 테스트

테스트 대상:
    - StorageBackend (ABC)
    - LocalStorageBackend
    - OneDriveStorageBackend
    - get_storage_backend (팩토리 함수)
"""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mail_attachment_storage import (
    StorageBackend,
    LocalStorageBackend,
    OneDriveStorageBackend,
    get_storage_backend
)


class TestStorageBackendSanitizeFilename:
    """StorageBackend.sanitize_filename 테스트"""

    def setup_method(self):
        self.storage = LocalStorageBackend(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.storage.base_directory, ignore_errors=True)

    def test_remove_special_chars(self):
        """특수문자 제거"""
        result = self.storage.sanitize_filename('file<>:"/\\|?*.txt')
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert '"' not in result
        assert "/" not in result
        assert "\\" not in result
        assert "|" not in result
        assert "?" not in result
        assert "*" not in result

    def test_max_length(self):
        """최대 길이 제한"""
        long_name = "a" * 100
        result = self.storage.sanitize_filename(long_name, max_length=50)
        assert len(result) == 50

    def test_whitespace_normalization(self):
        """공백 정규화"""
        result = self.storage.sanitize_filename("file   name   test.txt")
        assert "   " not in result
        assert result == "file name test.txt"

    def test_empty_to_untitled(self):
        """빈 문자열 → untitled"""
        result = self.storage.sanitize_filename("")
        assert result == "untitled"

    def test_only_special_chars_to_untitled(self):
        """특수문자만 있으면 → untitled"""
        result = self.storage.sanitize_filename("<>:?*")
        assert result == "untitled"


class TestStorageBackendCreateFolderName:
    """StorageBackend.create_folder_name 테스트"""

    def setup_method(self):
        self.storage = LocalStorageBackend(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.storage.base_directory, ignore_errors=True)

    def test_basic_folder_name(self, sample_mail_data):
        """기본 폴더명 생성"""
        result = self.storage.create_folder_name(sample_mail_data)
        # 형식: YYYYMMDD_보낸사람_제목
        assert result.startswith("20250109")
        assert "Test Sender" in result
        assert "테스트" in result

    def test_folder_name_with_z_timezone(self):
        """Z 타임존 처리"""
        mail_data = {
            "receivedDateTime": "2025-01-09T10:30:00Z",
            "from": {"emailAddress": {"name": "Sender", "address": "sender@test.com"}},
            "subject": "Test Subject"
        }
        result = self.storage.create_folder_name(mail_data)
        assert result.startswith("20250109")

    def test_folder_name_invalid_date_fallback(self):
        """잘못된 날짜 → 현재 날짜 fallback"""
        mail_data = {
            "receivedDateTime": "invalid-date",
            "from": {"emailAddress": {"name": "Sender"}},
            "subject": "Test"
        }
        result = self.storage.create_folder_name(mail_data)
        today = datetime.now().strftime("%Y%m%d")
        assert result.startswith(today)

    def test_folder_name_no_date_fallback(self):
        """날짜 없음 → 현재 날짜 fallback"""
        mail_data = {
            "from": {"emailAddress": {"name": "Sender"}},
            "subject": "Test"
        }
        result = self.storage.create_folder_name(mail_data)
        today = datetime.now().strftime("%Y%m%d")
        assert result.startswith(today)

    def test_folder_name_sender_from_address(self):
        """보낸사람 이름 없으면 주소 사용"""
        mail_data = {
            "receivedDateTime": "2025-01-09T10:00:00Z",
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "subject": "Test"
        }
        result = self.storage.create_folder_name(mail_data)
        assert "sender@example.com" in result or "senderexample.com" in result


class TestLocalStorageBackend:
    """LocalStorageBackend 테스트"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = LocalStorageBackend(self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_create_folder(self, sample_mail_data):
        """폴더 생성"""
        folder_path = await self.storage.create_folder(sample_mail_data)
        assert os.path.isdir(folder_path)

    @pytest.mark.asyncio
    async def test_save_file(self, sample_mail_data):
        """파일 저장"""
        folder_path = await self.storage.create_folder(sample_mail_data)
        content = b"Test file content"

        saved_path = await self.storage.save_file(
            folder_path, "test_file.txt", content, "text/plain"
        )

        assert saved_path is not None
        assert os.path.isfile(saved_path)
        with open(saved_path, "rb") as f:
            assert f.read() == content

    @pytest.mark.asyncio
    async def test_save_file_duplicate_name(self, sample_mail_data):
        """중복 파일명 처리"""
        folder_path = await self.storage.create_folder(sample_mail_data)

        # 첫 번째 파일
        path1 = await self.storage.save_file(folder_path, "file.txt", b"content1")
        # 두 번째 파일 (같은 이름)
        path2 = await self.storage.save_file(folder_path, "file.txt", b"content2")

        assert path1 != path2
        assert os.path.basename(path1) == "file.txt"
        assert "file_1.txt" in path2

    @pytest.mark.asyncio
    async def test_save_mail_content(self, sample_mail_data):
        """메일 본문 저장"""
        folder_path = await self.storage.create_folder(sample_mail_data)

        saved_path = await self.storage.save_mail_content(folder_path, sample_mail_data)

        assert saved_path is not None
        assert os.path.isfile(saved_path)
        with open(saved_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Subject:" in content
            assert "From:" in content
            assert sample_mail_data["subject"] in content

    @pytest.mark.asyncio
    async def test_save_mail_content_html_strip(self, sample_mail_data):
        """HTML 태그 제거 확인"""
        folder_path = await self.storage.create_folder(sample_mail_data)

        saved_path = await self.storage.save_mail_content(folder_path, sample_mail_data)

        with open(saved_path, "r", encoding="utf-8") as f:
            content = f.read()
            # HTML 태그가 제거되어야 함
            assert "<html>" not in content
            assert "<body>" not in content
            assert "<p>" not in content


class TestOneDriveStorageBackend:
    """OneDriveStorageBackend 테스트"""

    def setup_method(self):
        self.mock_auth = MagicMock()
        self.mock_auth.validate_and_refresh_token = AsyncMock(return_value="mock_token")

    @pytest.mark.asyncio
    async def test_init(self):
        """초기화 테스트"""
        storage = OneDriveStorageBackend(
            auth_manager=self.mock_auth,
            user_email="test@example.com",
            base_folder="/TestFolder"
        )
        assert storage.user_email == "test@example.com"
        assert storage.base_folder == "TestFolder"

    @pytest.mark.asyncio
    async def test_get_access_token(self):
        """토큰 획득 테스트"""
        storage = OneDriveStorageBackend(
            auth_manager=self.mock_auth,
            user_email="test@example.com"
        )
        token = await storage._get_access_token()
        assert token == "mock_token"

    @pytest.mark.asyncio
    async def test_get_access_token_failure(self):
        """토큰 획득 실패"""
        self.mock_auth.validate_and_refresh_token = AsyncMock(
            side_effect=Exception("Token error")
        )
        storage = OneDriveStorageBackend(
            auth_manager=self.mock_auth,
            user_email="test@example.com"
        )
        token = await storage._get_access_token()
        assert token is None

    @pytest.mark.asyncio
    async def test_upload_size_check(self):
        """업로드 크기 상수 확인"""
        storage = OneDriveStorageBackend(
            auth_manager=self.mock_auth,
            user_email="test@example.com"
        )
        assert storage.SIMPLE_UPLOAD_MAX_SIZE == 4 * 1024 * 1024  # 4MB
        assert storage.CHUNK_SIZE == 10 * 1024 * 1024  # 10MB
        assert storage.MAX_FILE_SIZE == 250 * 1024 * 1024 * 1024  # 250GB


class TestGetStorageBackend:
    """get_storage_backend 팩토리 함수 테스트"""

    def test_local_storage_default(self):
        """기본값 = local storage"""
        storage = get_storage_backend()
        assert isinstance(storage, LocalStorageBackend)

    def test_local_storage_explicit(self, temp_directory):
        """명시적 local storage"""
        storage = get_storage_backend(
            storage_type="local",
            base_directory=temp_directory
        )
        assert isinstance(storage, LocalStorageBackend)
        assert str(storage.base_directory) == temp_directory

    def test_onedrive_storage(self, mock_auth_manager):
        """OneDrive storage"""
        storage = get_storage_backend(
            storage_type="onedrive",
            auth_manager=mock_auth_manager,
            user_email="test@example.com",
            base_folder="/TestFolder"
        )
        assert isinstance(storage, OneDriveStorageBackend)

    def test_onedrive_requires_auth_manager(self):
        """OneDrive는 auth_manager 필수"""
        with pytest.raises(ValueError):
            get_storage_backend(
                storage_type="onedrive",
                user_email="test@example.com"
            )

    def test_onedrive_requires_user_email(self, mock_auth_manager):
        """OneDrive는 user_email 필수"""
        with pytest.raises(ValueError):
            get_storage_backend(
                storage_type="onedrive",
                auth_manager=mock_auth_manager
            )
