"""
개별 첨부파일 조회/다운로드 핸들러 (mail_attachment.py 에서 분리, 관문은 mail_attachment).

멀티유저(spec/spec_멀티유저.md ②-2.5 "토큰 보유 첨부 객체") — 이 객체는 토큰을 **보관하지
않는다.** `token_provider` 를 받아 요청마다 토큰을 얻어 헤더를 새로 만든다. 문자열
`access_token` 을 직접 넘기는 생성자는 mode 0 하위 호환 전용이고 mode 1 에서는 거부한다.

경로 성분(user·message_id·attachment_id)은 인코딩해 Graph 경로 주입을 막고, Authorization 을
단 요청은 redirect 를 따라가지 않는다.

한계 (astra 3차 N08 gap 3): 첨부 GET 응답은 `Content-Length` 가 있을 때만 본문을 읽기 전에
첨부 1건 한도(`MAX_ATTACHMENT_BYTES`, base64 기준 4/3 + 여유)를 거부한다. chunked 응답이면
`.json()` 이 본문 전체를 읽은 뒤 호출 측의 크기 검사가 적용된다. 로컬 저장은 `paths` 가 있으면(mode 1) 사용자
`files/downloads/outlook/` 안에 배타 생성한다.
"""

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from mcp_common.secure_files import safe_filename
from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import SecurityError
from mcp_common.security_policy import multi_user_enabled

from . import outlook_security as limits

from .outlook_security import (
    BEARER_KW,
    GRAPH_BASE,
    AttachmentLimitExceeded,
    GraphRequestError,
    acquire_token,
    bearer_headers,
    response_too_large,
    seg,
    user_seg,
)

logger = logging.getLogger(__name__)


class SingleAttachmentHandler:
    """
    개별 첨부파일 조회/다운로드용 핸들러

    메서드:
        - list_attachments(message_id, user_id="me")
        - get_attachment(message_id, attachment_id, user_id="me")
        - get_message_summary(message_id, user_id="me")
        - download_attachment(message_id, attachment_id, save_path, user_id="me")
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        *,
        token_provider: Any = None,
        user_email: Optional[str] = None,
        paths: Any = None,
    ):
        """
        Args:
            access_token: (mode 0 하위 호환) 이미 얻은 액세스 토큰. mode 1 에서는 쓸 수 없다.
            token_provider: 요청마다 토큰을 얻을 공급자 (권장)
            user_email: 공급자에 넘길 사용자 이메일
            paths: mode 1 사용자 경로 (로컬 저장 위치)
        """
        if access_token is None and token_provider is None:
            raise ValueError("access_token 또는 token_provider 가 필요합니다")
        if access_token is not None and multi_user_enabled():
            raise RuntimeError("멀티유저 모드에서는 토큰을 보관하는 첨부 핸들러를 만들 수 없습니다")
        self._token_provider = token_provider
        self._user_email = user_email
        self.paths = paths
        self.base_url = GRAPH_BASE
        if access_token is not None:
            # mode 0 하위 호환: 호출자가 준 토큰 (이 객체 수명 = 호출자 요청 1건)
            self.access_token = access_token
            self.headers = bearer_headers(access_token)

    async def request_headers(self) -> Dict[str, str]:
        """요청 1건용 헤더. 공급자가 있으면 매번 새로 만든다(보관하지 않음)."""
        if self._token_provider is None:
            return dict(self.headers)
        token = await acquire_token(self._token_provider, self._user_email)
        if not token:
            raise RuntimeError("Failed to acquire access token")
        return bearer_headers(token)

    def _message_url(self, user_id: str, message_id: str) -> str:
        return f"{self.base_url}/users/{user_seg(user_id)}/messages/{seg(message_id)}"

    async def _get_json(self, url: str, what: str) -> Dict[str, Any]:
        headers = await self.request_headers()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, **BEARER_KW) as response:
                if response.status == 200:
                    if response_too_large(response, limits.MAX_ATTACHMENT_BYTES * 4 // 3 + 64 * 1024):
                        raise AttachmentLimitExceeded("response_too_large", limits.MAX_ATTACHMENT_BYTES)
                    return await response.json()
                error_text = await response.text()
                # R06: 본문 원문을 예외에 싣지 않는다 — 상태 코드·검증된 오류 코드만
                raise GraphRequestError(response.status, error_text, what=what)

    async def list_attachments(self, message_id: str, user_id: str = "me") -> List[Dict[str, Any]]:
        """
        특정 메일의 첨부 파일 목록 조회

        Args:
            message_id: 메일 메시지 ID
            user_id: 사용자 ID (기본값: "me")

        Returns:
            첨부 파일 정보 목록
        """
        data = await self._get_json(f"{self._message_url(user_id, message_id)}/attachments", "list attachments")
        result = []
        for attachment in data.get("value", []):
            att_info = {
                "id": attachment.get("id"),
                "name": attachment.get("name"),
                "contentType": attachment.get("contentType"),
                "size": attachment.get("size"),
                "isInline": attachment.get("isInline", False),
                "@odata.type": attachment.get("@odata.type"),
            }
            if attachment.get("@odata.type") == "#microsoft.graph.fileAttachment":
                att_info["contentId"] = attachment.get("contentId")
                att_info["contentLocation"] = attachment.get("contentLocation")
            result.append(att_info)
        return result

    async def get_attachment(self, message_id: str, attachment_id: str, user_id: str = "me") -> Dict[str, Any]:
        """
        특정 첨부 파일의 상세 정보 및 내용 조회

        Args:
            message_id: 메일 메시지 ID
            attachment_id: 첨부 파일 ID
            user_id: 사용자 ID (기본값: "me")

        Returns:
            첨부 파일 상세 정보 (내용 포함)
        """
        url = f"{self._message_url(user_id, message_id)}/attachments/{seg(attachment_id)}"
        return await self._get_json(url, "get attachment")

    async def get_message_summary(self, message_id: str, user_id: str = "me") -> Dict[str, Any]:
        """폴더명 생성용 메일 요약(subject/from/receivedDateTime). 실패하면 빈 dict."""
        url = f"{self._message_url(user_id, message_id)}?$select=subject,from,receivedDateTime"
        try:
            return await self._get_json(url, "get message")
        except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
            raise
        except Exception:
            return {}

    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        save_path: Optional[str] = None,
        user_id: str = "me",
    ) -> str:
        """
        첨부 파일 다운로드 및 저장

        Args:
            message_id: 메일 메시지 ID
            attachment_id: 첨부 파일 ID
            save_path: 저장 경로 (없으면 downloads 폴더에 저장). mode 1 에서는 사용자 files/ 안만.
            user_id: 사용자 ID (기본값: "me")

        Returns:
            저장된 파일 경로 (mode 1 은 files/ 기준 상대경로)
        """
        attachment = await self.get_attachment(message_id, attachment_id, user_id)
        if attachment.get("@odata.type") != "#microsoft.graph.fileAttachment":
            raise ValueError(f"Unsupported attachment type: {attachment.get('@odata.type')}")
        content_bytes = attachment.get("contentBytes")
        if not content_bytes:
            raise ValueError("No content bytes in attachment")
        file_content = base64.b64decode(content_bytes)
        filename = attachment.get("name") or f"attachment_{attachment_id}"

        if self.paths is not None:
            from .mail_attachment_user_storage import UserLocalStorageBackend
            from .outlook_file_policy import resolve_save_dir

            if save_path:
                base = resolve_save_dir(self.paths, str(Path(str(save_path)).parent))
                storage = UserLocalStorageBackend(self.paths, base)
                folder = storage.base_directory
                filename = Path(str(save_path)).name or filename
            else:
                storage = UserLocalStorageBackend(self.paths, resolve_save_dir(self.paths, None))
                folder = storage.folder_for_name(storage.base_directory, str(message_id)[:8])
            return storage.public(storage.write_bytes(folder, filename, file_content))

        # mode 0 (기존 동작): save_path 는 그대로, 없으면 downloads/<message_id 8자>/<이름>.
        # 원격 이름·message_id 는 단일 이름으로 정화해 디렉터리 탈출을 막는다.
        if save_path:
            file_path = Path(save_path)
        else:
            file_path = Path("downloads") / safe_filename(str(message_id)[:8]) / safe_filename(filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(file_content)
        return str(file_path)


__all__ = ["SingleAttachmentHandler"]
