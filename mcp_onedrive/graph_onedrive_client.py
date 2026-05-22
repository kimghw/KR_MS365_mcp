"""
OneDrive Graph API Client
Microsoft Graph API를 사용한 OneDrive 작업 처리
session 모듈을 통한 인증 관리
"""

import base64
import logging
from typing import Optional, List, Dict, Any
import aiohttp

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session import AuthManager
from .onedrive_types import (
    DriveInfo,
    DriveItem,
    FileInfo,
    FolderInfo,
    ItemType,
    ConflictBehavior,
)

logger = logging.getLogger(__name__)


class GraphOneDriveClient:
    """OneDrive Graph API 클라이언트"""

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, auth_manager: Optional[AuthManager] = None):
        """
        클라이언트 초기화

        Args:
            auth_manager: 인증 매니저 인스턴스 (없으면 새로 생성)
        """
        self.auth_manager = auth_manager or AuthManager()
        self._session: Optional[aiohttp.ClientSession] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """클라이언트 초기화"""
        if self._initialized:
            return True

        self._session = aiohttp.ClientSession()
        self._initialized = True
        logger.info("GraphOneDriveClient initialized")
        return True

    async def close(self):
        """리소스 정리"""
        if self._session:
            await self._session.close()
            self._session = None
        self._initialized = False

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        """
        사용자 이메일로 유효한 액세스 토큰 조회 (자동 갱신 포함)

        Args:
            user_email: 사용자 이메일

        Returns:
            유효한 액세스 토큰 또는 None
        """
        try:
            token = await self.auth_manager.validate_and_refresh_token(user_email)
            return token
        except Exception as e:
            logger.error(f"토큰 조회 실패: {str(e)}")
            return None

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        user_email: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        content_type: str = "application/json",
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Graph API 요청 수행

        Args:
            method: HTTP 메서드 (GET, POST, PUT, PATCH, DELETE)
            endpoint: API 엔드포인트
            user_email: 사용자 이메일
            json_data: JSON 데이터
            data: 바이너리 데이터
            content_type: Content-Type 헤더
            timeout: 타임아웃 (초)

        Returns:
            API 응답
        """
        if not self._initialized:
            await self.initialize()

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다. 로그인이 필요합니다."}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
        }

        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data if json_data else None,
                data=data if data else None,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status in (200, 201, 204):
                    if response.status == 204:
                        return {"success": True}
                    result = await response.json()
                    return {"success": True, "data": result}
                else:
                    error_text = await response.text()
                    logger.error(f"API 요청 실패: {response.status} - {error_text}")
                    return {
                        "success": False,
                        "error": f"API 요청 실패: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"API 요청 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    def _build_path(self, folder_path: Optional[str]) -> str:
        """
        폴더 경로를 API 엔드포인트로 변환

        Args:
            folder_path: 폴더 경로 (예: Documents/MyFolder)

        Returns:
            API 엔드포인트 경로
        """
        if not folder_path or folder_path == "/":
            return "/me/drive/root/children"
        return f"/me/drive/root:/{folder_path}:/children"

    # ========================================================================
    # 드라이브 정보 메서드
    # ========================================================================

    async def get_drive_info(
        self,
        user_email: str,
    ) -> Dict[str, Any]:
        """
        사용자 드라이브 정보 조회

        Args:
            user_email: 사용자 이메일

        Returns:
            드라이브 정보
        """
        endpoint = "/me/drive"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            drive = DriveInfo.from_dict(result.get("data", {}))
            return {"success": True, "drive": drive.__dict__}

        return result

    # ========================================================================
    # 파일/폴더 목록 조회 메서드
    # ========================================================================

    async def list_files(
        self,
        user_email: str,
        folder_path: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        파일/폴더 목록 조회

        Args:
            user_email: 사용자 이메일
            folder_path: 폴더 경로 (없으면 루트)
            search: 검색어
            limit: 조회할 아이템 개수

        Returns:
            파일/폴더 목록
        """
        if search:
            # 검색 모드
            endpoint = f"/me/drive/root/search(q='{search}')?$top={limit}"
        else:
            # 폴더 목록 모드
            endpoint = self._build_path(folder_path) + f"?$top={limit}"

        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            items_data = result.get("data", {}).get("value", [])
            items = [DriveItem.from_dict(item) for item in items_data]
            return {
                "success": True,
                "files": [item.__dict__ for item in items],
                "count": len(items),
            }

        return result

    async def get_item(
        self,
        user_email: str,
        file_path: str,
    ) -> Dict[str, Any]:
        """
        파일/폴더 정보 조회

        Args:
            user_email: 사용자 이메일
            file_path: 파일/폴더 경로

        Returns:
            아이템 정보
        """
        endpoint = f"/me/drive/root:/{file_path}"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            item = DriveItem.from_dict(result.get("data", {}))
            return {"success": True, "item": item.__dict__}

        return result

    # ========================================================================
    # 파일 읽기/쓰기 메서드
    # ========================================================================

    async def read_file(
        self,
        user_email: str,
        file_path: str,
        as_text: bool = True,
    ) -> Dict[str, Any]:
        """
        파일 내용 읽기

        Args:
            user_email: 사용자 이메일
            file_path: 파일 경로
            as_text: True면 텍스트로, False면 base64로 반환

        Returns:
            파일 내용
        """
        if not self._initialized:
            await self.initialize()

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다."}

        headers = {"Authorization": f"Bearer {access_token}"}
        endpoint = f"/me/drive/root:/{file_path}:/content"
        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                if response.status == 200:
                    content_bytes = await response.read()

                    if as_text:
                        try:
                            content = content_bytes.decode("utf-8")
                            return {
                                "success": True,
                                "file_path": file_path,
                                "content": content,
                                "content_type": "text",
                            }
                        except UnicodeDecodeError:
                            # UTF-8 디코딩 실패 시 base64로 반환
                            content = base64.b64encode(content_bytes).decode("ascii")
                            return {
                                "success": True,
                                "file_path": file_path,
                                "content": content,
                                "content_type": "base64",
                            }
                    else:
                        content = base64.b64encode(content_bytes).decode("ascii")
                        return {
                            "success": True,
                            "file_path": file_path,
                            "content": content,
                            "content_type": "base64",
                        }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"파일 읽기 실패: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"파일 읽기 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    async def write_file(
        self,
        user_email: str,
        file_path: str,
        content: str,
        content_type: str = "text/plain",
        conflict_behavior: ConflictBehavior = ConflictBehavior.REPLACE,
    ) -> Dict[str, Any]:
        """
        파일 작성/업로드

        Args:
            user_email: 사용자 이메일
            file_path: 파일 경로
            content: 파일 내용
            content_type: 콘텐츠 타입
            conflict_behavior: 충돌 시 동작

        Returns:
            작성된 파일 정보
        """
        if not self._initialized:
            await self.initialize()

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다."}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
        }

        # 충돌 동작 설정
        conflict_str = conflict_behavior.value
        endpoint = f"/me/drive/root:/{file_path}:/content?@microsoft.graph.conflictBehavior={conflict_str}"
        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            data = content.encode("utf-8")
            async with self._session.put(
                url,
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                if response.status in (200, 201):
                    result = await response.json()
                    item = DriveItem.from_dict(result)
                    return {
                        "success": True,
                        "file": item.__dict__,
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"파일 쓰기 실패: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"파일 쓰기 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    async def delete_file(
        self,
        user_email: str,
        file_path: str,
    ) -> Dict[str, Any]:
        """
        파일/폴더 삭제

        Args:
            user_email: 사용자 이메일
            file_path: 파일/폴더 경로

        Returns:
            삭제 결과
        """
        endpoint = f"/me/drive/root:/{file_path}"
        result = await self._make_request("DELETE", endpoint, user_email)

        if result.get("success"):
            return {"success": True, "message": f"파일 삭제됨: {file_path}"}

        return result

    # ========================================================================
    # 폴더 생성 메서드
    # ========================================================================

    async def create_folder(
        self,
        user_email: str,
        folder_name: str,
        parent_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        폴더 생성

        Args:
            user_email: 사용자 이메일
            folder_name: 생성할 폴더 이름
            parent_path: 부모 폴더 경로 (없으면 루트)

        Returns:
            생성된 폴더 정보
        """
        if parent_path:
            endpoint = f"/me/drive/root:/{parent_path}:/children"
        else:
            endpoint = "/me/drive/root/children"

        json_data = {
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "rename",
        }

        result = await self._make_request("POST", endpoint, user_email, json_data)

        if result.get("success"):
            folder = FolderInfo.from_dict(result.get("data", {}))
            return {"success": True, "folder": folder.__dict__}

        return result

    async def copy_file(
        self,
        user_email: str,
        source_path: str,
        dest_path: str,
        new_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        파일 복사

        Args:
            user_email: 사용자 이메일
            source_path: 원본 파일 경로
            dest_path: 대상 폴더 경로
            new_name: 새 파일 이름 (없으면 원본 이름 유지)

        Returns:
            복사 작업 결과
        """
        # 먼저 대상 폴더 ID를 가져옴
        dest_result = await self.get_item(user_email, dest_path)
        if not dest_result.get("success"):
            return dest_result

        dest_id = dest_result.get("item", {}).get("id")
        if not dest_id:
            return {"success": False, "error": "대상 폴더를 찾을 수 없습니다."}

        endpoint = f"/me/drive/root:/{source_path}:/copy"
        json_data = {
            "parentReference": {"id": dest_id},
        }
        if new_name:
            json_data["name"] = new_name

        # copy 요청은 202 Accepted 반환
        if not self._initialized:
            await self.initialize()

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다."}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            async with self._session.post(
                url,
                headers=headers,
                json=json_data,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                if response.status == 202:
                    # 비동기 작업 시작됨
                    monitor_url = response.headers.get("Location")
                    return {
                        "success": True,
                        "message": "복사 작업이 시작되었습니다.",
                        "monitor_url": monitor_url,
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"파일 복사 실패: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"파일 복사 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    async def move_file(
        self,
        user_email: str,
        source_path: str,
        dest_path: str,
        new_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        파일 이동

        Args:
            user_email: 사용자 이메일
            source_path: 원본 파일 경로
            dest_path: 대상 폴더 경로
            new_name: 새 파일 이름 (없으면 원본 이름 유지)

        Returns:
            이동된 파일 정보
        """
        # 먼저 대상 폴더 ID를 가져옴
        dest_result = await self.get_item(user_email, dest_path)
        if not dest_result.get("success"):
            return dest_result

        dest_id = dest_result.get("item", {}).get("id")
        if not dest_id:
            return {"success": False, "error": "대상 폴더를 찾을 수 없습니다."}

        endpoint = f"/me/drive/root:/{source_path}"
        json_data = {
            "parentReference": {"id": dest_id},
        }
        if new_name:
            json_data["name"] = new_name

        result = await self._make_request("PATCH", endpoint, user_email, json_data)

        if result.get("success"):
            item = DriveItem.from_dict(result.get("data", {}))
            return {"success": True, "file": item.__dict__}

        return result
