"""
채팅에 파일 보내기(handler_teams_send_chat_file) 테스트.

Graph 에는 닿지 않는다 — 서비스가 파일을 어떻게 받아 넘기는지, 클라이언트가 어떤 차례로
무엇을 보내는지(채팅 찾기 → 올리기 → 권한 주기 → 첨부를 단 메시지)만 본다.
"""

import base64
import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_teams.graph_teams_client import GraphTeamsClient
from mcp_teams.teams_service import TeamsService

ME = "me@example.com"
PDF = b"%PDF-1.7 test"
UPLOADED = {
    "success": True, "item_id": "item-1", "guid": "5E1D1C9A-0000-4000-8000-123456789ABC",
    "content_url": "https://tenant-my.sharepoint.com/personal/me/Documents/Microsoft Teams Chat Files/a.pdf",
    "name": "a.pdf", "web_url": "https://tenant-my.sharepoint.com/a.pdf",
}


@pytest.fixture
def service():
    svc = TeamsService()
    svc._client = AsyncMock()
    svc._client.send_chat_file = AsyncMock(return_value={"success": True, "message_id": "m1"})
    svc._initialized = True
    return svc


class TestServiceSendChatFile:
    @pytest.mark.asyncio
    async def test_base64_content_is_decoded_and_delegated(self, service):
        result = await service.send_chat_file(
            content="<p>글</p>", file_name="a.pdf", file_base64=base64.b64encode(PDF).decode(),
            recipient_email="you@example.com", user_email=ME,
        )
        assert result["success"] is True
        service._client.send_chat_file.assert_awaited_once_with(
            user_email=ME, content="<p>글</p>", file_name="a.pdf", file_bytes=PDF,
            chat_id=None, recipient_email="you@example.com", prefix="", content_type="html",
        )

    @pytest.mark.asyncio
    async def test_file_path_is_read_and_named_after_the_file(self, service, tmp_path):
        path = tmp_path / "증빙.pdf"
        path.write_bytes(PDF)
        await service.send_chat_file(content="x", file_path=str(path), user_email=ME)
        kwargs = service._client.send_chat_file.await_args.kwargs
        assert (kwargs["file_name"], kwargs["file_bytes"]) == ("증빙.pdf", PDF)

    @pytest.mark.asyncio
    async def test_file_name_keeps_only_the_base_name(self, service):
        name = "..\\other/b.pdf"
        await service.send_chat_file(content="x", file_name=name, file_base64=base64.b64encode(PDF).decode(), user_email=ME)
        assert service._client.send_chat_file.await_args.kwargs["file_name"] == "b.pdf"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kwargs, error", [
        ({}, "file_base64 나 file_path"),
        ({"file_base64": "###", "file_name": "a.pdf"}, "올바른 base64"),
        ({"file_base64": base64.b64encode(PDF).decode()}, "file_name 이 필요"),
        ({"file_path": "Z:/없는/파일.pdf"}, "파일을 읽지 못했습니다"),
        ({"file_base64": "", "file_path": "", "file_name": "a.pdf"}, "file_base64 나 file_path"),
    ])
    async def test_bad_input_never_reaches_graph(self, service, kwargs, error):
        result = await service.send_chat_file(content="x", user_email=ME, **kwargs)
        assert result["success"] is False and error in result["error"]
        service._client.send_chat_file.assert_not_awaited()


def _client(responses):
    """_make_request 를 흉내 낸 클라이언트. 부른 것을 차례대로 calls 에 적는다."""
    client = GraphTeamsClient(token_provider=AsyncMock())
    calls = []

    async def fake_request(method, endpoint, user_email, json_data=None, timeout=30):
        calls.append((method, endpoint, json_data))
        for prefix, reply in responses.items():
            if endpoint.startswith(prefix):
                return reply
        return {"success": True, "data": {"id": "msg-1"}}

    client._make_request = fake_request
    client._upload_chat_file = AsyncMock(return_value=dict(UPLOADED))
    return client, calls


class TestClientSendChatFile:
    @pytest.mark.asyncio
    async def test_recipient_gets_chat_file_permission_then_message_with_attachment(self):
        client, calls = _client({"/chats": {"success": True, "data": {"id": "19:abc@unq.gbl.spaces"}}})
        result = await client.send_chat_file(ME, "<p>글</p>", "a.pdf", PDF, recipient_email="you@example.com")

        assert [(m, e) for m, e, _ in calls] == [
            ("POST", "/chats"),
            ("POST", "/me/drive/items/item-1/invite"),
            ("POST", "/me/chats/19:abc@unq.gbl.spaces/messages"),
        ]
        assert calls[0][2]["chatType"] == "oneOnOne"
        assert [m["user@odata.bind"] for m in calls[0][2]["members"]] == [
            "https://graph.microsoft.com/v1.0/users('me@example.com')",
            "https://graph.microsoft.com/v1.0/users('you@example.com')",
        ]
        assert calls[1][2] == {"requireSignIn": True, "sendInvitation": False, "roles": ["read"],
                               "recipients": [{"email": "you@example.com"}]}
        message = calls[2][2]
        assert message["body"] == {"contentType": "html",
                                   "content": f'<p>글</p><attachment id="{UPLOADED["guid"]}"></attachment>'}
        assert message["attachments"] == [{"id": UPLOADED["guid"], "contentType": "reference",
                                           "contentUrl": UPLOADED["content_url"], "name": "a.pdf"}]
        client._upload_chat_file.assert_awaited_once_with(ME, "a.pdf", PDF)
        assert result == {"success": True, "message_id": "msg-1", "chat_id": "19:abc@unq.gbl.spaces",
                          "file": {"name": "a.pdf", "web_url": UPLOADED["web_url"]}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("recipient", [None, "ME@example.com"])
    async def test_no_recipient_or_myself_goes_to_notes_without_sharing(self, recipient):
        client, calls = _client({})
        result = await client.send_chat_file(ME, "줄1\n<줄2>", "a.pdf", PDF, recipient_email=recipient,
                                             prefix="[claude]", content_type="text")
        assert [(m, e) for m, e, _ in calls] == [("POST", "/me/chats/48:notes/messages")]
        assert calls[0][2]["body"]["content"].startswith("[claude] 줄1<br>&lt;줄2&gt;<attachment id=")
        assert result["chat_id"] == "48:notes"

    @pytest.mark.asyncio
    async def test_group_chat_shares_with_every_other_member(self):
        client, calls = _client({"/chats/19:group/members": {"success": True, "data": {"value": [
            {"email": ME}, {"email": "a@example.com"}, {"email": "b@example.com"}, {"email": None}]}}})
        await client.send_chat_file(ME, "x", "a.pdf", PDF, chat_id="19:group")
        assert calls[1][2]["recipients"] == [{"email": "a@example.com"}, {"email": "b@example.com"}]
        assert calls[2][1] == "/me/chats/19:group/messages"

    @pytest.mark.asyncio
    async def test_chat_id_wins_over_recipient_and_shares_with_the_whole_chat(self):
        client, calls = _client({"/chats/19:group/members": {"success": True, "data": {"value": [
            {"email": ME}, {"email": "a@example.com"}, {"email": "b@example.com"}]}}})
        await client.send_chat_file(ME, "x", "a.pdf", PDF, chat_id="19:group", recipient_email="a@example.com")
        assert [(m, e) for m, e, _ in calls] == [
            ("GET", "/chats/19:group/members"),
            ("POST", "/me/drive/items/item-1/invite"),
            ("POST", "/me/chats/19:group/messages"),
        ]
        assert calls[1][2]["recipients"] == [{"email": "a@example.com"}, {"email": "b@example.com"}]

    @pytest.mark.asyncio
    async def test_nothing_is_uploaded_or_sent_when_chat_members_cannot_be_read(self):
        client, calls = _client({"/chats/19:group/members": {"success": False, "error": "API 요청 실패: 403"}})
        result = await client.send_chat_file(ME, "x", "a.pdf", PDF, chat_id="19:group")
        assert result["success"] is False and "구성원을 읽지 못해" in result["error"]
        client._upload_chat_file.assert_not_awaited()
        assert not any(e.endswith("/messages") for _, e, _ in calls)

    @pytest.mark.asyncio
    async def test_chat_with_only_me_is_sent_without_sharing(self):
        client, calls = _client({"/chats/19:solo/members": {"success": True, "data": {"value": [{"email": ME}]}}})
        result = await client.send_chat_file(ME, "x", "a.pdf", PDF, chat_id="19:solo")
        assert [e for _, e, _ in calls] == ["/chats/19:solo/members", "/me/chats/19:solo/messages"]
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_message_is_not_sent_when_sharing_fails(self):
        client, calls = _client({
            "/chats": {"success": True, "data": {"id": "19:abc"}},
            "/me/drive/items/item-1/invite": {"success": False, "error": "API 요청 실패: 403", "details": "denied"},
        })
        result = await client.send_chat_file(ME, "x", "a.pdf", PDF, recipient_email="you@example.com")
        assert result["success"] is False and "권한을 주지 못했습니다" in result["error"]
        assert not any(e.endswith("/messages") for _, e, _ in calls)

    @pytest.mark.asyncio
    async def test_nothing_is_uploaded_when_the_chat_cannot_be_found(self):
        client, calls = _client({"/chats": {"success": False, "error": "API 요청 실패: 404"}})
        result = await client.send_chat_file(ME, "x", "a.pdf", PDF, recipient_email="nobody@example.com")
        assert result["success"] is False
        client._upload_chat_file.assert_not_awaited()


def test_tool_is_declared_in_spec_and_wired():
    from mcp_teams.mcp_server.handlers import MCP_TOOLS, TOOL_HANDLERS

    tool = next(t for t in MCP_TOOLS if t["name"] == "handler_teams_send_chat_file")
    props = tool["inputSchema"]["properties"]
    assert {"content", "file_name", "file_base64", "file_path", "recipient_email", "chat_id",
            "prefix", "content_type", "user_email"} <= set(props)
    assert tool["inputSchema"]["required"] == ["content"]
    assert "handler_teams_send_chat_file" in TOOL_HANDLERS
