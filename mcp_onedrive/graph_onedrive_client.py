"""
OneDrive Graph API Client
Microsoft Graph API를 사용한 OneDrive 작업 처리
session 모듈을 통한 인증 관리

- 모든 경로는 `/me/drive/...` — 토큰 주인의 드라이브만 다룬다. `user_email` 은 토큰
  공급자에 넘겨 일치 확인(멀티유저) 또는 계정 선택(mode 0)에만 쓴다.
- 로그에는 상태 코드·Graph 오류 코드·예외 타입만 남긴다. 이메일·파일 경로·Graph 오류
  본문 원문은 남기지 않는다(spec/spec_멀티유저.md ②-2.7, ②-9).
- 드라이브 경로는 `mcp_common.graph_paths.graph_drive_path()` 로 성분마다 인코딩한다.
  `.`·`..` 성분과 백슬래시는 `SecurityError(not_found)` 로 거부한다 — 경로가 `/me/drive`
  밖(`/users/B/...`)으로 빠져나가지 못한다(②-7.5 G01). 두 모드 공통.
- 실패 응답에는 고정 메시지 + `graph_error_summary()`(상태 코드·검증된 `error.code`)만
  싣는다. Graph 오류 본문 원문·예외 문자열은 돌려주지 않는다(②-9). 두 모드 공통.
- bearer 를 단 요청은 redirect 를 따라가지 않는다(`BEARER_KW`, ②-7.5 R08). `/content` 의 302
  는 사전 서명 URL 로 **bearer 없이** 한 번만 간다 — https·공개 호스트만, 후속 redirect 금지
  (`graph_url_policy.check_presigned_url`). 두 모드 공통.
- `@odata.nextLink` 이어 조회는 `fetch_next_link()` 로만 한다(본인 `/me/drive/...` 범위).
"""

import base64
import json
import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from urllib.parse import quote
import aiohttp

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_common.graph_paths import graph_drive_path, graph_error_summary
from mcp_common.security_contracts import SecurityError
from mcp_common.security_policy import multi_user_enabled

from mcp_common.graph_url_policy import BEARER_KW, check_next_link, check_presigned_url, is_redirect

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol
from .onedrive_types import (
    DriveInfo,
    DriveItem,
    FileInfo,
    FolderInfo,
    ItemType,
    ConflictBehavior,
)

logger = logging.getLogger(__name__)


def _enc(path: str) -> str:
    """드라이브 경로를 URL 경로 조각으로 인코딩한다 (`#` `%` `?` 공백 등). `/` 는 구분자로 유지.

    성분마다 단일 세그먼트로 인코딩하고 `.`·`..`·백슬래시는 거부한다
    (`SecurityError(not_found)`) — aiohttp/yarl 이 dot-segment 를 정규화해 경로가
    `/me/drive` 밖으로 나가는 것을 막는다(G01).
    """
    return graph_drive_path(path)


#: 전송 단계 예외(연결 실패·타임아웃 등)의 공개 메시지 — 예외 원문은 응답에 싣지 않는다
_TRANSPORT_ERROR_MESSAGE = "OneDrive 요청 중 오류가 발생했습니다."


def _failure_fields(status: int, body_text: str) -> Dict[str, Any]:
    """Graph 비정상 응답 → 공개용 요약(상태 코드·`error.code`). 본문 원문은 싣지도 남기지도 않는다."""
    try:
        parsed = json.loads(body_text) if body_text else None
    except ValueError:
        parsed = None
    summary = graph_error_summary(status, parsed)
    logger.error(
        "OneDrive API 요청 실패: status=%s code=%s", status, summary.get("graph_error_code", "-")
    )
    return summary


def _content_result(content_bytes: bytes, file_path: str, as_text: bool) -> Dict[str, Any]:
    """받은 바이트를 응답 형태로. 텍스트 요청인데 UTF-8 이 아니면 base64 로 돌려준다."""
    if as_text:
        try:
            return {
                "success": True,
                "file_path": file_path,
                "content": content_bytes.decode("utf-8"),
                "content_type": "text",
            }
        except UnicodeDecodeError:
            pass
    return {
        "success": True,
        "file_path": file_path,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "content_type": "base64",
    }


#: `fetch_next_link()` 가 이어서 조회해도 되는 리소스(소문자) — 드라이브 밖은 거부
_NEXT_LINK_RESOURCES = frozenset({"drive", "drives"})


class GraphOneDriveClient:
    """OneDrive Graph API 클라이언트"""

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, token_provider: Optional["TokenProviderProtocol"] = None):
        """
        클라이언트 초기화

        Args:
            token_provider: 토큰 제공자. 멀티유저에서는 사용자 고정 공급자가 **필수**다.
                None 이면 mode 0 의 프로세스 공유 AuthManager 를 쓴다.

        Note:
            mode 0 에서 per-email refresh lock 이 인스턴스마다 분리되지 않도록 반드시
            mcp_common.auth.get_shared_auth_manager() 의 단일 인스턴스를 쓴다.
            공급자는 이 클라이언트의 소유가 아니므로 `close()` 에서 닫지 않는다.
        """
        if token_provider is None:
            if multi_user_enabled():
                raise RuntimeError(
                    "GraphOneDriveClient: 멀티유저 모드에서는 사용자 고정 token_provider 가 필요합니다"
                )
            from mcp_common.auth import get_shared_auth_manager
            token_provider = get_shared_auth_manager()
        self.token_provider = token_provider
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
        """리소스 정리 — 자신이 만든 HTTP 세션만 닫는다(토큰 공급자는 소유하지 않는다)."""
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
            token = await self.token_provider.validate_and_refresh_token(user_email)
            return token
        except SecurityError:
            # 연결 없음·재인증 필요·계정 불일치는 고정 오류 코드로 그대로 올린다
            # (런타임이 연결 안내를 붙인다). 다른 계정으로 재시도하지 않는다.
            raise
        except Exception as e:
            logger.error("토큰 조회 실패: %s", type(e).__name__)
            return None

    async def _assert_active(self, user_email: str) -> None:
        """bearer 없는 사전 서명 GET **직전**의 identity·폐기 재검사 (N01 읽기 경로).

        bound provider 에서 토큰을 다시 받되 값은 쓰지 않는다 — mode 1 의 `get_graph_token()` 이
        현재 요청 identity·계정 상태·auth_epoch 를 다시 확인하고, 폐기됐으면 `SecurityError`
        (`account_inactive`/`graph_not_connected`)를 올린다. Outlook `_assert_active()` 와 같다.
        """
        if not await self._get_access_token(user_email):
            raise RuntimeError("Failed to get access token")

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        user_email: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        content_type: str = "application/json",
        timeout: int = 60,
        absolute_url: Optional[str] = None,
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

        # absolute_url 은 정책 검사를 통과한 nextLink 만 온다 (`fetch_next_link`)
        url = absolute_url or f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data if json_data else None,
                data=data if data else None,
                timeout=aiohttp.ClientTimeout(total=timeout),
                **BEARER_KW,
            ) as response:
                if response.status in (200, 201, 204):
                    if response.status == 204:
                        return {"success": True}
                    result = await response.json()
                    return {"success": True, "data": result}
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"API 요청 실패: {response.status}",
                        **_failure_fields(response.status, error_text),
                    }
        except Exception as e:
            logger.error("API 요청 오류: %s", type(e).__name__)
            return {"success": False, "error": _TRANSPORT_ERROR_MESSAGE}

    async def fetch_next_link(self, user_email: str, next_link: str) -> Dict[str, Any]:
        """Graph 가 돌려준 `@odata.nextLink` 를 **본인 드라이브 범위에서만** GET 한다.

        정책(`check_next_link`)은 토큰 획득·HTTP 요청보다 먼저 판정한다. 다른 사용자·다른
        리소스·dot-segment·Graph 밖 호스트는 `path_not_allowed`. 이어 조회는 이 메서드로만 한다.
        """
        url = check_next_link(next_link, user_email, resources=_NEXT_LINK_RESOURCES)
        result = await self._make_request("GET", "", user_email, absolute_url=url)
        if result.get("success"):
            data = result.get("data", {})
            items = [DriveItem.from_dict(item) for item in data.get("value", [])]
            return {
                "success": True,
                "files": [item.__dict__ for item in items],
                "count": len(items),
                "next_link": data.get("@odata.nextLink"),
            }
        return result

    async def _download_presigned(
        self, user_email: str, location: Optional[str], status: int, file_path: str, as_text: bool
    ) -> Dict[str, Any]:
        """`/content` 의 3xx Location(사전 서명 URL)을 **bearer 없이** 한 번만 받는다.

        bearer 응답(302) 과 이 GET 사이에 await 경계가 있으므로 먼저 호출자의 활성 상태를 다시
        확인한다(`_assert_active`, N01). 그다음 https·공개 호스트만 허용하고(`check_presigned_url`),
        그 URL 이 다시 redirect 하면 따라가지 않는다. 응답에는 URL 을 싣지 않는다.
        """
        await self._assert_active(user_email)
        try:
            target = check_presigned_url(location)
        except SecurityError:
            logger.warning("OneDrive 사전 서명 다운로드 URL 거부: status=%s", status)
            return {
                "success": False,
                "error": "다운로드 URL 이 정책에 맞지 않습니다.",
                "status_code": status,
            }
        # headers 를 넘기지 않는다 — 세션 기본 헤더에도 bearer 가 없다(②-7.6)
        async with self._session.get(
            target, timeout=aiohttp.ClientTimeout(total=60), **BEARER_KW
        ) as response:
            if response.status == 200:
                return _content_result(await response.read(), file_path, as_text)
            if is_redirect(response.status):
                return {
                    "success": False,
                    "error": "다운로드 URL 이 다시 redirect 를 요구했습니다 (따라가지 않음).",
                    "status_code": response.status,
                }
            return {
                "success": False,
                "error": f"파일 다운로드 실패: {response.status}",
                **graph_error_summary(response.status),
            }

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
        return f"/me/drive/root:/{_enc(folder_path)}:/children"

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
            q = quote(search.replace("'", "''"), safe="")  # OData 문자열 리터럴: ' 는 '' 로
            endpoint = f"/me/drive/root/search(q='{q}')?$top={limit}"
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
        endpoint = f"/me/drive/root:/{_enc(file_path)}"
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
        endpoint = f"/me/drive/root:/{_enc(file_path)}:/content"
        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
                **BEARER_KW,
            ) as response:
                if response.status == 200:
                    return _content_result(await response.read(), file_path, as_text)
                if not is_redirect(response.status):
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"파일 읽기 실패: {response.status}",
                        **_failure_fields(response.status, error_text),
                    }
                # Graph 는 /content 를 사전 서명 URL 로 302 돌린다 — 첫 응답을 닫고 bearer 없이 간다
                location = response.headers.get("Location")
                status = response.status
            return await self._download_presigned(user_email, location, status, file_path, as_text)
        except SecurityError:
            # 사전 서명 GET 직전 재검사에서 폐기·연결 해제가 드러난 경우 — 고정 코드로 그대로 올린다
            raise
        except Exception as e:
            logger.error("파일 읽기 오류: %s", type(e).__name__)
            return {"success": False, "error": _TRANSPORT_ERROR_MESSAGE}

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
        endpoint = f"/me/drive/root:/{_enc(file_path)}:/content?@microsoft.graph.conflictBehavior={conflict_str}"
        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            data = content.encode("utf-8")
            async with self._session.put(
                url,
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=60),
                **BEARER_KW,
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
                        **_failure_fields(response.status, error_text),
                    }
        except Exception as e:
            logger.error("파일 쓰기 오류: %s", type(e).__name__)
            return {"success": False, "error": _TRANSPORT_ERROR_MESSAGE}

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
        endpoint = f"/me/drive/root:/{_enc(file_path)}"
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
            endpoint = f"/me/drive/root:/{_enc(parent_path)}:/children"
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

        endpoint = f"/me/drive/root:/{_enc(source_path)}:/copy"
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
                **BEARER_KW,
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
                        **_failure_fields(response.status, error_text),
                    }
        except Exception as e:
            logger.error("파일 복사 오류: %s", type(e).__name__)
            return {"success": False, "error": _TRANSPORT_ERROR_MESSAGE}

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

        endpoint = f"/me/drive/root:/{_enc(source_path)}"
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
