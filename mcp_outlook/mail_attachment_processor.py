"""
Mail Attachment Processor - 첨부파일 처리 유틸리티

BatchAttachmentHandler의 처리 로직을 분리한 모듈
오케스트레이터(_process_mail_with_options)에서 호출하는 순수 처리 함수들

Functions:
    - process_body_content: 메일 본문 처리
    - process_attachments: 첨부파일 목록 처리
    - process_attachment_with_conversion: 첨부파일 TXT 변환 처리
    - process_attachment_original: 첨부파일 원본 저장 처리
"""

import re
import base64
from typing import Dict, Any, List, Optional, Tuple

from .mail_attachment_storage import StorageBackend
from .mail_attachment_converter import ConversionPipeline


# 토큰 제한 상수
DEFAULT_MAX_TOKENS = 50000
CHARS_PER_TOKEN = 4  # 평균적으로 1토큰 ≈ 4자 (한글/영어 혼합 기준)


def estimate_token_count(text: str) -> int:
    """
    텍스트의 토큰 수 추정

    Args:
        text: 토큰 수를 추정할 텍스트

    Returns:
        추정 토큰 수
    """
    return len(text) // CHARS_PER_TOKEN


def truncate_to_token_limit(
    text: str,
    max_tokens: int = DEFAULT_MAX_TOKENS
) -> Tuple[str, bool, int]:
    """
    텍스트를 토큰 제한에 맞게 truncate

    Args:
        text: 원본 텍스트
        max_tokens: 최대 토큰 수 (기본값: 50000)

    Returns:
        (truncate된 텍스트, truncate 여부, 원본 토큰 수)
    """
    original_tokens = estimate_token_count(text)

    if original_tokens <= max_tokens:
        return text, False, original_tokens

    # 토큰 제한에 맞게 문자 수 계산
    max_chars = max_tokens * CHARS_PER_TOKEN

    # 단어 경계에서 자르기 (가능하면)
    truncated = text[:max_chars]

    # 마지막 완전한 문장/줄에서 자르기 시도
    last_newline = truncated.rfind('\n')
    last_period = truncated.rfind('. ')

    cut_point = max(last_newline, last_period)
    if cut_point > max_chars * 0.8:  # 80% 이상 유지되면 문장 경계에서 자름
        truncated = truncated[:cut_point + 1]

    # Truncation 표시 추가
    truncated += f"\n\n... [TRUNCATED: 원본 {original_tokens:,} 토큰 중 {max_tokens:,} 토큰만 반환됨]"

    return truncated, True, original_tokens


async def process_body_content(
    mail_data: Dict[str, Any],
    result: Dict[str, Any],
    storage: Optional[StorageBackend],
    folder_path: Optional[str],
    save_file: bool
) -> Optional[str]:
    """
    메일 본문 처리

    Args:
        mail_data: 메일 데이터
        result: 결과 딕셔너리 (업데이트됨)
        storage: 저장소 백엔드
        folder_path: 저장 폴더 경로
        save_file: 파일 저장 여부

    Returns:
        저장된 파일 경로 또는 None
    """
    message_id = mail_data.get("id", "")
    subject = mail_data.get("subject", "제목 없음")

    body = mail_data.get("body", {})
    body_content = body.get("content", "")
    body_type = body.get("contentType", "text")

    # HTML → TXT 변환
    if body_type == "html":
        body_content = re.sub(r"<[^>]+>", "", body_content)
        body_content = re.sub(r"&nbsp;", " ", body_content)
        body_content = re.sub(r"&lt;", "<", body_content)
        body_content = re.sub(r"&gt;", ">", body_content)
        body_content = re.sub(r"&amp;", "&", body_content)

    if save_file and storage:
        mail_file = await storage.save_mail_content(folder_path, mail_data)
        if mail_file:
            result["saved_mails"].append(mail_file)
            return mail_file
    else:
        # 메모리 반환
        result["body_contents"].append({
            "message_id": message_id,
            "subject": subject,
            "content": body_content
        })
        print(f"  [BODY] 본문 메모리 반환 ({len(body_content)} chars)")

    return None


async def process_attachments(
    mail_data: Dict[str, Any],
    result: Dict[str, Any],
    storage: Optional[StorageBackend],
    converter: Optional[ConversionPipeline],
    folder_path: Optional[str],
    save_file: bool
) -> List[str]:
    """
    첨부파일 목록 처리

    Args:
        mail_data: 메일 데이터
        result: 결과 딕셔너리 (업데이트됨)
        storage: 저장소 백엔드
        converter: 텍스트 변환기
        folder_path: 저장 폴더 경로
        save_file: 파일 저장 여부

    Returns:
        저장된 파일 경로 목록
    """
    message_id = mail_data.get("id", "")
    saved_files = []

    attachments = mail_data.get("attachments", [])
    for attachment in attachments:
        att_name = attachment.get("name", "attachment")
        content_bytes = attachment.get("contentBytes")

        if not content_bytes:
            print(f"  [SKIP] {att_name} - contentBytes 없음 (대용량 파일)")
            continue

        # Base64 디코딩
        file_content = base64.b64decode(content_bytes)

        # 변환 가능 여부에 따라 처리
        if converter and converter.can_convert(att_name):
            saved = await process_attachment_with_conversion(
                message_id, attachment, file_content, result, storage, converter, folder_path, save_file
            )
        else:
            saved = await process_attachment_original(
                message_id, attachment, file_content, result, storage, folder_path, save_file
            )

        if saved:
            saved_files.append(saved)

    return saved_files


async def process_attachment_with_conversion(
    message_id: str,
    attachment: Dict[str, Any],
    file_content: bytes,
    result: Dict[str, Any],
    storage: Optional[StorageBackend],
    converter: ConversionPipeline,
    folder_path: Optional[str],
    save_file: bool
) -> Optional[str]:
    """
    첨부파일 TXT 변환 처리

    Args:
        message_id: 메일 ID
        attachment: 첨부파일 데이터
        file_content: 디코딩된 파일 내용
        result: 결과 딕셔너리
        storage: 저장소 백엔드
        converter: 텍스트 변환기
        folder_path: 저장 폴더 경로
        save_file: 파일 저장 여부

    Returns:
        저장된 파일 경로 또는 None
    """
    att_name = attachment.get("name", "attachment")

    # TXT 변환 시도
    text, error = converter.convert(file_content, att_name)

    if text:
        txt_filename = converter.convert_to_txt_filename(att_name)

        # 토큰 제한 적용
        text, was_truncated, original_tokens = truncate_to_token_limit(text)

        if save_file and storage:
            txt_content = text.encode("utf-8")
            att_file = await storage.save_file(
                folder_path, txt_filename, txt_content, "text/plain; charset=utf-8"
            )
            if att_file:
                result["saved_attachments"].append(att_file)
                converted_info = {
                    "original": att_name,
                    "converted": txt_filename,
                    "path": att_file
                }
                if was_truncated:
                    converted_info["truncated"] = True
                    converted_info["original_tokens"] = original_tokens
                result["converted_files"].append(converted_info)
                truncate_msg = f" (truncated: {original_tokens:,} → {DEFAULT_MAX_TOKENS:,} tokens)" if was_truncated else ""
                print(f"  [CONVERTED] {att_name} → {txt_filename}{truncate_msg}")
                return att_file
        else:
            # 메모리 반환
            content_info = {
                "message_id": message_id,
                "original_name": att_name,
                "converted_name": txt_filename,
                "content_type": "text/plain",
                "content": text,
                "size": len(text)
            }
            if was_truncated:
                content_info["truncated"] = True
                content_info["original_tokens"] = original_tokens
            result["attachment_contents"].append(content_info)
            truncate_msg = f" (truncated: {original_tokens:,} → {DEFAULT_MAX_TOKENS:,} tokens)" if was_truncated else ""
            print(f"  [CONVERTED] {att_name} → 메모리 반환{truncate_msg}")
    else:
        # 변환 실패 시 원본 처리
        print(f"  [WARN] {att_name} 변환 실패: {error}, 원본 처리")
        return await process_attachment_original(
            message_id, attachment, file_content, result, storage, folder_path, save_file
        )

    return None


async def process_attachment_original(
    message_id: str,
    attachment: Dict[str, Any],
    file_content: bytes,
    result: Dict[str, Any],
    storage: Optional[StorageBackend],
    folder_path: Optional[str],
    save_file: bool
) -> Optional[str]:
    """
    첨부파일 원본 저장 처리

    Args:
        message_id: 메일 ID
        attachment: 첨부파일 데이터
        file_content: 디코딩된 파일 내용
        result: 결과 딕셔너리
        storage: 저장소 백엔드
        folder_path: 저장 폴더 경로
        save_file: 파일 저장 여부

    Returns:
        저장된 파일 경로 또는 None
    """
    att_name = attachment.get("name", "attachment")

    if save_file and storage:
        att_file = await storage.save_file(
            folder_path, att_name, file_content, attachment.get("contentType")
        )
        if att_file:
            result["saved_attachments"].append(att_file)
            return att_file
    else:
        result["attachment_contents"].append({
            "message_id": message_id,
            "original_name": att_name,
            "content_type": attachment.get("contentType"),
            "content_bytes": base64.b64encode(file_content).decode("ascii"),
            "size": len(file_content)
        })
        print(f"  [ORIGINAL] {att_name} → 메모리 반환 ({len(file_content)} bytes)")

    return None
