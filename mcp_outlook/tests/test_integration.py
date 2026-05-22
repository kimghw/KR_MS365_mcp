"""
첨부파일 저장 시스템 통합 테스트

테스트 시나리오 (attachment_storage_plan.md 10.2절):
    1. 로컬 저장 + 원본
    2. 로컬 저장 + TXT 변환
    3. OneDrive 저장 + 원본 (4MB 이하)
    4. OneDrive 저장 + 원본 (4MB 초과, 청크 업로드)
    5. OneDrive 저장 + TXT 변환
    6. 변환 실패 시 fallback
    7. 중복 파일명 처리
    8. 메타데이터 중복 제거
"""

import pytest
import os
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
    BatchAttachmentHandler
)
from mcp_outlook.mail_attachment_storage import (
    LocalStorageBackend,
    OneDriveStorageBackend,
    MailFolderManager,
    get_storage_backend
)
from mcp_outlook.mail_attachment_converter import (
    ConversionPipeline,
    get_conversion_pipeline
)


class TestScenario1_LocalStorage_Original:
    """시나리오 1: 로컬 저장 + 원본"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = LocalStorageBackend(self.temp_dir)
        self.converter = None  # 변환 없음

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_save_pdf_original(self, sample_mail_data):
        """PDF 원본 저장"""
        # 폴더 생성
        folder_path = await self.storage.create_folder(sample_mail_data)

        # PDF 첨부파일 저장
        pdf_attachment = sample_mail_data["attachments"][0]
        content = base64.b64decode(pdf_attachment["contentBytes"])

        saved_path = await self.storage.save_file(
            folder_path,
            pdf_attachment["name"],
            content,
            pdf_attachment["contentType"]
        )

        assert saved_path is not None
        assert saved_path.endswith(".pdf")
        assert os.path.isfile(saved_path)

    @pytest.mark.asyncio
    async def test_save_mail_content(self, sample_mail_data):
        """메일 본문 저장"""
        folder_path = await self.storage.create_folder(sample_mail_data)

        mail_path = await self.storage.save_mail_content(folder_path, sample_mail_data)

        assert mail_path is not None
        with open(mail_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert sample_mail_data["subject"] in content


class TestScenario2_LocalStorage_TxtConversion:
    """시나리오 2: 로컬 저장 + TXT 변환"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = LocalStorageBackend(self.temp_dir)
        self.converter = get_conversion_pipeline()

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_convert_and_save_txt(self, sample_mail_data):
        """TXT 파일 변환 및 저장"""
        folder_path = await self.storage.create_folder(sample_mail_data)

        # TXT 내용 (UTF-8)
        txt_content = "This is test content.\n테스트 내용입니다.".encode("utf-8")

        # 변환 시도
        if self.converter.can_convert("test.txt"):
            converted_text, error = self.converter.convert(txt_content, "test.txt")
            assert error is None
            assert "test content" in converted_text

            # 저장
            saved_path = await self.storage.save_file(
                folder_path, "test.txt", txt_content
            )
            assert saved_path is not None


class TestScenario6_ConversionFallback:
    """시나리오 6: 변환 실패 시 fallback"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = LocalStorageBackend(self.temp_dir)
        self.converter = get_conversion_pipeline()

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unsupported_format_fallback(self):
        """지원하지 않는 형식은 fallback"""
        content = b"binary data"
        text, error = self.converter.convert(content, "file.xyz")

        assert text is None
        assert error is not None
        assert "지원하지 않는" in error

    def test_doc_format_not_implemented(self):
        """구 형식(.doc) 미지원"""
        from mcp_outlook.mail_attachment_converter import WordConverter

        converter = WordConverter()
        with pytest.raises(NotImplementedError):
            converter.convert(b"doc content", "old.doc")


class TestScenario7_DuplicateFilename:
    """시나리오 7: 중복 파일명 처리"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = LocalStorageBackend(self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_duplicate_filename_handling(self, sample_mail_data):
        """중복 파일명 자동 처리"""
        folder_path = await self.storage.create_folder(sample_mail_data)

        # 같은 이름으로 3번 저장
        paths = []
        for i in range(3):
            path = await self.storage.save_file(
                folder_path, "document.txt", f"content {i}".encode()
            )
            paths.append(path)

        # 모두 다른 경로여야 함
        assert len(set(paths)) == 3

        # 파일명 패턴 확인
        filenames = [os.path.basename(p) for p in paths]
        assert "document.txt" in filenames
        assert "document_1.txt" in filenames
        assert "document_2.txt" in filenames


class TestScenario8_MetadataDuplicateRemoval:
    """시나리오 8: 메타데이터 중복 제거"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.metadata_file = os.path.join(self.temp_dir, "metadata.json")
        self.metadata_manager = MailMetadataManager(self.metadata_file)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_duplicate_detection(self, sample_mail_data):
        """중복 메일 감지"""
        message_id = "test_msg_001"

        # 처음에는 중복 아님
        assert self.metadata_manager.is_duplicate(message_id) is False

        # 처리 후 중복으로 표시
        self.metadata_manager.add_processed_mail(
            message_id, sample_mail_data, "/path", ["file1.txt"]
        )
        assert self.metadata_manager.is_duplicate(message_id) is True

    def test_filter_new_messages(self, sample_mail_data):
        """새 메시지만 필터링"""
        # 일부 메시지 처리됨으로 등록
        self.metadata_manager.add_processed_mail(
            "processed_1", sample_mail_data, "/path", []
        )
        self.metadata_manager.add_processed_mail(
            "processed_2", sample_mail_data, "/path", []
        )

        all_ids = ["processed_1", "processed_2", "new_1", "new_2", "new_3"]
        new_ids = self.metadata_manager.filter_new_messages(all_ids)

        assert len(new_ids) == 3
        assert "new_1" in new_ids
        assert "new_2" in new_ids
        assert "new_3" in new_ids
        assert "processed_1" not in new_ids


class TestIntegrationLocalStorageWorkflow:
    """로컬 저장소 전체 워크플로우 통합 테스트"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_full_workflow_local(self, sample_mail_data):
        """전체 로컬 저장 워크플로우"""
        # 1. Storage Backend 생성
        storage = get_storage_backend(
            storage_type="local",
            base_directory=self.temp_dir
        )

        # 2. Converter 생성
        converter = get_conversion_pipeline()

        # 3. 폴더 생성
        folder_path = await storage.create_folder(sample_mail_data)
        assert os.path.isdir(folder_path)

        # 4. 메일 본문 저장
        mail_path = await storage.save_mail_content(folder_path, sample_mail_data)
        assert os.path.isfile(mail_path)

        # 5. 첨부파일 저장
        for attachment in sample_mail_data["attachments"]:
            content_bytes = attachment.get("contentBytes")
            if content_bytes:
                content = base64.b64decode(content_bytes)
                filename = attachment["name"]

                # 변환 시도
                if converter.can_convert(filename):
                    text, error = converter.convert(content, filename)
                    if text:
                        txt_filename = converter.convert_to_txt_filename(filename)
                        await storage.save_file(
                            folder_path, txt_filename, text.encode("utf-8")
                        )
                    else:
                        # fallback: 원본 저장
                        await storage.save_file(
                            folder_path, filename, content
                        )
                else:
                    # 변환 불가: 원본 저장
                    await storage.save_file(
                        folder_path, filename, content
                    )

        # 6. 결과 확인
        files = os.listdir(folder_path)
        assert "mail_content.txt" in files
        assert len(files) >= 2  # 메일 본문 + 최소 1개 첨부파일


class TestOneDriveStorageMocked:
    """OneDrive 저장소 (모킹) 테스트"""

    @pytest.mark.asyncio
    async def test_onedrive_backend_creation(self, mock_auth_manager):
        """OneDrive Backend 생성"""
        storage = get_storage_backend(
            storage_type="onedrive",
            auth_manager=mock_auth_manager,
            user_email="test@example.com",
            base_folder="/Mail/Attachments"
        )

        assert isinstance(storage, OneDriveStorageBackend)
        assert storage.user_email == "test@example.com"

    @pytest.mark.asyncio
    async def test_onedrive_folder_name_creation(self, mock_auth_manager, sample_mail_data):
        """OneDrive 폴더명 생성"""
        storage = OneDriveStorageBackend(
            auth_manager=mock_auth_manager,
            user_email="test@example.com",
            base_folder="/Attachments"
        )

        folder_name = storage.create_folder_name(sample_mail_data)
        assert "20250109" in folder_name
        assert "Test Sender" in folder_name
