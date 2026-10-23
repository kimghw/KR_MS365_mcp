"""
Graph Mail Query - 메일 조회 엔트리포인트
인증 처리 및 Graph API 호출을 담당

역할:
    - 인증 처리 (AuthManager 활용)
    - URL로 Graph API 호출
    - 페이지네이션 처리
    - 클라이언트 사이드 필터링

URL 빌드는 graph_mail_url.py에서 담당

멀티유저(spec/spec_멀티유저.md ②-2.4·②-7.5, WP4):
    - 토큰 공급자는 주입받아 빌려 쓴다(`close()` 가 닫지 않는다). URL 빌더는 요청마다 새로
      만든다(이메일에 따라 바뀌는 공유 캐시 없음).
    - `query_url`(= `mail_query_url`)과 페이지 URL 은 mode 1 에서 `outlook_security.check_mail_query_url`
      정책을 토큰 획득 **전에** 통과해야 한다. Authorization 을 단 요청은 redirect 를 따라가지 않는다.
    - 발송 첨부(로컬 파일)는 mode 1 에서 사용자 `files/` 안만 읽는다.
    - 로그에 이메일·URL·Graph 오류 본문을 싣지 않는다.
"""

import asyncio
import logging
import aiohttp
import sys
import os
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol
    from mcp_common.user_paths import UserPaths
from .outlook_types import (
    FilterParams,
    ExcludeParams,
    SelectParams,
    build_filter_query,
    build_exclude_query,
    build_select_query,
)
from .graph_mail_url import GraphMailUrlBuilder
from . import outlook_security as limits
from .outlook_security import (
    BEARER_KW,
    GRAPH_BASE,
    acquire_token,
    bearer_headers,
    check_top,
    enforce_mail_query_url,
    read_limited,
    request_headers,
    graph_error_detail,
    is_graph_https,
    legacy_token_provider,
    public_error,
    user_seg,
)

logger = logging.getLogger(__name__)


class GraphMailQuery:
    """
    Graph API 메일 조회 클래스

    역할:
        - 인증 처리 (TokenProviderProtocol 활용)
        - URL로 Graph API 호출
        - 페이지네이션 처리
        - 클라이언트 사이드 필터링
    """

    # 토큰을 붙여도 되는 호스트. query_url 은 호출자가 준 URL 을 그대로 받으므로 반드시 검사한다.
    ALLOWED_GRAPH_HOSTS = frozenset({"graph.microsoft.com"})

    def __init__(
        self,
        token_provider: Optional["TokenProviderProtocol"] = None,
        paths: Optional["UserPaths"] = None,
    ):
        """
        Initialize Graph Mail Query

        Args:
            token_provider: 토큰 제공자 (None이면 mode 0 공유 AuthManager — mode 1 은 주입 필수)
            paths: mode 1 사용자 경로 (발송 첨부 읽기·첨부 저장 경계)
        """
        if token_provider is None:
            # 하위 호환성(mode 0): 공유 AuthManager 싱글톤 사용 (per-email refresh lock 공유)
            token_provider = legacy_token_provider()
        self.token_provider = token_provider
        self.paths = paths

    async def initialize(self) -> bool:
        """
        Lightweight initializer to align with callers that expect async setup
        """
        # No initialization needed - tokens are fetched per-request
        return True

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        """
        Get or refresh access token for a user
        Delegates to TokenProvider which handles caching and refresh

        Args:
            user_email: User email to get token for

        Returns:
            Access token or None if failed
        """
        # TokenProvider handles all token caching and refresh logic.
        # mode 1: 연결 없음·불일치는 SecurityError 로 올라간다(런타임이 연결 안내를 붙인다).
        return await acquire_token(self.token_provider, user_email)

    async def _request_headers(self, user_email: str) -> Dict[str, str]:
        """요청 1건 직전에 토큰을 새로 얻는다 (N01) — 문자열을 들고 await 를 넘기지 않는다."""
        return await request_headers(self.token_provider, user_email)

    async def _get_auth_url(self, user_email: str) -> Optional[Dict[str, Any]]:
        """
        인증 실패 시 로그인 URL을 생성하여 반환

        Args:
            user_email: 사용자 이메일

        Returns:
            auth_required 응답 dict 또는 None
        """
        if hasattr(self.token_provider, 'get_auth_url_for_login'):
            return await self.token_provider.get_auth_url_for_login(user_email)
        return None

    def _get_url_builder(self, user_email: str) -> GraphMailUrlBuilder:
        """
        URL 빌더 인스턴스 반환 — 요청마다 새로 만든다 (공유 상태 없음, ②-7.6)

        Args:
            user_email: 사용자 이메일

        Returns:
            GraphMailUrlBuilder 인스턴스
        """
        return GraphMailUrlBuilder(user_email)

    def _build_query_url(
        self,
        user_email: str,
        filter_query: Optional[str] = None,
        select_fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
    ) -> str:
        """
        Build complete query URL with parameters

        Args:
            user_email: User email for building URL
            filter_query: Filter query string
            select_fields: Fields to select
            order_by: Sort order

        Returns:
            Complete URL with query parameters
        """
        url_builder = self._get_url_builder(user_email)
        return url_builder.build_filter_url(
            filter_query=filter_query,
            select_fields=select_fields,
            order_by=order_by,
        )

    async def query_filter(
        self,
        user_email: str,
        filter: FilterParams,
        exclude: Optional[ExcludeParams] = None,
        select: Optional[SelectParams] = None,
        client_filter: Optional[ExcludeParams] = None,
        top: int = 450,
        orderby: Optional[str] = None,
    ) -> Dict[str, Any]:
        top = check_top(top)

        # Get access token for the user
        access_token = await self._get_access_token(user_email)
        if not access_token:
            auth_response = await self._get_auth_url(user_email)
            if auth_response:
                return auth_response
            raise Exception("Failed to get access token")

        # Build filter parts using graph_types helper functions
        query_parts = []

        # Add filter query
        if filter:
            filter_query = build_filter_query(filter)
            if filter_query:
                query_parts.append(filter_query)

        # Add exclude query to API filter
        if exclude:
            exclude_query = build_exclude_query(exclude)
            if exclude_query:
                query_parts.append(exclude_query)

        # Combine filter and exclude with AND
        combined_filter = " and ".join(query_parts) if query_parts else None

        # Get select fields (새 SelectParams 구조에 맞게 처리)
        select_fields = None
        if select:
            if isinstance(select, SelectParams):
                select_fields = select.get_selected_fields()
            elif isinstance(select, dict):
                # Dict인 경우 build_select_query 사용
                select_query = build_select_query(select)
                select_fields = select_query.split(",") if select_query else None
            elif isinstance(select, list):
                # 리스트 형태는 그대로 사용 (이미 필드명이 들어 있다고 가정)
                select_fields = select

        # Build final URL
        base_url = self._build_query_url(
            user_email=user_email, filter_query=combined_filter, select_fields=select_fields, order_by=orderby
        )

        # Fetch data with immediate filtering if client_filter is provided
        return await self._fetch_parallel_with_url(user_email, base_url, top, client_filter)

    def _apply_client_side_filter(self, emails: List[Dict], exclude: ExcludeParams) -> List[Dict]:
        """
        Apply client-side filtering to exclude emails based on ExcludeParams
        Supports all ExcludeParams fields for comprehensive client-side filtering

        Args:
            emails: List of email dictionaries
            exclude: ExcludeParams to apply

        Returns:
            Filtered list of emails
        """
        filtered_emails = []

        for email in emails:
            should_include = True

            # === 발신자 제외 ===
            # exclude_from_address (from 또는 sender 필드) - 단일값/리스트 지원
            # Note: Graph API 응답에서 from이 없으면 sender를 사용
            if exclude.get("exclude_from_address"):
                from_data = email.get("from") or email.get("sender")
                from_addr = from_data.get("emailAddress", {}).get("address", "").lower() if from_data else ""
                exclude_from = exclude.get("exclude_from_address")
                if isinstance(exclude_from, list):
                    if from_addr in [addr.lower() for addr in exclude_from]:
                        should_include = False
                        continue
                elif from_addr == exclude_from.lower():
                    should_include = False
                    continue

            # exclude_sender_address (sender 필드) - 단일값/리스트 지원
            if exclude.get("exclude_sender_address"):
                sender_addr = email.get("sender", {}).get("emailAddress", {}).get("address", "").lower()
                exclude_sender = exclude.get("exclude_sender_address")
                if isinstance(exclude_sender, list):
                    if sender_addr in [addr.lower() for addr in exclude_sender]:
                        should_include = False
                        continue
                elif sender_addr == exclude_sender.lower():
                    should_include = False
                    continue

            # === 키워드 제외 ===
            # exclude_subject_keywords
            if exclude.get("exclude_subject_keywords") and should_include:
                subject = email.get("subject", "").lower()
                for keyword in exclude.get("exclude_subject_keywords"):
                    if keyword.lower() in subject:
                        should_include = False
                        break

            # exclude_body_keywords
            if exclude.get("exclude_body_keywords") and should_include:
                body_content = email.get("body", {}).get("content", "").lower()
                for keyword in exclude.get("exclude_body_keywords"):
                    if keyword.lower() in body_content:
                        should_include = False
                        break

            # exclude_preview_keywords
            if exclude.get("exclude_preview_keywords") and should_include:
                body_preview = email.get("bodyPreview", "").lower()
                for keyword in exclude.get("exclude_preview_keywords"):
                    if keyword.lower() in body_preview:
                        should_include = False
                        break

            # === 속성 제외 ===
            # exclude_importance
            if exclude.get("exclude_importance") and should_include:
                if email.get("importance") == exclude.get("exclude_importance"):
                    should_include = False
                    continue

            # exclude_sensitivity
            if exclude.get("exclude_sensitivity") and should_include:
                if email.get("sensitivity") == exclude.get("exclude_sensitivity"):
                    should_include = False
                    continue

            # exclude_classification (inferenceClassification)
            if exclude.get("exclude_classification") and should_include:
                if email.get("inferenceClassification") == exclude.get("exclude_classification"):
                    should_include = False
                    continue

            # === 상태 제외 ===
            # exclude_read_status
            if exclude.get("exclude_read_status") is not None and should_include:
                if email.get("isRead") == exclude.get("exclude_read_status"):
                    should_include = False
                    continue

            # exclude_draft_status
            if exclude.get("exclude_draft_status") is not None and should_include:
                if email.get("isDraft") == exclude.get("exclude_draft_status"):
                    should_include = False
                    continue

            # exclude_attachment_status
            if exclude.get("exclude_attachment_status") is not None and should_include:
                if email.get("hasAttachments") == exclude.get("exclude_attachment_status"):
                    should_include = False
                    continue

            # exclude_delivery_receipt
            if exclude.get("exclude_delivery_receipt") is not None and should_include:
                if email.get("isDeliveryReceiptRequested") == exclude.get("exclude_delivery_receipt"):
                    should_include = False
                    continue

            # exclude_read_receipt
            if exclude.get("exclude_read_receipt") is not None and should_include:
                if email.get("isReadReceiptRequested") == exclude.get("exclude_read_receipt"):
                    should_include = False
                    continue

            # === 플래그 및 카테고리 제외 ===
            # exclude_flag_status
            if exclude.get("exclude_flag_status") and should_include:
                flag_status = email.get("flag", {}).get("flagStatus")
                if flag_status == exclude.get("exclude_flag_status"):
                    should_include = False
                    continue

            # exclude_categories
            if exclude.get("exclude_categories") and should_include:
                email_categories = email.get("categories", [])
                for cat in exclude.get("exclude_categories"):
                    if cat in email_categories:
                        should_include = False
                        break

            # === ID 제외 ===
            # exclude_id
            if exclude.get("exclude_id") and should_include:
                if email.get("id") == exclude.get("exclude_id"):
                    should_include = False
                    continue

            # exclude_conversation_id
            if exclude.get("exclude_conversation_id") and should_include:
                if email.get("conversationId") == exclude.get("exclude_conversation_id"):
                    should_include = False
                    continue

            # exclude_parent_folder_id
            if exclude.get("exclude_parent_folder_id") and should_include:
                if email.get("parentFolderId") == exclude.get("exclude_parent_folder_id"):
                    should_include = False
                    continue

            if should_include:
                filtered_emails.append(email)

        return filtered_emails

    async def query_url(
        self, user_email: str, url: str, top: int = 450, client_filter: Optional[ExcludeParams] = None
    ) -> Dict[str, Any]:
        """
        Query with pre-built URL

        Args:
            user_email: User email for authentication
            url: Complete Graph API URL with all parameters
            top: Maximum results (default 450)
            client_filter: ExcludeParams for client-side filtering (post-fetch)

        Returns:
            Email query results

        Example:
            url = "https://graph.microsoft.com/v1.0/users/me/messages?$filter=isRead eq false&$top=10"
            result = await query_url("user@example.com", url, top=100)
        """
        top = check_top(top)
        # mode 1: 호출자가 준 URL 은 토큰을 얻기 전에 경로 정책부터 통과해야 한다 (②-7.5)
        enforce_mail_query_url(url)

        # Get access token for the user
        access_token = await self._get_access_token(user_email)
        if not access_token:
            auth_response = await self._get_auth_url(user_email)
            if auth_response:
                return auth_response
            raise Exception("Failed to get access token")

        # Fetch data with the provided URL and apply filtering immediately
        return await self._fetch_parallel_with_url(user_email, url, top, client_filter)

    async def query_search(
        self,
        user_email: str,
        search: str,
        client_filter: Optional[ExcludeParams] = None,
        select: Optional[SelectParams] = None,
        top: int = 250,
        orderby: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Query with keyword search ($search parameter)

        Args:
            user_email: User email for authentication
            search: Search keyword or phrase (e.g., "from:boss@company.com", "subject:meeting")
            client_filter: ExcludeParams for client-side filtering (post-fetch)
            select: SelectParams for field selection
            top: Maximum results (default 250 - Graph API search limit)
            orderby: Sort order

        Returns:
            Email query results

        Example:
            search_term = "from:ceo@company.com OR subject:urgent"
            # SelectParams: 각 필드를 True로 지정
            select_params = SelectParams(
                id=True,
                subject=True,
                from_recipient=True,
                received_date_time=True
            )
            client_filter_params: ExcludeParams = {
                'exclude_subject_keywords': ['newsletter', 'spam']
            }

            await query_search(
                search=search_term,
                select=select_params,
                client_filter=client_filter_params
            )

        Note:
            - Graph API $search has a maximum of 250 results per query
            - $search cannot be combined with $filter
            - Search syntax follows KQL (Keyword Query Language)
        """
        top = check_top(top)

        # Get access token for the user
        access_token = await self._get_access_token(user_email)
        if not access_token:
            auth_response = await self._get_auth_url(user_email)
            if auth_response:
                return auth_response
            raise Exception("Failed to get access token")

        # Get select fields (새 SelectParams 구조에 맞게 처리)
        select_fields = None
        if select:
            if isinstance(select, SelectParams):
                select_fields = select.get_selected_fields()
            elif isinstance(select, dict):
                # Dict인 경우 build_select_query 사용
                select_query_str = build_select_query(select)
                select_fields = select_query_str.split(",") if select_query_str else None
            elif isinstance(select, list):
                # 리스트 형태는 그대로 사용 (이미 필드명이 들어 있다고 가정)
                select_fields = select

        # Enforce Graph API search limit
        actual_top = min(top, 250)

        # Build search URL using URL builder
        url_builder = self._get_url_builder(user_email)
        base_url = url_builder.build_search_url(
            search_query=search,
            select_fields=select_fields,
            order_by=orderby,
            top=actual_top,
        )

        # 직접 호출 (페이지네이션 없이)
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                headers = await self._request_headers(user_email)
                async with session.get(base_url, headers=headers, **BEARER_KW) as response:
                    if response.status == 200:
                        data = await response.json()
                        emails = data.get("value", [])

                        # Apply client-side filtering if provided
                        if client_filter and emails:
                            filtered_emails = self._apply_client_side_filter(emails, client_filter)
                            data["value"] = filtered_emails

                        return {
                            "value": data.get("value", []),
                            "total": len(data.get("value", [])),
                            "@odata.count": len(data.get("value", [])),
                            "request_url": base_url,
                            "search_term": search,
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "value": [],
                            "error": f"Search failed with status {response.status}: {graph_error_detail(error_text, 200)}",
                            "status": "error",
                        }
        except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
            raise
        except Exception as e:
            return {"value": [], "error": public_error(e), "status": "error"}

    def _build_message_payload(
        self,
        subject: str,
        body: str,
        body_type: str = "text",
        to_recipients: Optional[List[str]] = None,
        cc_recipients: Optional[List[str]] = None,
        bcc_recipients: Optional[List[str]] = None,
        attachments: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        sendMail(발송)·messages(임시저장) 공용 message 리소스 생성

        첨부 파일 문제(없는 경로, 3MB 초과)는 ValueError 로 올린다.
        """

        def _addr(addrs: List[str]) -> List[Dict[str, Any]]:
            return [{"emailAddress": {"address": a}} for a in addrs]

        message: Dict[str, Any] = {
            "subject": subject,
            "body": {
                "contentType": "HTML" if str(body_type).lower() == "html" else "Text",
                "content": body,
            },
        }
        if to_recipients:
            message["toRecipients"] = _addr(to_recipients)
        if cc_recipients:
            message["ccRecipients"] = _addr(cc_recipients)
        if bcc_recipients:
            message["bccRecipients"] = _addr(bcc_recipients)

        if attachments:
            import base64
            import mimetypes
            from pathlib import Path

            file_attachments = []
            for path_str in attachments:
                if self.paths is not None:
                    # mode 1: 사용자 files/ 안의 파일만 (resolve_safe_path + 경계). 경로 비노출.
                    # 읽기는 검증한 handle 로 한다 — 검사 뒤 교체·hardlink 우회 차단 (R12).
                    from mcp_common.secure_files import UnsafePathError, open_for_read

                    from .outlook_file_policy import resolve_read_file

                    path = resolve_read_file(self.paths, path_str)
                    shown = path.name
                    try:
                        with open_for_read(path, self.paths.files) as fh:
                            # 한도+1 바이트만 읽고 거부한다 — 전체를 메모리에 올리지 않는다 (N08)
                            data = read_limited(fh, limits.MAX_SEND_ATTACHMENT_BYTES, what="첨부파일")
                    except (FileNotFoundError, IsADirectoryError):
                        raise ValueError("첨부파일을 찾을 수 없음") from None
                    except UnsafePathError:
                        raise SecurityError(ErrorCode.PATH_NOT_ALLOWED) from None
                else:
                    path = Path(path_str)
                    shown = path_str
                    if not path.is_file():
                        raise ValueError(f"첨부파일을 찾을 수 없음: {path_str}")
                    with open(path, "rb") as fh:
                        try:
                            data = read_limited(fh, limits.MAX_SEND_ATTACHMENT_BYTES, what="첨부파일")
                        except ValueError:
                            # 직접 첨부는 파일당 3MB 까지 (초과는 업로드 세션이 필요) — mode 0 은 경로 표시 유지
                            raise ValueError(f"첨부파일이 3MB 초과 (직접 첨부 한도): {shown}") from None
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                file_attachments.append(
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": path.name,
                        "contentType": content_type,
                        "contentBytes": base64.b64encode(data).decode("ascii"),
                    }
                )
            message["attachments"] = file_attachments

        return message

    async def send_mail(
        self,
        user_email: str,
        to_recipients: List[str],
        subject: str,
        body: str,
        body_type: str = "text",
        cc_recipients: Optional[List[str]] = None,
        bcc_recipients: Optional[List[str]] = None,
        attachments: Optional[List[str]] = None,
        save_to_sent_items: bool = True,
    ) -> Dict[str, Any]:
        """
        메일 발송 - POST /users/{email}/sendMail

        Args:
            user_email: 발신자(인증) 이메일
            to_recipients: 받는 사람 주소 리스트
            subject: 제목
            body: 본문
            body_type: "text" 또는 "html"
            cc_recipients: 참조 주소 리스트
            bcc_recipients: 숨은 참조 주소 리스트
            attachments: 첨부할 로컬 파일 경로 리스트 (파일당 3MB 제한 - sendMail 직접 첨부 한도)
            save_to_sent_items: 보낸 편지함 저장 여부

        Returns:
            발송 결과 (202 Accepted 시 success)
        """
        access_token = await self._get_access_token(user_email)
        if not access_token:
            auth_response = await self._get_auth_url(user_email)
            if auth_response:
                return auth_response
            raise Exception("Failed to get access token")

        if not to_recipients:
            return {"status": "error", "error": "to_recipients 가 비어 있음"}

        try:
            message = self._build_message_payload(
                subject=subject,
                body=body,
                body_type=body_type,
                to_recipients=to_recipients,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                attachments=attachments,
            )
        except ValueError as e:
            return {"status": "error", "error": str(e)}

        url = f"{GRAPH_BASE}/users/{user_seg(user_email)}/sendMail"
        payload = {"message": message, "saveToSentItems": bool(save_to_sent_items)}

        try:
            async with aiohttp.ClientSession() as session:
                headers = await self._request_headers(user_email)
                async with session.post(url, headers=headers, json=payload, **BEARER_KW) as response:
                    # sendMail 은 성공 시 202 Accepted + 빈 본문을 돌려준다
                    if response.status == 202:
                        return {
                            "status": "success",
                            "message": "메일 발송 완료",
                            "to": to_recipients,
                            "cc": cc_recipients or [],
                            "bcc": bcc_recipients or [],
                            "subject": subject,
                            "attachments": [a["name"] for a in message.get("attachments", [])],
                            "save_to_sent_items": bool(save_to_sent_items),
                        }
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"sendMail failed with status {response.status}: {graph_error_detail(error_text, 300)}",
                    }
        except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
            raise
        except Exception as e:
            return {"status": "error", "error": public_error(e)}

    async def save_draft(
        self,
        user_email: str,
        subject: str,
        body: str,
        body_type: str = "text",
        to_recipients: Optional[List[str]] = None,
        cc_recipients: Optional[List[str]] = None,
        bcc_recipients: Optional[List[str]] = None,
        attachments: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        메일 임시저장 - POST /users/{email}/messages (Drafts 폴더에 생성)

        발송과 달리 받는 사람 없이도 저장할 수 있다.

        Args:
            user_email: 작성자(인증) 이메일
            subject: 제목
            body: 본문
            body_type: "text" 또는 "html"
            to_recipients: 받는 사람 주소 리스트 (임시저장은 생략 가능)
            cc_recipients: 참조 주소 리스트
            bcc_recipients: 숨은 참조 주소 리스트
            attachments: 첨부할 로컬 파일 경로 리스트 (파일당 3MB 제한)

        Returns:
            저장 결과 (201 Created 시 success + draft_id/web_link)
        """
        access_token = await self._get_access_token(user_email)
        if not access_token:
            auth_response = await self._get_auth_url(user_email)
            if auth_response:
                return auth_response
            raise Exception("Failed to get access token")

        try:
            message = self._build_message_payload(
                subject=subject,
                body=body,
                body_type=body_type,
                to_recipients=to_recipients,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                attachments=attachments,
            )
        except ValueError as e:
            return {"status": "error", "error": str(e)}

        url = f"{GRAPH_BASE}/users/{user_seg(user_email)}/messages"

        try:
            async with aiohttp.ClientSession() as session:
                headers = await self._request_headers(user_email)
                async with session.post(url, headers=headers, json=message, **BEARER_KW) as response:
                    # 임시저장은 성공 시 201 Created + 생성된 message 리소스를 돌려준다
                    if response.status == 201:
                        data = await response.json()
                        return {
                            "status": "success",
                            "message": "임시저장 완료 (Drafts)",
                            "draft_id": data.get("id"),
                            "web_link": data.get("webLink"),
                            "to": to_recipients or [],
                            "cc": cc_recipients or [],
                            "bcc": bcc_recipients or [],
                            "subject": subject,
                            "attachments": [a["name"] for a in message.get("attachments", [])],
                        }
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"draft save failed with status {response.status}: {graph_error_detail(error_text, 300)}",
                    }
        except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
            raise
        except Exception as e:
            return {"status": "error", "error": public_error(e)}

    async def _fetch_parallel_with_url(
        self,
        user_email: str,
        base_url: str,
        total_items: int,
        client_filter: Optional[ExcludeParams] = None,
    ) -> Dict[str, Any]:
        """
        Internal method to fetch with parallel pagination
        Always fetches in pages of 150 items
        Applies client-side filtering immediately as data is received

        토큰은 페이지 요청마다 공급자에서 새로 얻는다 (N01) — 인자로 받지 않는다.

        Args:
            user_email: User email for context
            base_url: Base URL without pagination
            total_items: Total items to fetch
            client_filter: Optional client-side filter to apply immediately on fetch

        Returns:
            All fetched and filtered emails
        """
        # 한도 밖 top 은 코루틴을 하나도 만들기 전에 거부한다 (R02)
        total_items = check_top(total_items)
        # mode 1: 경로 정책 위반은 SecurityError (토큰을 실은 요청을 만들기 전에)
        enforce_mail_query_url(base_url)
        if not is_graph_https(base_url):
            return {
                "status": "error",
                "error": f"허용되지 않은 URL — https://graph.microsoft.com 만 가능: {base_url}",
                "value": [],
                "total": 0,
            }

        page_size = 150
        max_concurrent = 3

        # Calculate number of pages (even for small requests)
        num_pages = (total_items + page_size - 1) // page_size

        # For single page requests, still use parallel structure for consistency
        logger.info("[MAIL] fetching %d emails in %d page(s) (%d per page)", total_items, num_pages, page_size)

        async def fetch_page(session, url, page_num):
            try:
                # 페이지마다 토큰을 새로 얻는다 — 폐기·epoch 변경이 다음 페이지에서 바로 끊긴다 (N01)
                headers = await self._request_headers(user_email)
                async with session.get(url, headers=headers, **BEARER_KW) as response:
                    if response.status == 200:
                        data = await response.json()
                        emails = data.get("value", [])

                        # Apply client-side filtering immediately if provided
                        if client_filter and emails:
                            filtered_emails = self._apply_client_side_filter(emails, client_filter)
                            data["value"] = filtered_emails
                            logger.debug(
                                "[MAIL] page %d: %d emails, kept %d", page_num, len(emails), len(filtered_emails)
                            )
                        else:
                            logger.debug("[MAIL] page %d: %d emails", page_num, len(emails))

                        return data
                    else:
                        logger.warning("[MAIL] page %d: HTTP %s", page_num, response.status)
                        return {"value": [], "error": f"HTTP {response.status}", "page": page_num}
            except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
                raise  # 폐기·연결 없음은 부분 결과로 감추지 않는다
            except Exception as e:
                logger.warning("[MAIL] page %d: %s", page_num, type(e).__name__)
                return {"value": [], "error": public_error(e), "page": page_num}

        def page_url_for(page: int) -> str:
            skip = page * page_size
            # Always use page_size of 150, except for the last page
            top = min(page_size, total_items - skip)
            separator = "&" if "?" in base_url else "?"
            url = f"{base_url}{separator}$top={top}&$skip={skip}"
            # 다음 페이지 URL 도 같은 정책 (②-7.5)
            enforce_mail_query_url(url)
            return url

        # 페이지 코루틴을 전부 미리 만들지 않는다 (R02): 동시 실행 수만큼의 worker 가
        # 하나를 끝낸 뒤에야 다음 페이지를 만든다. 동시에 존재하는 페이지 작업 ≤ max_concurrent.
        page_results: Dict[int, Dict[str, Any]] = {}
        next_page = 0

        async def worker(session):
            nonlocal next_page
            while next_page < num_pages:
                page = next_page
                next_page += 1
                page_results[page] = await fetch_page(session, page_url_for(page), page + 1)

        async with aiohttp.ClientSession() as session:
            start_time = datetime.now()
            await asyncio.gather(*(worker(session) for _ in range(min(max_concurrent, num_pages))))
            elapsed = (datetime.now() - start_time).total_seconds()

        results = [page_results[i] for i in range(num_pages)]

        # Collect all emails and errors
        all_emails = []
        errors = []
        for result in results:
            all_emails.extend(result.get("value", []))
            # Collect error information if present
            if result.get("error"):
                errors.append(result)

        # $skip 병렬 조회 중 새 메일이 오면 페이지 경계가 밀려 같은 메일이 두 페이지에 걸친다 — id 로 중복 제거
        seen: set = set()
        deduped = []
        for email in all_emails:
            eid = email.get("id")
            if eid and eid in seen:
                continue
            seen.add(eid)
            deduped.append(email)
        all_emails = deduped

        logger.info("[MAIL] fetched %d emails in %.2fs (%d page error(s))", len(all_emails), elapsed, len(errors))

        return_data = {
            "value": all_emails,
            "total": len(all_emails),
            "@odata.count": len(all_emails),
            "request_url": base_url,  # Include the built URL
            "pages_requested": num_pages,
            "fetch_time": elapsed,
        }

        # 오류 정보 반영: 전 페이지 실패는 실패 계약(status:error)으로, 부분 실패는 partial 로 표시
        if errors:
            return_data["errors"] = errors
            return_data["has_errors"] = True
            if len(errors) >= num_pages:
                # 전량 실패 — 상위에서 성공으로 오판하지 않도록 실패 상태 부여
                return_data["status"] = "error"
                return_data["error"] = f"모든 페이지 요청 실패 ({len(errors)}/{num_pages})"
            else:
                # 부분 실패 — 성공분 보존 (is_failure 는 partial 을 실패로 보지 않음)
                return_data["status"] = "partial"

        return return_data

    def format_emails(self, results: Dict[str, Any], verbose: bool = False) -> str:
        """
        Format email results for display

        Args:
            results: Email query results
            verbose: Include body preview

        Returns:
            Formatted string
        """
        emails = results.get("value", [])

        if not emails:
            return "No emails found."

        output = []
        output.append(f"\n{'='*80}")
        output.append(f"Found {len(emails)} email(s)")
        output.append(f"{'='*80}\n")

        for idx, email in enumerate(emails, 1):
            # Parse datetime
            received_dt = email.get("receivedDateTime", "Unknown")
            if received_dt != "Unknown":
                try:
                    dt = datetime.fromisoformat(received_dt.replace("Z", "+00:00"))
                    received_dt = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass

            # Get info
            subject = email.get("subject", "No Subject")
            from_info = email.get("from", {})
            sender_name = from_info.get("emailAddress", {}).get("name", "Unknown")
            sender_email = from_info.get("emailAddress", {}).get("address", "Unknown")
            is_read = email.get("isRead", False)
            has_attachments = email.get("hasAttachments", False)
            importance = email.get("importance", "normal")

            # Format
            read_status = "[READ]" if is_read else "[UNREAD]"
            attach_icon = "[ATTACH]" if has_attachments else ""
            imp_icon = "[!]" if importance == "high" else ""

            output.append(f"[{idx}] {read_status} {imp_icon}{attach_icon} {subject}")
            output.append(f"    From: {sender_name} <{sender_email}>")
            output.append(f"    Date: {received_dt}")

            if verbose and email.get("bodyPreview"):
                preview = email.get("bodyPreview", "")[:150]
                output.append(f"    Preview: {preview}...")

            output.append("")

        return "\n".join(output)

    async def process_with_options(
        self,
        user_email: str,
        mail_data: Dict[str, Any],
        mail_storage: str = "memory",
        attachment_handling: str = "skip",
        output_format: str = "combined",
        save_directory: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        메일 데이터를 받아서 처리 옵션에 따라 처리

        Args:
            user_email: User email for authentication
            mail_data: 쿼리 결과 (fetch_parallel_with_url의 반환값)
            mail_storage: 메일 저장 방식 ("memory", "text", "json", "database")
            attachment_handling: 첨부파일 처리 ("skip", "download", "convert", "convert_delete")
            output_format: 출력 형식 ("combined", "separated", "structured")
            save_directory: 저장 디렉토리

        Returns:
            처리된 결과
        """
        from .mail_attachment import BatchAttachmentHandler

        # 메일 목록 추출
        if isinstance(mail_data, dict):
            emails = mail_data.get("value", [mail_data])
        else:
            emails = mail_data if isinstance(mail_data, list) else [mail_data]

        # 첨부파일 처리가 필요한 경우
        if attachment_handling in ["download", "convert", "convert_delete"]:
            message_ids = [email.get("id") for email in emails if email.get("id")]
            if message_ids:
                handler = BatchAttachmentHandler(
                    base_directory=save_directory or "downloads",
                    token_provider=self.token_provider,
                    paths=self.paths,
                )
                attachment_result = await handler.fetch_and_save(
                    user_email=user_email,
                    message_ids=message_ids,
                    skip_duplicates=True,
                )
                return {
                    "status": "success",
                    "value": emails,
                    "total": len(emails),
                    "attachment_result": attachment_result,
                }

        # 첨부파일 처리 없이 메일만 반환
        return {
            "status": "success",
            "value": emails,
            "total": len(emails),
        }

    async def close(self):
        """Clean up resources — 토큰 공급자는 빌린 것이므로 닫지 않는다 (②-2.4 종료 경로 소유권).

        세션은 요청마다 열고 닫으므로 이 객체가 소유한 열린 자원은 없다.
        """
        return None


# Convenience function for quick queries
async def query_emails(
    user_email: str,
    filter_params: Optional[Dict[str, Any]] = None,
    search_term: Optional[str] = None,
    url: Optional[str] = None,
    top: int = 450,
) -> Dict[str, Any]:
    """
    Quick function to query emails

    Args:
        user_email: User email (required)
        filter_params: Filter parameters
        search_term: Search keyword
        url: Pre-built URL
        top: Maximum results

    Returns:
        Email query results
    """
    query = GraphMailQuery()

    if url:
        return await query.query_url(user_email=user_email, url=url, top=top)
    elif search_term:
        return await query.query_search(user_email=user_email, search=search_term, top=top)
    elif filter_params:
        return await query.query_filter(user_email=user_email, filter=FilterParams(**filter_params), top=top)
    else:
        return {"status": "error", "error": "Must provide either url, search_term, or filter_params"}
