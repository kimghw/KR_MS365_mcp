"""
Teams 멀티유저 격리 (spec/spec_멀티유저.md ②-7.3, ②-7.6, ②-10 D04·F01).

- mode 1 DB 는 사용자별 `db/teams.db` — auth.db 를 쓰지 않는다.
- 같은 chat_id 를 A·B 가 써도 topic·한글 이름·활성 상태가 독립이다 (D04).
- mode 0 구버전 auth.db 의 teams_chats 는 데이터 손실 없이 owner_key 를 얻는다.
- 진입점은 호출 principal·user_email 을 확인하고, file_path 는 본인 files/ 안만 연다.

Graph 는 부르지 않는다.
"""

import base64
import logging
import sqlite3
from unittest.mock import AsyncMock

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_context import bind_service
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode
from mcp_common.user_paths import ensure_user_dirs, paths_for
from mcp_teams.graph_teams_client import GraphTeamsClient
from mcp_teams.mcp_server import handlers
from mcp_teams.storage_schema import LegacySchemaError, ensure_storage
from mcp_teams.teams_db_manager import TeamsDBManager
from mcp_teams.teams_service import TeamsService

A = "alice@contoso.com"
B = "bob@contoso.com"
KA = "a" * 64
KB = "b" * 64
SHARED = "19:shared@thread.v2"


def _chat(cid, topic, members=()):
    return {"id": cid, "chatType": "group", "topic": topic, "members": list(members)}


def _rows(path, chat_id):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT owner_key, user_id, topic, topic_kr, is_active FROM teams_chats WHERE chat_id = ? ORDER BY user_id",
        (chat_id,),
    )]
    conn.close()
    return rows


# ----------------------------------------------------------------------
# DB 수준
# ----------------------------------------------------------------------
class TestSameChatIdIndependent:
    async def _d04(self, alice_db, bob_db, path):
        await alice_db.sync_chats_to_db(A, [_chat(SHARED, "Alice topic"), _chat("19:a-only", "x")])
        await bob_db.sync_chats_to_db(B, [_chat(SHARED, "Bob topic")])

        saved = await alice_db.save_korean_name(A, "앨리스 이름", chat_id=SHARED)
        assert saved["saved"] is True
        # B 는 A 만의 채팅에 한글 이름을 저장할 수 없다 (자기 범위에 없음)
        assert (await bob_db.save_korean_name(B, "침범", chat_id="19:a-only"))["saved"] is False

        # B 가 전체 목록 동기화로 SHARED 를 비활성화해도 A 는 활성 그대로
        await bob_db.sync_chats_to_db(B, [])
        rows = {r["user_id"]: r for r in _rows(path, SHARED)}
        assert rows[A]["topic"] == "Alice topic" and rows[A]["topic_kr"] == "앨리스 이름"
        assert rows[A]["is_active"] == 1
        assert rows[B]["topic"] == "Bob topic" and rows[B]["topic_kr"] is None
        assert rows[B]["is_active"] == 0

        assert await alice_db.find_chat_by_name(A, "Alice") == SHARED
        assert await bob_db.find_chat_by_name(B, "Alice") is None
        assert [c["chat_id"] for c in await bob_db.get_chats_with_korean_names(B)] == []

    async def test_d04_fixed_owner_on_shared_file(self, tmp_path):
        path = str(tmp_path / "teams.db")
        await self._d04(TeamsDBManager(path, owner_key=KA), TeamsDBManager(path, owner_key=KB), path)

    async def test_d04_mode0_two_emails_same_file(self, tmp_path):
        path = str(tmp_path / "auth.db")
        db = TeamsDBManager(path)
        await self._d04(db, db, path)

    async def test_fixed_owner_ignores_passed_user_id(self, tmp_path):
        path = str(tmp_path / "teams.db")
        alice, bob = TeamsDBManager(path, owner_key=KA), TeamsDBManager(path, owner_key=KB)
        await bob.sync_chats_to_db(B, [_chat(SHARED, "Bob topic")])
        # A 의 DB 관리자에게 B 의 이메일을 넘겨도 B 의 행이 보이지 않는다
        assert await alice.find_chat_by_name(B, "Bob") is None
        assert await alice.get_chats_with_korean_names(B) == []

    def test_user_db_never_uses_auth_db(self, tmp_path):
        with pytest.raises(ValueError):
            TeamsDBManager(str(tmp_path / "auth.db"), owner_key=KA)

    def test_missing_owner_never_runs_unscoped_sql(self, tmp_path):
        db = TeamsDBManager(str(tmp_path / "auth.db"))
        with pytest.raises(ValueError):
            db._owner(None)

    def test_mode1_requires_owner_key(self, tmp_path):
        with multi_user_mode(tmp_path / "root"):
            with pytest.raises(RuntimeError):
                TeamsDBManager(str(tmp_path / "teams.db"))

    async def test_logs_do_not_contain_names_or_ids(self, tmp_path, caplog):
        db = TeamsDBManager(str(tmp_path / "teams.db"), owner_key=KA)
        caplog.set_level(logging.DEBUG, logger="mcp_teams")
        await db.sync_chats_to_db(A, [_chat("19:SECRET-CHAT", "SECRET-TOPIC")])
        await db.find_chat_by_name(A, "SECRET-TOPIC")
        await db.find_chat_by_name(A, "SECRET-NAME")
        await db.save_korean_name(A, "비밀이름", chat_id="19:SECRET-CHAT")
        text = "\n".join(r.getMessage() for r in caplog.records)
        for secret in ("SECRET-CHAT", "SECRET-TOPIC", "SECRET-NAME", "비밀이름", A):
            assert secret not in text


_LEGACY_SQL = """
CREATE TABLE teams_chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    chat_type TEXT DEFAULT 'unknown',
    topic TEXT, topic_kr TEXT,
    member_count INTEGER DEFAULT 0, members_json TEXT,
    peer_user_name TEXT, peer_user_email TEXT,
    last_message_preview TEXT, last_message_time TEXT,
    last_sent_at TEXT, last_received_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_sync_at TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(user_id, chat_id)
);
CREATE TABLE azure_user_info (user_email TEXT PRIMARY KEY, access_token TEXT);
INSERT INTO azure_user_info VALUES ('alice@contoso.com', 'opaque');
INSERT INTO teams_chats (user_id, chat_id, topic, topic_kr, is_active)
    VALUES ('alice@contoso.com', '19:shared@thread.v2', 'Legacy topic', '레거시', TRUE);
"""


class TestLegacyMigration:
    async def test_mode0_auth_db_table_gains_owner_key_without_loss(self, tmp_path):
        path = str(tmp_path / "auth.db")
        conn = sqlite3.connect(path)
        conn.executescript(_LEGACY_SQL)
        conn.close()

        db = TeamsDBManager(path)

        assert await db.find_chat_by_name(A, "레거시") == SHARED
        rows = _rows(path, SHARED)
        assert rows == [{"owner_key": A, "user_id": A, "topic": "Legacy topic", "topic_kr": "레거시", "is_active": 1}]
        # 다른 테이블(인증 정보)은 건드리지 않는다
        conn = sqlite3.connect(path)
        assert conn.execute("SELECT COUNT(*) FROM azure_user_info").fetchone()[0] == 1
        conn.close()
        # 이전 후 upsert 가 (owner_key, chat_id) 로 동작하고 한글 이름을 보존한다
        await db.sync_chats_to_db(A, [_chat(SHARED, "New topic")])
        assert _rows(path, SHARED)[0]["topic_kr"] == "레거시"
        assert _rows(path, SHARED)[0]["topic"] == "New topic"
        TeamsDBManager(path)  # 재실행해도 문제없다

    def test_user_db_with_legacy_table_is_rejected(self, tmp_path):
        path = str(tmp_path / "teams.db")
        conn = sqlite3.connect(path)
        conn.executescript(_LEGACY_SQL)
        conn.close()
        with pytest.raises(LegacySchemaError):
            TeamsDBManager(path, owner_key=KA)


# ----------------------------------------------------------------------
# 서비스·factory·핸들러
# ----------------------------------------------------------------------
@pytest.fixture
def mu(tmp_path):
    with multi_user_mode(tmp_path / "root") as root:
        yield root


async def _user_service(principal):
    paths = ensure_user_dirs(paths_for(principal))
    tokens = FakeTokenProvider(principal)
    svc = await handlers.create_service(principal, paths, tokens)
    assert await svc.initialize()
    return svc, tokens, paths


@pytest.fixture
async def users(mu):
    alice, bob = make_principal(A), make_principal(B)
    a_svc, a_tok, a_paths = await _user_service(alice)
    b_svc, b_tok, b_paths = await _user_service(bob)
    yield {"alice": alice, "bob": bob, "a": a_svc, "b": b_svc,
           "a_tok": a_tok, "b_tok": b_tok, "a_paths": a_paths, "b_paths": b_paths}
    await a_svc.close()
    await b_svc.close()


class TestFactoryIsolation:
    async def test_factory_constructs_only(self, mu):
        alice = make_principal(A)
        paths = paths_for(alice)
        svc = await handlers.create_service(alice, paths, FakeTokenProvider(alice))
        assert isinstance(svc, TeamsService)
        assert svc._db_manager is None and svc._client is None
        assert not paths.teams_db.exists()

    async def test_users_get_own_teams_db_not_auth_db(self, users):
        a, b = users["a"], users["b"]
        assert a._db_manager.db_path == str(users["a_paths"].teams_db)
        assert b._db_manager.db_path == str(users["b_paths"].teams_db)
        assert a._db_manager.db_path != b._db_manager.db_path
        assert not users["a_paths"].auth_db.exists()
        assert a._client.token_provider is users["a_tok"]
        await a.close()
        assert users["a_tok"].closed is False

    async def test_pool_lease_isolates(self, mu):
        pool = UserServicePool(token_provider_factory=FakeTokenProvider)
        pool.register(handlers.SERVER_NAME, handlers.create_service)
        alice, bob = make_principal(A), make_principal(B)
        async with pool.lease(handlers.SERVER_NAME, alice) as a_svc:
            async with pool.lease(handlers.SERVER_NAME, bob) as b_svc:
                assert a_svc is not b_svc
                assert a_svc._db_manager.db_path != b_svc._db_manager.db_path
        await pool.close()

    def test_graph_client_without_provider_fails_in_mode1(self, mu):
        with pytest.raises(SecurityError):
            GraphTeamsClient()

    async def test_d04_through_services(self, users):
        for key, email, topic in (("a", A, "Alice topic"), ("b", B, "Bob topic")):
            svc = users[key]
            svc._client.list_chats = AsyncMock(return_value={
                "success": True, "chats": [_chat(SHARED, topic)], "count": 1, "has_more": False,
            })
            with bound(users["alice" if key == "a" else "bob"]):
                assert (await svc.sync_chats(user_email=email))["synced"] == 1
        with bound(users["alice"]):
            assert (await users["a"].save_korean_name(topic_kr="앨리스", chat_id=SHARED))["saved"] is True
            assert (await users["a"].get_chats_without_korean())["count"] == 0
        with bound(users["bob"]):
            found = await users["b"].find_chat_by_name(recipient_name="앨리스")
        assert found["found"] is False


class TestCallerChecks:
    async def test_other_users_email_is_identity_mismatch(self, users):
        users["a"]._client.list_chats = AsyncMock(return_value={"success": True, "chats": []})
        with bound(users["alice"]):
            with pytest.raises(SecurityError) as exc:
                await users["a"].list_chats(user_email=B)
        assert exc.value.code == ErrorCode.IDENTITY_MISMATCH
        users["a"]._client.list_chats.assert_not_awaited()

    async def test_service_of_other_principal_is_not_found(self, users):
        with bound(users["bob"]):
            with pytest.raises(SecurityError) as exc:
                await users["a"].list_teams(user_email=B)
        assert exc.value.code == ErrorCode.NOT_FOUND

    async def test_omitted_email_uses_own_account_without_default_lookup(self, users, monkeypatch):
        import mcp_teams.teams_service as svc_mod

        monkeypatch.setattr(svc_mod, "_get_default_user_email", lambda: pytest.fail("기본 사용자 조회 금지"))
        users["a"]._client.list_teams = AsyncMock(return_value={"success": True, "teams": []})
        with bound(users["alice"]):
            await users["a"].list_teams()
        users["a"]._client.list_teams.assert_awaited_once_with(A)

    async def test_token_mismatch_propagates(self, users):
        with pytest.raises(SecurityError) as exc:
            await users["a"]._client._get_access_token(B)
        assert exc.value.code == ErrorCode.IDENTITY_MISMATCH

    async def test_handler_uses_leased_service_and_never_falls_back(self, users):
        users["a"]._client.list_teams = AsyncMock(return_value={"success": True, "teams": [], "count": 0})
        with bound(users["alice"]), bind_service(handlers.SERVER_NAME, users["a"]):
            assert (await handlers.handle_list_teams({"user_email": A}))["success"] is True
        with bound(users["alice"]):
            with pytest.raises(SecurityError) as exc:
                await handlers.handle_list_teams({"user_email": A})
        assert exc.value.code == ErrorCode.MISSING_PRINCIPAL

    def test_user_email_contract_unchanged(self):
        for tool in handlers.MCP_TOOLS:
            prop = tool["inputSchema"]["properties"]["user_email"]
            assert prop["type"] == "string"
            assert "user_email" not in tool["inputSchema"].get("required", [])
            assert "다른 계정은 선택할 수 없다" in prop["description"]


class TestFilePathPolicy:
    PDF = b"%PDF-1.7 test"

    def _send(self, users):
        svc = users["a"]
        svc._client.send_chat_file = AsyncMock(return_value={"success": True, "message_id": "m1"})
        return svc

    async def test_relative_and_absolute_inside_own_files_root(self, users):
        svc = self._send(users)
        (users["a_paths"].uploads / "증빙.pdf").write_bytes(self.PDF)
        with bound(users["alice"]):
            await svc.send_chat_file(content="x", file_path="uploads/증빙.pdf")
            await svc.send_chat_file(content="x", file_path=str(users["a_paths"].uploads / "증빙.pdf"))
        calls = svc._client.send_chat_file.await_args_list
        assert [c.kwargs["file_name"] for c in calls] == ["증빙.pdf", "증빙.pdf"]
        assert all(c.kwargs["file_bytes"] == self.PDF for c in calls)
        assert all(c.kwargs["user_email"] == A for c in calls)

    @pytest.mark.parametrize("bad", [
        "../{other}/files/uploads/b.pdf",
        "uploads/../../../{other}/files/uploads/b.pdf",
        "{abs_other}",
        "\\\\server\\share\\b.pdf",
        "//server/share/b.pdf",
        "uploads/b.pdf:secret",
        "C:b.pdf",
        "uploads/CON",
        "",
    ])
    async def test_paths_outside_own_files_root_are_rejected(self, users, bad):
        svc = self._send(users)
        other_file = users["b_paths"].uploads / "b.pdf"
        other_file.write_bytes(self.PDF)
        bad = bad.format(other=users["bob"].user_key, abs_other=str(other_file))
        with bound(users["alice"]):
            if bad == "":
                result = await svc.send_chat_file(content="x", file_path=bad)
                assert result["success"] is False
            else:
                with pytest.raises(SecurityError) as exc:
                    await svc.send_chat_file(content="x", file_path=bad)
                assert exc.value.code == ErrorCode.PATH_NOT_ALLOWED
        svc._client.send_chat_file.assert_not_awaited()

    async def test_auth_and_db_dirs_are_outside_files_root(self, users):
        svc = self._send(users)
        with bound(users["alice"]):
            for bad in (str(users["a_paths"].teams_db), "../db/teams.db", "../auth/auth.db"):
                with pytest.raises(SecurityError):
                    await svc.send_chat_file(content="x", file_path=bad)

    async def test_missing_file_inside_root_reports_without_path(self, users):
        svc = self._send(users)
        with bound(users["alice"]):
            result = await svc.send_chat_file(content="x", file_path="uploads/none.pdf")
        assert result["success"] is False
        assert str(users["a_paths"].root) not in result["error"]

    async def test_base64_still_works_in_mode1(self, users):
        svc = self._send(users)
        with bound(users["alice"]):
            result = await svc.send_chat_file(
                content="x", file_name="a.pdf", file_base64=base64.b64encode(self.PDF).decode()
            )
        assert result["success"] is True


async def test_ensure_storage_creates_teams_db(tmp_path):
    with multi_user_mode(tmp_path / "root"):
        alice = make_principal(A)
        paths = paths_for(alice)
        ensure_storage(alice, paths)
        assert paths.teams_db.is_file()
        with pytest.raises(SecurityError):
            ensure_storage(make_principal(B), paths)


# ----------------------------------------------------------------------
# 런타임 경유 (WP1 ToolRuntime → 서비스 풀 lease → 핸들러)
# ----------------------------------------------------------------------
@pytest.fixture
async def runtime_pool(mu, monkeypatch):
    from mcp_common.service_pool import get_service_pool, reset_service_pool_for_tests

    async def _active(principal):
        return None

    monkeypatch.setattr(handlers.runtime, "active_checker", _active)
    reset_service_pool_for_tests(UserServicePool(token_provider_factory=FakeTokenProvider))
    pool = get_service_pool()
    yield pool
    await pool.close()
    reset_service_pool_for_tests()


async def test_d04_through_runtime_dispatch(runtime_pool):
    import json

    alice, bob = make_principal(A), make_principal(B)
    for principal, email, topic in ((alice, A, "Alice topic"), (bob, B, "Bob topic")):
        async with runtime_pool.lease(handlers.SERVER_NAME, principal) as svc:
            await svc._db_manager.sync_chats_to_db(email, [_chat(SHARED, topic)])

    with bound(alice):
        saved = json.loads((await handlers.runtime.call(
            "handler_teams_save_korean_name", {"topic_kr": "앨리스", "chat_id": SHARED}
        ))[0]["text"])
    assert saved["saved"] is True

    with bound(bob):
        found = json.loads((await handlers.runtime.call(
            "handler_teams_find_chat_by_name", {"recipient_name": "앨리스"}
        ))[0]["text"])
        missing = json.loads((await handlers.runtime.call(
            "handler_teams_get_chats_without_korean", {"user_email": B}
        ))[0]["text"])
    assert found["found"] is False
    assert missing["count"] == 0  # 그룹 채팅이라 peer 없음 — B 행은 그대로, A 의 이름이 섞이지 않음
    async with runtime_pool.lease(handlers.SERVER_NAME, bob) as b_svc:
        rows = await b_svc._db_manager.get_chats_with_korean_names(B)
    assert [(r["topic"], r["topic_kr"]) for r in rows] == [("Bob topic", None)]


# ----------------------------------------------------------------------
# G01 — 호출자 ID 가 Graph 경로 구조를 바꾸지 못한다 / ②-9 오류 본문 비노출 (두 모드 공통)
# ----------------------------------------------------------------------
def _endpoint_client():
    provider = AsyncMock(validate_and_refresh_token=AsyncMock(return_value="t"))
    client = GraphTeamsClient(token_provider=provider)
    calls = []

    async def fake_request(method, endpoint, user_email, json_data=None, timeout=30):
        calls.append((method, endpoint))
        return {"success": True, "data": {"id": "x", "value": []}}

    client._make_request = fake_request
    client._upload_chat_file = AsyncMock(return_value={"success": False, "error": "no"})
    return client, calls


def _teams_id_calls(client, value):
    return [
        lambda: client.get_chat(A, value),
        lambda: client.get_chat_messages(A, value),
        lambda: client.send_chat_message(A, "hi", chat_id=value),
        lambda: client.send_chat_file(A, "hi", "a.pdf", b"x", chat_id=value),
        lambda: client.list_channels(A, value),
        lambda: client.get_channel_messages(A, value, "c"),
        lambda: client.get_channel_messages(A, "t", value),
        lambda: client.send_channel_message(A, value, "c", "hi"),
        lambda: client.get_message_replies(A, "t", "c", value),
    ]


@pytest.mark.parametrize("value", ["..", ".", "%2e%2e", "a\nb"])
async def test_dot_segment_ids_are_rejected_before_any_request(value):
    client, calls = _endpoint_client()
    for call in _teams_id_calls(client, value):
        with pytest.raises(SecurityError) as exc:
            await call()
        assert exc.value.code == ErrorCode.NOT_FOUND
    assert calls == []
    client._upload_chat_file.assert_not_awaited()


@pytest.mark.parametrize("value", [f"../../users/{B}", "../../../../$batch", f"..%2F..%2Fusers%2F{B}"])
async def test_slash_ids_are_encoded_as_one_segment(value):
    from urllib.parse import quote

    client, calls = _endpoint_client()
    for call in _teams_id_calls(client, value):
        await call()
    encoded = quote(value, safe="")
    assert calls
    for _, endpoint in calls:
        assert ".." not in endpoint.split("?")[0].split("/"), endpoint
        assert encoded in endpoint, endpoint


async def test_upload_file_name_cannot_escape_chat_files_folder():
    client = GraphTeamsClient(token_provider=AsyncMock(validate_and_refresh_token=AsyncMock(return_value="t")))
    with pytest.raises(SecurityError):
        await client._upload_chat_file(A, "..", b"x")


class _Resp:
    status = 500

    async def text(self):
        return '{"error":{"code":"InternalServerError","message":"CANARY-BODY"}}'

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def test_graph_error_body_is_not_returned():
    client = GraphTeamsClient(token_provider=AsyncMock(validate_and_refresh_token=AsyncMock(return_value="t")))
    client._session = type("S", (), {"request": lambda self, *a, **k: _Resp(), "put": lambda self, *a, **k: _Resp()})()
    client._initialized = True
    for result in (await client.list_chats(A), await client._upload_chat_file(A, "a.pdf", b"x")):
        assert result["success"] is False
        assert "CANARY-BODY" not in str(result) and "details" not in result
        assert result["status_code"] == 500 and result["graph_error_code"] == "InternalServerError"


# ----------------------------------------------------------------------
# R08 — bearer 요청은 redirect 를 따라가지 않는다 / R12 — 검증한 handle 에서 읽는다
# ----------------------------------------------------------------------
import os  # noqa: E402
from pathlib import Path  # noqa: E402


class _RedirectResp:
    status = 302
    headers = {"Location": "https://evil.example/CANARY-LOCATION"}

    async def text(self):
        return ""

    async def json(self):
        return {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _KwargsSession:
    def __init__(self):
        self.kwargs = []

    def request(self, *args, **kwargs):
        self.kwargs.append(kwargs)
        return _RedirectResp()

    put = request


async def test_redirects_are_not_followed_and_not_leaked():
    client = GraphTeamsClient(token_provider=AsyncMock(validate_and_refresh_token=AsyncMock(return_value="t")))
    client._session = _KwargsSession()
    client._initialized = True
    results = [
        await client.list_chats(A),
        await client.get_chat(A, "19:c"),
        await client.send_chat_message(A, "hi", chat_id="19:c"),
        await client._upload_chat_file(A, "a.pdf", b"x"),
    ]
    for result in results:
        assert result["success"] is False and result["status_code"] == 302, result
        assert "CANARY-LOCATION" not in str(result) and "details" not in result
    assert len(client._session.kwargs) == 4
    assert all(k.get("allow_redirects") is False for k in client._session.kwargs)


def _spy_open_for_read(monkeypatch):
    import mcp_teams.teams_service as svc_mod
    from mcp_common import secure_files

    seen = []

    def spy(path, root):
        seen.append((Path(os.path.realpath(path)), Path(os.path.realpath(root))))
        return secure_files.open_for_read(path, root)

    monkeypatch.setattr(svc_mod, "open_for_read", spy)
    return seen


async def test_mode1_send_file_reads_through_verified_handle(users, monkeypatch):
    seen = _spy_open_for_read(monkeypatch)
    svc = users["a"]
    svc._client.send_chat_file = AsyncMock(return_value={"success": True, "message_id": "m1"})
    target = users["a_paths"].uploads / "증빙.pdf"
    target.write_bytes(b"%PDF-1.7 r12")

    with bound(users["alice"]):
        result = await svc.send_chat_file(content="x", file_path="uploads/증빙.pdf")

    assert result["success"] is True
    assert svc._client.send_chat_file.await_args.kwargs["file_bytes"] == b"%PDF-1.7 r12"
    assert seen == [(Path(os.path.realpath(target)), Path(os.path.realpath(users["a_paths"].files)))]


async def test_mode1_hardlinked_file_inside_files_root_is_refused(users):
    svc = users["a"]
    svc._client.send_chat_file = AsyncMock(return_value={"success": True})
    source = users["a_paths"].db_dir / "secret.bin"
    source.write_bytes(b"secret")
    link = users["a_paths"].uploads / "leak.pdf"
    try:
        os.link(source, link)
    except OSError:
        pytest.skip("hard links not supported here")

    with bound(users["alice"]):
        with pytest.raises(SecurityError) as exc:
            await svc.send_chat_file(content="x", file_path="uploads/leak.pdf")
    assert exc.value.code == ErrorCode.PATH_NOT_ALLOWED
    svc._client.send_chat_file.assert_not_awaited()


async def test_mode0_send_file_reads_only_within_allowed_roots(tmp_path, monkeypatch):
    seen = _spy_open_for_read(monkeypatch)
    monkeypatch.setenv("MCP_ALLOWED_PATHS", str(tmp_path))
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.7 mode0")
    svc = TeamsService()
    svc._client = AsyncMock()
    svc._client.send_chat_file = AsyncMock(return_value={"success": True})
    svc._initialized = True

    result = await svc.send_chat_file(content="x", file_path=str(tmp_path / "a.pdf"), user_email=A)
    assert result["success"] is True
    assert seen == [(Path(os.path.realpath(tmp_path / "a.pdf")), Path(os.path.realpath(tmp_path)))]

    outside = tmp_path.parent / "outside.pdf"  # 허용 루트 밖 — 읽지 않고, 경로도 응답에 싣지 않는다
    result = await svc.send_chat_file(content="x", file_path=str(outside), user_email=A)
    assert result["success"] is False and "허용 루트 밖" in result["error"]
    assert str(tmp_path.parent) not in result["error"]
    assert len(seen) == 1


# ----------------------------------------------------------------------
# R02 — limit 1~1000 · names ≤ 500 을 서비스 경계에서 막는다 (Graph·DB 작업 전)
# N01 — 다단계 전송(구성원 조회 → 업로드 → 권한 → 메시지)은 단계마다 토큰을 새로 받는다
# ----------------------------------------------------------------------
import json as _json  # noqa: E402

from mcp_common.errors import ToolExecutionError  # noqa: E402
from mcp_teams.teams_types import check_limit, check_list_size  # noqa: E402


def _invalid(exc_info):
    payload = exc_info.value.payload
    assert payload["error"] == "invalid_argument", payload
    return payload


@pytest.mark.parametrize("bad", [0, -5, 1001, "x", True, None])
def test_check_limit_rejects_out_of_range(bad):
    with pytest.raises(ToolExecutionError) as exc:
        check_limit(bad)
    _invalid(exc)


def test_check_list_size_rejects_over_cap_and_non_lists():
    check_list_size(None, "names")
    check_list_size([{}] * 500, "names")
    with pytest.raises(ToolExecutionError) as exc:
        check_list_size([{}] * 501, "names")
    assert _invalid(exc)["maximum"] == 500
    with pytest.raises(ToolExecutionError):
        check_list_size("not-a-list", "names")


def _mode0_service():
    svc = TeamsService()
    svc._client = AsyncMock()
    svc._db_manager = AsyncMock()
    svc._initialized = True
    return svc


@pytest.mark.parametrize("call", [
    lambda s: s.list_chats(user_email=A, limit=5000),
    lambda s: s.get_chat_messages(chat_id="19:c", user_email=A, limit=0),
    lambda s: s.get_channel_messages(team_id="t", channel_id="c", user_email=A, limit=1001),
    lambda s: s.sync_chats(user_email=A, limit=-1),
])
async def test_service_rejects_bad_limit_before_graph(call):
    svc = _mode0_service()
    with pytest.raises(ToolExecutionError) as exc:
        await call(svc)
    _invalid(exc)
    assert not svc._client.method_calls


async def test_service_rejects_oversized_names_before_db():
    svc = _mode0_service()
    with pytest.raises(ToolExecutionError) as exc:
        await svc.save_korean_names_batch(names=[{"topic_en": "a", "topic_kr": "ㄱ"}] * 501, user_email=A)
    _invalid(exc)
    assert not svc._db_manager.method_calls


class _JsonResp:
    def __init__(self, payload):
        self.status = 200
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return _json.dumps(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _StepSession:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        return _JsonResp(self._payload)

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url))
        return _JsonResp(self._payload)


class _RevokingProvider(FakeTokenProvider):
    """n 번째 토큰 발급 직후 연결이 폐기된 공급자 — 이후 발급은 graph_not_connected."""

    def __init__(self, principal, *, revoke_after: int):
        super().__init__(principal)
        self._revoke_after = revoke_after

    async def validate_and_refresh_token(self, email=None, auto_reauth=False):
        token = await super().validate_and_refresh_token(email, auto_reauth)
        if self.calls.count("validate_and_refresh_token") >= self._revoke_after:
            self.connected = False
        return token


async def test_n01_revocation_between_send_file_steps_stops_before_upload():
    provider = _RevokingProvider(make_principal(A), revoke_after=1)
    client = GraphTeamsClient(token_provider=provider)
    client._session = _StepSession({"value": [{"email": "peer@contoso.com"}], "id": "x"})
    client._initialized = True

    with pytest.raises(SecurityError) as exc:
        await client.send_chat_file(A, "hi", "a.pdf", b"%PDF", chat_id="19:group")

    assert exc.value.code == ErrorCode.GRAPH_NOT_CONNECTED
    assert [m for m, _ in client._session.calls] == ["GET"]  # 구성원 조회만; 업로드·메시지는 나가지 않았다


async def test_each_send_file_step_fetches_a_fresh_token():
    provider = FakeTokenProvider(make_principal(A))
    client = GraphTeamsClient(token_provider=provider)
    client._session = _StepSession({
        "value": [{"email": "peer@contoso.com"}], "id": "item-1",
        "eTag": "{5E1D1C9A-0000-4000-8000-123456789ABC},1", "webDavUrl": "https://x/a.pdf", "name": "a.pdf",
    })
    client._initialized = True

    result = await client.send_chat_file(A, "hi", "a.pdf", b"%PDF", chat_id="19:group")

    assert result["success"] is True
    steps = [m for m, _ in client._session.calls]
    assert steps == ["GET", "PUT", "GET", "POST", "POST"]  # 구성원·업로드·상세·권한·메시지
    assert provider.calls.count("validate_and_refresh_token") == len(steps)
