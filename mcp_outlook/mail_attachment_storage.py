"""
Graph Mail Storage Backend - 첨부파일 저장 처리

저장소 옵션:
    - LocalStorageBackend: 로컬 디스크 저장
    - OneDriveStorageBackend: OneDrive 폴더 업로드

Classes:
    - StorageBackend (ABC): 저장소 추상 인터페이스
    - LocalStorageBackend: 로컬 저장 구현 (mode 0 — 프로젝트 기준 경로)
    - OneDriveStorageBackend: OneDrive 저장 구현
    - UserLocalStorageBackend: mode 1 사용자 `files/` 전용 구현 (mail_attachment_user_storage.py)

멀티유저(spec/spec_멀티유저.md ②-7.4) — 같은 이름 파일은 존재 검사 후 덮어쓰기 대신
O_EXCL 배타 생성으로 만든다(동시 저장 경합 제거, 기존 `_1` 접미사 규칙 유지). 로그에는
파일명·경로·Graph 오류 본문을 싣지 않는다. 이 모듈은 테스트가 `mail_attachment_storage`
최상위 이름으로도 import 하므로 패키지 내부 의존은 **절대 import** 로만 쓴다.
"""

import os
import re
import base64
import asyncio
import logging
import aiohttp
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Dict, Any, Optional, Tuple, TYPE_CHECKING
from datetime import datetime
from urllib.parse import unquote

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_common.graph_paths import graph_drive_path, graph_segment
from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import SecurityError
from mcp_outlook.outlook_security import (
    BEARER_KW,
    PRESIGNED_KW,
    bearer_headers,
    check_upload_url,
    graph_error_code,
    is_redirect,
    user_seg,
)

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol
    from mcp_common.user_paths import UserPaths

logger = logging.getLogger(__name__)


def build_mail_content_text(mail_data: Dict[str, Any]) -> str:
    """mail_content.txt 본문 (로컬·OneDrive·mode 1 공용)."""
    content_lines = [
        "=" * 60,
        f"Subject: {mail_data.get('subject', 'N/A')}",
        f"From: {mail_data.get('from', {}).get('emailAddress', {}).get('address', 'N/A')}",
        f"Received: {mail_data.get('receivedDateTime', 'N/A')}",
        f"Message ID: {mail_data.get('id', 'N/A')}",
        "=" * 60,
        "",
    ]
    body = mail_data.get("body", {})
    body_content = body.get("content", "")
    if body.get("contentType", "text") == "html":
        # HTML 태그 간단히 제거
        body_content = re.sub(r"<[^>]+>", "", body_content)
        body_content = re.sub(r"&nbsp;", " ", body_content)
        body_content = re.sub(r"&lt;", "<", body_content)
        body_content = re.sub(r"&gt;", ">", body_content)
        body_content = re.sub(r"&amp;", "&", body_content)
    content_lines.append(body_content)
    return "\n".join(content_lines)


def open_numbered_exclusive(folder: Path, safe_name: str) -> Tuple[Path, BinaryIO]:
    """`name`, `name_1`, `name_2` ... 순으로 O_EXCL 배타 생성 (mode 0 이름 규칙 유지).

    존재 검사 후 `open("wb")` 하던 기존 방식은 동시 저장 시 서로 덮어쓸 수 있었다.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    name_parts = safe_name.rsplit(".", 1)
    for counter in range(0, 100000):
        if counter == 0:
            candidate = safe_name
        elif len(name_parts) == 2:
            candidate = f"{name_parts[0]}_{counter}.{name_parts[1]}"
        else:
            candidate = f"{safe_name}_{counter}"
        path = Path(folder) / candidate
        try:
            fd = os.open(path, flags, 0o666)
        except FileExistsError:
            continue
        except PermissionError:
            if path.exists():  # Windows: 같은 이름의 디렉터리
                continue
            raise
        return path, os.fdopen(fd, "wb")
    raise FileExistsError("could not allocate a unique file name")


class StorageBackend(ABC):
    """
    저장소 추상 인터페이스

    모든 저장소 백엔드가 구현해야 하는 메서드 정의
    """

    # 파일시스템에서 사용 불가한 특수문자
    INVALID_CHARS = r'[<>:"/\\|?*\x00-\x1f]'

    def sanitize_filename(self, name: str, max_length: int = 50) -> str:
        """
        파일명에서 특수문자 제거

        Args:
            name: 원본 파일명
            max_length: 최대 길이

        Returns:
            정제된 파일명
        """
        sanitized = re.sub(self.INVALID_CHARS, "", name)
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
        if not sanitized:
            sanitized = "untitled"
        return sanitized

    def create_folder_name(self, mail_data: Dict[str, Any]) -> str:
        """
        메일 데이터로부터 폴더명 생성

        Args:
            mail_data: 메일 데이터 (subject, from, receivedDateTime 필요)

        Returns:
            폴더명 (형식: YYYYMMDD_보낸사람_제목)
        """
        # 날짜 추출
        received_dt = mail_data.get("receivedDateTime", "")
        if received_dt:
            try:
                dt = datetime.fromisoformat(received_dt.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y%m%d")
            except (ValueError, AttributeError):
                date_str = datetime.now().strftime("%Y%m%d")
        else:
            date_str = datetime.now().strftime("%Y%m%d")

        # 보낸 사람 추출
        from_info = mail_data.get("from", {})
        email_addr = from_info.get("emailAddress", {})
        sender = email_addr.get("name") or email_addr.get("address", "unknown")
        sender = self.sanitize_filename(sender, max_length=30)

        # 제목 추출
        subject = mail_data.get("subject", "no_subject")
        subject = self.sanitize_filename(subject, max_length=50)

        return f"{date_str}_{sender}_{subject}"

    @abstractmethod
    async def create_folder(self, mail_data: Dict[str, Any]) -> str:
        """
        메일별 폴더 생성

        Args:
            mail_data: 메일 데이터

        Returns:
            생성된 폴더 경로/식별자
        """
        pass

    @abstractmethod
    async def create_folder_flat(self, base_path: Optional[str] = None) -> str:
        """
        flat_folder 모드: 베이스 폴더만 생성

        Args:
            base_path: 커스텀 베이스 경로

        Returns:
            생성된 폴더 경로/식별자
        """
        pass

    @abstractmethod
    async def save_file(
        self,
        folder_path: str,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None
    ) -> Optional[str]:
        """
        파일 저장

        Args:
            folder_path: 폴더 경로/식별자
            filename: 파일명
            content: 파일 내용 (bytes)
            content_type: MIME 타입 (선택)

        Returns:
            저장된 파일 경로/URL 또는 None
        """
        pass

    @abstractmethod
    async def save_mail_content(
        self,
        folder_path: str,
        mail_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        메일 본문을 텍스트 파일로 저장

        Args:
            folder_path: 폴더 경로/식별자
            mail_data: 메일 데이터

        Returns:
            저장된 파일 경로/URL 또는 None
        """
        pass


class LocalStorageBackend(StorageBackend):
    """
    로컬 디스크 저장 Backend

    기존 MailFolderManager 로직을 StorageBackend 인터페이스로 구현
    """

    def __init__(self, base_directory: str = "downloads"):
        """
        초기화

        Args:
            base_directory: 기본 저장 디렉토리
        """
        path = Path(base_directory)
        if not path.is_absolute():
            # 상대 경로는 프로젝트 루트 기준으로 변환
            project_root = Path(__file__).resolve().parent.parent
            path = project_root / base_directory
        self.base_directory = path
        self.base_directory.mkdir(parents=True, exist_ok=True)

    async def create_folder(self, mail_data: Dict[str, Any]) -> str:
        """
        메일에 해당하는 로컬 폴더 생성

        Args:
            mail_data: 메일 데이터

        Returns:
            폴더 경로
        """
        folder_name = self.create_folder_name(mail_data)
        folder_path = self.base_directory / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        return str(folder_path)

    async def create_folder_flat(self, base_path: Optional[str] = None) -> str:
        """
        flat_folder 모드: base_directory만 사용 (하위폴더 없음)

        Args:
            base_path: 커스텀 베이스 경로 (None이면 self.base_directory 사용)

        Returns:
            폴더 경로
        """
        if base_path:
            path = Path(base_path)
            if not path.is_absolute():
                project_root = Path(__file__).resolve().parent.parent
                path = project_root / base_path
        else:
            path = self.base_directory
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    async def save_file(
        self,
        folder_path: str,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None
    ) -> Optional[str]:
        """
        파일을 로컬 디스크에 저장

        Args:
            folder_path: 폴더 경로
            filename: 파일명
            content: 파일 내용 (bytes)
            content_type: MIME 타입 (미사용)

        Returns:
            저장된 파일 경로 또는 None
        """
        try:
            # 파일명 정제 + 중복 파일명은 배타 생성(_1, _2 ...)으로 처리
            safe_name = self.sanitize_filename(filename, max_length=100)
            file_path, fh = open_numbered_exclusive(Path(folder_path), safe_name)
            with fh:
                fh.write(content)

            logger.info("[LOCAL] saved attachment (%d bytes)", len(content))
            return str(file_path)

        except Exception as e:
            logger.warning("[LOCAL] attachment save failed: %s", type(e).__name__)
            return None

    async def save_mail_content(
        self,
        folder_path: str,
        mail_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        메일 본문을 txt 파일로 저장

        Args:
            folder_path: 폴더 경로
            mail_data: 메일 데이터

        Returns:
            저장된 파일 경로 또는 None
        """
        try:
            file_path = Path(folder_path) / "mail_content.txt"

            # 파일 저장 (mode 0: 같은 메일 재처리 시 덮어쓴다 — 기존 동작)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(build_mail_content_text(mail_data))

            logger.info("[LOCAL] saved mail_content.txt")
            return str(file_path)

        except Exception as e:
            logger.warning("[LOCAL] mail body save failed: %s", type(e).__name__)
            return None


class OneDriveStorageBackend(StorageBackend):
    """
    OneDrive 저장 Backend

    Microsoft Graph API를 사용하여 OneDrive에 파일 업로드
    - 4MB 이하: 단순 PUT 업로드
    - 4MB 초과: Upload Session (청크 업로드)
    """

    # 업로드 크기 제한
    SIMPLE_UPLOAD_MAX_SIZE = 4 * 1024 * 1024  # 4MB
    CHUNK_SIZE = 10 * 1024 * 1024  # 10MB per chunk (권장: 5-10MB)
    MAX_FILE_SIZE = 250 * 1024 * 1024 * 1024  # 250GB (OneDrive 제한)

    def __init__(
        self,
        auth_manager: "TokenProviderProtocol",
        user_email: str,
        base_folder: str = "/Attachments"
    ):
        """
        초기화

        Args:
            auth_manager: 토큰 제공자 (TokenProviderProtocol 구현체, 예: session.AuthManager)
            user_email: 사용자 이메일 (토큰 조회용)
            base_folder: OneDrive 기본 폴더 경로
        """
        self.auth_manager = auth_manager
        self.user_email = user_email
        # R07: 도구 입력 폴더는 성분별 인코딩한 Graph 드라이브 경로로만 보관한다
        # (`..`·역슬래시 거부, `?`·`#`·`%` 인코딩). 이후 모든 URL 은 이 값을 그대로 쓴다.
        self.base_folder = graph_drive_path(base_folder)
        self.graph_url = "https://graph.microsoft.com/v1.0"

    def child_path(self, name: str) -> str:
        """`base_folder/<이름 하나>` — 이름을 경로 성분 하나로 인코딩해 붙인다."""
        child = graph_segment(name)
        return f"{self.base_folder}/{child}" if self.base_folder else child

    MAX_PATH_LENGTH = 400

    async def _get_access_token(self, retry: int = 1) -> Optional[str]:
        """
        액세스 토큰 획득 (재시도 포함)

        Args:
            retry: 재시도 횟수

        Returns:
            액세스 토큰 또는 None
        """
        for attempt in range(retry + 1):
            try:
                return await self.auth_manager.validate_and_refresh_token(self.user_email)
            except SecurityError:
                # 멀티유저: 연결 없음·계정 불일치는 재시도하지 않고 그대로 올린다
                raise
            except Exception as e:
                if attempt < retry:
                    logger.warning("[ONEDRIVE] token retry %d/%d: %s", attempt + 1, retry, type(e).__name__)
                    await asyncio.sleep(1)
                else:
                    logger.warning("[ONEDRIVE] token acquisition failed: %s", type(e).__name__)
                    return None

    async def _request_headers(self, content_type: Optional[str] = "application/json") -> Dict[str, str]:
        """Graph 요청 1건 직전에 토큰을 새로 얻는다 (N01). 없으면 예외 — 조용히 진행하지 않는다."""
        token = await self._get_access_token()
        if not token:
            raise Exception("Failed to get access token")
        return bearer_headers(token, content_type)

    async def _assert_active(self) -> None:
        """사전 서명 URL 요청(bearer 없음) 직전의 identity·폐기 재검사 (N01). 토큰 값은 쓰지 않는다."""
        if not await self._get_access_token():
            raise Exception("Failed to get access token")

    async def _ensure_folder_exists(
        self,
        session: aiohttp.ClientSession,
        folder_path: str
    ) -> bool:
        """
        폴더 존재 확인 및 생성 — GET·POST 각각 직전에 토큰을 새로 얻는다 (N01)

        Args:
            session: aiohttp 세션
            folder_path: 폴더 경로

        Returns:
            성공 여부
        """
        # 경로를 부분으로 분할하여 순차적으로 생성 (folder_path 는 이미 성분별 인코딩된 값)
        parts = [p for p in folder_path.split("/") if p]
        current_path = ""
        drive_root = f"{self.graph_url}/users/{user_seg(self.user_email)}/drive/root"

        for part in parts:
            parent_path = current_path if current_path else "root"
            current_path = f"{current_path}/{part}" if current_path else part

            # 폴더 존재 확인
            check_url = f"{drive_root}:/{current_path}"
            headers = await self._request_headers()
            async with session.get(check_url, headers=headers, **BEARER_KW) as response:
                if response.status == 200:
                    continue  # 이미 존재

            # 폴더 생성
            if parent_path == "root":
                create_url = f"{drive_root}/children"
            else:
                create_url = f"{drive_root}:/{parent_path}:/children"

            create_data = {
                "name": unquote(part),  # 본문의 이름은 디코딩한 원래 폴더명
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename"
            }

            headers = await self._request_headers()  # 변경 요청 직전 재획득 (N01)
            async with session.post(create_url, headers=headers, json=create_data, **BEARER_KW) as response:
                if response.status not in [200, 201, 409]:  # 409 = 이미 존재
                    error_text = await response.text()
                    logger.warning(
                        "[ONEDRIVE] folder create failed: HTTP %s %s",
                        response.status, graph_error_code(error_text),
                    )
                    return False

        return True

    async def create_folder(self, mail_data: Dict[str, Any]) -> str:
        """
        OneDrive에 메일별 폴더 생성

        Args:
            mail_data: 메일 데이터

        Returns:
            폴더 경로
        """
        folder_path = self.child_path(self.create_folder_name(mail_data))

        if len(folder_path) > self.MAX_PATH_LENGTH:
            # 경로가 너무 길면 제목 축소
            folder_path = self.child_path(self.create_folder_name({
                **mail_data,
                "subject": mail_data.get("subject", "")[:20]
            }))

        if not await self._get_access_token():  # 연결 확인만 — 토큰은 요청마다 다시 얻는다 (N01)
            raise Exception("Failed to get access token")

        async with aiohttp.ClientSession() as session:
            success = await self._ensure_folder_exists(session, folder_path)
            if not success:
                raise Exception("Failed to create OneDrive folder")

        return folder_path

    async def create_folder_flat(self, base_path: Optional[str] = None) -> str:
        """
        flat_folder 모드: base_folder만 생성 (하위폴더 없음)

        Args:
            base_path: 커스텀 베이스 경로 (None이면 self.base_folder 사용)

        Returns:
            폴더 경로
        """
        # base_path 는 이미 인코딩된 드라이브 경로(child_path 결과)여야 한다. 원시 입력이 오면
        # 같은 규칙으로 다시 정규화한다(인코딩 결과는 재인코딩해도 성분 구조가 바뀌지 않는다).
        folder_path = graph_drive_path(unquote(base_path)) if base_path else self.base_folder

        if not await self._get_access_token():  # 연결 확인만 — 토큰은 요청마다 다시 얻는다 (N01)
            raise Exception("Failed to get access token")

        async with aiohttp.ClientSession() as session:
            success = await self._ensure_folder_exists(session, folder_path)
            if not success:
                raise Exception("Failed to create OneDrive folder")

        return folder_path

    async def _upload_simple(
        self,
        session: aiohttp.ClientSession,
        content_type: Optional[str],
        file_path: str,
        content: bytes,
        filename: str
    ) -> Optional[str]:
        """
        단순 PUT 업로드 (4MB 이하) — PUT 직전에 토큰을 새로 얻는다 (N01)

        Args:
            session: aiohttp 세션
            content_type: MIME 타입
            file_path: OneDrive 파일 경로
            content: 파일 내용
            filename: 원본 파일명

        Returns:
            저장된 파일 URL 또는 None
        """
        upload_url = f"{self.graph_url}/users/{user_seg(self.user_email)}/drive/root:/{file_path}:/content"

        headers = await self._request_headers(content_type or "application/octet-stream")
        async with session.put(upload_url, headers=headers, data=content, **BEARER_KW) as response:
            if response.status in [200, 201]:
                result = await response.json()
                web_url = result.get("webUrl", file_path)
                logger.info("[ONEDRIVE] uploaded (%d bytes)", len(content))
                return web_url
            else:
                error_text = await response.text()
                logger.warning(
                    "[ONEDRIVE] upload failed: HTTP %s %s", response.status, graph_error_code(error_text)
                )
                return None

    async def _upload_large(
        self,
        session: aiohttp.ClientSession,
        file_path: str,
        content: bytes,
        filename: str
    ) -> Optional[str]:
        """
        Upload Session을 사용한 대용량 파일 업로드 (4MB 초과)

        - 세션 생성 POST 직전에 토큰을 새로 얻는다 (N01).
        - uploadUrl 은 사전 서명 URL: 공용 `check_presigned_url` 통과, bearer 미부착,
          redirect 미추종, 3xx 는 오류 — 청크 본문을 다른 곳으로 다시 보내지 않는다 (N05).
        - 청크·상태 조회·재시도·취소 요청 직전마다 공급자로 identity·폐기를 재검사한다 (N01).

        Args:
            session: aiohttp 세션
            file_path: OneDrive 파일 경로
            content: 파일 내용
            filename: 원본 파일명

        Returns:
            저장된 파일 URL 또는 None
        """
        file_size = len(content)
        logger.info("[ONEDRIVE] large upload start (%d bytes)", file_size)

        # Step 1: Upload Session 생성 (Graph bearer 사용 — redirect 미추종)
        create_session_url = (
            f"{self.graph_url}/users/{user_seg(self.user_email)}/drive/root:/{file_path}:/createUploadSession"
        )

        session_body = {
            "item": {
                "@microsoft.graph.conflictBehavior": "rename",
                "name": filename
            }
        }

        headers = await self._request_headers()
        async with session.post(create_session_url, headers=headers, json=session_body, **BEARER_KW) as response:
            if response.status not in [200, 201]:
                error_text = await response.text()
                logger.warning(
                    "[ONEDRIVE] upload session create failed: HTTP %s %s",
                    response.status, graph_error_code(error_text),
                )
                return None

            session_data = await response.json()
            upload_url = session_data.get("uploadUrl")

            if not upload_url:
                logger.warning("[ONEDRIVE] upload session returned no uploadUrl")
                return None

        # uploadUrl 은 사전 서명 URL 이다 (②-7.5, N05): 공용 정책을 통과해야 하고 Graph bearer 를 붙이지 않는다.
        upload_url = check_upload_url(upload_url)

        async def cancel_session() -> None:
            try:
                await self._assert_active()
                await session.delete(upload_url, **PRESIGNED_KW)
            except Exception as exc:  # 취소 실패는 업로드 실패 결과를 바꾸지 않는다
                logger.warning("[ONEDRIVE] upload session cancel failed: %s", type(exc).__name__)

        # Step 2: 청크 단위로 업로드
        chunk_size = self.CHUNK_SIZE
        uploaded = 0
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        for chunk_num in range(total_chunks):
            start = chunk_num * chunk_size
            end = min(start + chunk_size, file_size)
            chunk_data = content[start:end]
            chunk_len = len(chunk_data)
            is_last_chunk = (chunk_num == total_chunks - 1)

            # Content-Range 헤더 설정 (Authorization 없음)
            content_range = f"bytes {start}-{end - 1}/{file_size}"

            chunk_headers = {
                "Content-Length": str(chunk_len),
                "Content-Range": content_range,
            }

            await self._assert_active()  # 청크(변경 요청) 직전 identity 재검사 (N01)
            async with session.put(upload_url, headers=chunk_headers, data=chunk_data, **PRESIGNED_KW) as response:
                if is_redirect(response.status):
                    # 사전 서명 URL 이 다른 곳으로 보내려 한다 — 청크 본문을 다시 보내지 않는다 (N05)
                    logger.warning("[ONEDRIVE] chunk upload redirected (HTTP %s) — aborting", response.status)
                    await cancel_session()
                    return None
                if response.status in [200, 201]:
                    # 업로드 완료 (마지막 청크에서만 200/201 반환)
                    result = await response.json()
                    web_url = result.get("webUrl", file_path)
                    logger.info("[ONEDRIVE] large upload done (%d bytes)", file_size)
                    return web_url
                elif response.status == 202:
                    # 계속 업로드 중
                    uploaded = end
                    progress = (uploaded / file_size) * 100
                    logger.info("[ONEDRIVE] chunk %d/%d (%.1f%%)", chunk_num + 1, total_chunks, progress)

                    # 마지막 청크인데 202가 반환된 경우 (비정상)
                    if is_last_chunk:
                        logger.warning("[ONEDRIVE] last chunk returned 202 — checking session status")
                        # 마지막 청크 202: 세션 상태 확인
                        await self._assert_active()
                        async with session.get(upload_url, **PRESIGNED_KW) as status_resp:
                            if status_resp.status in [200, 201]:
                                status_data = await status_resp.json()
                                web_url = status_data.get("webUrl", file_path)
                                logger.info("[ONEDRIVE] large upload done (delayed)")
                                return web_url
                else:
                    logger.warning("[ONEDRIVE] chunk upload failed: HTTP %s", response.status)

                    # 1회 재시도 — 직전에 identity 를 다시 확인한다 (N01)
                    await asyncio.sleep(2)
                    await self._assert_active()
                    async with session.put(
                        upload_url, headers=chunk_headers, data=chunk_data, **PRESIGNED_KW
                    ) as retry_resp:
                        if is_redirect(retry_resp.status):
                            logger.warning("[ONEDRIVE] chunk retry redirected (HTTP %s) — aborting", retry_resp.status)
                        elif retry_resp.status in [200, 201, 202]:
                            if retry_resp.status in [200, 201]:
                                result = await retry_resp.json()
                                web_url = result.get("webUrl", file_path)
                                logger.info("[ONEDRIVE] large upload done (retry)")
                                return web_url
                            # 202면 계속 진행
                            uploaded = end
                            logger.info("[ONEDRIVE] chunk %d/%d retry ok", chunk_num + 1, total_chunks)
                            continue
                        else:
                            logger.warning("[ONEDRIVE] chunk retry failed: HTTP %s", retry_resp.status)

                    # Upload Session 취소
                    await cancel_session()
                    return None

        # 모든 청크가 202로 끝난 경우 (비정상 - 마지막 청크는 200/201이어야 함)
        logger.warning("[ONEDRIVE] upload finished without 200/201")
        return None

    async def save_file(
        self,
        folder_path: str,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None
    ) -> Optional[str]:
        """
        파일을 OneDrive에 업로드
        - 4MB 이하: 단순 PUT 업로드
        - 4MB 초과: Upload Session (청크 업로드)

        Args:
            folder_path: 폴더 경로
            filename: 파일명
            content: 파일 내용 (bytes)
            content_type: MIME 타입

        Returns:
            저장된 파일 URL 또는 None
        """
        try:
            file_size = len(content)

            # 최대 파일 크기 확인
            if file_size > self.MAX_FILE_SIZE:
                logger.warning("[ONEDRIVE] skipped: larger than 250GB")
                return None

            if not await self._get_access_token():  # 연결 확인만 — 토큰은 요청마다 다시 얻는다 (N01)
                return None

            # 파일명 정제 + 경로 성분 인코딩 (R07)
            safe_name = self.sanitize_filename(filename, max_length=100)
            file_path = f"{folder_path}/{graph_segment(safe_name)}" if folder_path else graph_segment(safe_name)

            async with aiohttp.ClientSession() as session:
                if file_size <= self.SIMPLE_UPLOAD_MAX_SIZE:
                    # 4MB 이하: 단순 PUT 업로드
                    return await self._upload_simple(session, content_type, file_path, content, safe_name)
                else:
                    # 4MB 초과: Upload Session (청크 업로드)
                    return await self._upload_large(session, file_path, content, safe_name)

        except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
            raise
        except Exception as e:
            logger.warning("[ONEDRIVE] upload error: %s", type(e).__name__)
            return None

    async def save_mail_content(
        self,
        folder_path: str,
        mail_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        메일 본문을 OneDrive에 txt 파일로 저장

        Args:
            folder_path: 폴더 경로
            mail_data: 메일 데이터

        Returns:
            저장된 파일 URL 또는 None
        """
        try:
            content_bytes = build_mail_content_text(mail_data).encode("utf-8")

            return await self.save_file(
                folder_path,
                "mail_content.txt",
                content_bytes,
                "text/plain; charset=utf-8"
            )

        except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
            raise
        except Exception as e:
            logger.warning("[ONEDRIVE] mail body save failed: %s", type(e).__name__)
            return None


class MailFolderManager(LocalStorageBackend):
    """
    메일 폴더 및 파일 관리 (하위 호환성 유지)

    LocalStorageBackend를 상속하여 기존 동기 인터페이스 제공
    - get_mail_folder_path(): 동기 메서드
    - save_attachment(): 동기 메서드
    - save_mail_content(): 동기 메서드 오버로드
    """

    def get_mail_folder_path(self, mail_data: Dict[str, Any]) -> Path:
        """
        메일에 해당하는 폴더 경로 반환 (필요시 생성)

        Args:
            mail_data: 메일 데이터

        Returns:
            폴더 경로
        """
        folder_name = self.create_folder_name(mail_data)
        folder_path = self.base_directory / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path

    def save_attachment(
        self, folder_path: Path, attachment: Dict[str, Any]
    ) -> Optional[str]:
        """
        첨부파일 저장 (동기 버전)

        Args:
            folder_path: 저장할 폴더 경로
            attachment: 첨부파일 데이터 (name, contentBytes 필요)

        Returns:
            저장된 파일 경로 또는 None
        """
        import base64

        name = attachment.get("name", "attachment")
        content_bytes = attachment.get("contentBytes")

        if not content_bytes:
            logger.info("[SKIP] attachment without contentBytes (large file)")
            return None

        # 파일명 정제
        safe_name = self.sanitize_filename(name, max_length=100)

        try:
            # Base64 디코딩 후 배타 생성 (중복 파일명은 _1, _2 ...)
            file_content = base64.b64decode(content_bytes)
            file_path, fh = open_numbered_exclusive(Path(folder_path), safe_name)
            with fh:
                fh.write(file_content)

            logger.info("[SAVED] attachment (%d bytes)", len(file_content))
            return str(file_path)

        except Exception as e:
            logger.warning("[SAVED] attachment save failed: %s", type(e).__name__)
            return None

    def save_mail_content(  # type: ignore[override]
        self, folder_path: Path, mail_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        메일 본문을 txt 파일로 저장 (동기 버전, 하위 호환성)

        Note: 부모 클래스의 async 버전을 동기 버전으로 오버라이드

        Args:
            folder_path: 저장할 폴더 경로
            mail_data: 메일 데이터

        Returns:
            저장된 파일 경로 또는 None
        """
        try:
            file_path = Path(folder_path) / "mail_content.txt"

            # 파일 저장 (mode 0 기존 동작: 덮어쓰기)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(build_mail_content_text(mail_data))

            logger.info("[SAVED] mail_content.txt")
            return str(file_path)

        except Exception as e:
            logger.warning("[SAVED] mail body save failed: %s", type(e).__name__)
            return None


def get_storage_backend(
    storage_type: str = "local",
    auth_manager: Optional["TokenProviderProtocol"] = None,
    user_email: Optional[str] = None,
    paths: Optional["UserPaths"] = None,
    **kwargs
) -> StorageBackend:
    """
    Storage Backend 팩토리 함수

    Args:
        storage_type: "local" 또는 "onedrive"
        auth_manager: AuthManager (OneDrive용) — mode 1 에서는 사용자 고정 provider
        user_email: 사용자 이메일 (OneDrive용)
        paths: mode 1 사용자 경로. 주면 로컬 저장은 사용자 `files/` 안으로만 간다.
        **kwargs: 추가 옵션
            - base_directory: 로컬 저장 디렉토리 (기본: "downloads")
            - base_folder: OneDrive 기본 폴더 (기본: "/Attachments")

    Returns:
        StorageBackend 인스턴스
    """
    if storage_type != "onedrive" and paths is not None:
        from mcp_outlook.mail_attachment_user_storage import UserLocalStorageBackend
        from mcp_outlook.outlook_file_policy import resolve_save_dir

        return UserLocalStorageBackend(paths, resolve_save_dir(paths, kwargs.get("base_directory")))
    if storage_type == "onedrive":
        if not auth_manager or not user_email:
            raise ValueError("OneDrive storage requires auth_manager and user_email")
        return OneDriveStorageBackend(
            auth_manager=auth_manager,
            user_email=user_email,
            base_folder=kwargs.get("base_folder", "/Attachments")
        )
    else:
        return LocalStorageBackend(
            base_directory=kwargs.get("base_directory", "downloads")
        )
