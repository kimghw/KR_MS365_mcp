"""
Teams Graph API Client
Microsoft Graph API를 사용한 Teams 작업 처리
session 모듈을 통한 인증 관리
"""

import html
import logging
import re
from dataclasses import asdict
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from urllib.parse import quote
import aiohttp

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol
from .teams_types import (
    ChatInfo,
    MessageInfo,
    TeamInfo,
    ChannelInfo,
    ChatType,
    MessageImportance,
)

logger = logging.getLogger(__name__)


class GraphTeamsClient:
    """Teams Graph API 클라이언트"""

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    NOTES_CHAT_ID = "48:notes"  # 나의 Notes 특수 채팅

    def __init__(self, token_provider: Optional["TokenProviderProtocol"] = None):
        """
        클라이언트 초기화

        Args:
            token_provider: 토큰 제공자 (없으면 프로세스 공유 AuthManager 사용)
        """
        if token_provider is None:
            # AuthManager 를 새로 만들면 per-email refresh lock 이 인스턴스별로 갈려
            # 무의미해진다. 프로세스 단일 인스턴스를 공유한다.
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
        logger.info("GraphTeamsClient initialized")
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
            token = await self.token_provider.validate_and_refresh_token(user_email)
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
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Graph API 요청 수행

        Args:
            method: HTTP 메서드 (GET, POST, PATCH, DELETE)
            endpoint: API 엔드포인트
            user_email: 사용자 이메일
            json_data: JSON 데이터
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
            "Content-Type": "application/json",
        }

        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data if json_data else None,
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
    # 채팅 관련 메서드
    # ========================================================================

    async def list_chats(
        self,
        user_email: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        사용자의 채팅 목록 조회

        Args:
            user_email: 사용자 이메일
            limit: 조회할 채팅 개수

        Returns:
            채팅 목록
        """
        endpoint = f"/me/chats?$top={limit}&$expand=members,lastMessagePreview"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            chats_data = result.get("data", {}).get("value", [])
            chats = [ChatInfo.from_dict(c) for c in chats_data]
            return {
                "success": True,
                # asdict: members(UserInfo 데이터클래스)까지 dict로 변환해 JSON 직렬화 가능하게 함
                "chats": [asdict(c) for c in chats],
                "count": len(chats),
                # 다음 페이지가 있으면 부분 목록 — 동기화에서 비활성화 판단에 쓰지 않는다
                "has_more": bool(result.get("data", {}).get("@odata.nextLink")),
            }

        return result

    async def get_chat(
        self,
        user_email: str,
        chat_id: str,
    ) -> Dict[str, Any]:
        """
        특정 채팅 정보 조회

        Args:
            user_email: 사용자 이메일
            chat_id: 채팅 ID

        Returns:
            채팅 정보
        """
        endpoint = f"/me/chats/{chat_id}"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            chat = ChatInfo.from_dict(result.get("data", {}))
            return {"success": True, "chat": chat.__dict__}

        return result

    # ========================================================================
    # 메시지 관련 메서드
    # ========================================================================

    async def get_chat_messages(
        self,
        user_email: str,
        chat_id: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        채팅 메시지 목록 조회

        Args:
            user_email: 사용자 이메일
            chat_id: 채팅 ID (없으면 Notes 채팅 사용)
            limit: 조회할 메시지 개수

        Returns:
            메시지 목록
        """
        chat_id = chat_id or self.NOTES_CHAT_ID
        endpoint = f"/me/chats/{chat_id}/messages?$top={limit}&$orderby=createdDateTime desc"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            messages_data = result.get("data", {}).get("value", [])
            messages = [MessageInfo.from_dict(m) for m in messages_data]
            return {
                "success": True,
                "messages": [m.__dict__ for m in messages],
                "count": len(messages),
            }

        return result

    async def send_chat_message(
        self,
        user_email: str,
        content: str,
        chat_id: Optional[str] = None,
        prefix: str = "[claude]",
        content_type: str = "text",
    ) -> Dict[str, Any]:
        """
        채팅에 메시지 전송

        Args:
            user_email: 사용자 이메일
            content: 메시지 내용
            chat_id: 채팅 ID (없으면 Notes 채팅 사용)
            prefix: 메시지 프리픽스
            content_type: 콘텐츠 타입 (text 또는 html)

        Returns:
            전송된 메시지 정보
        """
        chat_id = chat_id or self.NOTES_CHAT_ID

        # 프리픽스 추가
        if prefix:
            full_content = f"{prefix} {content}"
        else:
            full_content = content

        endpoint = f"/me/chats/{chat_id}/messages"
        json_data = {
            "body": {
                "contentType": content_type,
                "content": full_content,
            }
        }

        result = await self._make_request("POST", endpoint, user_email, json_data)

        if result.get("success"):
            message = MessageInfo.from_dict(result.get("data", {}))
            return {
                "success": True,
                "message_id": message.id,
                "message": message.__dict__,
            }

        return result

    # ------------------------------------------------------------------------
    # 채팅에 파일 보내기
    # ------------------------------------------------------------------------
    # Graph 에는 "채팅에 파일을 올리는" 한 번의 호출이 없다. Teams 앱이 하는 일을 차례대로 한다:
    #   1) 보내는 사람의 OneDrive "Microsoft Teams Chat Files" 폴더에 파일을 올린다
    #   2) 받는 사람들에게 그 파일의 읽기 권한을 준다(앱은 이것을 알아서 한다)
    #   3) 메시지 본문에 <attachment id="…"> 를 넣고 attachments 에 그 파일을 reference 로 단다
    # attachment 의 id 는 driveItem 의 eTag 안에 있는 GUID, contentUrl 은 webDavUrl 이다.

    CHAT_FILES_FOLDER = "Microsoft Teams Chat Files"
    UPLOAD_TIMEOUT = 120

    async def _upload_chat_file(self, user_email: str, file_name: str, data: bytes) -> Dict[str, Any]:
        """파일을 보내는 사람의 OneDrive(Teams 채팅 파일 폴더)에 올리고 첨부에 쓸 값(id·guid·url)을 돌려준다."""
        if not self._initialized:
            await self.initialize()
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다. 로그인이 필요합니다."}

        path = quote(f"{self.CHAT_FILES_FOLDER}/{file_name}")
        # 같은 이름이 있으면 덮어쓰지 않고 이름을 바꿔 올린다 — 앞서 보낸 파일이 바뀌면 안 된다.
        url = f"{self.GRAPH_BASE_URL}/me/drive/root:/{path}:/content?@microsoft.graph.conflictBehavior=rename"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/octet-stream"}
        try:
            async with self._session.put(
                url, headers=headers, data=data, timeout=aiohttp.ClientTimeout(total=self.UPLOAD_TIMEOUT)
            ) as response:
                if response.status not in (200, 201):
                    error_text = await response.text()
                    logger.error(f"파일 업로드 실패: {response.status} - {error_text}")
                    return {"success": False, "error": f"파일 업로드 실패: {response.status}", "details": error_text}
                item = await response.json()
        except Exception as e:
            logger.error(f"파일 업로드 오류: {str(e)}")
            return {"success": False, "error": str(e)}

        # webDavUrl 은 달라고 해야 준다.
        detail = await self._make_request(
            "GET", f"/me/drive/items/{item['id']}?$select=id,name,eTag,webUrl,webDavUrl,sharepointIds", user_email
        )
        if not detail.get("success"):
            return detail
        info = detail.get("data", {})
        guid = (info.get("sharepointIds") or {}).get("listItemUniqueId")
        if not guid:
            match = re.search(r"\{?([0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})\}?", info.get("eTag") or "")
            guid = match.group(1) if match else None
        content_url = info.get("webDavUrl") or info.get("webUrl")
        if not guid or not content_url:
            return {"success": False, "error": "올린 파일의 첨부 정보를 읽지 못했습니다.", "details": str(info)}
        return {"success": True, "item_id": info["id"], "guid": guid, "content_url": content_url,
                "name": info.get("name") or file_name, "web_url": info.get("webUrl")}

    async def _one_on_one_chat_id(self, user_email: str, recipient_email: str) -> Dict[str, Any]:
        """받는 사람과의 1:1 채팅 ID. 이미 있으면 그 채팅이, 없으면 새로 만든 채팅이 온다."""
        def member(upn: str) -> Dict[str, Any]:
            return {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"{self.GRAPH_BASE_URL}/users('{upn}')",
            }

        result = await self._make_request(
            "POST", "/chats", user_email, {"chatType": "oneOnOne", "members": [member(user_email), member(recipient_email)]}
        )
        if not result.get("success"):
            return result
        chat_id = result.get("data", {}).get("id")
        if not chat_id:
            return {"success": False, "error": "1:1 채팅을 찾지 못했습니다."}
        return {"success": True, "chat_id": chat_id}

    async def _chat_member_emails(self, user_email: str, chat_id: str) -> Optional[List[str]]:
        """채팅 구성원의 메일(나는 빼고). 못 읽으면 None — 빈 목록(나뿐인 채팅)과 가려야 한다."""
        result = await self._make_request("GET", f"/chats/{chat_id}/members", user_email)
        if not result.get("success"):
            return None
        emails = [m.get("email") for m in result.get("data", {}).get("value", []) if m.get("email")]
        return [e for e in emails if e.lower() != user_email.lower()]

    async def send_chat_file(
        self,
        user_email: str,
        content: str,
        file_name: str,
        file_bytes: bytes,
        chat_id: Optional[str] = None,
        recipient_email: Optional[str] = None,
        prefix: str = "",
        content_type: str = "html",
    ) -> Dict[str, Any]:
        """
        채팅에 파일을 붙여 메시지 전송

        Args:
            user_email: 보내는 사람
            content: 메시지 본문
            file_name: 파일 이름(확장자 포함)
            file_bytes: 파일 내용
            chat_id: 채팅 ID. 없으면 recipient_email 과의 1:1 채팅, 그것도 없으면(또는 나 자신이면) Notes
            recipient_email: 받는 사람 메일(1:1 채팅)
            prefix: 메시지 프리픽스
            content_type: 본문 형식 (text 또는 html). 첨부 표식 때문에 실제로는 항상 html 로 나간다

        Returns:
            전송된 메시지와 올린 파일 정보
        """
        # 어느 채팅으로 가고 누가 파일을 읽어야 하는지부터 정한다 — 정하지 못하면 아무것도 올리지 않는다.
        # chat_id 를 주었으면 그 채팅의 구성원 모두가 읽는 사람이다(recipient_email 을 같이 주었어도 chat_id 가 먼저다).
        to_self = not recipient_email or recipient_email.lower() == user_email.lower()
        readers: List[str] = []
        if chat_id:
            if chat_id != self.NOTES_CHAT_ID:
                members = await self._chat_member_emails(user_email, chat_id)
                if members is None:
                    return {"success": False, "error": "채팅 구성원을 읽지 못해 파일 권한을 줄 수 없습니다(보내지 않았습니다)."}
                readers = members
        elif to_self:
            chat_id = self.NOTES_CHAT_ID   # 나에게 보내기 — 권한을 줄 사람이 없다
        else:
            chat = await self._one_on_one_chat_id(user_email, recipient_email)
            if not chat.get("success"):
                return chat
            chat_id = chat["chat_id"]
            readers = [recipient_email]

        uploaded = await self._upload_chat_file(user_email, file_name, file_bytes)
        if not uploaded.get("success"):
            return uploaded

        # 받는 사람이 파일을 열 수 있게 읽기 권한을 준다.
        if readers:
            shared = await self._make_request(
                "POST", f"/me/drive/items/{uploaded['item_id']}/invite", user_email,
                {"requireSignIn": True, "sendInvitation": False, "roles": ["read"],
                 "recipients": [{"email": e} for e in readers]},
            )
            if not shared.get("success"):
                return {"success": False, "error": "받는 사람에게 파일 권한을 주지 못했습니다(메시지는 보내지 않았습니다).",
                        "details": shared.get("details") or shared.get("error"), "file": uploaded}

        body = content if content_type == "html" else html.escape(content).replace("\n", "<br>")
        if prefix:
            body = f"{html.escape(prefix)} {body}"
        json_data = {
            "body": {"contentType": "html", "content": f'{body}<attachment id="{uploaded["guid"]}"></attachment>'},
            "attachments": [{
                "id": uploaded["guid"],
                "contentType": "reference",
                "contentUrl": uploaded["content_url"],
                "name": uploaded["name"],
            }],
        }
        result = await self._make_request("POST", f"/me/chats/{chat_id}/messages", user_email, json_data)
        if not result.get("success"):
            return {**result, "file": uploaded}
        message = MessageInfo.from_dict(result.get("data", {}))
        return {
            "success": True,
            "message_id": message.id,
            "chat_id": chat_id,
            "file": {"name": uploaded["name"], "web_url": uploaded.get("web_url")},
        }

    # ========================================================================
    # 팀 관련 메서드
    # ========================================================================

    async def list_teams(
        self,
        user_email: str,
    ) -> Dict[str, Any]:
        """
        사용자가 속한 팀 목록 조회

        Args:
            user_email: 사용자 이메일

        Returns:
            팀 목록
        """
        endpoint = "/me/joinedTeams"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            teams_data = result.get("data", {}).get("value", [])
            teams = [TeamInfo.from_dict(t) for t in teams_data]
            return {
                "success": True,
                "teams": [t.__dict__ for t in teams],
                "count": len(teams),
            }

        return result

    async def list_channels(
        self,
        user_email: str,
        team_id: str,
    ) -> Dict[str, Any]:
        """
        팀의 채널 목록 조회

        Args:
            user_email: 사용자 이메일
            team_id: 팀 ID

        Returns:
            채널 목록
        """
        endpoint = f"/teams/{team_id}/channels"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            channels_data = result.get("data", {}).get("value", [])
            channels = [ChannelInfo.from_dict(c) for c in channels_data]
            return {
                "success": True,
                "channels": [c.__dict__ for c in channels],
                "count": len(channels),
            }

        return result

    async def get_channel_messages(
        self,
        user_email: str,
        team_id: str,
        channel_id: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        채널 메시지 목록 조회

        Args:
            user_email: 사용자 이메일
            team_id: 팀 ID
            channel_id: 채널 ID
            limit: 조회할 메시지 개수

        Returns:
            메시지 목록
        """
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages?$top={limit}"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            messages_data = result.get("data", {}).get("value", [])
            messages = [MessageInfo.from_dict(m) for m in messages_data]
            return {
                "success": True,
                "messages": [m.__dict__ for m in messages],
                "count": len(messages),
            }

        return result

    async def send_channel_message(
        self,
        user_email: str,
        team_id: str,
        channel_id: str,
        content: str,
        content_type: str = "text",
    ) -> Dict[str, Any]:
        """
        채널에 메시지 전송

        Args:
            user_email: 사용자 이메일
            team_id: 팀 ID
            channel_id: 채널 ID
            content: 메시지 내용
            content_type: 콘텐츠 타입 (text 또는 html)

        Returns:
            전송된 메시지 정보
        """
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages"
        json_data = {
            "body": {
                "contentType": content_type,
                "content": content,
            }
        }

        result = await self._make_request("POST", endpoint, user_email, json_data)

        if result.get("success"):
            message = MessageInfo.from_dict(result.get("data", {}))
            return {
                "success": True,
                "message_id": message.id,
                "message": message.__dict__,
            }

        return result

    async def get_message_replies(
        self,
        user_email: str,
        team_id: str,
        channel_id: str,
        message_id: str,
    ) -> Dict[str, Any]:
        """
        메시지 답글 목록 조회

        Args:
            user_email: 사용자 이메일
            team_id: 팀 ID
            channel_id: 채널 ID
            message_id: 메시지 ID

        Returns:
            답글 목록
        """
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            replies_data = result.get("data", {}).get("value", [])
            replies = [MessageInfo.from_dict(r) for r in replies_data]
            return {
                "success": True,
                "replies": [r.__dict__ for r in replies],
                "count": len(replies),
            }

        return result
