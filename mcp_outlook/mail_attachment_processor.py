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

import asyncio
import re
import base64
import binascii
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple

from mcp_common.security_contracts import ErrorCode, SecurityError

from . import conversion_workers
from . import outlook_security as limits
from .conversion_workers import WorkerGroup
from .mail_attachment_storage import StorageBackend
from .mail_attachment_converter import ConversionPipeline
from .outlook_security import ByteBudget

#: 슬롯 대기 폴링 간격(초). 비차단 acquire 사이의 sleep — 취소가 들어올 수 있는 유일한 지점이다.
_SLOT_POLL_SECONDS = 0.01


async def convert_with_deadline(
    converter: ConversionPipeline,
    file_content: bytes,
    att_name: str,
    *,
    owner_key: Optional[str],
    workers: WorkerGroup,
) -> Tuple[Optional[str], Optional[str]]:
    """변환 1건을 **실제 스레드**에서 deadline 안에 돌린다 (astra 3차 P01).

    - 사용자별 슬롯(`conversion_workers.slots_for`, 프로세스 전역)을 스레드를 띄우기 **전에** 얻고,
      스레드가 실제로 끝날 때(`finally`) 놓는다 — timeout 뒤에도 돌고 있는 스레드는 슬롯을 쥔다.
    - 슬롯을 `CONVERSION_SLOT_TIMEOUT_SECONDS` 안에 못 얻으면 `SecurityError(OVERLOADED)`.
    - 스레드는 `workers`(서비스 범위 `WorkerGroup`)에 등록돼 `MailService.close()` 가 join 한다.
    - deadline 초과는 `(None, "conversion_timeout")` — 요청은 더 기다리지 않는다.

    취소 안전성 (astra 4차 Q01): 슬롯은 이벤트 루프 안에서 **비차단** `acquire(0)` 로만 얻고,
    대기는 `asyncio.sleep` 으로 한다. 취소는 슬롯을 쥐지 않은 `sleep` 지점에서만 들어오므로
    "취소된 뒤 뒤늦게 획득된 슬롯"이 생기지 않는다(차단 acquire 를 다른 스레드에 맡기지 않는다).
    획득 후 converter 스레드가 소유권을 넘겨받기(`start()` 성공) 전의 어떤 예외·취소도 슬롯을
    되돌린다.
    """
    slots = conversion_workers.slots_for(owner_key, limits.MAX_CONVERSION_WORKERS)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, float(limits.CONVERSION_SLOT_TIMEOUT_SECONDS))
    while not slots.acquire(0.0):  # 비차단 — 취소가 끼어들 await 가 없다
        if loop.time() >= deadline:
            logger.warning("[CONVERT] no converter slot available")
            raise SecurityError(ErrorCode.OVERLOADED)
        await asyncio.sleep(_SLOT_POLL_SECONDS)  # 취소는 여기서만 — 슬롯을 쥐지 않은 상태

    # 여기서부터 스레드 start() 성공까지는 이 코루틴이 슬롯 소유자다.
    try:
        future: "asyncio.Future[Tuple[Optional[str], Optional[str]]]" = loop.create_future()

        def _deliver(value):
            if not future.done():
                future.set_result(value)

        def _target():
            outcome: Tuple[Optional[str], Optional[str]] = (None, "변환 실패")
            try:
                outcome = converter.convert(file_content, att_name)
            except BaseException as exc:  # 변환기 예외는 스레드 안에서 끝낸다
                outcome = (None, f"변환 실패: {type(exc).__name__}")
            finally:
                try:
                    slots.release()
                finally:
                    workers.finished(thread)
                try:
                    loop.call_soon_threadsafe(_deliver, outcome)
                except RuntimeError:
                    pass  # 이벤트 루프가 이미 닫혔다 — 결과를 받을 요청이 없다

        thread = threading.Thread(
            target=_target, name=f"outlook-convert-{(owner_key or conversion_workers.LEGACY_KEY)[:8]}", daemon=True
        )
        workers.register(thread)
        try:
            thread.start()
        except BaseException:
            workers.finished(thread)
            raise
    except BaseException:
        # 스레드가 소유권을 받기 전의 실패(start 실패·취소·그 밖의 예외) — 슬롯을 되돌린다
        slots.release()
        raise
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=limits.CONVERSION_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("[CONVERT] conversion timed out (%.0fs); worker thread keeps its slot until it exits",
                       limits.CONVERSION_TIMEOUT_SECONDS)
        return None, "conversion_timeout"

# 로그에는 첨부 이름·제목·경로를 싣지 않는다 (spec/spec_멀티유저.md ②-9) — 크기·건수만.
logger = logging.getLogger(__name__)


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
        result["errors"].append(f"본문 저장 실패 ({subject[:30]})")
    else:
        # 메모리 반환
        result["body_contents"].append({
            "message_id": message_id,
            "subject": subject,
            "content": body_content
        })
        logger.info("[BODY] body returned in memory (%d chars)", len(body_content))

    return None


async def process_attachments(
    mail_data: Dict[str, Any],
    result: Dict[str, Any],
    storage: Optional[StorageBackend],
    converter: Optional[ConversionPipeline],
    folder_path: Optional[str],
    save_file: bool,
    budget: Optional[ByteBudget] = None,
    workers: Optional[WorkerGroup] = None,
    owner_key: Optional[str] = None,
) -> List[str]:
    """
    첨부파일 목록 처리

    decode 전에 크기를 추정해 첨부 1건 상한(`MAX_ATTACHMENT_BYTES`)과 요청 예산(`budget`)을
    넘는 첨부는 건너뛴다 (N08). 건너뛴 첨부는 `errors` 에 사유 코드로 남는다.

    Args:
        mail_data: 메일 데이터
        result: 결과 딕셔너리 (업데이트됨)
        storage: 저장소 백엔드
        converter: 텍스트 변환기
        folder_path: 저장 폴더 경로
        save_file: 파일 저장 여부
        budget: 요청 1건의 decode 바이트 예산 (None 이면 이 호출만의 예산)
        workers: converter 스레드를 등록할 서비스 범위 `WorkerGroup` (None 이면 이 호출만의 그룹 — drain 대상 아님)
        owner_key: 변환 슬롯의 사용자 키 (None 이면 mode 0 legacy 키)

    Returns:
        저장된 파일 경로 목록
    """
    message_id = mail_data.get("id", "")
    saved_files = []
    if budget is None:
        budget = ByteBudget(limits.MAX_REQUEST_ATTACHMENT_BYTES)
    if workers is None:
        workers = WorkerGroup()

    attachments = mail_data.get("attachments", [])
    for attachment in attachments:
        att_name = attachment.get("name", "attachment")
        content_bytes = attachment.get("contentBytes")

        if not content_bytes:
            logger.info("[SKIP] attachment without contentBytes (large file)")
            continue

        # decode 전 크기 검사 (N08): 1건 상한 → 요청 예산 순
        estimated = limits.base64_decoded_size(content_bytes)
        if estimated > limits.MAX_ATTACHMENT_BYTES:
            logger.info("[SKIP] attachment over per-attachment limit (%d bytes)", estimated)
            result["errors"].append({"message_id": message_id, "error": "attachment_too_large",
                                     "limit_bytes": limits.MAX_ATTACHMENT_BYTES})
            continue
        if not budget.take(estimated):
            logger.info("[SKIP] attachment over per-request budget")
            result["errors"].append({"message_id": message_id, "error": "request_attachment_budget_exceeded",
                                     "limit_bytes": budget.limit})
            continue

        # Base64 디코딩
        try:
            file_content = base64.b64decode(content_bytes, validate=False)
        except (binascii.Error, ValueError):
            result["errors"].append({"message_id": message_id, "error": "attachment_decode_failed"})
            continue

        # 변환 가능 여부에 따라 처리
        if converter and converter.can_convert(att_name):
            saved = await process_attachment_with_conversion(
                message_id, attachment, file_content, result, storage, converter, folder_path, save_file,
                workers=workers, owner_key=owner_key,
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
    save_file: bool,
    workers: Optional[WorkerGroup] = None,
    owner_key: Optional[str] = None,
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

    # TXT 변환 시도 — 슬롯 + 실제 스레드 + deadline (N08/P01). 시간 초과는 변환 실패로 보고 원본 처리한다.
    text, error = await convert_with_deadline(
        converter, file_content, att_name, owner_key=owner_key, workers=workers or WorkerGroup()
    )

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
                logger.info("[CONVERTED] attachment saved as txt (truncated=%s)", was_truncated)
                return att_file
            result["errors"].append(f"첨부 저장 실패: {txt_filename}")
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
            logger.info("[CONVERTED] attachment returned in memory (truncated=%s)", was_truncated)
    else:
        # 변환 실패 시 원본 처리
        logger.info("[CONVERT] conversion failed, falling back to original")
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
        result["errors"].append(f"첨부 저장 실패: {att_name}")
    else:
        result["attachment_contents"].append({
            "message_id": message_id,
            "original_name": att_name,
            "content_type": attachment.get("contentType"),
            "content_bytes": base64.b64encode(file_content).decode("ascii"),
            "size": len(file_content)
        })
        logger.info("[ORIGINAL] attachment returned in memory (%d bytes)", len(file_content))

    return None
