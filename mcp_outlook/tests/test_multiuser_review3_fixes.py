"""
astra 3차 보안 리뷰(spec/reviews/멀티유저_astra_3차_2026-10-23.md) Outlook 잔여 항목 회귀.

- N08 gap 1: 특정 첨부 다운로드도 첨부 1건 상한(`MAX_ATTACHMENT_BYTES`)을 decode 전에 적용한다.
- N08 gap 2: 사용자 누적 quota 는 호출자 지정 저장 폴더를 포함한 `files/` 전체를 센다.
- N08 gap 3: `Content-Length` 가 있으면 본문을 읽기 전에 거부한다.
- P01: converter 는 사용자별 슬롯을 쥔 실제 스레드로 돌고, 슬롯 소진은 `overloaded`,
  `MailService.close()` 는 hard cap 까지 join 한 뒤 남으면 실패를 올린다.
- N06: mode 0 `MailMetadataManager` 는 매 쓰기 직전 이전 잠금을 다시 확인한다.
"""

import asyncio
import json
import time

import pytest

from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import MIGRATION_LOCK_NAME
from mcp_common.testing import bound

from mcp_outlook import conversion_workers
from mcp_outlook import outlook_security as limits
from mcp_outlook.mail_attachment import BatchAttachmentHandler, MailMetadataManager
from mcp_outlook.mcp_server import handlers
from mcp_outlook.tests.multiuser_fakes import *  # noqa: F401,F403 - fixtures


def _attachment_route(name: str, data: bytes, headers=None):
    def _route(call):
        if "/attachments/" in call.url:
            resp = FakeResponse(200, {
                "name": name, "contentBytes": b64(data), "@odata.type": "#microsoft.graph.fileAttachment",
            })
            if headers:
                resp.headers.update(headers)
            return resp
        return FakeResponse(404, text='{"error":{"code":"ErrorItemNotFound"}}')

    return _route


# ----------------------------------------------------------------------
# N08 gap 1
# ----------------------------------------------------------------------
async def test_gap1_specific_attachment_per_item_limit(mu, alice, alice_paths, alice_tokens, monkeypatch):
    monkeypatch.setattr(limits, "MAX_ATTACHMENT_BYTES", 100)
    monkeypatch.setattr(limits, "MAX_REQUEST_ATTACHMENT_BYTES", 10_000)  # 요청 예산은 넉넉 — 1건 상한만 걸린다
    install_http(monkeypatch, _attachment_route("big.bin", b"x" * 200))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice):
        result = await svc.download_attachments(
            user_email=ALICE_EMAIL, message_attachment_ids=[{"message_id": "m1", "attachment_id": "a1"}]
        )
    assert result["status"] == "error"
    item = result["results"][0]
    assert item["success"] is False
    assert item["error"] == "attachment_too_large" and item["limit_bytes"] == 100
    assert user_files(alice_paths) == []
    assert result["errors"][0]["error"] == "attachment_too_large"


async def test_gap1_specific_attachment_request_budget(mu, alice, alice_paths, alice_tokens, monkeypatch):
    monkeypatch.setattr(limits, "MAX_ATTACHMENT_BYTES", 1000)
    monkeypatch.setattr(limits, "MAX_REQUEST_ATTACHMENT_BYTES", 150)
    install_http(monkeypatch, _attachment_route("f.bin", b"x" * 100))
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        result = await handler.fetch_specific_attachments(
            ALICE_EMAIL,
            [{"message_id": "m1", "attachment_id": "a1"}, {"message_id": "m1", "attachment_id": "a2"}],
            flat_folder=True,
        )
    assert result["downloaded"] == 1 and result["failed"] == 1
    assert result["results"][1]["error"] == "request_attachment_budget_exceeded"
    assert result["results"][1]["limit_bytes"] == 150


# ----------------------------------------------------------------------
# N08 gap 2
# ----------------------------------------------------------------------
async def test_gap2_quota_covers_caller_directory_and_whole_files_root(mu, alice, alice_paths, alice_tokens, monkeypatch):
    monkeypatch.setattr(limits, "MAX_USER_DOWNLOAD_BYTES", 100)
    (alice_paths.uploads / "other-domain.bin").write_bytes(b"u" * 60)  # downloads/outlook 밖의 기존 사용량
    mail = mail_with_attachments("m1", [{"name": "a.bin", "data": b"a" * 50}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice):
        with pytest.raises(ToolExecutionError) as err:
            await svc.download_attachments(
                user_email=ALICE_EMAIL, message_attachment_ids=["m1"],
                save_directory="projects/q3", flat_folder=True, include_body=False,
            )
        assert err.value.payload["error"] == "quota_exceeded"
        assert not (alice_paths.files / "projects" / "q3" / "a.bin").exists()

        # 30바이트면 60 + 30 ≤ 100 — 통과. 그 뒤 같은 요청 범위에서 또 쓰면 누적된다.
        small = mail_with_attachments("m2", [{"name": "b.bin", "data": b"b" * 30}])
        install_http(monkeypatch, batch_router({alice_tokens.token: small}))
        ok = await svc.download_attachments(
            user_email=ALICE_EMAIL, message_attachment_ids=["m2"],
            save_directory="projects/q3", flat_folder=True, include_body=False,
        )
    assert ok["status"] == "success"
    assert (alice_paths.files / "projects" / "q3" / "b.bin").read_bytes() == b"b" * 30


# ----------------------------------------------------------------------
# N08 gap 3
# ----------------------------------------------------------------------
async def test_gap3_content_length_rejects_before_reading_body(mu, alice, alice_paths, alice_tokens, monkeypatch):
    json_calls = []

    class _Resp(FakeResponse):
        async def json(self):
            json_calls.append(1)
            return await super().json()

    huge = str(limits.MAX_REQUEST_ATTACHMENT_BYTES * 2)

    def _batch(call):
        if call.url.endswith("/$batch"):
            resp = _Resp(200, {"responses": []})
            resp.headers["Content-Length"] = huge
            return resp
        if "/attachments/" in call.url:
            resp = _Resp(200, {"name": "x", "contentBytes": b64(b"x")})
            resp.headers["Content-Length"] = str(limits.MAX_ATTACHMENT_BYTES * 2)
            return resp
        return FakeResponse(404)

    install_http(monkeypatch, _batch)
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        meta = await handler.fetch_metadata_only(ALICE_EMAIL, ["m1"])
        saved = await handler.fetch_and_save(ALICE_EMAIL, ["m1"])
        specific = await handler.fetch_specific_attachments(
            ALICE_EMAIL, [{"message_id": "m1", "attachment_id": "a1"}], flat_folder=True
        )
    assert json_calls == []  # 본문을 읽지 않았다
    assert meta["errors"] == [{"batch": 1, "error": "response_too_large", "limit_bytes": limits.MAX_REQUEST_ATTACHMENT_BYTES}]
    assert saved["errors"][0]["error"] == "response_too_large"
    assert specific["results"][0]["error"] == "response_too_large"
    assert specific["results"][0]["limit_bytes"] == limits.MAX_ATTACHMENT_BYTES


async def test_gap3_without_content_length_body_is_read(mu, alice, alice_paths, alice_tokens, monkeypatch):
    mail = mail_with_attachments("m1", [{"name": "a.bin", "data": b"a"}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        result = await handler.fetch_and_save(ALICE_EMAIL, ["m1"], include_body=False)
    assert result["processed"] == 1 and result["errors"] == []


# ----------------------------------------------------------------------
# P01
# ----------------------------------------------------------------------
@pytest.fixture
def slow_converter(monkeypatch):
    from mcp_outlook import mail_attachment as ma
    from mcp_outlook.mail_attachment_converter import ConversionPipeline

    class _Slow(ConversionPipeline):
        def convert(self, content, filename):
            time.sleep(0.4)
            return "converted", None

    conversion_workers.reset_registry_for_tests()
    monkeypatch.setattr(limits, "CONVERSION_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(limits, "CONVERSION_SLOT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(limits, "MAX_CONVERSION_WORKERS", 2)
    monkeypatch.setattr(conversion_workers, "HARD_JOIN_CAP_SECONDS", 0.02)
    monkeypatch.setattr(ma, "get_conversion_pipeline", lambda: _Slow())
    yield
    time.sleep(0.6)  # 살아 있던 스레드가 끝나도록 — 다음 테스트에 새지 않게
    conversion_workers.reset_registry_for_tests()


async def test_p01_slots_overloaded_and_close_reports_live_threads(
    mu, alice, alice_paths, alice_tokens, monkeypatch, slow_converter
):
    mail = mail_with_attachments("m1", [{"name": f"doc{i}.txt", "data": b"plain"} for i in range(3)])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()

    started = time.monotonic()
    with bound(alice):
        with pytest.raises(SecurityError) as err:  # 세 번째 변환은 슬롯이 없다
            await svc.download_attachments(
                user_email=ALICE_EMAIL, message_attachment_ids=["m1"], convert_to_txt=True, include_body=False
            )
    assert err.value.code == ErrorCode.OVERLOADED
    assert time.monotonic() - started < 0.35  # timeout 뒤 스레드를 기다리지 않았다

    # timeout 난 두 스레드가 아직 슬롯을 쥐고 있다 — 서비스 범위 그룹이 그 스레드를 안다
    assert conversion_workers.live_workers(alice.user_key) == 2
    assert len(svc.workers.live()) == 2

    # close 는 hard cap 까지 join 하고, 그래도 살아 있으면 실패를 올린다 (풀이 drain 실패로 기록)
    with pytest.raises(RuntimeError):
        await svc.close()

    # 같은 사용자의 새 서비스도 같은 슬롯을 본다 (프로세스 전역)
    svc2 = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc2.initialize()
    one = mail_with_attachments("m2", [{"name": "doc.txt", "data": b"plain"}])
    install_http(monkeypatch, batch_router({alice_tokens.token: one}))
    with bound(alice):
        with pytest.raises(SecurityError) as err2:  # 구 서비스의 스레드가 슬롯을 쥐고 있어 새 서비스도 overloaded
            await svc2.download_attachments(
                user_email=ALICE_EMAIL, message_attachment_ids=["m2"], convert_to_txt=True, include_body=False
            )
    assert err2.value.code == ErrorCode.OVERLOADED
    assert conversion_workers.live_workers(alice.user_key) == 2  # 새 스레드는 만들어지지 않았다

    # 스레드가 실제로 끝나면 슬롯이 돌아오고 close 도 성공한다
    await asyncio.sleep(0.6)
    assert conversion_workers.live_workers(alice.user_key) == 0
    assert svc.workers.live() == []
    await svc.close()
    await svc2.close()


async def test_p01_overloaded_is_tool_error_not_partial(mu, alice, alice_paths, alice_tokens, monkeypatch, slow_converter):
    """슬롯 소진은 부분 결과로 감추지 않고 재시도 가능한 overloaded 로 올라간다."""
    conversion_workers.slots_for(alice.user_key, 2)
    held = conversion_workers.slots_for(alice.user_key, 2)
    assert held.acquire(0.01) and held.acquire(0.01)  # 다른 요청이 슬롯 2개를 쥔 상태
    try:
        mail = mail_with_attachments("m1", [{"name": "doc.txt", "data": b"plain"}])
        install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
        with bound(alice):
            handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
            with pytest.raises(SecurityError) as err:
                await handler.fetch_and_save(ALICE_EMAIL, ["m1"], convert_to_txt=True, include_body=False)
        assert err.value.code == ErrorCode.OVERLOADED
        assert user_files(alice_paths) == []
    finally:
        held.release()
        held.release()


async def test_p01_mode0_uses_legacy_slot_key(monkeypatch, tmp_path, slow_converter):
    from unittest.mock import AsyncMock, MagicMock

    mail = mail_with_attachments("m1", [{"name": "doc.txt", "data": b"plain"}])
    install_http(monkeypatch, lambda call: FakeResponse(200, {"responses": [{"id": "1", "status": 200, "body": mail}]}))
    provider = MagicMock()
    provider.validate_and_refresh_token = AsyncMock(return_value="tok")
    handler = BatchAttachmentHandler(base_directory=str(tmp_path), token_provider=provider)
    result = await handler.fetch_and_save("u@x", ["m1"], convert_to_txt=True, include_body=False)
    assert result["processed"] == 1 and result["converted_files"] == []  # timeout → 원본 저장
    assert conversion_workers.live_workers(None) == 1
    assert len(handler.workers.live()) == 1


# ----------------------------------------------------------------------
# N06
# ----------------------------------------------------------------------
def test_n06_legacy_metadata_rechecks_freeze_before_each_write(tmp_path, monkeypatch):
    monkeypatch.delenv("MS365_MIGRATION_OVERRIDE", raising=False)
    metadata_file = tmp_path / "mail_metadata.json"
    manager = MailMetadataManager(str(metadata_file))
    mail = {"subject": "s", "from": {"emailAddress": {"address": "x@y"}}, "attachments": []}
    manager.add_processed_mail("m1", mail, "/p", [])
    before = metadata_file.read_text(encoding="utf-8")

    (tmp_path / MIGRATION_LOCK_NAME).write_text("{}", encoding="utf-8")  # 열린 뒤 이전이 시작됐다
    with pytest.raises(ToolExecutionError) as err:
        manager.add_processed_mail("m2", mail, "/p", [])
    assert err.value.payload["error"] == "legacy_store_frozen"
    assert metadata_file.read_text(encoding="utf-8") == before  # 파일은 그대로
    assert not manager.is_duplicate("m2") or "m2" not in json.loads(before).get("processed_messages", {})
