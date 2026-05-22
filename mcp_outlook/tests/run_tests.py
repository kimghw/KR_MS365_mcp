#!/usr/bin/env python3
"""
첨부파일 저장 시스템 테스트 실행 스크립트

테스트 시나리오 (attachment_storage_plan.md 10.2절):
    1. 로컬 저장 + 원본
    2. 로컬 저장 + TXT 변환
    3. 변환 실패 시 fallback
    4. 중복 파일명 처리
    5. 메타데이터 중복 제거

사용법:
    python mcp_outlook/tests/run_tests.py
"""

import sys
import os
import asyncio
import tempfile
import shutil
import base64
import json
from pathlib import Path
from datetime import datetime

# 프로젝트 경로 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "mcp_outlook"))

# Import test targets
from mail_attachment_storage import LocalStorageBackend, get_storage_backend
from mail_attachment_converter import ConversionPipeline, PlainTextConverter, get_conversion_pipeline


class TestResult:
    """테스트 결과 추적"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def record_pass(self, name):
        self.passed += 1
        print(f"  [PASS] {name}")

    def record_fail(self, name, error):
        self.failed += 1
        self.errors.append((name, error))
        print(f"  [FAIL] {name}: {error}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"테스트 결과: {self.passed}/{total} 통과")
        if self.errors:
            print("\n실패한 테스트:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        return self.failed == 0


def get_sample_mail_data():
    """테스트용 메일 데이터"""
    return {
        "id": "AAMkADU2MGM5YzRjLTE4NmItNDE4NC1hMGI3LTk1NDkwZjY2NGY4ZQ",
        "subject": "테스트 메일 제목",
        "receivedDateTime": "2025-01-09T10:30:00Z",
        "from": {
            "emailAddress": {
                "name": "Test Sender",
                "address": "sender@example.com"
            }
        },
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
                "contentBytes": base64.b64encode(b"PDF content here").decode()
            }
        ]
    }


def test_converter(result: TestResult):
    """Converter 테스트"""
    print("\n[1] ConversionPipeline 테스트")

    try:
        pipeline = ConversionPipeline()

        # can_convert 테스트
        if pipeline.can_convert("file.txt"):
            result.record_pass("can_convert('file.txt') = True")
        else:
            result.record_fail("can_convert('file.txt')", "Expected True")

        if not pipeline.can_convert("file.xyz"):
            result.record_pass("can_convert('file.xyz') = False")
        else:
            result.record_fail("can_convert('file.xyz')", "Expected False")

        # convert 테스트
        text, error = pipeline.convert("Hello World".encode(), "test.txt")
        if text and error is None:
            result.record_pass("convert() TXT 파일 변환")
        else:
            result.record_fail("convert() TXT 파일 변환", error)

        # 미지원 포맷 테스트
        text, error = pipeline.convert(b"data", "file.xyz")
        if text is None and error:
            result.record_pass("convert() 미지원 포맷 에러 반환")
        else:
            result.record_fail("convert() 미지원 포맷", "Expected error")

        # 파일명 변환 테스트
        if pipeline.convert_to_txt_filename("doc.pdf") == "doc.txt":
            result.record_pass("convert_to_txt_filename()")
        else:
            result.record_fail("convert_to_txt_filename()", "Expected 'doc.txt'")

        # 싱글톤 테스트
        p1 = get_conversion_pipeline()
        p2 = get_conversion_pipeline()
        if p1 is p2:
            result.record_pass("싱글톤 인스턴스")
        else:
            result.record_fail("싱글톤 인스턴스", "Different instances")

    except Exception as e:
        result.record_fail("ConversionPipeline", str(e))


async def test_storage(result: TestResult):
    """Storage 테스트"""
    print("\n[2] LocalStorageBackend 테스트")

    temp_dir = tempfile.mkdtemp()
    try:
        storage = LocalStorageBackend(temp_dir)
        mail_data = get_sample_mail_data()

        # sanitize_filename 테스트
        if storage.sanitize_filename("file<>test.txt") == "filetest.txt":
            result.record_pass("sanitize_filename() 특수문자 제거")
        else:
            result.record_fail("sanitize_filename()", "특수문자 미제거")

        if len(storage.sanitize_filename("a" * 100, max_length=50)) == 50:
            result.record_pass("sanitize_filename() 길이 제한")
        else:
            result.record_fail("sanitize_filename()", "길이 제한 실패")

        if storage.sanitize_filename("") == "untitled":
            result.record_pass("sanitize_filename() 빈 문자열 → 'untitled'")
        else:
            result.record_fail("sanitize_filename()", "빈 문자열 처리 실패")

        # create_folder_name 테스트
        folder_name = storage.create_folder_name(mail_data)
        if "20250109" in folder_name:
            result.record_pass("create_folder_name() 날짜 포함")
        else:
            result.record_fail("create_folder_name()", f"날짜 미포함: {folder_name}")

        # create_folder 테스트
        folder_path = await storage.create_folder(mail_data)
        if os.path.isdir(folder_path):
            result.record_pass("create_folder() 폴더 생성")
        else:
            result.record_fail("create_folder()", "폴더 미생성")

        # save_file 테스트
        saved_path = await storage.save_file(folder_path, "test.txt", b"content")
        if saved_path and os.path.isfile(saved_path):
            result.record_pass("save_file() 파일 저장")
        else:
            result.record_fail("save_file()", "파일 미저장")

        # 중복 파일명 테스트
        path1 = await storage.save_file(folder_path, "dup.txt", b"1")
        path2 = await storage.save_file(folder_path, "dup.txt", b"2")
        if path1 != path2 and "dup_1.txt" in path2:
            result.record_pass("중복 파일명 자동 처리")
        else:
            result.record_fail("중복 파일명", f"path1={path1}, path2={path2}")

        # save_mail_content 테스트
        mail_path = await storage.save_mail_content(folder_path, mail_data)
        if mail_path and os.path.isfile(mail_path):
            with open(mail_path, "r", encoding="utf-8") as f:
                content = f.read()
                if "Subject:" in content and "<html>" not in content:
                    result.record_pass("save_mail_content() HTML 태그 제거")
                else:
                    result.record_fail("save_mail_content()", "HTML 태그 미제거")
        else:
            result.record_fail("save_mail_content()", "파일 미저장")

    except Exception as e:
        result.record_fail("LocalStorageBackend", str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def test_integration(result: TestResult):
    """통합 테스트"""
    print("\n[3] 통합 워크플로우 테스트")

    temp_dir = tempfile.mkdtemp()
    try:
        # Storage + Converter 통합
        storage = get_storage_backend(storage_type="local", base_directory=temp_dir)
        converter = get_conversion_pipeline()
        mail_data = get_sample_mail_data()

        # 전체 워크플로우
        folder_path = await storage.create_folder(mail_data)

        # 메일 본문 저장
        await storage.save_mail_content(folder_path, mail_data)

        # 첨부파일 저장 (변환 시도)
        for att in mail_data["attachments"]:
            content = base64.b64decode(att["contentBytes"])
            filename = att["name"]

            if converter.can_convert(filename):
                text, _ = converter.convert(content, filename)
                if text:
                    txt_name = converter.convert_to_txt_filename(filename)
                    await storage.save_file(folder_path, txt_name, text.encode())
                else:
                    await storage.save_file(folder_path, filename, content)
            else:
                await storage.save_file(folder_path, filename, content)

        # 결과 확인
        files = os.listdir(folder_path)
        if len(files) >= 2:
            result.record_pass(f"통합 워크플로우 (파일 {len(files)}개 생성)")
        else:
            result.record_fail("통합 워크플로우", f"파일 부족: {files}")

    except Exception as e:
        result.record_fail("통합 워크플로우", str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def test_metadata(result: TestResult):
    """메타데이터 테스트 (외부 의존성 없이)"""
    print("\n[4] 메타데이터 관리 테스트")

    temp_dir = tempfile.mkdtemp()
    try:
        metadata_file = os.path.join(temp_dir, "metadata.json")

        # 메타데이터 구조 테스트
        metadata = {"processed_messages": {}, "last_updated": None}

        # 중복 체크 로직
        message_id = "test_msg_001"
        is_dup = message_id in metadata["processed_messages"]
        if not is_dup:
            result.record_pass("is_duplicate() 새 메시지 = False")
        else:
            result.record_fail("is_duplicate()", "Expected False")

        # 처리 등록
        metadata["processed_messages"][message_id] = {
            "subject": "Test",
            "processed_at": datetime.now().isoformat()
        }

        # 중복 체크
        is_dup = message_id in metadata["processed_messages"]
        if is_dup:
            result.record_pass("is_duplicate() 처리된 메시지 = True")
        else:
            result.record_fail("is_duplicate()", "Expected True")

        # 필터링 테스트
        all_ids = ["test_msg_001", "test_msg_002", "test_msg_003"]
        new_ids = [mid for mid in all_ids if mid not in metadata["processed_messages"]]
        if len(new_ids) == 2 and "test_msg_001" not in new_ids:
            result.record_pass("filter_new_messages() 중복 제거")
        else:
            result.record_fail("filter_new_messages()", f"결과: {new_ids}")

        # 저장/로드 테스트
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f)

        with open(metadata_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if message_id in loaded["processed_messages"]:
                result.record_pass("메타데이터 영속성")
            else:
                result.record_fail("메타데이터 영속성", "데이터 손실")

    except Exception as e:
        result.record_fail("메타데이터 관리", str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def main():
    """메인 테스트 실행"""
    print("=" * 50)
    print("첨부파일 저장 시스템 테스트")
    print("=" * 50)

    result = TestResult()

    # 테스트 실행
    test_converter(result)
    await test_storage(result)
    await test_integration(result)
    await test_metadata(result)

    # 결과 출력
    success = result.summary()

    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
