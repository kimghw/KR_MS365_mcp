"""
OneDrive Service - GraphOneDriveClient Facade
인자를 그대로 위임하고, 필요시 일부 값만 조정하는 서비스 레이어
(mcp_outlook/outlook_service.py 구조 참조)

멀티유저(MS365_MULTI_USER=1, spec/spec_멀티유저.md ②-7.3·②-7.6):
  - 서비스는 사용자별로 풀(`mcp_common.service_pool`)이 만든다. 생성 시 받은 사용자 고정
    `token_provider` 를 GraphClient 에 그대로 넘기며, 공용 AuthManager 를 끌어오지 않는다.
  - `user_email` 은 요청 principal 의 연결 계정만 허용한다(생략 → 본인). 기본 사용자
    선택(환경변수·auth.db)은 mode 0 에서만 쓴다.
  - OneDrive 도구는 로컬 파일을 쓰지 않는다(읽기 결과는 응답 본문으로만 돌려준다).
    로컬 저장을 추가할 때는 `paths.downloads_for("onedrive")` + `mcp_common.secure_files`
    를 쓰고, 응답에는 `public_path()` 상대경로만 싣는다.
"""

import logging
from typing import Dict, Any, Optional, List

from mcp_common.principal import MISSING, assert_user_email, require_principal
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled
from mcp_common.user_resolver import resolve_user_email

from .graph_onedrive_client import GraphOneDriveClient
from mcp_common.input_bounds import check_top
from .onedrive_types import (
    ConflictBehavior,
)

logger = logging.getLogger(__name__)


# 기본 사용자 선택은 mcp_common.user_resolver 정책(SSOT)에 위임한다. **mode 0 전용.**
def _get_default_user_email() -> Optional[str]:
    """
    기본 사용자 이메일 반환 (mode 0 전용 — 멀티유저 경로에서는 부르지 않는다).

    Returns:
        결정된 사용자 이메일 또는 None
    """
    return resolve_user_email()


# mcp_service 는 메타데이터 표식일 뿐 런타임에는 영향이 없다.
# 도구의 실제 계약은 spec/param_spec/onedrive.yaml 이며 이 데코레이터의 인자가 아니다.
from mcp_common.service_meta import mcp_service


class OneDriveService:
    """
    GraphOneDriveClient의 Facade

    - 동일 시그니처로 위임
    - 일부 값만 조정/하드코딩
    """

    def __init__(self, token_provider: Optional[Any] = None, paths: Optional[Any] = None):
        """
        Args:
            token_provider: 사용자 고정 토큰 공급자(멀티유저 factory 가 주입). None 이면
                mode 0 의 공용 AuthManager 를 GraphClient 가 쓴다 — mode 1 에서는 오류.
            paths: 사용자 저장 경로(`mcp_common.user_paths.UserPaths`). 현재 로컬 저장은 없다.
        """
        self._token_provider = token_provider
        self._paths = paths
        # 이 서비스가 묶인 사용자. 요청 principal 과 다르면 거부한다(방어 심층).
        self._owner_key: Optional[str] = getattr(token_provider, "user_key", None)
        self._client: Optional[GraphOneDriveClient] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """서비스 초기화"""
        if self._initialized:
            return True

        self._client = GraphOneDriveClient(token_provider=self._token_provider)

        if await self._client.initialize():
            self._initialized = True
            return True
        return False

    def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized or not self._client:
            raise RuntimeError("OneDriveService not initialized. Call initialize() first.")

    def _resolve_email(self, user_email: Optional[str]) -> Optional[str]:
        """호출 대상 계정.

        - mode 1: 요청 principal 의 연결 계정만 (생략 → 본인, 다른 값 → `identity_mismatch`).
          다른 사용자에게 묶인 서비스로 들어온 요청도 거부한다.
        - mode 0: 명시값 → `mcp_common.user_resolver` 기본 사용자.
        """
        if multi_user_enabled():
            email = assert_user_email(MISSING if user_email is None else user_email)
            if self._owner_key is not None and require_principal().user_key != self._owner_key:
                raise SecurityError(ErrorCode.IDENTITY_MISMATCH)
            return email
        return user_email or _get_default_user_email()

    async def close(self):
        """리소스 정리 — 자신이 만든 GraphClient(HTTP 세션)만 닫는다. 토큰 공급자는 닫지 않는다."""
        if self._client:
            await self._client.close()
            self._client = None
        self._initialized = False

    # ========================================================================
    # 드라이브 정보 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_onedrive_get_drive_info",
        server_name="onedrive",
        service_name="get_drive_info",
        category="onedrive_drive",
        tags=["query", "drive"],
        priority=5,
        description="OneDrive 드라이브 정보 조회",
    )
    async def get_drive_info(
        self,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """드라이브 정보 조회"""
        self._ensure_initialized()
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.get_drive_info(user_email)

    # ========================================================================
    # 파일/폴더 목록 조회 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_onedrive_list_files",
        server_name="onedrive",
        service_name="list_files",
        category="onedrive_file",
        tags=["query", "file", "folder"],
        priority=5,
        description="OneDrive 파일/폴더 목록 조회",
    )
    async def list_files(
        self,
        user_email: Optional[str] = None,
        folder_path: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """파일/폴더 목록 조회"""
        self._ensure_initialized()
        limit = check_top(limit, name="limit")  # R02 — = onedrive.yaml limit maximum
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.list_files(user_email, folder_path, search, limit)

    @mcp_service(
        tool_name="handler_onedrive_get_item",
        server_name="onedrive",
        service_name="get_item",
        category="onedrive_file",
        tags=["query", "file"],
        priority=5,
        description="OneDrive 파일/폴더 정보 조회",
    )
    async def get_item(
        self,
        file_path: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """파일/폴더 정보 조회"""
        self._ensure_initialized()
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.get_item(user_email, file_path)

    # ========================================================================
    # 파일 읽기/쓰기 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_onedrive_read_file",
        server_name="onedrive",
        service_name="read_file",
        category="onedrive_file",
        tags=["read", "file"],
        priority=5,
        description="OneDrive 파일 내용 읽기",
    )
    async def read_file(
        self,
        file_path: str,
        user_email: Optional[str] = None,
        as_text: bool = True,
    ) -> Dict[str, Any]:
        """파일 내용 읽기"""
        self._ensure_initialized()
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.read_file(user_email, file_path, as_text)

    @mcp_service(
        tool_name="handler_onedrive_write_file",
        server_name="onedrive",
        service_name="write_file",
        category="onedrive_file",
        tags=["write", "file"],
        priority=5,
        description="OneDrive 파일 쓰기/업로드",
    )
    async def write_file(
        self,
        file_path: str,
        content: str,
        user_email: Optional[str] = None,
        content_type: str = "text/plain",
        overwrite: bool = True,
    ) -> Dict[str, Any]:
        """파일 쓰기/업로드"""
        self._ensure_initialized()
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}

        conflict_behavior = ConflictBehavior.REPLACE if overwrite else ConflictBehavior.FAIL

        return await self._client.write_file(
            user_email=user_email,
            file_path=file_path,
            content=content,
            content_type=content_type,
            conflict_behavior=conflict_behavior,
        )

    @mcp_service(
        tool_name="handler_onedrive_delete_file",
        server_name="onedrive",
        service_name="delete_file",
        category="onedrive_file",
        tags=["delete", "file"],
        priority=5,
        description="OneDrive 파일/폴더 삭제",
    )
    async def delete_file(
        self,
        file_path: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """파일/폴더 삭제"""
        self._ensure_initialized()
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.delete_file(user_email, file_path)

    # ========================================================================
    # 폴더 관리 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_onedrive_create_folder",
        server_name="onedrive",
        service_name="create_folder",
        category="onedrive_folder",
        tags=["create", "folder"],
        priority=5,
        description="OneDrive 폴더 생성",
    )
    async def create_folder(
        self,
        folder_name: str,
        user_email: Optional[str] = None,
        parent_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """폴더 생성"""
        self._ensure_initialized()
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.create_folder(user_email, folder_name, parent_path)

    # ========================================================================
    # 파일 복사/이동 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_onedrive_copy_file",
        server_name="onedrive",
        service_name="copy_file",
        category="onedrive_file",
        tags=["copy", "file"],
        priority=5,
        description="OneDrive 파일 복사",
    )
    async def copy_file(
        self,
        source_path: str,
        dest_path: str,
        user_email: Optional[str] = None,
        new_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """파일 복사"""
        self._ensure_initialized()
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.copy_file(user_email, source_path, dest_path, new_name)

    @mcp_service(
        tool_name="handler_onedrive_move_file",
        server_name="onedrive",
        service_name="move_file",
        category="onedrive_file",
        tags=["move", "file"],
        priority=5,
        description="OneDrive 파일 이동",
    )
    async def move_file(
        self,
        source_path: str,
        dest_path: str,
        user_email: Optional[str] = None,
        new_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """파일 이동"""
        self._ensure_initialized()
        user_email = self._resolve_email(user_email)
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.move_file(user_email, source_path, dest_path, new_name)
