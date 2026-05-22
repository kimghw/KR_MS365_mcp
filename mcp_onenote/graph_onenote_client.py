"""
OneNote Graph API Client
Microsoft Graph API를 사용한 OneNote 작업 처리
session 모듈을 통한 인증 관리
"""

import re
import logging
from typing import Optional, List, Dict, Any
import aiohttp

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session import AuthManager
from session.auth_database import AuthDatabase
from .onenote_types import (
    NotebookInfo,
    SectionInfo,
    PageInfo,
    PageContent,
    SyncResult,
    PageAction,
)

logger = logging.getLogger(__name__)


def get_default_user_email() -> Optional[str]:
    """
    auth.db의 azure_user_info 테이블에서 첫 번째 user_email을 가져온다.

    Returns:
        첫 번째 사용자의 이메일 또는 None
    """
    try:
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email') or users[0].get('email')
        return None
    except Exception as e:
        logger.error(f"기본 사용자 조회 실패: {e}")
        return None


class GraphOneNoteClient:
    """OneNote Graph API 클라이언트"""

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
        logger.info("GraphOneNoteClient initialized")
        return True

    async def close(self):
        """리소스 정리"""
        if self._session:
            await self._session.close()
            self._session = None
        self._initialized = False

    def _normalize_onenote_id(self, entity_id: str) -> str:
        """
        OneNote Entity ID를 Graph API 형식으로 정규화
        SharePoint URL의 GUID는 1- 접두사가 없지만, Graph API는 필요함

        Args:
            entity_id: Notebook/Section/Page ID

        Returns:
            정규화된 ID (1- 접두사 포함)
        """
        if not entity_id:
            return entity_id

        # 이미 1- 접두사가 있으면 그대로 반환
        if entity_id.startswith("1-"):
            return entity_id

        # GUID 형식인지 확인 (8-4-4-4-12 형식)
        guid_pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        if re.match(guid_pattern, entity_id):
            logger.info(f"OneNote ID 정규화: {entity_id} → 1-{entity_id}")
            return f"1-{entity_id}"

        return entity_id

    async def _get_access_token(self, user_email: Optional[str] = None) -> Optional[str]:
        """
        사용자 이메일로 유효한 액세스 토큰 조회 (자동 갱신 포함)

        Args:
            user_email: 사용자 이메일 (None이면 auth.db에서 첫 번째 사용자 사용)

        Returns:
            유효한 액세스 토큰 또는 None
        """
        try:
            # user_email이 없으면 기본 사용자 조회
            if not user_email:
                user_email = get_default_user_email()
                if not user_email:
                    logger.error("기본 사용자를 찾을 수 없습니다. 로그인이 필요합니다.")
                    return None
                logger.info(f"기본 사용자 사용: {user_email}")

            token = await self.auth_manager.validate_and_refresh_token(user_email)
            return token
        except Exception as e:
            logger.error(f"토큰 조회 실패: {str(e)}")
            return None

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        user_email: Optional[str] = None,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        content_type: str = "application/json",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Graph API 요청 수행

        Args:
            method: HTTP 메서드 (GET, POST, PATCH, DELETE)
            endpoint: API 엔드포인트
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
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

    # ========================================================================
    # 노트북 관련 메서드
    # ========================================================================

    async def list_notebooks(self, user_email: Optional[str] = None) -> Dict[str, Any]:
        """
        사용자의 노트북 목록 조회

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)

        Returns:
            노트북 목록
        """
        result = await self._make_request("GET", "/me/onenote/notebooks", user_email)

        if result.get("success"):
            notebooks_data = result.get("data", {}).get("value", [])
            notebooks = [NotebookInfo.from_dict(nb) for nb in notebooks_data]
            return {
                "success": True,
                "notebooks": [nb.__dict__ for nb in notebooks],
                "count": len(notebooks),
            }

        return result

    # ========================================================================
    # 섹션 관련 메서드
    # ========================================================================

    async def list_sections(
        self,
        user_email: Optional[str] = None,
        notebook_id: Optional[str] = None,
        top: int = 50,
    ) -> Dict[str, Any]:
        """
        섹션 목록 조회

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            notebook_id: 노트북 ID (없으면 전체 섹션 조회)
            top: 조회할 섹션 개수

        Returns:
            섹션 목록
        """
        if notebook_id:
            notebook_id = self._normalize_onenote_id(notebook_id)
            endpoint = f"/me/onenote/notebooks/{notebook_id}/sections?$top={top}"
        else:
            endpoint = f"/me/onenote/sections?$top={top}"

        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            sections_data = result.get("data", {}).get("value", [])
            sections = [SectionInfo.from_dict(s) for s in sections_data]
            return {
                "success": True,
                "sections": [s.__dict__ for s in sections],
                "count": len(sections),
            }

        return result

    async def create_section(
        self,
        notebook_id: str,
        section_name: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        노트북에 새 섹션 생성

        Args:
            notebook_id: 노트북 ID
            section_name: 생성할 섹션 이름
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)

        Returns:
            생성된 섹션 정보
        """
        notebook_id = self._normalize_onenote_id(notebook_id)
        endpoint = f"/me/onenote/notebooks/{notebook_id}/sections"

        result = await self._make_request(
            "POST",
            endpoint,
            user_email,
            json_data={"displayName": section_name},
        )

        if result.get("success"):
            section = SectionInfo.from_dict(result.get("data", {}))
            return {"success": True, "section": section.__dict__}

        return result

    # ========================================================================
    # 페이지 관련 메서드
    # ========================================================================

    async def _make_request_full_url(
        self,
        url: str,
        user_email: Optional[str] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        전체 URL로 GET 요청 수행 (페이징용)

        Args:
            url: 전체 URL (@odata.nextLink)
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            timeout: 타임아웃 (초)

        Returns:
            API 응답
        """
        if not self._initialized:
            await self.initialize()

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다."}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.request(
                "GET", url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return {"success": True, "data": result}
                else:
                    error_text = await response.text()
                    logger.error(f"API 요청 실패: {response.status} - {error_text}")
                    return {"success": False, "error": f"API 요청 실패: {response.status}"}
        except Exception as e:
            logger.error(f"API 요청 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    async def list_pages(
        self,
        user_email: Optional[str] = None,
        section_id: Optional[str] = None,
        top: int = 100,
    ) -> Dict[str, Any]:
        """
        페이지 목록 조회 (@odata.nextLink 페이징 지원)

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            section_id: 섹션 ID (없으면 전체 페이지 조회)
            top: 페이지당 조회 개수 (최대 100)

        Returns:
            페이지 목록
        """
        if section_id:
            section_id = self._normalize_onenote_id(section_id)
            endpoint = f"/me/onenote/sections/{section_id}/pages?$top={top}&$select=id,title,createdDateTime,lastModifiedDateTime,level,order,contentUrl,links&$expand=parentSection($expand=parentNotebook($select=id,displayName);$select=id,displayName)"
        else:
            endpoint = f"/me/onenote/pages?$top={top}&$select=id,title,createdDateTime,lastModifiedDateTime,level,order,contentUrl,links&$expand=parentSection($expand=parentNotebook($select=id,displayName);$select=id,displayName)"

        result = await self._make_request("GET", endpoint, user_email)

        if not result.get("success"):
            return result

        all_pages_data = result.get("data", {}).get("value", [])

        # @odata.nextLink 페이징
        next_link = result.get("data", {}).get("@odata.nextLink")
        while next_link:
            logger.info(f"페이징 진행 중... 현재 {len(all_pages_data)}개")
            next_result = await self._make_request_full_url(next_link, user_email)
            if not next_result.get("success"):
                break
            page_data = next_result.get("data", {}).get("value", [])
            if not page_data:
                break
            all_pages_data.extend(page_data)
            next_link = next_result.get("data", {}).get("@odata.nextLink")

        pages = [PageInfo.from_dict(p) for p in all_pages_data]
        return {
            "success": True,
            "pages": [p.__dict__ for p in pages],
            "count": len(pages),
        }

    async def get_page_content(
        self,
        page_id: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        페이지 내용 조회

        Args:
            page_id: 페이지 ID
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)

        Returns:
            페이지 내용 (HTML)
        """
        page_id = self._normalize_onenote_id(page_id)
        access_token = await self._get_access_token(user_email)

        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다."}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "text/html",
        }

        url = f"{self.GRAPH_BASE_URL}/me/onenote/pages/{page_id}/content"

        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 200:
                    content = await response.text()
                    return {
                        "success": True,
                        "page_id": page_id,
                        "content": content,
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"페이지 내용 조회 실패: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"페이지 내용 조회 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    async def create_page(
        self,
        section_id: str,
        title: str,
        content: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        새 페이지 생성

        Args:
            section_id: 섹션 ID
            title: 페이지 제목
            content: 페이지 내용 (HTML)
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)

        Returns:
            생성된 페이지 정보
        """
        section_id = self._normalize_onenote_id(section_id)

        # OneNote 페이지 HTML 형식
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
</head>
<body>
    {content}
</body>
</html>"""

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다."}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/xhtml+xml",
        }

        url = f"{self.GRAPH_BASE_URL}/me/onenote/sections/{section_id}/pages"

        try:
            async with self._session.post(
                url,
                headers=headers,
                data=html_content.encode("utf-8"),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 201:
                    result = await response.json()
                    page = PageInfo.from_dict(result)
                    return {"success": True, "page": page.__dict__}
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"페이지 생성 실패: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"페이지 생성 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    async def update_page(
        self,
        page_id: str,
        action: PageAction,
        content: str,
        target: Optional[str] = None,
        position: str = "after",
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        페이지 내용 업데이트

        Args:
            page_id: 페이지 ID
            action: 작업 유형 (append, prepend, insert, replace)
            content: 추가/변경할 내용 (HTML)
            target: 타겟 요소 ID (예: #p:{guid})
            position: 삽입 위치 (before, after)
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)

        Returns:
            업데이트 결과
        """
        page_id = self._normalize_onenote_id(page_id)

        # PATCH 요청용 JSON 배열 생성
        patch_content = []

        if action == PageAction.APPEND:
            patch_content.append({
                "target": target or "body",
                "action": "append",
                "content": content,
            })
        elif action == PageAction.PREPEND:
            patch_content.append({
                "target": target or "body",
                "action": "prepend",
                "content": content,
            })
        elif action == PageAction.INSERT:
            patch_content.append({
                "target": target or "body",
                "action": "insert",
                "position": position,
                "content": content,
            })
        elif action == PageAction.REPLACE:
            patch_content.append({
                "target": target or "body",
                "action": "replace",
                "content": content,
            })

        elif action == PageAction.CLEAN:
            patch_content.append({
                "target": target or "body",
                "action": "replace",
                "content": "<p></p>",
            })

        if not patch_content:
            return {"success": False, "error": f"지원하지 않는 action: {action}"}

        endpoint = f"/me/onenote/pages/{page_id}/content"

        result = await self._make_request(
            "PATCH",
            endpoint,
            user_email,
            json_data=patch_content,
        )

        return result

    async def delete_page(
        self,
        page_id: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        페이지 삭제

        Args:
            page_id: 페이지 ID
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)

        Returns:
            삭제 결과
        """
        page_id = self._normalize_onenote_id(page_id)
        endpoint = f"/me/onenote/pages/{page_id}"

        result = await self._make_request("DELETE", endpoint, user_email)
        return result
