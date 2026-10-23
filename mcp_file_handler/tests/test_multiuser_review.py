"""astra 보안 리뷰(2026-10-23) FileHandler 항목 회귀 — R05·R08·R09·R12·R14.

- R05: 반복 취소·종료에도 요청 temp 와 서비스 수명이 worker 를 넘긴다.
- R08: 사전 서명 다운로드 URL 은 https·표준 포트·공인 주소만, 추가 redirect 금지.
- R09: 파일 바이트·요청 예산·파일 수·폴더 깊이·결과 크기·변환 시간 상한 (mode 1 은 넓히기 금지).
- R12: 로컬 입력은 검증한 handle 에서 요청 디렉터리로 복사한 뒤 복사본만 변환기에 준다.
- R14: 메타데이터 응답은 입력이 아니라 정규화한 상대 참조를 반사한다.
"""

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_context import bind_service
from mcp_common.testing import FakeTokenProvider, bound
from mcp_common.user_paths import ensure_user_dirs, paths_for

from mcp_file_handler import file_manager as fm_module
from mcp_file_handler.config.settings import Settings
from mcp_file_handler.limits import MB, LimitExceeded
from mcp_file_handler.mcp_server import handlers
from mcp_file_handler.onedrive import client as client_module
from mcp_file_handler.onedrive.client import UnsafeDownloadUrl, validate_download_url
from mcp_file_handler.request_scope import current_scope
from mcp_file_handler.service import FileHandlerService

from .conftest import DOWNLOAD_BASE, RecordingConverter, install_converter

SHARE_A = "https://contoso-my.sharepoint.com/:t:/g/personal/alice/AAA"


def _within(path, root) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


@asynccontextmanager
async def custom_service(mu, principal, config):
    """설정을 바꾼 mode 1 서비스 (풀 대신 직접 생성·초기화·bind)."""
    paths = ensure_user_dirs(paths_for(principal))
    service = FileHandlerService(
        principal=principal, paths=paths, tokens=FakeTokenProvider(principal), config=config
    )
    service.initialize()
    try:
        with bound(principal), bind_service(handlers.SERVER_NAME, service):
            yield service
    finally:
        await service.close()


def _upload(mu, principal, name, content: bytes) -> Path:
    paths = mu.paths(principal)
    paths.uploads.mkdir(parents=True, exist_ok=True)
    target = paths.uploads / name
    target.write_bytes(content)
    return target


# ----------------------------------------------------------------------
# R05 — 반복 취소
# ----------------------------------------------------------------------
async def test_r05_double_cancel_keeps_temp_dir_until_worker_exits(mu):
    paths = mu.paths(mu.alice)
    _upload(mu, mu.alice, "slow.txt", b"slow")
    started, release = threading.Event(), threading.Event()
    record = {}

    def hook(path):
        started.set()
        assert release.wait(10)
        work_dir = current_scope().work_dir
        record["dir_existed_at_end"] = work_dir.exists()
        (work_dir / "late.txt").write_text("written after both cancels", encoding="utf-8")
        record["wrote_after_cancel"] = True

    async with mu.leased(mu.alice) as service:
        install_converter(service, RecordingConverter(hook))
        task = asyncio.create_task(handlers.handle_convert_file_to_text({"input_path": "uploads/slow.txt"}))
        assert await asyncio.to_thread(started.wait, 10)

        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()  # 두 번째 취소가 첫 취소의 대기를 끊지 않아야 한다
        await asyncio.sleep(0.05)
        assert not task.done()  # worker 가 아직 도는 동안 취소가 완료되지 않는다
        assert any(p.is_dir() for p in paths.tmp.iterdir())  # 요청 temp 가 살아 있다

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert record == {"dir_existed_at_end": True, "wrote_after_cancel": True}
    assert list(paths.tmp.iterdir()) == []  # worker 가 끝난 뒤에야 지워졌다


async def test_r05_close_waits_for_inflight_worker(mu):
    _upload(mu, mu.alice, "slow.txt", b"slow")
    started, release = threading.Event(), threading.Event()
    record = {}

    def hook(path):
        started.set()
        assert release.wait(10)
        record["dir_alive"] = current_scope().work_dir.exists()

    async with custom_service(mu, mu.alice, {}) as service:
        install_converter(service, RecordingConverter(hook))
        task = asyncio.create_task(handlers.handle_convert_file_to_text({"input_path": "uploads/slow.txt"}))
        assert await asyncio.to_thread(started.wait, 10)
        task.cancel()
        await asyncio.sleep(0.05)
        closing = asyncio.create_task(service.close())  # 종료가 worker 를 기다린다
        await asyncio.sleep(0.1)
        assert not closing.done() and service._manager is not None
        release.set()
        await closing
        with pytest.raises(asyncio.CancelledError):
            await task
    assert record == {"dir_alive": True}
    assert service._manager is None


# ----------------------------------------------------------------------
# R08 — 사전 서명 URL
# ----------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://download.example.invalid/x",
    "https://download.example.invalid:8443/x",
    "https://user:pw@download.example.invalid/x",
    "https://127.0.0.1/x",
    "https://[::1]/x",
    "https://10.1.2.3/x",
    "https://169.254.169.254/latest/meta-data",
    "https://0.0.0.0/x",
    "https://localhost/x",
    "https://localhost./x",
    "https://files.internal/x",
    "https://nas.local/x",
    "https://intranet/x",          # 단일 라벨 호스트 (3차 N05)
    "",
])
def test_r08_download_url_policy_rejects(monkeypatch, url):
    import ipaddress

    from mcp_common import graph_url_policy

    monkeypatch.setattr(graph_url_policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("8.8.8.8")])
    with pytest.raises(UnsafeDownloadUrl):
        validate_download_url(url)


def test_r08_download_url_policy_checks_resolved_addresses(monkeypatch):
    import ipaddress

    from mcp_common import graph_url_policy

    public, private = ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("10.0.0.5")
    monkeypatch.setattr(graph_url_policy, "_resolved_addresses", lambda host: [public, private])
    with pytest.raises(UnsafeDownloadUrl):            # 해석된 주소 중 하나라도 사설이면 거부
        validate_download_url("https://cdn.example.invalid/x")
    monkeypatch.setattr(graph_url_policy, "_resolved_addresses", lambda host: [])
    with pytest.raises(UnsafeDownloadUrl):            # DNS 해석 실패도 거부 (3차 N05)
        validate_download_url("https://cdn.example.invalid/x")
    monkeypatch.setattr(graph_url_policy, "_resolved_addresses", lambda host: [public])
    assert validate_download_url("https://cdn.example.invalid:443/x").endswith("/x")
    assert validate_download_url("https://cdn.example.invalid./x").endswith("/x")


async def test_r08_private_location_and_second_redirect_are_not_followed(mu):
    mu.graph.add_file(mu.alice, SHARE_A, "a.txt", b"payload")
    mu.graph.location_override = "http://169.254.169.254/latest/meta-data"
    async with mu.leased(mu.alice) as service:
        install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
    assert result["success"] is False
    assert not any(url.startswith("http://169.254") for url, _ in mu.graph.calls)
    assert "169.254" not in json.dumps(result, ensure_ascii=False)

    mu.graph.location_override = None
    mu.graph.presigned_redirect_to = "https://8.8.4.4/elsewhere"
    async with mu.leased(mu.alice) as service:
        install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
    assert result["success"] is False
    assert not any("elsewhere" in url for url, _ in mu.graph.calls)
    assert mu.graph.tokens_used_for(DOWNLOAD_BASE) == {None}


# ----------------------------------------------------------------------
# R09 — 자원 상한
# ----------------------------------------------------------------------
def test_r09_mode1_limits_cannot_be_widened(mu, monkeypatch):
    paths = paths_for(mu.alice)
    assert Settings({"max_file_size": 100000, "max_download_files": 10**6}, paths=paths)["max_file_size"] == 100
    assert Settings({"max_download_files": 10**6}, paths=paths)["max_download_files"] == 200
    assert Settings({"max_file_size": 1}, paths=paths)["max_file_size"] == 1      # 낮추기는 허용
    assert Settings({"max_file_size": -5}, paths=paths)["max_file_size"] == 100   # 잘못된 값은 기본값
    monkeypatch.setenv("MCP_ATTACHMENT_MAX_FILE_SIZE", "100000")
    monkeypatch.setenv("MCP_ATTACHMENT_CONVERSION_TIMEOUT", "999999")
    monkeypatch.setenv("MCP_ATTACHMENT_MAX_WORKERS", "64")
    settings = Settings(paths=paths)
    assert settings["max_file_size"] == 100
    assert settings["conversion_timeout"] == 300
    assert settings["max_workers"] == 4


async def test_r09_streamed_download_aborts_at_file_cap(mu):
    big = mu.graph.add_file(mu.alice, SHARE_A, "big.txt", b"x" * (3 * MB))
    async with custom_service(mu, mu.alice, {"max_file_size": 1}) as service:
        install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
    assert result["success"] is False
    assert LimitExceeded("file_too_large").message in result["errors"]
    (response,) = mu.graph.download_responses
    assert response.closed and 0 < response.chunks_served < (3 * MB) // (64 * 1024)
    assert list(mu.paths(mu.alice).tmp.iterdir()) == []

    # Content-Length 가 상한을 넘으면 한 바이트도 받지 않는다
    mu.graph.download_responses.clear()
    mu.graph.declared_length[big] = 5 * MB
    async with custom_service(mu, mu.alice, {"max_file_size": 1}) as service:
        install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
    assert result["success"] is False
    assert mu.graph.download_responses[0].chunks_served == 0


async def test_r09_request_budget_file_count_and_depth(mu):
    # 요청 예산: 1 MB 안에 600 KB 두 개는 들어가지 않는다
    mu.graph.add_folder(mu.alice, SHARE_A, "f", [
        ("file", "one.txt", b"1" * (600 * 1024)),
        ("file", "two.txt", b"2" * (600 * 1024)),
    ])
    async with custom_service(mu, mu.alice, {"max_file_size": 1, "max_total_size": 1}) as service:
        install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
    assert result["success"] is False
    assert LimitExceeded("request_too_large").message in result["errors"]

    # 파일 수
    mu.graph.add_folder(mu.alice, SHARE_A + "-n", "f", [("file", f"{i}.txt", b"x") for i in range(3)])
    async with custom_service(mu, mu.alice, {"max_download_files": 2}) as service:
        install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A + "-n"})
    assert result["success"] is False
    assert LimitExceeded("too_many_files").message in result["errors"]

    # 폴더 깊이
    mu.graph.add_folder(mu.alice, SHARE_A + "-d", "f", [
        ("folder", "l1", [("folder", "l2", [("folder", "l3", [("file", "deep.txt", b"deep")])])]),
    ])
    async with custom_service(mu, mu.alice, {"max_folder_depth": 1}) as service:
        install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A + "-d"})
    assert result["success"] is False
    assert LimitExceeded("folder_too_deep").message in result["errors"]
    assert list(mu.paths(mu.alice).tmp.iterdir()) == []


async def test_r09_local_input_size_and_output_caps(mu):
    _upload(mu, mu.alice, "big.txt", b"x" * (2 * MB))
    _upload(mu, mu.alice, "long.txt", b"0123456789" * 5)
    async with custom_service(mu, mu.alice, {"max_file_size": 1, "max_output_chars": 12}) as service:
        conv = install_converter(service, RecordingConverter())
        too_big = await handlers.handle_convert_file_to_text({"input_path": "uploads/big.txt"})
        assert too_big["success"] is False
        assert LimitExceeded("file_too_large").message in too_big["errors"]
        assert conv.calls == []  # 변환기까지 가지 않는다

        capped = await handlers.handle_convert_file_to_text({"input_path": "uploads/long.txt"})
        assert capped["success"] is True
        assert capped["text"] == "012345678901"
        assert capped["metadata"]["truncated"] is True
        assert LimitExceeded("output_truncated").message in capped["errors"]

        # 요청 합계: 한 디렉터리 호출 안에서 두 번째 파일부터는 남은 예산만큼만
        listing = await handlers.handle_process_directory({"directory_path": "uploads"})
        texts = {r["file"]: r.get("text", "") for r in listing["results"]}
        assert sum(len(t) for t in texts.values()) <= 12


async def test_r09_conversion_timeout_discards_slow_worker(mu, monkeypatch):
    _upload(mu, mu.alice, "slow.txt", b"slow")
    finished = threading.Event()

    def hook(path):
        time.sleep(1.5)
        finished.set()

    async with custom_service(mu, mu.alice, {"conversion_timeout": 1}) as service:
        install_converter(service, RecordingConverter(hook))
        result = await handlers.handle_convert_file_to_text({"input_path": "uploads/slow.txt"})
    assert result["success"] is False
    assert LimitExceeded("conversion_timeout").message in result["errors"]  # 결과는 버려졌다
    # 응답은 converter 스레드가 실제로 끝난 뒤에 나간다 (N03 — 수명 기준은 실제 스레드)
    assert finished.is_set()
    assert list(mu.paths(mu.alice).tmp.iterdir()) == []


async def test_r09_abandoned_workers_are_bounded_by_slots(mu, monkeypatch):
    from mcp_file_handler import conversion_workers

    monkeypatch.setattr(fm_module, "_SLOT_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(conversion_workers, "HARD_JOIN_CAP_SECONDS", 0.2)
    _upload(mu, mu.alice, "a.txt", b"a")
    _upload(mu, mu.alice, "b.txt", b"b")
    release = threading.Event()

    def hook(path):
        if Path(path).name == "a.txt":
            assert release.wait(10)

    async with custom_service(mu, mu.alice, {"max_workers": 1, "conversion_timeout": 1}) as service:
        install_converter(service, RecordingConverter(hook))
        stuck = await handlers.handle_convert_file_to_text({"input_path": "uploads/a.txt"})
        assert LimitExceeded("conversion_timeout").message in stuck["errors"]
        # 버려진 스레드가 유일한 슬롯을 쥐고 있다 → 새 변환은 overloaded (무한 스레드 누적 없음)
        with pytest.raises(SecurityError) as err:
            await handlers.handle_convert_file_to_text({"input_path": "uploads/b.txt"})
        assert err.value.code == ErrorCode.OVERLOADED
        release.set()
        await asyncio.sleep(0.3)
        ok = await handlers.handle_convert_file_to_text({"input_path": "uploads/b.txt"})
        assert ok["success"] and ok["text"] == "b"


# ----------------------------------------------------------------------
# R12 — 검증한 handle 에서 복사
# ----------------------------------------------------------------------
async def test_r12_converter_reads_staged_copy_not_original(mu):
    original = _upload(mu, mu.alice, "doc.txt", b"original-bytes")
    paths = mu.paths(mu.alice)
    async with mu.leased(mu.alice) as service:
        conv = install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_file_to_text({"input_path": "uploads/doc.txt"})
        saved = await handlers.handle_save_file_metadata({"file_url": "uploads/doc.txt", "keywords": ["k"]})
    assert result["success"] and result["text"] == "original-bytes"
    (call,) = conv.calls
    assert call["path"].resolve() != original.resolve()
    assert call["path"].parent.name == "input" and _within(call["path"], call["work_dir"])
    assert _within(call["path"], paths.tmp)
    assert call["content"] == b"original-bytes"
    assert result["metadata"]["filename"] == "doc.txt"
    assert saved["file_url"] == "uploads/doc.txt"  # 메타데이터 키는 원래 참조
    assert list(paths.tmp.iterdir()) == []       # 복사본은 요청과 함께 사라진다


# ----------------------------------------------------------------------
# R14 — 정규화한 참조 반사
# ----------------------------------------------------------------------
async def test_r14_metadata_responses_reflect_normalized_reference(mu):
    paths = mu.paths(mu.alice)
    absolute = str(_upload(mu, mu.alice, "abs.txt", b"abs"))
    missing_abs = str(paths.uploads / "never.txt")
    async with mu.leased(mu.alice):
        saved = await handlers.handle_save_file_metadata({"file_url": absolute, "keywords": ["k"]})
        got = await handlers.handle_get_file_metadata({"file_url": absolute})
        absent = await handlers.handle_get_file_metadata({"file_url": missing_abs})
        deleted = await handlers.handle_delete_file_metadata({"file_url": absolute})
        again = await handlers.handle_delete_file_metadata({"file_url": missing_abs})

    assert saved == {"success": True, "file_url": "uploads/abs.txt"}
    assert got["found"] and got["metadata"]["file_url"] == "uploads/abs.txt"
    assert absent == {"success": True, "found": False, "file_url": "uploads/never.txt"}
    assert deleted == {"success": True, "deleted": True, "file_url": "uploads/abs.txt"}
    assert again["file_url"] == "uploads/never.txt" and again["already_absent"]
    for payload in (saved, got, absent, deleted, again):
        dumped = json.dumps(payload, ensure_ascii=False)
        assert str(paths.files) not in dumped and str(mu.root) not in dumped
