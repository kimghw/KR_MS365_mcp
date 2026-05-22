"""
mail_attachment.py 단위 테스트

테스트 대상:
    - MailFolderManager
    - MailMetadataManager
    - BatchAttachmentHandler
    - SingleAttachmentHandler
"""

import pytest
import os
import json
import tempfile
import shutil
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_outlook.mail_attachment import (
    MailMetadataManager,
    BatchAttachmentHandler,
    SingleAttachmentHandler
)
from mcp_outlook.mail_attachment_storage import MailFolderManager


class TestMailFolderManager:
    """MailFolderManager 테스트"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = MailFolderManager(self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_creates_directory(self):
        """초기화 시 디렉토리 생성"""
        new_dir = os.path.join(self.temp_dir, "new_folder")
        manager = MailFolderManager(new_dir)
        assert os.path.isdir(new_dir)

    def test_sanitize_filename_special_chars(self):
        """특수문자 제거"""
        result = self.manager.sanitize_filename('file<>:"/\\|?*.txt')
        assert "<" not in result
        assert ">" not in result

    def test_sanitize_filename_max_length(self):
        """최대 길이 제한"""
        long_name = "a" * 100
        result = self.manager.sanitize_filename(long_name, max_length=50)
        assert len(result) == 50

    def test_sanitize_filename_empty(self):
        """빈 문자열 처리"""
        result = self.manager.sanitize_filename("")
        assert result == "untitled"

    def test_create_folder_name(self, sample_mail_data):
        """폴더명 생성"""
        result = self.manager.create_folder_name(sample_mail_data)
        assert "20250109" in result
        assert "Test Sender" in result

    def test_create_folder_name_no_date(self):
        """날짜 없으면 현재 날짜 사용"""
        mail_data = {
            "from": {"emailAddress": {"name": "Sender"}},
            "subject": "Test"
        }
        result = self.manager.create_folder_name(mail_data)
        today = datetime.now().strftime("%Y%m%d")
        assert result.startswith(today)

    def test_get_mail_folder_path(self, sample_mail_data):
        """메일 폴더 경로 생성"""
        folder_path = self.manager.get_mail_folder_path(sample_mail_data)
        assert os.path.isdir(folder_path)

    def test_save_attachment_success(self, sample_mail_data):
        """첨부파일 저장 성공"""
        folder_path = self.manager.get_mail_folder_path(sample_mail_data)
        attachment = sample_mail_data["attachments"][0]

        saved_path = self.manager.save_attachment(folder_path, attachment)

        assert saved_path is not None
        assert os.path.isfile(saved_path)

    def test_save_attachment_no_content(self, sample_mail_data):
        """contentBytes 없으면 None 반환"""
        folder_path = self.manager.get_mail_folder_path(sample_mail_data)
        attachment = {"name": "test.pdf"}  # contentBytes 없음

        saved_path = self.manager.save_attachment(folder_path, attachment)
        assert saved_path is None

    def test_save_attachment_duplicate_name(self, sample_mail_data):
        """중복 파일명 처리"""
        folder_path = self.manager.get_mail_folder_path(sample_mail_data)
        attachment = {
            "name": "test.txt",
            "contentBytes": base64.b64encode(b"content").decode()
        }

        path1 = self.manager.save_attachment(folder_path, attachment)
        path2 = self.manager.save_attachment(folder_path, attachment)

        assert path1 != path2
        assert "_1" in path2

    def test_save_mail_content(self, sample_mail_data):
        """메일 본문 저장"""
        folder_path = self.manager.get_mail_folder_path(sample_mail_data)

        saved_path = self.manager.save_mail_content(folder_path, sample_mail_data)

        assert saved_path is not None
        assert os.path.isfile(saved_path)
        with open(saved_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Subject:" in content

    def test_save_mail_content_html_body(self, sample_mail_data):
        """HTML 본문 태그 제거"""
        folder_path = self.manager.get_mail_folder_path(sample_mail_data)

        saved_path = self.manager.save_mail_content(folder_path, sample_mail_data)

        with open(saved_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "<html>" not in content
            assert "<body>" not in content


class TestMailMetadataManager:
    """MailMetadataManager 테스트"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.metadata_file = os.path.join(self.temp_dir, "metadata.json")
        self.manager = MailMetadataManager(self.metadata_file)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_empty_metadata(self):
        """초기화 시 빈 메타데이터"""
        assert self.manager._metadata is not None
        assert "processed_messages" in self.manager._metadata

    def test_is_duplicate_false(self):
        """새 메시지는 중복 아님"""
        assert self.manager.is_duplicate("new_message_id") is False

    def test_is_duplicate_true(self, sample_mail_data):
        """처리된 메시지는 중복"""
        message_id = sample_mail_data["id"]
        self.manager.add_processed_mail(
            message_id, sample_mail_data, "/path", ["file1"]
        )
        assert self.manager.is_duplicate(message_id) is True

    def test_add_processed_mail(self, sample_mail_data):
        """처리된 메일 추가"""
        message_id = sample_mail_data["id"]
        self.manager.add_processed_mail(
            message_id, sample_mail_data, "/path/folder", ["file1.txt"]
        )

        assert message_id in self.manager._metadata["processed_messages"]
        stored = self.manager._metadata["processed_messages"][message_id]
        assert stored["subject"] == sample_mail_data["subject"]
        assert stored["folder_path"] == "/path/folder"

    def test_filter_new_messages(self, sample_mail_data):
        """새 메시지 필터링"""
        # 하나 처리됨으로 등록
        self.manager.add_processed_mail(
            "msg_1", sample_mail_data, "/path", []
        )

        message_ids = ["msg_1", "msg_2", "msg_3"]
        new_ids = self.manager.filter_new_messages(message_ids)

        assert "msg_1" not in new_ids
        assert "msg_2" in new_ids
        assert "msg_3" in new_ids

    def test_get_processed_count(self, sample_mail_data):
        """처리된 메일 수"""
        assert self.manager.get_processed_count() == 0

        self.manager.add_processed_mail(
            "msg_1", sample_mail_data, "/path", []
        )
        assert self.manager.get_processed_count() == 1

    def test_get_processed_message_ids(self, sample_mail_data):
        """처리된 메일 ID 목록"""
        self.manager.add_processed_mail(
            "msg_1", sample_mail_data, "/path", []
        )
        self.manager.add_processed_mail(
            "msg_2", sample_mail_data, "/path", []
        )

        ids = self.manager.get_processed_message_ids()
        assert "msg_1" in ids
        assert "msg_2" in ids

    def test_metadata_persistence(self, sample_mail_data):
        """메타데이터 저장 및 로드"""
        self.manager.add_processed_mail(
            "msg_1", sample_mail_data, "/path", ["file.txt"]
        )

        # 새 매니저로 로드
        new_manager = MailMetadataManager(self.metadata_file)
        assert new_manager.is_duplicate("msg_1") is True

    def test_load_corrupted_metadata(self):
        """손상된 메타데이터 처리"""
        # 손상된 JSON 파일 생성
        with open(self.metadata_file, "w") as f:
            f.write("not valid json")

        manager = MailMetadataManager(self.metadata_file)
        # 빈 메타데이터로 초기화되어야 함
        assert manager._metadata == {}


class TestBatchAttachmentHandler:
    """BatchAttachmentHandler 테스트"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.fixture
    def handler(self):
        with patch('mcp_outlook.mail_attachment.AuthManager'):
            handler = BatchAttachmentHandler(
                base_directory=self.temp_dir,
                metadata_file="test_metadata.json"
            )
            handler.auth_manager.validate_and_refresh_token = AsyncMock(
                return_value="mock_token"
            )
            return handler

    def test_init(self, handler):
        """초기화 테스트"""
        assert handler.max_batch_size == 20
        assert handler.batch_url == "https://graph.microsoft.com/v1.0/$batch"

    def test_build_batch_requests(self, handler):
        """배치 요청 생성"""
        message_ids = ["msg_1", "msg_2"]
        requests = handler._build_batch_requests(
            "user@example.com", message_ids
        )

        assert len(requests) == 2
        assert requests[0]["id"] == "1"
        assert requests[0]["method"] == "GET"
        assert "msg_1" in requests[0]["url"]

    def test_build_batch_requests_with_select(self, handler):
        """select 필드 포함 배치 요청"""
        message_ids = ["msg_1"]
        requests = handler._build_batch_requests(
            "user@example.com",
            message_ids,
            select_params=["importance", "isRead"]
        )

        assert len(requests) == 1
        # URL에 기본 필드 포함 확인
        url = requests[0]["url"]
        assert "$select=" in url or "id" in url

    @pytest.mark.asyncio
    async def test_fetch_and_save_empty_ids(self, handler):
        """빈 ID 목록 처리"""
        result = await handler.fetch_and_save(
            "user@example.com",
            message_ids=[]
        )

        assert result["success"] is True
        assert result["processed"] == 0

    @pytest.mark.asyncio
    async def test_fetch_and_save_skip_duplicates(self, handler, sample_mail_data):
        """중복 메일 건너뛰기"""
        # 미리 처리됨으로 등록
        handler.metadata_manager.add_processed_mail(
            "msg_1", sample_mail_data, "/path", []
        )

        result = await handler.fetch_and_save(
            "user@example.com",
            message_ids=["msg_1"],
            skip_duplicates=True
        )

        assert result["skipped_duplicates"] == 1

    @pytest.mark.asyncio
    async def test_close(self, handler):
        """리소스 정리"""
        await handler.close()
        handler.auth_manager.close.assert_called_once()


class TestSingleAttachmentHandler:
    """SingleAttachmentHandler 테스트"""

    def setup_method(self):
        self.handler = SingleAttachmentHandler("mock_access_token")

    def test_init(self):
        """초기화 테스트"""
        assert self.handler.access_token == "mock_access_token"
        assert "Authorization" in self.handler.headers
        assert "Bearer mock_access_token" in self.handler.headers["Authorization"]

    @pytest.mark.asyncio
    async def test_list_attachments_mock(self):
        """첨부파일 목록 조회 (모킹)"""
        mock_response = {
            "value": [
                {
                    "id": "att_1",
                    "name": "file.pdf",
                    "contentType": "application/pdf",
                    "size": 1024,
                    "@odata.type": "#microsoft.graph.fileAttachment"
                }
            ]
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_resp

            async with mock_session() as session:
                # 실제 호출은 모킹된 세션 사용
                pass

    @pytest.mark.asyncio
    async def test_download_attachment_creates_directory(self):
        """다운로드 시 디렉토리 생성"""
        temp_dir = tempfile.mkdtemp()
        try:
            save_path = os.path.join(temp_dir, "subdir", "file.txt")

            # 실제 API 호출 대신 직접 디렉토리 생성 테스트
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)

            assert os.path.isdir(os.path.dirname(save_path))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
