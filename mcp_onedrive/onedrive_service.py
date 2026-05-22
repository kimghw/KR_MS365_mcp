"""
OneDrive Service - GraphOneDriveClient Facade
인자를 그대로 위임하고, 필요시 일부 값만 조정하는 서비스 레이어
(mcp_outlook/outlook_service.py 구조 참조)
"""

from typing import Dict, Any, Optional, List

from .graph_onedrive_client import GraphOneDriveClient
from .onedrive_types import (
    ConflictBehavior,
)

# Default user email helper
def _get_default_user_email() -> Optional[str]:
    """
    auth.db의 azure_user_info 테이블에서 첫 번째 user_email을 가져옴

    Returns:
        첫 번째 사용자 이메일 또는 None
    """
    try:
        from session.auth_database import AuthDatabase
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email') or users[0].get('email')
        return None
    except Exception:
        return None

# mcp_service decorator is only needed for registry scanning, not runtime
try:
    from mcp_editor.mcp_service_registry.mcp_service_decorator import mcp_service
except ImportError:
    # Define a no-op decorator for runtime when mcp_editor is not available
    def mcp_service(**kwargs):
        def decorator(func):
            return func
        return decorator


class OneDriveService:
    """
    GraphOneDriveClient의 Facade

    - 동일 시그니처로 위임
    - 일부 값만 조정/하드코딩
    """

    def __init__(self):
        self._client: Optional[GraphOneDriveClient] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """서비스 초기화"""
        if self._initialized:
            return True

        self._client = GraphOneDriveClient()

        if await self._client.initialize():
            self._initialized = True
            return True
        return False

    def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized or not self._client:
            raise RuntimeError("OneDriveService not initialized. Call initialize() first.")

    async def close(self):
        """리소스 정리"""
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
        if not user_email:
            user_email = _get_default_user_email()
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
        if not user_email:
            user_email = _get_default_user_email()
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
        if not user_email:
            user_email = _get_default_user_email()
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
        if not user_email:
            user_email = _get_default_user_email()
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
        if not user_email:
            user_email = _get_default_user_email()
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
        if not user_email:
            user_email = _get_default_user_email()
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
        if not user_email:
            user_email = _get_default_user_email()
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
        if not user_email:
            user_email = _get_default_user_email()
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
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "user_email이 필요합니다. 등록된 사용자가 없습니다."}
        return await self._client.move_file(user_email, source_path, dest_path, new_name)
