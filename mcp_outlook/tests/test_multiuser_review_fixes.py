"""
astra 보안 리뷰(spec/reviews/멀티유저_astra_2026-10-23.md) R02·R06·R07·R12 회귀.

- R02: 한도 밖 `top`·목록은 코루틴·세션·토큰 요청을 하나도 만들기 전에 거부되고,
  허용 범위에서는 페이지 작업이 동시 실행 수(3)만큼만 존재한다.
- R06: 부분 성공 응답의 오류 항목에 Graph 오류 원문(canary)이 없다.
- R07: OneDrive 폴더·파일명은 성분별 인코딩된 경로로만 URL 에 들어간다.
- R12: 발송 첨부는 검증한 handle(`open_for_read`)로 읽는다.
"""

import asyncio
import json

import aiohttp
import pytest

from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import bound

from mcp_outlook.graph_mail_id_batch import GraphMailIdBatch
from mcp_outlook.graph_mail_query import GraphMailQuery
from mcp_outlook.mail_attachment import BatchAttachmentHandler
from mcp_outlook.mail_attachment_storage import OneDriveStorageBackend
from mcp_outlook.mcp_server import handlers
from mcp_outlook.outlook_security import MAX_MESSAGE_IDS, MAX_TOP, check_top
from mcp_outlook.tests.multiuser_fakes import *  # noqa: F401,F403 - fixtures

G = "https://graph.microsoft.com/v1.0"
CANARY = "CANARY-7f3a alice@contoso.com C:\\Users\\alice\\secret.txt Bearer eyJhbGciOi"
GRAPH_404 = {"error": {"code": "ErrorItemNotFound", "message": f"The item was not found: {CANARY}"}}


def _no_canary(payload) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    assert "CANARY" not in text and "alice@contoso.com" not in text and "eyJhbGciOi" not in text, text


# ----------------------------------------------------------------------
# R02
# ----------------------------------------------------------------------
@pytest.mark.parametrize("top", [0, -1, MAX_TOP + 1, 10**12, "abc", True])
async def test_r02_huge_top_rejected_before_any_page_work(mu, alice, alice_paths, alice_tokens, monkeypatch, top):
    http = install_http(monkeypatch, lambda call: FakeResponse(200, {"value": []}))
    created = []
    original = GraphMailQuery._fetch_parallel_with_url

    async def _spy(self, *args, **kwargs):
        created.append(1)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(GraphMailQuery, "_fetch_parallel_with_url", _spy)
    query = GraphMailQuery(token_provider=alice_tokens, paths=alice_paths)
    with bound(alice), pytest.raises(ToolExecutionError) as err:
        await query.query_url(user_email=ALICE_EMAIL, url=f"{G}/me/messages", top=top)
    assert err.value.payload["error"] == "invalid_argument"
    assert err.value.payload["argument"] == "top"
    assert alice_tokens.calls == []           # 토큰도 요청하지 않았다
    assert http.sessions == 0 and http.calls == []
    assert created == []                      # 페이지 조회 함수에 들어가지도 않았다


async def test_r02_service_boundary_rejects_top_and_lists(mu, alice, alice_paths, alice_tokens, monkeypatch):
    http = install_http(monkeypatch, lambda call: FakeResponse(200, {"value": []}))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    too_many = [f"m{i}" for i in range(MAX_MESSAGE_IDS + 1)]
    with bound(alice):
        for coro in (
            svc.fetch_filter(user_email=ALICE_EMAIL, top=10**12),
            svc.fetch_search(user_email=ALICE_EMAIL, search_term="x", top=MAX_TOP + 1),
            svc.fetch_url(user_email=ALICE_EMAIL, url=f"{G}/me/messages", top=0),
            svc.process_with_download(user_email=ALICE_EMAIL, top=10**9),
            svc.batch_and_fetch(user_email=ALICE_EMAIL, message_ids=too_many),
            svc.fetch_attachments_metadata(user_email=ALICE_EMAIL, message_ids=too_many),
            svc.download_attachments(user_email=ALICE_EMAIL, message_attachment_ids=too_many),
            svc.send_mail(user_email=ALICE_EMAIL, to_recipients=["a@b"] * 501, subject="s", body="b"),
            svc.save_draft(user_email=ALICE_EMAIL, subject="s", body="b", attachments=["x"] * 21),
        ):
            with pytest.raises(ToolExecutionError) as err:
                await coro
            assert err.value.payload["error"] == "invalid_argument"
    assert alice_tokens.calls == [] and http.calls == []


async def test_r02_direct_fetch_guard_even_when_service_bypassed(mu, alice, alice_paths, alice_tokens, monkeypatch):
    http = install_http(monkeypatch, lambda call: FakeResponse(200, {"value": []}))
    query = GraphMailQuery(token_provider=alice_tokens, paths=alice_paths)
    with bound(alice), pytest.raises(ToolExecutionError):
        await query._fetch_parallel_with_url(ALICE_EMAIL, f"{G}/me/messages", 10**12)
    assert http.sessions == 0
    # 배치 클라이언트도 목록 상한을 스스로 지킨다
    batch = GraphMailIdBatch(token_provider=alice_tokens)
    with bound(alice), pytest.raises(ToolExecutionError):
        await batch.batch_fetch_by_ids(ALICE_EMAIL, [f"m{i}" for i in range(MAX_MESSAGE_IDS + 1)])
    assert alice_tokens.calls == []


async def test_r02_pages_are_created_incrementally(mu, alice, alice_paths, alice_tokens, monkeypatch):
    in_flight = {"now": 0, "max": 0, "urls": []}

    class _Resp(FakeResponse):
        async def __aenter__(self):
            in_flight["now"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["now"])
            await asyncio.sleep(0.001)
            return self

        async def __aexit__(self, *_):
            in_flight["now"] -= 1
            return False

    def _route(call):
        in_flight["urls"].append(call.url)
        skip = int(call.url.split("$skip=")[1])
        top = int(call.url.split("$top=")[1].split("&")[0])
        return _Resp(200, {"value": [{"id": f"m{skip + i}"} for i in range(min(150, top))]})

    install_http(monkeypatch, _route)
    query = GraphMailQuery(token_provider=alice_tokens, paths=alice_paths)
    with bound(alice):
        result = await query.query_url(user_email=ALICE_EMAIL, url=f"{G}/me/messages", top=MAX_TOP)
    assert result["pages_requested"] == 7
    assert len(in_flight["urls"]) == 7
    assert in_flight["max"] <= 3                     # 동시에 존재한 페이지 작업 ≤ 3
    assert len(result["value"]) == 1000               # 페이지 순서·중복 제거 유지
    assert check_top(MAX_TOP) == MAX_TOP


# ----------------------------------------------------------------------
# R06
# ----------------------------------------------------------------------
def _mixed_batch(ok_mail):
    return {
        "responses": [
            {"id": "1", "status": 200, "body": ok_mail},
            {"id": "2", "status": 404, "body": GRAPH_404},
        ]
    }


async def test_r06_partial_batch_errors_have_no_canary(mu, alice, alice_paths, alice_tokens, monkeypatch):
    ok_mail = mail_with_attachments("m1", [{"name": "a.pdf", "data": b"x"}])
    install_http(monkeypatch, lambda call: FakeResponse(200, _mixed_batch(ok_mail)))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()

    with bound(alice):
        meta = await svc.fetch_attachments_metadata(user_email=ALICE_EMAIL, message_ids=["m1", "m2"])
        saved = await svc.download_attachments(user_email=ALICE_EMAIL, message_attachment_ids=["m1", "m2"])
        fetched = await svc.batch_and_fetch(user_email=ALICE_EMAIL, message_ids=["m1", "m2"])

    for payload in (meta, saved, fetched):
        assert payload["status"] == "partial", payload.get("status")
        _no_canary(payload)
        assert payload["errors"], payload
    # 정상 메일 본문·첨부 내용은 그대로
    assert meta["value"][0]["subject"] == "Quarterly report"
    assert meta["value"][0]["body"]["content"] == "body text"
    assert fetched["value"][0]["id"] == "m1"
    # 오류 항목은 상태 코드 + 검증된 오류 코드만
    entry = meta["errors"][0]
    assert entry["message_id"] == "m2"
    assert entry["status_code"] == 404 and entry["graph_error_code"] == "ErrorItemNotFound"
    assert set(entry) <= {"message_id", "status_code", "graph_error_code"}
    assert fetched["errors"][0] == {"mail_id": "m2", "status_code": 404, "graph_error_code": "ErrorItemNotFound"}


async def test_r06_mode0_partial_batch_errors_have_no_canary(monkeypatch, tmp_path):
    """mode 0 도 같은 요약 규칙 — 모드에 따라 원문이 새지 않는다."""
    from unittest.mock import AsyncMock, MagicMock

    ok_mail = mail_with_attachments("m1", [{"name": "a.pdf", "data": b"x"}])
    install_http(monkeypatch, lambda call: FakeResponse(200, _mixed_batch(ok_mail)))
    provider = MagicMock()
    provider.validate_and_refresh_token = AsyncMock(return_value="tok")
    handler = BatchAttachmentHandler(base_directory=str(tmp_path), token_provider=provider)
    result = await handler.fetch_and_save("u@x", ["m1", "m2"])
    assert result["processed"] == 1 and len(result["errors"]) == 1
    _no_canary(result)
    batch = GraphMailIdBatch(token_provider=provider)
    deleted = await batch.batch_delete_by_ids("u@x", ["m1", "m2"])
    _no_canary(deleted)
    failed_m2 = [f for f in deleted["failed_items"] if f["mail_id"] == "m2"][0]
    assert failed_m2 == {"mail_id": "m2", "status_code": 404, "graph_error_code": "ErrorItemNotFound"}


async def test_r06_batch_level_failure_and_invalid_code_sanitized(mu, alice, alice_paths, alice_tokens, monkeypatch):
    body = {"error": {"code": f"Bad Code {CANARY}", "message": CANARY}}
    install_http(monkeypatch, lambda call: FakeResponse(429, text=json.dumps(body)))
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        result = await handler.fetch_metadata_only(ALICE_EMAIL, ["m1"])
    _no_canary(result)
    assert result["errors"] == [{"batch": 1, "status_code": 429}]  # 형식 검사에 실패한 코드는 버린다


async def test_r06_specific_attachment_failure_sanitized(mu, alice, alice_paths, alice_tokens, monkeypatch):
    install_http(monkeypatch, lambda call: FakeResponse(404, text=json.dumps(GRAPH_404)))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice):
        result = await svc.download_attachments(
            user_email=ALICE_EMAIL, message_attachment_ids=[{"message_id": "m1", "attachment_id": "a1"}]
        )
    assert result["status"] == "error"
    _no_canary(result)
    item = result["results"][0]
    assert item["success"] is False
    assert item["status_code"] == 404 and item["graph_error_code"] == "ErrorItemNotFound"
    assert "error" not in item


# ----------------------------------------------------------------------
# R07
# ----------------------------------------------------------------------
@pytest.mark.parametrize("folder", ["../x?y#z", "a/../b", "/Attachments/..", "a\\b", "%2e%2e/x"])
async def test_r07_traversal_folder_rejected_before_token(mu, alice, alice_paths, alice_tokens, monkeypatch, folder):
    http = install_http(monkeypatch, lambda call: FakeResponse(200, {}))
    with pytest.raises(SecurityError) as err:
        OneDriveStorageBackend(auth_manager=alice_tokens, user_email=ALICE_EMAIL, base_folder=folder)
    assert err.value.code == ErrorCode.NOT_FOUND
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice), pytest.raises(SecurityError):
        await svc.download_attachments(
            user_email=ALICE_EMAIL, message_attachment_ids=["m1"], storage_type="onedrive", onedrive_folder=folder
        )
    assert alice_tokens.calls == [] and http.calls == []


async def test_r07_special_chars_become_encoded_segments(mu, alice, alice_tokens, monkeypatch):
    def _route(call):
        if call.method == "GET":
            return FakeResponse(404)
        return FakeResponse(201, {"webUrl": "https://onedrive/x"})

    http = install_http(monkeypatch, _route)
    storage = OneDriveStorageBackend(auth_manager=alice_tokens, user_email=ALICE_EMAIL, base_folder="/Mail?x#y/sub")
    assert storage.base_folder == "Mail%3Fx%23y/sub"
    assert storage.child_path("a/b?c") == "Mail%3Fx%23y/sub/a%2Fb%3Fc"

    folder = await storage.create_folder_flat()
    saved = await storage.save_file(folder, "re?port#1.pdf", b"data", "application/pdf")
    assert saved == "https://onedrive/x"

    for call in http.calls:
        assert "?" not in call.url.split("/drive/root")[-1].replace("%3F", "") or ":/content" in call.url
        assert "#" not in call.url
        assert "/.." not in call.url
    create_bodies = [c.kwargs["json"]["name"] for c in http.calls if c.method == "POST" and "children" in c.url]
    assert create_bodies == ["Mail?x#y", "sub"]  # 본문에는 디코딩된 원래 이름
    upload = [c for c in http.calls if c.method == "PUT"][0]
    # sanitize_filename 이 `?` 를 떼고(기존 규칙), 남은 `#` 는 성분 인코딩된다
    assert upload.url.endswith("/drive/root:/Mail%3Fx%23y/sub/report%231.pdf:/content")


async def test_r07_upload_session_uses_encoded_path(mu, alice, alice_tokens, monkeypatch):
    presigned = "https://contoso-my.sharepoint.com/up?tempauth=abc"

    def _route(call):
        if call.url.endswith(":/createUploadSession"):
            return FakeResponse(200, {"uploadUrl": presigned})
        if call.url == presigned:
            return FakeResponse(201, {"webUrl": "https://onedrive/large"})
        return FakeResponse(404)

    http = install_http(monkeypatch, _route)
    storage = OneDriveStorageBackend(auth_manager=alice_tokens, user_email=ALICE_EMAIL, base_folder="A?b")
    big = b"x" * (OneDriveStorageBackend.SIMPLE_UPLOAD_MAX_SIZE + 1)
    assert await storage.save_file(storage.base_folder, "big#1.bin", big) == "https://onedrive/large"
    create = [c for c in http.calls if c.method == "POST"][0]
    assert create.url.endswith("/drive/root:/A%3Fb/big%231.bin:/createUploadSession")
    assert create.kwargs["json"]["item"]["name"] == "big#1.bin"


# ----------------------------------------------------------------------
# R12
# ----------------------------------------------------------------------
async def test_r12_send_attachment_read_via_validated_handle(mu, alice, alice_paths, alice_tokens, monkeypatch):
    import mcp_common.secure_files as secure_files

    (alice_paths.uploads / "note.txt").write_bytes(b"hello")
    opened = []
    real = secure_files.open_for_read

    def _spy(path, root):
        opened.append((path, root))
        return real(path, root)

    monkeypatch.setattr(secure_files, "open_for_read", _spy)
    install_http(monkeypatch, lambda call: FakeResponse(202))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice):
        ok = await svc.send_mail(
            user_email=ALICE_EMAIL, to_recipients=["x@fabrikam.com"], subject="s", body="b",
            attachments=["uploads/note.txt"],
        )
    assert ok["status"] == "success", ok
    assert len(opened) == 1 and opened[0][1] == alice_paths.files
    assert opened[0][0].name == "note.txt"
