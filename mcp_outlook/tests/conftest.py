"""
첨부파일 저장 시스템 테스트 공통 Fixtures

테스트 시나리오:
    1. 로컬 저장 + 원본
    2. 로컬 저장 + TXT 변환
    3. OneDrive 저장 + 원본 (4MB 이하)
    4. OneDrive 저장 + 원본 (4MB 초과, 청크 업로드)
    5. OneDrive 저장 + TXT 변환
    6. 변환 실패 시 fallback
    7. 중복 파일명 처리
    8. 메타데이터 중복 제거
"""

import os
import sys
import pytest
import tempfile
import shutil
import json
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# 프로젝트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def temp_directory():
    """임시 디렉토리 생성 및 정리"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_mail_data():
    """테스트용 메일 데이터"""
    return {
        "id": "AAMkADU2MGM5YzRjLTE4NmItNDE4NC1hMGI3LTk1NDkwZjY2NGY4ZQBGAAAAAANBKRsD4lAXQZzoWzEdTmo7BwCPaix-hUChSr7TxmyhTjRvAAAAAAEMAACP",
        "subject": "테스트 메일 제목",
        "receivedDateTime": "2025-01-09T10:30:00Z",
        "from": {
            "emailAddress": {
                "name": "Test Sender",
                "address": "sender@example.com"
            }
        },
        "toRecipients": [
            {
                "emailAddress": {
                    "name": "Test Recipient",
                    "address": "recipient@example.com"
                }
            }
        ],
        "body": {
            "contentType": "html",
            "content": "<html><body><p>This is a test email body.</p></body></html>"
        },
        "hasAttachments": True,
        "attachments": [
            {
                "id": "att_001",
                "name": "test_document.pdf",
                "contentType": "application/pdf",
                "size": 1024,
                "isInline": False,
                "@odata.type": "#microsoft.graph.fileAttachment",
                "contentBytes": base64.b64encode(b"PDF content here").decode()
            },
            {
                "id": "att_002",
                "name": "test_image.png",
                "contentType": "image/png",
                "size": 2048,
                "isInline": True,
                "@odata.type": "#microsoft.graph.fileAttachment",
                "contentBytes": base64.b64encode(b"PNG content here").decode()
            }
        ]
    }


@pytest.fixture
def sample_mail_data_no_attachments():
    """첨부파일 없는 메일 데이터"""
    return {
        "id": "AAMkADU2MGM5YzRjLTE4NmItNDE4NC1hMGI3LTk1NDkwZjY2NGY4ZQBGAAAAAANBKRsD4lAXQZzoWzEdTmo7BwCPaix",
        "subject": "첨부파일 없는 메일",
        "receivedDateTime": "2025-01-09T11:00:00Z",
        "from": {
            "emailAddress": {
                "name": "Another Sender",
                "address": "another@example.com"
            }
        },
        "body": {
            "contentType": "text",
            "content": "Plain text email body."
        },
        "hasAttachments": False,
        "attachments": []
    }


@pytest.fixture
def sample_large_attachment():
    """대용량 첨부파일 (5MB)"""
    content = b"X" * (5 * 1024 * 1024)  # 5MB
    return {
        "id": "att_large",
        "name": "large_file.bin",
        "contentType": "application/octet-stream",
        "size": len(content),
        "isInline": False,
        "@odata.type": "#microsoft.graph.fileAttachment",
        "contentBytes": base64.b64encode(content).decode()
    }


@pytest.fixture
def mock_auth_manager():
    """모의 AuthManager"""
    mock = MagicMock()
    mock.validate_and_refresh_token = AsyncMock(return_value="mock_access_token_12345")
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_aiohttp_session():
    """모의 aiohttp ClientSession"""
    mock_session = MagicMock()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"responses": []})
    mock_response.text = AsyncMock(return_value="")

    mock_session.post = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_response),
        __aexit__=AsyncMock(return_value=None)
    ))
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_response),
        __aexit__=AsyncMock(return_value=None)
    ))
    mock_session.put = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_response),
        __aexit__=AsyncMock(return_value=None)
    ))
    mock_session.delete = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_response),
        __aexit__=AsyncMock(return_value=None)
    ))

    return mock_session


@pytest.fixture
def sample_pdf_content():
    """테스트용 PDF 바이트 (실제 PDF 구조 시뮬레이션)"""
    # 간단한 PDF 구조
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


@pytest.fixture
def sample_docx_content():
    """테스트용 DOCX 바이트 (실제 테스트시 python-docx로 생성)"""
    # DOCX는 ZIP 포맷이므로 간단히 모킹
    return b"PK\x03\x04...DOCX content..."


@pytest.fixture
def sample_txt_content():
    """테스트용 TXT 파일"""
    return "This is a plain text file.\nLine 2.\nLine 3.".encode("utf-8")


@pytest.fixture
def sample_csv_content():
    """테스트용 CSV 파일"""
    return "name,age,city\nAlice,30,Seoul\nBob,25,Busan".encode("utf-8")


@pytest.fixture
def batch_response_success(sample_mail_data):
    """성공적인 배치 응답"""
    return {
        "responses": [
            {
                "id": "1",
                "status": 200,
                "body": sample_mail_data
            }
        ]
    }


@pytest.fixture
def batch_response_partial_failure(sample_mail_data):
    """부분 실패 배치 응답"""
    return {
        "responses": [
            {
                "id": "1",
                "status": 200,
                "body": sample_mail_data
            },
            {
                "id": "2",
                "status": 404,
                "body": {
                    "error": {
                        "code": "ErrorItemNotFound",
                        "message": "The specified object was not found in the store."
                    }
                }
            }
        ]
    }


@pytest.fixture
def onedrive_upload_session_response():
    """OneDrive Upload Session 생성 응답"""
    return {
        "uploadUrl": "https://graph.microsoft.com/v1.0/upload/session/abc123",
        "expirationDateTime": "2025-01-10T10:00:00Z"
    }


@pytest.fixture
def onedrive_upload_complete_response():
    """OneDrive 업로드 완료 응답"""
    return {
        "id": "01BYE5RZ5MYLM2QQXHRBF3ZTPJX2VH7JLN",
        "name": "test_file.txt",
        "webUrl": "https://onedrive.live.com/redir?resid=...",
        "size": 1024
    }
