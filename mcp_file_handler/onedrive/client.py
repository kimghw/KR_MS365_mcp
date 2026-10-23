"""OneDrive Graph API client (동기, requests 기반).

토큰은 `SyncTokenBridge` 로만 얻는다 (spec/spec_멀티유저.md ②-2.2, ②-5.2):

- mode 1: 사용자 고정 `BoundTokenProvider` 가 필수다. AuthManager 를 만들거나 빌리지 않는다.
- mode 0: 주입된 auth manager, 없으면 첫 토큰 요청 때 공유 AuthManager
  (`mcp_common.auth.get_shared_auth_manager`). 별도 `AuthManager()` 를 만들지 않는다.
- 예전 `executor.submit(asyncio.run, coro)` 브리지는 없다 — 동기 작업은 작업 스레드에서
  돌고, 토큰 코루틴은 요청 이벤트 루프에서 돈다.

Graph URL 정책 (②-7.5):

- bearer 를 실은 Graph 호출은 redirect 를 따라가지 않는다.
- Graph 가 준 사전 서명 다운로드 URL 에는 bearer 를 붙이지 않는다 (G02). 그 URL 은 공용
  `mcp_common.graph_url_policy.check_presigned_url` 을 통과해야 하고(https·기본 포트·
  userinfo 없음·사설/루프백/링크로컬/단일 라벨 거부·DNS 해석 실패 거부·해석된 모든 주소 공개),
  GET 직전에 호출자 활성 상태를 다시 확인하며(N01), 그 응답의 추가 redirect 는 따라가지
  않는다 (astra 리뷰 R08·3차 N05).
- 다운로드 파일은 `secure_files.create_exclusive` 로 배타 생성한다 — 같은 이름이 있으면
  덮어쓰지 않고 ` (n)` 접미사를 붙인다 (F04). 최종 경계 확인은 downloader 가 한다.
- 스트림 누적 바이트는 파일 상한·요청 예산(`limits.StreamGuard`)에 걸리는 순간 중단하고
  부분 파일을 지운다 (R09).

로그에는 파일명·경로·공유 URL·외부 응답 본문을 싣지 않는다.
"""

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

from mcp_common.graph_url_policy import check_presigned_url, is_redirect
from mcp_common.secure_files import create_exclusive
from mcp_common.security_contracts import SecurityError

from ..limits import LimitExceeded, RequestLimits, StreamGuard
from ..token_bridge import SyncTokenBridge

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = 'https://graph.microsoft.com/v1.0'
DEFAULT_HTTP_TIMEOUT = 60.0
_CHUNK = 64 * 1024


class UnsafeDownloadUrl(ValueError):
    """사전 서명 다운로드 URL 정책 위반. 메시지에 URL 을 넣지 않는다."""


def _is_redirect(response: Any) -> bool:
    return is_redirect(getattr(response, 'status_code', None))


def validate_download_url(url: str) -> str:
    """사전 서명 다운로드 URL 정책 — 공용 `graph_url_policy.check_presigned_url` 하나로 판정한다
    (astra 3차 N05: 다섯 도메인이 같은 규칙). https·userinfo 없음·기본 포트·끝의 `.` 처리·
    사설/루프백/링크로컬/단일 라벨 거부·DNS 해석 실패 거부·해석된 모든 주소가 공개 대역.
    통과하면 그대로 돌려주고, 아니면 `UnsafeDownloadUrl`(URL 비노출).
    """
    try:
        return check_presigned_url(url)
    except SecurityError:
        raise UnsafeDownloadUrl("download url rejected by policy") from None


class OneDriveClient:
    """OneDrive API client."""

    def __init__(
        self,
        auth_manager: Any = None,
        *,
        token_provider: Any = None,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
        files_root: Optional[Path] = None,
    ):
        """Initialize OneDrive client.

        Args:
            auth_manager: mode 0 전용 — `validate_and_refresh_token()` 을 가진 객체.
                없으면 첫 토큰 요청 때 공유 AuthManager 를 쓴다.
            token_provider: mode 1 필수 — 사용자 고정 `BoundTokenProvider`.
            timeout: HTTP 요청 시간 제한(초)
            files_root: mode 1 의 사용자 `files/` — 다운로드 파일 생성 경계(`create_exclusive(root=)`)
        """
        self.auth_manager = auth_manager
        self.files_root = Path(files_root) if files_root is not None else None
        self.base_url = GRAPH_BASE_URL
        self.timeout = timeout
        self._tokens = SyncTokenBridge(token_provider=token_provider, auth_manager=auth_manager)

    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------
    def _get_access_token(self) -> Optional[str]:
        """동기 토큰 획득 — 브리지 규칙은 `token_bridge` 모듈 docstring 참조."""
        return self._tokens.get_token()

    def _assert_active(self) -> None:
        """bearer 없는 후속 요청 전 활성 재검사 — 공급자의 토큰 획득이 현재 요청 identity 를 다시 확인한다."""
        if not self._get_access_token():
            raise RuntimeError("caller is no longer active")

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        token = self._get_access_token()
        if not token:
            raise RuntimeError("Failed to obtain a valid access token")
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

    # ------------------------------------------------------------------
    # Graph calls
    # ------------------------------------------------------------------
    def _item_url(self, item_id: str, suffix: str = '') -> str:
        # item id 는 Graph 응답에서 오지만 URL 경로 성분으로만 쓰이게 인코딩한다
        return f"{self.base_url}/me/drive/items/{quote(str(item_id), safe='!')}{suffix}"

    def _get_json(self, url: str) -> Any:
        response = requests.get(
            url, headers=self._get_headers(), allow_redirects=False, timeout=self.timeout
        )
        if _is_redirect(response):
            raise RuntimeError("Graph 가 예상하지 못한 redirect 를 돌려줬습니다")
        response.raise_for_status()
        return response.json()

    def get_item_by_path(self, path: str) -> Dict[str, Any]:
        """Get item metadata by path."""
        encoded = quote(str(path).strip('/'), safe='/')
        return self._get_json(f"{self.base_url}/me/drive/root:/{encoded}")

    def get_item_by_id(self, item_id: str) -> Dict[str, Any]:
        """Get item metadata by ID."""
        return self._get_json(self._item_url(item_id))

    def get_item_by_share_url(self, share_url: str) -> Dict[str, Any]:
        """Get item metadata from share URL."""
        encoded_url = base64.urlsafe_b64encode(
            share_url.encode('utf-8')
        ).rstrip(b'=').decode('utf-8')

        # 공유 URL 토큰 형식: "u!" + base64url(패딩 제거) — https://learn.microsoft.com/graph/api/shares-get#encoding-sharing-urls
        return self._get_json(f"{self.base_url}/shares/u!{encoded_url}/driveItem")

    def list_children(self, item_id: str) -> List[Dict[str, Any]]:
        """List children of a folder."""
        return self._get_json(self._item_url(item_id, '/children')).get('value', [])

    def _content_response(self, item_id: str):
        """`/content` 응답. 302 면 검증한 사전 서명 URL 을 bearer **없이** 한 번만 요청한다."""
        response = requests.get(
            self._item_url(item_id, '/content'),
            headers=self._get_headers(),
            allow_redirects=False,
            stream=True,
            timeout=self.timeout,
        )
        if _is_redirect(response):
            download_url = response.headers.get('Location', '')
            response.close()
            download_url = validate_download_url(download_url)
            # 사전 서명 GET 직전에 호출자 활성 상태를 다시 확인한다 (astra 3차 N01): 토큰 공급자에서
            # 토큰을 다시 얻고 버린다 — 폐기·비활성이면 여기서 끝나고 GET 은 나가지 않는다.
            self._assert_active()
            response = requests.get(
                download_url, stream=True, timeout=self.timeout, allow_redirects=False
            )
            if _is_redirect(response):
                response.close()
                raise UnsafeDownloadUrl("download url redirected again")
        response.raise_for_status()
        return response

    def download_file(
        self,
        item_id: str,
        output_path: str,
        *,
        limits: Optional[RequestLimits] = None,
    ) -> str:
        """Download file by ID.

        `output_path` 의 디렉터리에 그 이름으로 **배타 생성**한다. 같은 이름이 이미 있으면
        ` (n)` 접미사가 붙은 새 파일이 되므로, 실제 경로는 반환값을 써야 한다.
        `limits` 가 있으면 선언 길이·스트림 누적 바이트를 파일 상한과 요청 예산에 적용하고,
        초과하는 순간 스트림을 끊고 부분 파일을 지운다 (`LimitExceeded`).

        Returns:
            Path to downloaded file
        """
        response = self._content_response(item_id)
        guard = StreamGuard(limits)
        try:
            guard.check_declared(response.headers.get('Content-Length'))
        except LimitExceeded:
            response.close()
            raise
        output = Path(output_path)
        path, handle = create_exclusive(output.parent, output.name, root=self.files_root)
        try:
            with handle:
                for chunk in response.iter_content(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    guard.add(len(chunk))
                    handle.write(chunk)
        except BaseException:
            response.close()
            try:
                path.unlink()
            except OSError:
                pass
            raise
        logger.info("Downloaded one OneDrive file")
        return str(path)

    def get_file_content(self, item_id: str, *, limits: Optional[RequestLimits] = None) -> bytes:
        """Get file content directly (상한이 있으면 초과 시 `LimitExceeded`)."""
        response = self._content_response(item_id)
        guard = StreamGuard(limits)
        guard.check_declared(response.headers.get('Content-Length'))
        chunks: List[bytes] = []
        try:
            for chunk in response.iter_content(chunk_size=_CHUNK):
                if chunk:
                    guard.add(len(chunk))
                    chunks.append(chunk)
        finally:
            response.close()
        return b''.join(chunks)
