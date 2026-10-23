"""
Outlook 멀티유저 — 로컬 파일 격리 (spec/spec_멀티유저.md ②-7.3·7.4, F02/F03/F04).

- 원격 첨부 이름(`../..`·절대경로·예약명·ADS)은 사용자 `files/downloads/outlook/` 밖으로 못 나간다.
- 호출자 저장 위치는 `resolve_safe_path` 관문 + 사용자 `files/` 경계.
- A·B 가 같은 이름을 동시에 받아도 파일이 분리되고, 같은 사용자의 동시 저장도 덮어쓰지 않는다.
- 응답 경로는 `files/` 기준 상대경로, 로그에 이메일·제목·파일명·경로·토큰이 없다.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import bound

from mcp_outlook.mail_attachment import BatchAttachmentHandler
from mcp_outlook.mail_attachment_user_storage import UserLocalStorageBackend
from mcp_outlook.mcp_server import handlers
from mcp_outlook.outlook_file_policy import resolve_save_dir
from mcp_outlook.tests.multiuser_fakes import *  # noqa: F401,F403 - fixtures

EVIL_NAMES = [
    "../../x",
    "..\\..\\evil.bat",
    "C:\\Windows\\System32\\drivers\\etc\\hosts",
    "/etc/passwd",
    "CON",
    "a:b.txt",
    "..",
    "trailing. ",
]


def _inside(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


async def test_f02_remote_names_stay_in_user_downloads(mu, alice, alice_paths, alice_tokens, monkeypatch, caplog):
    attachments = [{"name": n, "data": f"payload-{i}".encode()} for i, n in enumerate(EVIL_NAMES)]
    mail = mail_with_attachments("m1", attachments, subject="..\\..\\..\\escape")
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))

    caplog.set_level(logging.DEBUG)
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        result = await handler.fetch_and_save(ALICE_EMAIL, ["m1"])

    assert result["success"] is True, result["errors"]
    downloads = alice_paths.downloads_for("outlook")
    created = user_files(alice_paths)
    assert len(created) == len(EVIL_NAMES) + 1  # 첨부 + mail_content.txt
    for path in created:
        assert _inside(path, downloads)
    # 데이터 루트 전체에서 사용자 영역 밖으로 새어 나간 파일이 없다
    for path in mu.rglob("*"):
        if path.is_file():
            assert _inside(path, alice_paths.root)
    # 응답은 files/ 기준 상대경로
    refs = result["saved_attachments"] + result["saved_mails"] + result["saved_folders"]
    assert refs
    for ref in refs:
        assert not Path(ref).is_absolute()
        assert ref.startswith("downloads/outlook/")
        assert _inside(alice_paths.files / ref, downloads)
    # 로그에 민감 값 없음
    for secret in (ALICE_EMAIL, alice_tokens.token, str(mu), "escape", "passwd", "evil.bat", "sender@fabrikam.com"):
        assert secret not in caplog.text


async def test_f02_specific_attachment_ids_and_names(mu, alice, alice_paths, alice_tokens, monkeypatch):
    def _route(call):
        if "/attachments/" in call.url:
            return FakeResponse(200, {
                "name": "../../../../outside.txt",
                "contentBytes": b64(b"secret"),
                "@odata.type": "#microsoft.graph.fileAttachment",
            })
        return FakeResponse(404, text='{"error":{"code":"ErrorItemNotFound"}}')

    http = install_http(monkeypatch, _route)
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        result = await handler.fetch_specific_attachments(
            ALICE_EMAIL, [{"message_id": "../../../users/bob@contoso.com", "attachment_id": "../a"}]
        )

    assert result["downloaded"] == 1, result
    entry = result["results"][0]
    assert not Path(entry["file_path"]).is_absolute()
    assert entry["file_path"].startswith("downloads/outlook/")
    for path in user_files(alice_paths):
        assert _inside(path, alice_paths.downloads_for("outlook"))
    # message_id·attachment_id 는 인코딩돼 Graph 경로를 바꾸지 못한다
    for call in http.calls:
        assert "/../" not in call.url
        assert "/users/bob@" not in call.url
        assert call.kwargs.get("allow_redirects") is False


@pytest.mark.parametrize("save_directory", ["../../outside", "..\\..\\outside", "C:\\Windows\\Temp", "\\\\server\\share", "a:stream"])
async def test_caller_save_directory_outside_files_rejected(
    mu, alice, alice_paths, alice_tokens, monkeypatch, save_directory
):
    http = install_http(monkeypatch, lambda call: FakeResponse(500))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice), pytest.raises(SecurityError) as err:
        await svc.download_attachments(
            user_email=ALICE_EMAIL, message_attachment_ids=["m1"], save_directory=save_directory
        )
    assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
    assert http.calls == []  # 경로 거부가 Graph 호출보다 먼저


async def test_caller_cannot_target_other_users_files(mu, alice, bob, alice_paths, bob_paths, alice_tokens):
    with bound(alice), pytest.raises(SecurityError) as err:
        BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths, base_directory=str(bob_paths.files))
    assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
    with bound(alice), pytest.raises(SecurityError):
        resolve_save_dir(alice_paths, str(alice_paths.db_dir))  # 자기 db/ 도 파일 영역이 아니다


async def test_caller_relative_directory_inside_files(mu, alice, alice_paths, alice_tokens, monkeypatch):
    mail = mail_with_attachments("m1", [{"name": "report.pdf", "data": b"pdf"}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice):
        result = await svc.download_attachments(
            user_email=ALICE_EMAIL, message_attachment_ids=["m1"], save_directory="projects/q3", flat_folder=True
        )
    assert result["status"] == "success", result
    assert result["saved_attachments"] == ["projects/q3/report.pdf"]
    assert (alice_paths.files / "projects" / "q3" / "report.pdf").read_bytes() == b"pdf"


async def test_f03_same_filename_two_users_concurrently(
    mu, alice, bob, alice_paths, bob_paths, alice_tokens, bob_tokens, monkeypatch
):
    mail_a = mail_with_attachments("m1", [{"name": "report.pdf", "data": b"ALICE-DATA"}])
    mail_b = mail_with_attachments("m1", [{"name": "report.pdf", "data": b"BOB-DATA"}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail_a, bob_tokens.token: mail_b}))

    async def _run(principal, paths, tokens, email):
        with bound(principal):
            handler = BatchAttachmentHandler(token_provider=tokens, paths=paths)
            await asyncio.sleep(0)
            return await handler.fetch_and_save(email, ["m1"], include_body=False)

    res_a, res_b = await asyncio.gather(
        _run(alice, alice_paths, alice_tokens, ALICE_EMAIL),
        _run(bob, bob_paths, bob_tokens, BOB_EMAIL),
    )
    # 같은 상대 경로지만 서로 다른 사용자 루트의 서로 다른 파일
    assert res_a["saved_attachments"] == res_b["saved_attachments"]
    ref = res_a["saved_attachments"][0]
    assert (alice_paths.files / ref).read_bytes() == b"ALICE-DATA"
    assert (bob_paths.files / ref).read_bytes() == b"BOB-DATA"
    assert [p.name for p in user_files(alice_paths)] == ["report.pdf"]
    assert [p.name for p in user_files(bob_paths)] == ["report.pdf"]


async def test_f04_same_user_concurrent_saves_do_not_overwrite(mu, alice, alice_paths):
    storage = UserLocalStorageBackend(alice_paths, resolve_save_dir(alice_paths, None))
    folder = await storage.create_folder(mail_with_attachments("m1", []))

    def _save(i):
        return asyncio.run(storage.save_file(folder, "same.pdf", f"content-{i}".encode()))

    with ThreadPoolExecutor(max_workers=16) as pool:
        refs = list(pool.map(_save, range(40)))

    assert all(refs) and len(set(refs)) == 40
    contents = sorted((alice_paths.files / r).read_bytes() for r in refs)
    assert contents == sorted(f"content-{i}".encode() for i in range(40))


async def test_f04_same_mail_processed_twice_keeps_both(mu, alice, alice_paths, alice_tokens, monkeypatch):
    mail = mail_with_attachments("m1", [{"name": "same.pdf", "data": b"v"}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))

    async def _once():
        with bound(alice):
            handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
            return await handler.fetch_and_save(ALICE_EMAIL, ["m1"], skip_duplicates=False)

    first, second = await asyncio.gather(_once(), _once())
    refs = first["saved_attachments"] + second["saved_attachments"] + first["saved_mails"] + second["saved_mails"]
    assert len(set(refs)) == 4  # 첨부 2 + 본문 2, 덮어쓴 파일 없음
    assert len(user_files(alice_paths)) == 4
    with bound(alice):
        assert handler_store_ids(alice_paths) == ["m1"]


def handler_store_ids(paths):
    from mcp_outlook.storage_schema import OutlookMetadataStore

    return OutlookMetadataStore.for_paths(paths).get_processed_message_ids()


async def test_send_attachments_limited_to_user_files(mu, alice, alice_paths, alice_tokens, monkeypatch):
    (alice_paths.files / "uploads" / "note.txt").write_bytes(b"hello")
    alice_paths.auth_db.write_bytes(b"not-a-real-db")
    sent = []

    def _route(call):
        sent.append(call)
        return FakeResponse(202)

    install_http(monkeypatch, _route)
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice):
        ok = await svc.send_mail(
            user_email=ALICE_EMAIL, to_recipients=["x@fabrikam.com"], subject="s", body="b",
            attachments=["uploads/note.txt"],
        )
        assert ok["status"] == "success", ok
        assert ok["attachments"] == ["note.txt"]
        for bad in (str(alice_paths.auth_db), "../auth/auth.db", "../../" + "x", str(mu / "system" / "x")):
            with pytest.raises(SecurityError) as err:
                await svc.send_mail(
                    user_email=ALICE_EMAIL, to_recipients=["x@fabrikam.com"], subject="s", body="b",
                    attachments=[bad],
                )
            assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
        missing = await svc.save_draft(user_email=ALICE_EMAIL, subject="s", body="b", attachments=["uploads/none.txt"])
    assert missing["status"] == "error"
    assert str(mu) not in missing["error"]
    assert len(sent) == 1  # 거부된 요청은 Graph 로 나가지 않았다
