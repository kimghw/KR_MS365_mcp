"""
Graph Mail Storage Backend - 첨부파일 저장 처리

저장소 옵션:
    - LocalStorageBackend: 로컬 디스크 저장
    - OneDriveStorageBackend: OneDrive 폴더 업로드

Classes:
    - StorageBackend (ABC): 저장소 추상 인터페이스
    - LocalStorageBackend: 로컬 저장 구현
    - OneDriveStorageBackend: OneDrive 저장 구현
"""

import os
import re
import base64
import asyncio
import aiohttp
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session.auth_manager import AuthManager


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
            # 파일명 정제
            safe_name = self.sanitize_filename(filename, max_length=100)
            folder = Path(folder_path)

            # 중복 파일명 처리
            file_path = folder / safe_name
            counter = 1
            while file_path.exists():
                name_parts = safe_name.rsplit(".", 1)
                if len(name_parts) == 2:
                    new_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
                else:
                    new_name = f"{safe_name}_{counter}"
                file_path = folder / new_name
                counter += 1

            # 파일 저장
            with open(file_path, "wb") as f:
                f.write(content)

            print(f"  [LOCAL] {file_path.name} ({len(content):,} bytes)")
            return str(file_path)

        except Exception as e:
            print(f"  [ERROR] {filename} 저장 실패: {e}")
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

            # 메일 정보 구성
            content_lines = [
                "=" * 60,
                f"Subject: {mail_data.get('subject', 'N/A')}",
                f"From: {mail_data.get('from', {}).get('emailAddress', {}).get('address', 'N/A')}",
                f"Received: {mail_data.get('receivedDateTime', 'N/A')}",
                f"Message ID: {mail_data.get('id', 'N/A')}",
                "=" * 60,
                "",
            ]

            # 본문 추출
            body = mail_data.get("body", {})
            body_content = body.get("content", "")
            body_type = body.get("contentType", "text")

            if body_type == "html":
                # HTML 태그 간단히 제거
                body_content = re.sub(r"<[^>]+>", "", body_content)
                body_content = re.sub(r"&nbsp;", " ", body_content)
                body_content = re.sub(r"&lt;", "<", body_content)
                body_content = re.sub(r"&gt;", ">", body_content)
                body_content = re.sub(r"&amp;", "&", body_content)

            content_lines.append(body_content)

            # 파일 저장
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(content_lines))

            print(f"  [LOCAL] mail_content.txt")
            return str(file_path)

        except Exception as e:
            print(f"  [ERROR] 메일 본문 저장 실패: {e}")
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
        auth_manager: AuthManager,
        user_email: str,
        base_folder: str = "/Attachments"
    ):
        """
        초기화

        Args:
            auth_manager: 인증 매니저
            user_email: 사용자 이메일 (토큰 조회용)
            base_folder: OneDrive 기본 폴더 경로
        """
        self.auth_manager = auth_manager
        self.user_email = user_email
        self.base_folder = base_folder.strip("/")
        self.graph_url = "https://graph.microsoft.com/v1.0"

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
            except Exception as e:
                if attempt < retry:
                    print(f"토큰 획득 실패, 재시도 ({attempt + 1}/{retry}): {e}")
                    await asyncio.sleep(1)
                else:
                    print(f"토큰 획득 최종 실패: {e}")
                    return None

    async def _ensure_folder_exists(
        self,
        session: aiohttp.ClientSession,
        headers: Dict[str, str],
        folder_path: str
    ) -> bool:
        """
        폴더 존재 확인 및 생성

        Args:
            session: aiohttp 세션
            headers: 요청 헤더
            folder_path: 폴더 경로

        Returns:
            성공 여부
        """
        # 경로를 부분으로 분할하여 순차적으로 생성
        parts = folder_path.strip("/").split("/")
        current_path = ""

        for part in parts:
            parent_path = current_path if current_path else "root"
            current_path = f"{current_path}/{part}" if current_path else part

            # 폴더 존재 확인
            check_url = f"{self.graph_url}/users/{self.user_email}/drive/root:/{current_path}"
            async with session.get(check_url, headers=headers) as response:
                if response.status == 200:
                    continue  # 이미 존재

            # 폴더 생성
            if parent_path == "root":
                create_url = f"{self.graph_url}/users/{self.user_email}/drive/root/children"
            else:
                create_url = f"{self.graph_url}/users/{self.user_email}/drive/root:/{parent_path}:/children"

            create_data = {
                "name": part,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename"
            }

            async with session.post(create_url, headers=headers, json=create_data) as response:
                if response.status not in [200, 201, 409]:  # 409 = 이미 존재
                    error_text = await response.text()
                    print(f"  [ERROR] 폴더 생성 실패 ({current_path}): {error_text[:100]}")
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
        folder_name = self.create_folder_name(mail_data)
        folder_path = f"{self.base_folder}/{folder_name}"

        if len(folder_path) > self.MAX_PATH_LENGTH:
            # 경로가 너무 길면 제목 축소
            folder_name = self.create_folder_name({
                **mail_data,
                "subject": mail_data.get("subject", "")[:20]
            })
            folder_path = f"{self.base_folder}/{folder_name}"

        access_token = await self._get_access_token()
        if not access_token:
            raise Exception("Failed to get access token")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            success = await self._ensure_folder_exists(session, headers, folder_path)
            if not success:
                raise Exception(f"Failed to create folder: {folder_path}")

        return folder_path

    async def create_folder_flat(self, base_path: Optional[str] = None) -> str:
        """
        flat_folder 모드: base_folder만 생성 (하위폴더 없음)

        Args:
            base_path: 커스텀 베이스 경로 (None이면 self.base_folder 사용)

        Returns:
            폴더 경로
        """
        folder_path = base_path if base_path else self.base_folder

        access_token = await self._get_access_token()
        if not access_token:
            raise Exception("Failed to get access token")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            success = await self._ensure_folder_exists(session, headers, folder_path)
            if not success:
                raise Exception(f"Failed to create folder: {folder_path}")

        return folder_path

    async def _upload_simple(
        self,
        session: aiohttp.ClientSession,
        headers: Dict[str, str],
        file_path: str,
        content: bytes,
        filename: str
    ) -> Optional[str]:
        """
        단순 PUT 업로드 (4MB 이하)

        Args:
            session: aiohttp 세션
            headers: 요청 헤더
            file_path: OneDrive 파일 경로
            content: 파일 내용
            filename: 원본 파일명

        Returns:
            저장된 파일 URL 또는 None
        """
        upload_url = f"{self.graph_url}/users/{self.user_email}/drive/root:/{file_path}:/content"

        async with session.put(upload_url, headers=headers, data=content) as response:
            if response.status in [200, 201]:
                result = await response.json()
                web_url = result.get("webUrl", file_path)
                print(f"  [ONEDRIVE] {filename} ({len(content):,} bytes)")
                return web_url
            else:
                error_text = await response.text()
                print(f"  [ERROR] {filename} 업로드 실패: {error_text[:100]}")
                return None

    async def _upload_large(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        file_path: str,
        content: bytes,
        filename: str
    ) -> Optional[str]:
        """
        Upload Session을 사용한 대용량 파일 업로드 (4MB 초과)

        Args:
            session: aiohttp 세션
            access_token: 액세스 토큰
            file_path: OneDrive 파일 경로
            content: 파일 내용
            filename: 원본 파일명

        Returns:
            저장된 파일 URL 또는 None
        """
        file_size = len(content)
        print(f"  [ONEDRIVE] 대용량 업로드 시작: {filename} ({file_size:,} bytes)")

        # Step 1: Upload Session 생성
        create_session_url = f"{self.graph_url}/users/{self.user_email}/drive/root:/{file_path}:/createUploadSession"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        session_body = {
            "item": {
                "@microsoft.graph.conflictBehavior": "rename",
                "name": filename
            }
        }

        async with session.post(create_session_url, headers=headers, json=session_body) as response:
            if response.status not in [200, 201]:
                error_text = await response.text()
                print(f"  [ERROR] Upload Session 생성 실패: {error_text[:100]}")
                return None

            session_data = await response.json()
            upload_url = session_data.get("uploadUrl")

            if not upload_url:
                print(f"  [ERROR] Upload URL을 받지 못함")
                return None

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

            # Content-Range 헤더 설정
            content_range = f"bytes {start}-{end - 1}/{file_size}"

            chunk_headers = {
                "Content-Length": str(chunk_len),
                "Content-Range": content_range,
            }

            async with session.put(upload_url, headers=chunk_headers, data=chunk_data) as response:
                if response.status in [200, 201]:
                    # 업로드 완료 (마지막 청크에서만 200/201 반환)
                    result = await response.json()
                    web_url = result.get("webUrl", file_path)
                    print(f"  [ONEDRIVE] 업로드 완료: {filename} ({file_size:,} bytes)")
                    return web_url
                elif response.status == 202:
                    # 계속 업로드 중
                    uploaded = end
                    progress = (uploaded / file_size) * 100
                    print(f"    청크 {chunk_num + 1}/{total_chunks} 완료 ({progress:.1f}%)")

                    # 마지막 청크인데 202가 반환된 경우 (비정상)
                    if is_last_chunk:
                        print(f"  [WARN] 마지막 청크인데 202 반환됨, 업로드 세션 상태 확인 필요")
                        # 마지막 청크 202: 세션 상태 확인
                        async with session.get(upload_url) as status_resp:
                            if status_resp.status in [200, 201]:
                                status_data = await status_resp.json()
                                web_url = status_data.get("webUrl", file_path)
                                print(f"  [ONEDRIVE] 업로드 완료 (지연): {filename}")
                                return web_url
                else:
                    error_text = await response.text()
                    print(f"  [ERROR] 청크 업로드 실패: {error_text[:100]}")

                    # 1회 재시도
                    await asyncio.sleep(2)
                    async with session.put(upload_url, headers=chunk_headers, data=chunk_data) as retry_resp:
                        if retry_resp.status in [200, 201, 202]:
                            if retry_resp.status in [200, 201]:
                                result = await retry_resp.json()
                                web_url = result.get("webUrl", file_path)
                                print(f"  [ONEDRIVE] 업로드 완료 (재시도): {filename}")
                                return web_url
                            # 202면 계속 진행
                            uploaded = end
                            print(f"    청크 {chunk_num + 1}/{total_chunks} 재시도 성공")
                            continue
                        else:
                            retry_error = await retry_resp.text()
                            print(f"  [ERROR] 청크 재시도도 실패: {retry_error[:100]}")

                    # Upload Session 취소
                    await session.delete(upload_url)
                    return None

        # 모든 청크가 202로 끝난 경우 (비정상 - 마지막 청크는 200/201이어야 함)
        print(f"  [ERROR] 업로드 완료 응답(200/201)을 받지 못함")
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
                print(f"  [SKIP] {filename} - 250GB 초과 (OneDrive 제한)")
                return None

            access_token = await self._get_access_token()
            if not access_token:
                return None

            # 파일명 정제
            safe_name = self.sanitize_filename(filename, max_length=100)
            file_path = f"{folder_path}/{safe_name}"

            async with aiohttp.ClientSession() as session:
                if file_size <= self.SIMPLE_UPLOAD_MAX_SIZE:
                    # 4MB 이하: 단순 PUT 업로드
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": content_type or "application/octet-stream",
                    }
                    return await self._upload_simple(session, headers, file_path, content, safe_name)
                else:
                    # 4MB 초과: Upload Session (청크 업로드)
                    return await self._upload_large(session, access_token, file_path, content, safe_name)

        except Exception as e:
            print(f"  [ERROR] {filename} 업로드 예외: {e}")
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
            # 메일 정보 구성
            content_lines = [
                "=" * 60,
                f"Subject: {mail_data.get('subject', 'N/A')}",
                f"From: {mail_data.get('from', {}).get('emailAddress', {}).get('address', 'N/A')}",
                f"Received: {mail_data.get('receivedDateTime', 'N/A')}",
                f"Message ID: {mail_data.get('id', 'N/A')}",
                "=" * 60,
                "",
            ]

            # 본문 추출
            body = mail_data.get("body", {})
            body_content = body.get("content", "")
            body_type = body.get("contentType", "text")

            if body_type == "html":
                body_content = re.sub(r"<[^>]+>", "", body_content)
                body_content = re.sub(r"&nbsp;", " ", body_content)
                body_content = re.sub(r"&lt;", "<", body_content)
                body_content = re.sub(r"&gt;", ">", body_content)
                body_content = re.sub(r"&amp;", "&", body_content)

            content_lines.append(body_content)

            # bytes로 변환
            content_bytes = "\n".join(content_lines).encode("utf-8")

            return await self.save_file(
                folder_path,
                "mail_content.txt",
                content_bytes,
                "text/plain; charset=utf-8"
            )

        except Exception as e:
            print(f"  [ERROR] 메일 본문 저장 실패: {e}")
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
            print(f"  [SKIP] {name} - contentBytes 없음 (대용량 파일)")
            return None

        # 파일명 정제
        safe_name = self.sanitize_filename(name, max_length=100)

        # 중복 파일명 처리
        folder = Path(folder_path)
        file_path = folder / safe_name
        counter = 1
        while file_path.exists():
            name_parts = safe_name.rsplit(".", 1)
            if len(name_parts) == 2:
                new_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
            else:
                new_name = f"{safe_name}_{counter}"
            file_path = folder / new_name
            counter += 1

        try:
            # Base64 디코딩 및 저장
            file_content = base64.b64decode(content_bytes)
            with open(file_path, "wb") as f:
                f.write(file_content)

            print(f"  [SAVED] {file_path.name} ({len(file_content):,} bytes)")
            return str(file_path)

        except Exception as e:
            print(f"  [ERROR] {name} 저장 실패: {e}")
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

            # 메일 정보 구성
            content_lines = [
                "=" * 60,
                f"Subject: {mail_data.get('subject', 'N/A')}",
                f"From: {mail_data.get('from', {}).get('emailAddress', {}).get('address', 'N/A')}",
                f"Received: {mail_data.get('receivedDateTime', 'N/A')}",
                f"Message ID: {mail_data.get('id', 'N/A')}",
                "=" * 60,
                "",
            ]

            # 본문 추출
            body = mail_data.get("body", {})
            body_content = body.get("content", "")
            body_type = body.get("contentType", "text")

            if body_type == "html":
                # HTML 태그 간단히 제거
                body_content = re.sub(r"<[^>]+>", "", body_content)
                body_content = re.sub(r"&nbsp;", " ", body_content)
                body_content = re.sub(r"&lt;", "<", body_content)
                body_content = re.sub(r"&gt;", ">", body_content)
                body_content = re.sub(r"&amp;", "&", body_content)

            content_lines.append(body_content)

            # 파일 저장
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(content_lines))

            print(f"  [SAVED] mail_content.txt")
            return str(file_path)

        except Exception as e:
            print(f"  [ERROR] 메일 본문 저장 실패: {e}")
            return None


def get_storage_backend(
    storage_type: str = "local",
    auth_manager: Optional[AuthManager] = None,
    user_email: Optional[str] = None,
    **kwargs
) -> StorageBackend:
    """
    Storage Backend 팩토리 함수

    Args:
        storage_type: "local" 또는 "onedrive"
        auth_manager: AuthManager (OneDrive용)
        user_email: 사용자 이메일 (OneDrive용)
        **kwargs: 추가 옵션
            - base_directory: 로컬 저장 디렉토리 (기본: "downloads")
            - base_folder: OneDrive 기본 폴더 (기본: "/Attachments")

    Returns:
        StorageBackend 인스턴스
    """
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
