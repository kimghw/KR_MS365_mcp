"""
astra 2차 보안 리뷰(spec/reviews/멀티유저_astra_2차_2026-10-23.md) N01·N05·N08 회귀.

- N01: 토큰은 Graph 요청 1건 직전마다 공급자에서 새로 얻는다. 첫 GET 뒤 폐기되면 폴더 POST 0건.
- N05: 업로드 세션 URL 은 공용 `check_presigned_url` — 사설·loopback·비표준 포트·`localhost.` 거부,
  bearer 미부착, redirect 미추종, 3xx 는 오류(청크 재전송 없음). `beta` 메일 URL 거부.
- N08: 첨부 decode 1건·요청 예산, 변환 deadline, 사용자 누적 quota, 발송 첨부 제한 읽기.
"""

import asyncio
import json
import time

import pytest

from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import bound

from mcp_outlook import outlook_security as limits
from mcp_outlook.graph_mail_id_batch import GraphMailIdBatch
from mcp_outlook.graph_mail_query import GraphMailQuery
from mcp_outlook.mail_attachment import BatchAttachmentHandler
from mcp_outlook.mail_attachment_storage import OneDriveStorageBackend
from mcp_outlook.mail_attachment_user_storage import UserLocalStorageBackend
from mcp_outlook.mcp_server import handlers
from mcp_outlook.outlook_file_policy import resolve_save_dir
from mcp_outlook.outlook_security import check_mail_query_url
from mcp_outlook.tests.multiuser_fakes import *  # noqa: F401,F403 - fixtures

G = "https://graph.microsoft.com/v1.0"


class RevokingProvider:
    """`revoked` 가 켜진 뒤의 모든 토큰 요청에 `account_inactive` 를 돌려주는 공급자."""

    def __init__(self, principal):
        self.principal = principal
        self.token = "tok-" + principal.user_key[:8]
        self.revoked = False
        self.acquires = 0

    @property
    def user_key(self):
        return self.principal.user_key

    async def get_graph_token(self, *, minimum_ttl_seconds: int = 120):
        raise NotImplementedError

    async def validate_and_refresh_token(self, email=None, auto_reauth=False):
        self.acquires += 1
        if self.revoked:
            raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)
        return self.token

    async def close(self):
        return None


# ----------------------------------------------------------------------
# N01
# ----------------------------------------------------------------------
async def test_n01_revoked_between_first_get_and_folder_post(mu, alice, alice_paths, monkeypatch):
    """공개 경로(mail_attachment_download → OneDrive 폴더 생성): 첫 GET 응답 시점에 폐기 → POST 0건."""
    provider = RevokingProvider(alice)
    mail = mail_with_attachments("m1", [{"name": "a.pdf", "data": b"x"}])

    def _route(call):
        if call.method == "POST" and call.url.endswith("/$batch"):
            return FakeResponse(200, {"responses": [{"id": "1", "status": 200, "body": mail}]})
        if call.method == "GET" and "/drive/root:" in call.url:
            provider.revoked = True  # 첫 폴더 확인 GET 을 처리하는 동안 키가 폐기됐다
            return FakeResponse(404, text='{"error":{"code":"itemNotFound"}}')
        return FakeResponse(201, {"id": "f1", "webUrl": "https://onedrive/x"})

    http = install_http(monkeypatch, _route)
    svc = await handlers.create_service(alice, alice_paths, provider)
    await svc.initialize()
    with bound(alice), pytest.raises(SecurityError) as err:
        await svc.download_attachments(
            user_email=ALICE_EMAIL, message_attachment_ids=["m1"],
            storage_type="onedrive", onedrive_folder="/Attachments",
        )
    assert err.value.code == ErrorCode.ACCOUNT_INACTIVE
    methods = [(c.method, "children" in c.url or "content" in c.url) for c in http.calls]
    assert [c.method for c in http.calls if c.method == "GET"] == ["GET"]
    assert not [c for c in http.calls if c.method in ("POST", "PUT") and "/drive/" in c.url], methods
    assert provider.acquires >= 3  # 배치·초기 확인·GET 뒤 POST 직전 재획득에서 끊겼다


async def test_n01_storage_reacquires_before_every_request(mu, alice, monkeypatch):
    provider = RevokingProvider(alice)
    seen = []

    def _route(call):
        seen.append((call.method, call.authorization))
        if call.method == "GET":
            return FakeResponse(404)
        return FakeResponse(201, {"webUrl": "https://onedrive/x"})

    install_http(monkeypatch, _route)
    storage = OneDriveStorageBackend(auth_manager=provider, user_email=ALICE_EMAIL, base_folder="A/B")
    await storage.create_folder_flat()
    await storage.save_file(storage.base_folder, "f.bin", b"data")
    # 초기 확인 2회 + GET 2 + POST 2 + PUT 1 = 7회, 요청마다 1회씩
    requests_sent = len(seen)
    assert requests_sent == 5
    assert provider.acquires == requests_sent + 2
    assert all(auth == f"Bearer {provider.token}" for _, auth in seen)


async def test_n01_pagination_and_batches_reacquire_per_request(mu, alice, alice_paths, monkeypatch):
    provider = RevokingProvider(alice)

    def _route(call):
        if call.url.endswith("/$batch"):
            return FakeResponse(200, {"responses": []})
        skip = int(call.url.split("$skip=")[1])
        if skip >= 150:
            provider.revoked = True  # 2페이지 응답 중 폐기
        return FakeResponse(200, {"value": [{"id": f"m{skip}"}]})

    http = install_http(monkeypatch, _route)
    query = GraphMailQuery(token_provider=provider, paths=alice_paths)
    with bound(alice):
        with pytest.raises(SecurityError) as err:
            await query.query_url(user_email=ALICE_EMAIL, url=f"{G}/me/messages", top=450)
    assert err.value.code == ErrorCode.ACCOUNT_INACTIVE
    assert len(http.calls) <= 3  # 폐기 뒤 새 페이지 요청은 없다

    provider = RevokingProvider(alice)
    batch = GraphMailIdBatch(token_provider=provider)
    http = install_http(monkeypatch, _route)
    with bound(alice):
        await batch.batch_fetch_by_ids(ALICE_EMAIL, [f"m{i}" for i in range(45)])  # 3 배치
    assert provider.acquires == 1 + 3  # 초기 확인 + 배치마다 재획득


async def test_n01_chunk_upload_rechecks_identity_before_each_chunk(mu, alice, monkeypatch):
    provider = RevokingProvider(alice)
    presigned = "https://contoso-my.sharepoint.com/up?tempauth=abc"
    puts = []

    def _route(call):
        if call.url.endswith(":/createUploadSession"):
            return FakeResponse(200, {"uploadUrl": presigned})
        if call.url == presigned and call.method == "PUT":
            puts.append(call)
            provider.revoked = True  # 첫 청크 뒤 폐기
            return FakeResponse(202)
        return FakeResponse(404)

    http = install_http(monkeypatch, _route)
    storage = OneDriveStorageBackend(auth_manager=provider, user_email=ALICE_EMAIL, base_folder="A")
    big = b"x" * (OneDriveStorageBackend.CHUNK_SIZE * 2 + 1)  # 3 청크
    with pytest.raises(SecurityError) as err:
        await storage.save_file(storage.base_folder, "big.bin", big)
    assert err.value.code == ErrorCode.ACCOUNT_INACTIVE
    assert len(puts) == 1  # 폐기 뒤 두 번째 청크는 나가지 않았다
    assert all(c.authorization is None for c in puts)


# ----------------------------------------------------------------------
# N05
# ----------------------------------------------------------------------
@pytest.mark.parametrize("upload_url", [
    "https://127.0.0.1:8443/upload",
    "https://127.0.0.1/upload",
    "https://localhost./content",
    "https://localhost/content",
    "https://10.0.0.5/up",
    "https://[::1]/up",
    "https://169.254.169.254/latest/meta-data",
    "https://contoso-my.sharepoint.com:8443/up",
    "https://user:pw@contoso-my.sharepoint.com/up",
    "http://contoso-my.sharepoint.com/up",
    "https://internal/up",
])
async def test_n05_private_or_nonstandard_upload_url_rejected(mu, alice, alice_tokens, monkeypatch, upload_url):
    def _route(call):
        if call.url.endswith(":/createUploadSession"):
            return FakeResponse(200, {"uploadUrl": upload_url})
        return FakeResponse(201, {})

    http = install_http(monkeypatch, _route)
    storage = OneDriveStorageBackend(auth_manager=alice_tokens, user_email=ALICE_EMAIL, base_folder="A")
    session = __import__("aiohttp").ClientSession()
    with pytest.raises(SecurityError) as err:
        await storage._upload_large(session, "A/a.bin", b"x", "a.bin")
    assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
    assert [c.method for c in http.calls] == ["POST"]  # 세션 생성만, 본문 전송 없음


async def test_n05_dns_to_private_address_rejected(mu, alice, alice_tokens, monkeypatch):
    import ipaddress

    from mcp_common import graph_url_policy

    monkeypatch.setattr(graph_url_policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("10.1.2.3")])
    install_http(monkeypatch, lambda call: FakeResponse(200, {"uploadUrl": "https://evil-but-public-looking.example/up"}))
    storage = OneDriveStorageBackend(auth_manager=alice_tokens, user_email=ALICE_EMAIL, base_folder="A")
    with pytest.raises(SecurityError):
        await storage._upload_large(__import__("aiohttp").ClientSession(), "A/a.bin", b"x", "a.bin")


async def test_n05_redirect_on_chunk_is_error_without_resend(mu, alice, alice_tokens, monkeypatch):
    presigned = "https://contoso-my.sharepoint.com/up?tempauth=abc"
    calls = []

    def _route(call):
        calls.append(call)
        if call.url.endswith(":/createUploadSession"):
            return FakeResponse(200, {"uploadUrl": presigned})
        if call.method == "PUT":
            resp = FakeResponse(302)
            resp.headers["Location"] = "https://evil.example/steal"
            return resp
        return FakeResponse(204)

    install_http(monkeypatch, _route)
    storage = OneDriveStorageBackend(auth_manager=alice_tokens, user_email=ALICE_EMAIL, base_folder="A")
    result = await storage._upload_large(__import__("aiohttp").ClientSession(), "A/a.bin", b"x" * 10, "a.bin")
    assert result is None
    puts = [c for c in calls if c.method == "PUT"]
    assert len(puts) == 1  # 3xx 뒤 재시도(본문 재전송) 없음
    assert puts[0].kwargs.get("allow_redirects") is False and puts[0].authorization is None
    assert all("evil.example" not in c.url for c in calls)
    deletes = [c for c in calls if c.method == "DELETE"]
    assert len(deletes) == 1 and deletes[0].authorization is None and deletes[0].kwargs.get("allow_redirects") is False


def test_n05_beta_mail_url_rejected(mu, alice):
    with bound(alice):
        with pytest.raises(SecurityError) as err:
            check_mail_query_url(f"https://graph.microsoft.com/beta/me/messages")
        assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
        check_mail_query_url(f"{G}/me/messages")


# ----------------------------------------------------------------------
# N08
# ----------------------------------------------------------------------
async def test_n08_per_attachment_and_per_request_limits(mu, alice, alice_paths, alice_tokens, monkeypatch):
    monkeypatch.setattr(limits, "MAX_ATTACHMENT_BYTES", 100)
    monkeypatch.setattr(limits, "MAX_REQUEST_ATTACHMENT_BYTES", 150)
    mail = mail_with_attachments("m1", [
        {"name": "ok1.bin", "data": b"a" * 80},
        {"name": "too-big.bin", "data": b"b" * 200},   # 1건 상한 초과
        {"name": "ok2.bin", "data": b"c" * 60},        # 80 + 60 = 140 ≤ 150
        {"name": "budget.bin", "data": b"d" * 20},     # 140 + 20 > 150 → 요청 예산 초과
    ])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        result = await handler.fetch_and_save(ALICE_EMAIL, ["m1"], include_body=False)
    names = sorted(p.name for p in user_files(alice_paths))
    assert names == ["ok1.bin", "ok2.bin"]
    codes = sorted(e["error"] for e in result["errors"])
    assert codes == ["attachment_too_large", "request_attachment_budget_exceeded"]
    assert "CANARY" not in json.dumps(result, default=str)


async def test_n08_conversion_deadline_falls_back_to_original(mu, alice, alice_paths, alice_tokens, monkeypatch):
    from mcp_outlook import mail_attachment as ma
    from mcp_outlook.mail_attachment_converter import ConversionPipeline

    class _Slow(ConversionPipeline):
        def convert(self, content, filename):
            time.sleep(0.5)
            return "converted text", None

    monkeypatch.setattr(limits, "CONVERSION_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(ma, "get_conversion_pipeline", lambda: _Slow())
    mail = mail_with_attachments("m1", [{"name": "doc.txt", "data": b"plain"}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
    started = time.monotonic()
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        result = await handler.fetch_and_save(ALICE_EMAIL, ["m1"], convert_to_txt=True, include_body=False)
    assert time.monotonic() - started < 0.45  # 변환이 끝날 때까지 기다리지 않았다
    assert result["converted_files"] == []
    assert [p.name for p in user_files(alice_paths)] == ["doc.txt"]  # 원본으로 처리
    assert (alice_paths.files / result["saved_attachments"][0]).read_bytes() == b"plain"
    await asyncio.sleep(0.5)  # worker thread 종료 대기 (테스트 정리)


async def test_n08_user_download_quota(mu, alice, alice_paths, alice_tokens, monkeypatch):
    monkeypatch.setattr(limits, "MAX_USER_DOWNLOAD_BYTES", 100)
    downloads = alice_paths.downloads_for("outlook")
    downloads.mkdir(parents=True, exist_ok=True)
    (downloads / "existing.bin").write_bytes(b"e" * 60)  # 이미 60바이트 사용

    storage = UserLocalStorageBackend(alice_paths, resolve_save_dir(alice_paths, None))
    assert await storage.save_file(storage.public(storage.base_directory), "a.bin", b"a" * 30)  # 90
    with pytest.raises(ToolExecutionError) as err:
        storage.write_bytes(storage.base_directory, "b.bin", b"b" * 20)  # 110 > 100
    assert err.value.payload["error"] == "quota_exceeded"
    assert sorted(p.name for p in user_files(alice_paths)) == ["a.bin", "existing.bin"]

    # 공개 경로에서도 같은 오류가 그대로 올라간다
    mail = mail_with_attachments("m1", [{"name": "c.bin", "data": b"c" * 50}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
    with bound(alice):
        handler = BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths)
        with pytest.raises(ToolExecutionError) as err:
            await handler.fetch_and_save(ALICE_EMAIL, ["m1"], include_body=False)
    assert err.value.payload["error"] == "quota_exceeded"


async def test_n08_send_attachment_limited_read(mu, alice, alice_paths, alice_tokens, monkeypatch):
    import mcp_common.secure_files as secure_files

    limit = limits.MAX_SEND_ATTACHMENT_BYTES
    (alice_paths.uploads / "exact.bin").write_bytes(b"x" * limit)
    (alice_paths.uploads / "over.bin").write_bytes(b"x" * (limit + 1))
    read_sizes = []
    real = secure_files.open_for_read

    class _Spy:
        def __init__(self, fh):
            self._fh = fh

        def read(self, n=-1):
            read_sizes.append(n)
            return self._fh.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self._fh.__exit__(*a)

    monkeypatch.setattr(secure_files, "open_for_read", lambda p, r: _Spy(real(p, r)))
    sent = []
    install_http(monkeypatch, lambda call: (sent.append(call), FakeResponse(202))[1])
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice):
        ok = await svc.send_mail(user_email=ALICE_EMAIL, to_recipients=["x@fabrikam.com"], subject="s", body="b",
                                 attachments=["uploads/exact.bin"])
        bad = await svc.send_mail(user_email=ALICE_EMAIL, to_recipients=["x@fabrikam.com"], subject="s", body="b",
                                  attachments=["uploads/over.bin"])
    assert ok["status"] == "success"
    assert bad["status"] == "error" and "3MB" in bad["error"] and str(mu) not in bad["error"]
    assert read_sizes == [limit + 1, limit + 1]  # 전체가 아니라 한도+1 바이트만 읽는다
    assert len(sent) == 1
