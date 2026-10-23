"""FileHandler 멀티유저 격리 회귀 — spec/spec_멀티유저.md ②-10 D05·F01·F02·F03·F04·F05·F06.

네트워크 없음: 토큰은 `FakeTokenProvider`, Graph 는 conftest 의 `FakeGraph`.
"""

import asyncio
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import make_principal

from mcp_file_handler.mcp_server import handlers
from mcp_file_handler.metadata.storage import OWNED_TABLE, OwnedSQLiteStorage
from mcp_file_handler.onedrive.client import OneDriveClient
from mcp_file_handler.request_scope import FileRequestScope, bind_scope

from .conftest import RecordingConverter, install_converter

SHARE_A = "https://contoso-my.sharepoint.com/:t:/g/personal/alice/AAA"
SHARE_B = "https://contoso-my.sharepoint.com/:t:/g/personal/bob/BBB"


def _within(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _all_files(root: Path):
    return [p for p in Path(root).rglob("*") if p.is_file()]


# ----------------------------------------------------------------------
# D05 — metadata
# ----------------------------------------------------------------------
async def test_d05_metadata_search_get_delete_are_owner_scoped(mu):
    shared_url = "https://contoso.sharepoint.com/sites/x/report.docx"
    b_only = "https://contoso.sharepoint.com/sites/x/bob-only.docx"

    async with mu.leased(mu.bob):
        assert (await handlers.handle_save_file_metadata(
            {"file_url": shared_url, "keywords": ["bob-kw"], "additional_metadata": {"who": "bob"}}
        ))["success"]
        assert (await handlers.handle_save_file_metadata(
            {"file_url": b_only, "keywords": ["secret"]}
        ))["success"]

    async with mu.leased(mu.alice):
        assert (await handlers.handle_save_file_metadata(
            {"file_url": shared_url, "keywords": ["alice-kw"], "additional_metadata": {"who": "alice"}}
        ))["success"]

        everything = await handlers.handle_search_metadata({})
        assert everything["count"] == 1
        assert everything["results"][0]["metadata"]["who"] == "alice"
        assert (await handlers.handle_search_metadata({"keyword": "secret"}))["count"] == 0
        assert (await handlers.handle_search_metadata({"file_url": "bob-only"}))["count"] == 0

        got = await handlers.handle_get_file_metadata({"file_url": b_only})
        assert got == {"success": True, "found": False, "file_url": b_only}
        same = await handlers.handle_get_file_metadata({"file_url": shared_url})
        assert same["metadata"]["keywords"] == ["alice-kw"]

        deleted = await handlers.handle_delete_file_metadata({"file_url": b_only})
        assert deleted["deleted"] is False
        assert (await handlers.handle_delete_file_metadata({"file_url": shared_url}))["deleted"] is True

    async with mu.leased(mu.bob):
        results = (await handlers.handle_search_metadata({}))["results"]
        assert sorted(r["file_url"] for r in results) == sorted([shared_url, b_only])
        assert {r["metadata"]["who"] for r in results if r["file_url"] == shared_url} == {"bob"}

    # 저장 위치도 사용자별 db/metadata.db 이고 행마다 owner_key 가 있다
    for principal in (mu.alice, mu.bob):
        db = mu.paths(principal).metadata_db
        with sqlite3.connect(db) as conn:
            owners = {row[0] for row in conn.execute(f"SELECT owner_key FROM {OWNED_TABLE}")}
        assert owners <= {principal.user_key}


def test_d05_owned_storage_filters_by_owner_even_in_one_db_file(tmp_path):
    """DB 파일이 하나여도 SQL 의 owner 조건만으로 격리돼야 한다 (②-7.3)."""
    db = tmp_path / "shared.db"
    alice = OwnedSQLiteStorage(db, make_principal("alice@contoso.com").user_key)
    bob = OwnedSQLiteStorage(db, make_principal("bob@contoso.com").user_key)
    url = "https://contoso.sharepoint.com/x.docx"
    assert bob.save(url, ["b"], {"who": "bob"})
    assert bob.save("https://contoso.sharepoint.com/b%_only", ["b"], {})
    assert alice.save(url, ["a"], {"who": "alice"})

    assert [r["metadata"]["who"] for r in alice.search()] == ["alice"]
    assert alice.search(file_url="%") == []          # LIKE 와일드카드도 문자 그대로
    assert alice.get("https://contoso.sharepoint.com/b%_only") is None
    assert alice.delete("https://contoso.sharepoint.com/b%_only") is False
    assert alice.delete(url) is True
    assert bob.get(url)["metadata"] == {"who": "bob"}
    assert len(bob.search()) == 2


# ----------------------------------------------------------------------
# F06 — 자기 auth.db / db/metadata.db 도 파일 도구로 못 연다
# ----------------------------------------------------------------------
async def test_f06_file_tools_cannot_reach_own_auth_or_business_db(mu):
    paths = mu.paths(mu.alice)
    async with mu.leased(mu.alice):
        paths.auth_db.write_bytes(b"not-a-real-db")       # 존재해도 거부돼야 한다
        assert paths.metadata_db.exists()                 # 서비스 초기화가 만든 업무 DB

        targets = [
            str(paths.auth_db),
            str(paths.metadata_db),
            "../auth/auth.db",
            "../db/metadata.db",
            "uploads/../../db/metadata.db",
        ]
        for target in targets:
            with pytest.raises(SecurityError) as err:
                await handlers.handle_convert_file_to_text({"input_path": target})
            assert err.value.code == ErrorCode.PATH_NOT_ALLOWED
            # 거부 응답에 사용자 files/ 루트 등 절대경로가 없다 (예전 "허용 루트: ..." 문구 제거)
            dumped = json.dumps(err.value.payload, ensure_ascii=False) + str(err.value)
            assert str(mu.root) not in dumped and str(paths.files) not in dumped
            with pytest.raises(SecurityError):
                await handlers.handle_save_file_metadata({"file_url": target, "keywords": ["x"]})
            with pytest.raises(SecurityError):
                await handlers.handle_get_file_metadata({"file_url": target})
            with pytest.raises(SecurityError):
                await handlers.handle_delete_file_metadata({"file_url": target})

        for directory in (str(paths.db_dir), str(paths.auth_dir), str(paths.root), ".."):
            with pytest.raises(SecurityError) as err:
                await handlers.handle_process_directory({"directory_path": directory})
            assert err.value.code == ErrorCode.PATH_NOT_ALLOWED

        # 다른 사용자의 files/ 도 마찬가지
        bob_file = mu.paths(mu.bob).uploads / "b.txt"
        bob_file.parent.mkdir(parents=True, exist_ok=True)
        bob_file.write_text("bob", encoding="utf-8")
        with pytest.raises(SecurityError):
            await handlers.handle_convert_file_to_text({"input_path": str(bob_file)})


@pytest.mark.parametrize("bad", [
    "\\\\server\\share\\a.txt",
    "//server/share/a.txt",
    "\\\\?\\C:\\Windows\\win.ini",
    "uploads/a.txt:secret",
    "C:relative.txt",
    "uploads/CON.txt",
    "uploads/nul",
    "~/a.txt",
    "uploads/a\x00.txt",
])
async def test_f01_special_paths_rejected(mu, bad):
    async with mu.leased(mu.alice):
        with pytest.raises(SecurityError) as err:
            await handlers.handle_convert_file_to_text({"input_path": bad})
        assert err.value.code == ErrorCode.PATH_NOT_ALLOWED


async def test_relative_paths_resolve_under_own_files_and_responses_are_public(mu):
    paths = mu.paths(mu.alice)
    paths.uploads.mkdir(parents=True, exist_ok=True)
    (paths.uploads / "a.txt").write_text("hello-a", encoding="utf-8")
    async with mu.leased(mu.alice) as service:
        install_converter(service, RecordingConverter())
        single = await handlers.handle_convert_file_to_text({"input_path": "uploads/a.txt"})
        assert single["success"] and single["text"] == "hello-a"

        listing = await handlers.handle_process_directory({"directory_path": "uploads"})
        assert listing["processed"] == 1
        assert listing["results"][0]["file"] == "uploads/a.txt"
        assert str(mu.root) not in json.dumps(listing, ensure_ascii=False)

        missing = await handlers.handle_convert_file_to_text({"input_path": "uploads/none.txt"})
        assert missing["success"] is False
        assert str(mu.root) not in json.dumps(missing, ensure_ascii=False)

        saved = await handlers.handle_save_file_metadata({"file_url": "uploads/a.txt", "keywords": ["k"]})
        assert saved["success"]
        found = await handlers.handle_search_metadata({"keyword": "k"})
        assert [r["file_url"] for r in found["results"]] == ["uploads/a.txt"]


# ----------------------------------------------------------------------
# F02 — 원격 이름 traversal
# ----------------------------------------------------------------------
@pytest.mark.parametrize("remote_name", [
    "../../evil.txt",
    "..\\..\\evil.txt",
    "/etc/evil.txt",
    "C:\\Windows\\evil.txt",
    "\\\\server\\share\\evil.txt",
])
async def test_f02_remote_file_name_stays_in_request_dir(mu, remote_name):
    mu.graph.add_file(mu.alice, SHARE_A, remote_name, b"payload")
    alice_files = mu.paths(mu.alice).files
    async with mu.leased(mu.alice) as service:
        conv = install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})

    assert result["success"], result
    assert result["text"].endswith("payload")
    (call,) = conv.calls
    assert _within(call["path"], mu.paths(mu.alice).tmp)
    assert call["path"].name == "evil.txt"
    # 데이터 루트 어디에도 사용자 files/ 밖에 쓴 파일이 없다 (system/deployment 제외)
    stray = [p for p in _all_files(mu.root)
             if not _within(p, alice_files) and "db" not in p.parts and "system" not in p.parts]
    assert stray == []


async def test_f02_remote_folder_names_cannot_escape(mu):
    mu.graph.add_folder(mu.alice, SHARE_A, "..", [
        ("folder", "..", [("file", "../../deep.txt", b"deep")]),
        ("folder", "C:\\abs", [("file", "x.txt", b"x")]),
        ("file", "..\\top.txt", b"top"),
    ])
    async with mu.leased(mu.alice) as service:
        conv = install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})

    assert result["success"], result
    assert sorted(c["content"] for c in conv.calls) == [b"deep", b"top", b"x"]
    for call in conv.calls:
        assert _within(call["path"], call["work_dir"])
        assert _within(call["work_dir"], mu.paths(mu.alice).tmp)
    assert list(mu.paths(mu.alice).tmp.iterdir()) == []  # 요청이 끝나면 자기 temp 만 정리


async def test_downloaded_files_pass_shared_path_gate_no_trusted_roots(mu, monkeypatch):
    """다운로드 파일도 공용 관문(resolve_safe_path, mode 1 = 호출자 files/)을 통과한다."""
    from mcp_file_handler import file_manager as fm_module
    from mcp_file_handler import path_policy

    assert not hasattr(fm_module.FileManager, "_trusted_roots")
    real = path_policy.resolve_safe_path
    gated = []

    def spy(path, *, must_exist=False):
        resolved = real(path, must_exist=must_exist)
        gated.append(Path(resolved))
        return resolved

    monkeypatch.setattr(path_policy, "resolve_safe_path", spy)
    mu.graph.add_file(mu.alice, SHARE_A, "gate.txt", b"gated")
    async with mu.leased(mu.alice) as service:
        conv = install_converter(service, RecordingConverter())
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
    assert result["success"]
    (call,) = conv.calls
    assert call["path"].resolve() in gated


# ----------------------------------------------------------------------
# F03 — A 와 B 가 같은 파일명을 동시에
# ----------------------------------------------------------------------
async def test_f03_same_name_for_two_users_concurrently(mu):
    mu.graph.add_file(mu.alice, SHARE_A, "report.txt", b"alice-content")
    mu.graph.add_file(mu.bob, SHARE_B, "report.txt", b"bob-content")
    barrier = threading.Barrier(2, timeout=10)
    seen = {}

    def hook(path):
        barrier.wait()          # 두 파일이 동시에 존재하는 순간을 만든다
        seen[Path(path).read_bytes()] = Path(path)

    async def run(principal, url):
        async with mu.leased(principal) as service:
            install_converter(service, RecordingConverter(hook))
            return await handlers.handle_convert_onedrive_to_text({"url": url})

    res_a, res_b = await asyncio.gather(run(mu.alice, SHARE_A), run(mu.bob, SHARE_B))

    assert res_a["text"].endswith("alice-content")
    assert res_b["text"].endswith("bob-content")
    assert _within(seen[b"alice-content"], mu.paths(mu.alice).tmp)
    assert _within(seen[b"bob-content"], mu.paths(mu.bob).tmp)
    assert seen[b"alice-content"] != seen[b"bob-content"]


# ----------------------------------------------------------------------
# F04 — 같은 사용자의 동시 생성
# ----------------------------------------------------------------------
async def test_f04_same_user_concurrent_downloads_do_not_overwrite(mu):
    share_1 = SHARE_A + "-1"
    share_2 = SHARE_A + "-2"
    mu.graph.add_file(mu.alice, share_1, "same.txt", b"first")
    mu.graph.add_file(mu.alice, share_2, "same.txt", b"second")
    barrier = threading.Barrier(2, timeout=10)
    seen = {}

    def hook(path):
        barrier.wait()
        seen[Path(path).read_bytes()] = Path(path)

    async with mu.leased(mu.alice) as service:
        install_converter(service, RecordingConverter(hook))

    async def run(url):
        async with mu.leased(mu.alice):
            return await handlers.handle_convert_onedrive_to_text({"url": url})

    r1, r2 = await asyncio.gather(run(share_1), run(share_2))
    assert r1["text"].endswith("first") and r2["text"].endswith("second")
    assert seen[b"first"] != seen[b"second"]
    assert seen[b"first"].parent != seen[b"second"].parent  # 요청별 디렉터리


async def test_f04_exclusive_create_in_same_directory(mu, tmp_path):
    """같은 디렉터리·같은 이름으로 동시에 받아도 덮어쓰지 않는다 (create_exclusive)."""
    id_1 = mu.graph.add_file(mu.alice, SHARE_A + "-x", "dup.txt", b"one")
    id_2 = mu.graph.add_file(mu.alice, SHARE_A + "-y", "dup.txt", b"two")
    target = mu.paths(mu.alice).downloads_for("file_handler")
    target.mkdir(parents=True, exist_ok=True)

    async with mu.leased(mu.alice) as service:
        client = service.manager.onedrive_processor.client
        scope = FileRequestScope(owner_key=mu.alice.user_key, loop=asyncio.get_running_loop())

        def download(item_id):
            with bind_scope(scope):
                return client.download_file(item_id, str(target / "dup.txt"))

        p1, p2 = await asyncio.gather(
            asyncio.to_thread(download, id_1), asyncio.to_thread(download, id_2)
        )
    assert p1 != p2
    assert {Path(p1).read_bytes(), Path(p2).read_bytes()} == {b"one", b"two"}


async def test_f04_concurrent_metadata_saves_have_no_lost_update(mu):
    urls = [f"https://contoso.sharepoint.com/doc-{i}.docx" for i in range(20)]

    async def save(url):
        async with mu.leased(mu.alice):
            return await handlers.handle_save_file_metadata({"file_url": url, "keywords": ["batch"]})

    results = await asyncio.gather(*(save(u) for u in urls))
    assert all(r["success"] for r in results)
    async with mu.leased(mu.alice):
        found = await handlers.handle_search_metadata({"keyword": "batch"})
    assert sorted(r["file_url"] for r in found["results"]) == sorted(urls)


# ----------------------------------------------------------------------
# F05 — A 의 cleanup 이 B 의 temp 를 지우지 않는다
# ----------------------------------------------------------------------
@pytest.mark.parametrize("second_user", ["bob", "alice"])
async def test_f05_cleanup_only_touches_own_request_dir(mu, second_user):
    other = mu.bob if second_user == "bob" else mu.alice
    other_share = SHARE_B if second_user == "bob" else SHARE_A + "-other"
    mu.graph.add_file(mu.alice, SHARE_A, "a.txt", b"aaa")
    mu.graph.add_file(other, other_share, "o.txt", b"ooo")

    started = threading.Event()
    release = threading.Event()
    observed = {}

    def hold(path):
        if Path(path).name == "o.txt":
            observed["path"] = Path(path)
            started.set()
            assert release.wait(10)

    async def run_other():
        async with mu.leased(other) as service:
            install_converter(service, RecordingConverter(hold))
            return await handlers.handle_convert_onedrive_to_text({"url": other_share})

    task = asyncio.create_task(run_other())
    assert await asyncio.to_thread(started.wait, 10)

    async with mu.leased(mu.alice) as service:
        if not any(isinstance(c, RecordingConverter) for c in service.manager.file_detector.converters):
            install_converter(service, RecordingConverter(hold))
        res_a = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
    assert res_a["success"]

    # A 의 요청은 끝나고 자기 temp 를 지웠지만, 진행 중인 다른 요청의 파일은 그대로다
    assert observed["path"].exists()
    release.set()
    res_other = await task
    assert res_other["success"] and res_other["text"].endswith("ooo")
    assert not observed["path"].exists()  # 그 요청도 끝나면 자기 것만 정리
