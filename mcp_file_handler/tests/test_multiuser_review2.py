"""astra 2차 보안 리뷰(2026-10-23) FileHandler 항목 회귀 — N03·N06·N08·N10·R02.

- N03: 변환 시간 초과 뒤에도 실제 converter 스레드가 temp·lease·drain 의 수명 기준이다.
  슬롯은 프로세스 전역 user_key 별이라 서비스 재생성이 상한을 넘기지 못한다.
- N06: legacy(mode 0) SQLite/JSON metadata 가 migration freeze 에 참여한다 (생성·쓰기마다 검사).
- N08: 로컬 디렉터리 순회에도 파일 수·바이트 예산이 적용된다.
- N10: search_metadata 응답의 criteria.file_url 은 공개 참조이거나 생략된다.
- R02: keywords 는 스키마(maxItems/maxLength)와 서비스 경계에서 모두 상한이 있다.
"""

import asyncio
import json
import threading
import time

import pytest

from mcp_common.errors import ToolValidationError
from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError
from mcp_common.security_policy import MIGRATION_LOCK_NAME
from mcp_common.validation import validate_arguments

from mcp_file_handler import conversion_workers
from mcp_file_handler import file_manager as fm_module
from mcp_file_handler.limits import KEYWORD_MAX_LENGTH, KEYWORDS_MAX_ITEMS, MB, LimitExceeded
from mcp_file_handler.mcp_server import handlers
from mcp_file_handler.metadata.storage import JSONStorage, SQLiteStorage
from mcp_file_handler.request_scope import current_scope

from .conftest import RecordingConverter, install_converter
from .test_multiuser_review import _upload, custom_service


async def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


# ----------------------------------------------------------------------
# N03 — converter 스레드가 수명 기준
# ----------------------------------------------------------------------
async def test_n03_timeout_response_waits_for_converter_thread(mu):
    _upload(mu, mu.alice, "slow.txt", b"slow")
    finished = threading.Event()

    def hook(path):
        time.sleep(1.5)
        finished.set()

    async with custom_service(mu, mu.alice, {"conversion_timeout": 1}) as service:
        install_converter(service, RecordingConverter(hook))
        started = time.monotonic()
        result = await handlers.handle_convert_file_to_text({"input_path": "uploads/slow.txt"})
        elapsed = time.monotonic() - started
        assert LimitExceeded("conversion_timeout").message in result["errors"]
        assert finished.is_set() and elapsed >= 1.4      # 스레드가 끝난 뒤에야 요청이 끝났다
        assert service.live_converter_threads == 0
        assert conversion_workers.live_workers(mu.alice.user_key) == 0
    assert list(mu.paths(mu.alice).tmp.iterdir()) == []


async def test_n03_cleanup_deferred_until_converter_exits(mu, monkeypatch):
    monkeypatch.setattr(conversion_workers, "HARD_JOIN_CAP_SECONDS", 0.2)
    paths = mu.paths(mu.alice)
    _upload(mu, mu.alice, "stuck.txt", b"stuck")
    release = threading.Event()
    record = {}

    def hook(path):
        assert release.wait(10)
        work_dir = current_scope().work_dir
        record["dir_alive_at_exit"] = work_dir.exists()
        record["input_copy_alive"] = any(work_dir.rglob("stuck.txt"))

    async with custom_service(mu, mu.alice, {"conversion_timeout": 1}) as service:
        install_converter(service, RecordingConverter(hook))
        result = await handlers.handle_convert_file_to_text({"input_path": "uploads/stuck.txt"})
        assert LimitExceeded("conversion_timeout").message in result["errors"]
        # hard cap 이 지나 요청은 끝났지만, 스레드가 살아 있는 동안 요청 디렉터리는 남는다
        assert service.live_converter_threads == 1
        assert conversion_workers.live_workers(mu.alice.user_key) == 1
        assert [p for p in paths.tmp.iterdir() if p.is_dir()]
        assert any(group.cleanup_deferred for group in service._groups)

        release.set()
        assert await _wait_until(lambda: list(paths.tmp.iterdir()) == [])  # 마지막 스레드가 정리
        assert record == {"dir_alive_at_exit": True, "input_copy_alive": True}
        assert await _wait_until(lambda: conversion_workers.live_workers(mu.alice.user_key) == 0)
        assert service.live_converter_threads == 0


async def test_n03_close_drains_live_converter_threads(mu, monkeypatch):
    monkeypatch.setattr(conversion_workers, "HARD_JOIN_CAP_SECONDS", 0.2)
    _upload(mu, mu.alice, "stuck.txt", b"stuck")
    release = threading.Event()

    def hook(path):
        assert release.wait(10)

    async with custom_service(mu, mu.alice, {"conversion_timeout": 1}) as service:
        install_converter(service, RecordingConverter(hook))
        await handlers.handle_convert_file_to_text({"input_path": "uploads/stuck.txt"})
        assert service.live_converter_threads == 1
        monkeypatch.setattr(conversion_workers, "HARD_JOIN_CAP_SECONDS", 10.0)
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0.2)
        assert not closing.done()          # close() 가 살아 있는 converter 를 기다린다
        release.set()
        await closing
        assert service.live_converter_threads == 0 and service._manager is None


async def test_n03_user_slots_survive_service_recreation(mu, monkeypatch):
    monkeypatch.setattr(conversion_workers, "HARD_JOIN_CAP_SECONDS", 0.2)
    monkeypatch.setattr(fm_module, "_SLOT_WAIT_SECONDS", 0.2)
    _upload(mu, mu.alice, "a.txt", b"a")
    _upload(mu, mu.alice, "b.txt", b"b")
    release = threading.Event()

    def hook(path):
        if path.endswith("a.txt"):
            assert release.wait(10)

    # 첫 서비스의 close() 는 살아 있는 converter 때문에 실패로 보고된다 (3차 N03) — 스레드는 계속 슬롯을 쥔다
    with pytest.raises(RuntimeError, match="converter threads still alive"):
        async with custom_service(mu, mu.alice, {"max_workers": 1, "conversion_timeout": 1}) as first:
            install_converter(first, RecordingConverter(hook))
            stuck = await handlers.handle_convert_file_to_text({"input_path": "uploads/a.txt"})
            assert LimitExceeded("conversion_timeout").message in stuck["errors"]
    assert conversion_workers.live_workers(mu.alice.user_key) == 1

    async with custom_service(mu, mu.alice, {"max_workers": 4}) as second:  # 재생성 — 상한은 사용자 단위
        install_converter(second, RecordingConverter(hook))
        with pytest.raises(SecurityError) as err:
            await handlers.handle_convert_file_to_text({"input_path": "uploads/b.txt"})
        assert err.value.code == ErrorCode.OVERLOADED
        release.set()
        assert await _wait_until(lambda: conversion_workers.live_workers(mu.alice.user_key) == 0)
        ok = await handlers.handle_convert_file_to_text({"input_path": "uploads/b.txt"})
        assert ok["success"] and ok["text"] == "b"

    # 다른 사용자의 슬롯은 독립이다
    assert conversion_workers.slots_for(mu.bob.user_key, 4) is not conversion_workers.slots_for(mu.alice.user_key, 4)


# ----------------------------------------------------------------------
# N06 — migration freeze
# ----------------------------------------------------------------------
def test_n06_legacy_metadata_stores_honor_migration_lock(tmp_path, monkeypatch, clean_config_env):
    monkeypatch.delenv("MS365_MIGRATION_OVERRIDE", raising=False)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    lock = legacy / MIGRATION_LOCK_NAME

    sqlite_store = SQLiteStorage(str(legacy / "metadata.db"))
    assert sqlite_store.save("https://x/one", ["k"], {})
    json_store = JSONStorage(str(legacy / "metadata.json"))
    assert json_store.save("https://x/one", ["k"], {})

    lock.write_text("{}", encoding="utf-8")  # 기동 뒤에 생긴 잠금도 writer 를 멈춘다
    for store in (sqlite_store, json_store):
        with pytest.raises(StartupConfigError):
            store.save("https://x/two", [], {})
        with pytest.raises(StartupConfigError):
            store.delete("https://x/one")
        assert store.get("https://x/one")["keywords"] == ["k"]  # 읽기는 막지 않는다
        assert store.search(keyword="k")
    with pytest.raises(StartupConfigError):
        SQLiteStorage(str(legacy / "metadata.db"))
    with pytest.raises(StartupConfigError):
        JSONStorage(str(legacy / "metadata.json"))
    assert json.loads((legacy / "metadata.json").read_text(encoding="utf-8")).keys() == {"https://x/one"}

    monkeypatch.setenv("MS365_MIGRATION_OVERRIDE", "1")  # 운영자 명시 우회만 통과
    assert sqlite_store.save("https://x/three", [], {})
    lock.unlink()


# ----------------------------------------------------------------------
# N08 — 로컬 디렉터리 상한
# ----------------------------------------------------------------------
async def test_n08_local_directory_file_count_and_byte_budget(mu):
    for i in range(3):
        _upload(mu, mu.alice, f"{i}.txt", b"x")
    async with custom_service(mu, mu.alice, {"max_download_files": 2}) as service:
        install_converter(service, RecordingConverter())
        with pytest.raises(LimitExceeded) as err:
            await handlers.handle_process_directory({"directory_path": "uploads"})
        assert err.value.code == "too_many_files"
        assert err.value.payload["limit"] == "too_many_files"

    big_dir = mu.paths(mu.alice).uploads / "big"
    big_dir.mkdir()
    (big_dir / "big1.txt").write_bytes(b"1" * (600 * 1024))
    (big_dir / "big2.txt").write_bytes(b"2" * (600 * 1024))
    async with custom_service(mu, mu.alice, {"max_file_size": 1, "max_total_size": 1}) as service:
        install_converter(service, RecordingConverter())
        listing = await handlers.handle_process_directory({"directory_path": "uploads/big"})
        assert listing["processed"] == 2
        assert sorted(r["success"] for r in listing["results"]) == [False, True]
        failed = next(r for r in listing["results"] if not r["success"])
        assert LimitExceeded("request_too_large").message in failed["errors"]
        assert failed["file"].startswith("uploads/big/")


# ----------------------------------------------------------------------
# N10 — search criteria 반사
# ----------------------------------------------------------------------
async def test_n10_search_criteria_echo_is_public_reference_or_omitted(mu):
    paths = mu.paths(mu.alice)
    inside = str(_upload(mu, mu.alice, "abs.txt", b"abs"))
    outside = str(mu.root / "users" / "nope" / "files" / "abs.txt")
    async with mu.leased(mu.alice):
        await handlers.handle_save_file_metadata({"file_url": "uploads/abs.txt", "keywords": ["k"]})
        await handlers.handle_save_file_metadata(
            {"file_url": "https://contoso.sharepoint.com/sites/x/report.docx", "keywords": ["k"]}
        )
        by_abs = await handlers.handle_search_metadata({"file_url": inside})
        by_outside = await handlers.handle_search_metadata({"file_url": outside})
        by_fragment = await handlers.handle_search_metadata({"file_url": "sharepoint.com/sites"})
        by_keyword = await handlers.handle_search_metadata({"keyword": "k"})

    assert by_abs["criteria"] == {"file_url": "uploads/abs.txt"}
    assert [r["file_url"] for r in by_abs["results"]] == ["uploads/abs.txt"]  # 상대 키와 매칭된다
    assert by_outside["criteria"] == {} and by_outside["count"] == 0
    assert by_fragment["criteria"] == {"file_url": "sharepoint.com/sites"} and by_fragment["count"] == 1
    assert by_keyword["count"] == 2
    for payload in (by_abs, by_outside, by_fragment, by_keyword):
        dumped = json.dumps(payload, ensure_ascii=False)
        assert str(paths.files) not in dumped and str(mu.root) not in dumped


# ----------------------------------------------------------------------
# R02 — keywords 상한
# ----------------------------------------------------------------------
async def test_r02_keywords_bounded_in_schema_and_at_service_boundary(mu):
    schema = handlers.runtime.input_schema("save_file_metadata")
    keywords = schema["properties"]["keywords"]
    assert keywords["maxItems"] == KEYWORDS_MAX_ITEMS == 100
    assert keywords["items"]["maxLength"] == KEYWORD_MAX_LENGTH == 200
    with pytest.raises(ToolValidationError):
        validate_arguments(schema, {"file_url": "https://x/doc", "keywords": ["k"] * 101}, tool="save_file_metadata")
    with pytest.raises(ToolValidationError):
        validate_arguments(schema, {"file_url": "https://x/doc", "keywords": ["k" * 201]}, tool="save_file_metadata")

    async with mu.leased(mu.alice) as service:
        oversized = ["k" * 300] * 150 + [5, None]
        saved = await service.save_metadata("https://x/doc", oversized)  # 스키마를 우회한 직접 호출
        assert saved["success"]
        stored = (await service.get_metadata("https://x/doc"))["metadata"]["keywords"]
    assert len(stored) == 100 and all(len(k) == 200 for k in stored)
