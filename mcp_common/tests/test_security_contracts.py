"""WP0 공용 계약 테스트 — principal·user_key·모드 정책·경로·서비스 풀 (spec/spec_멀티유저.md ②-11.1)."""

import asyncio
import os

import pytest

from mcp_common.errors import ToolExecutionError
from mcp_common.principal import (
    MISSING,
    Principal,
    assert_owner,
    assert_user_email,
    compute_user_key,
    current_principal,
    require_principal,
)
from mcp_common.security_contracts import AccessToken, BoundTokenProvider, ErrorCode, SecurityError, StartupConfigError
from mcp_common.security_policy import (
    assert_transport_allowed,
    ensure_deployment,
    get_policy,
    multi_user_enabled,
    startup_problems,
    validate_startup,
)
from mcp_common.service_context import bind_service, current_service, service_for
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode, single_user_mode
from mcp_common.user_paths import ensure_user_dirs, paths_for


def _code(exc_info) -> str:
    return exc_info.value.code


# ----------------------------------------------------------------------
# user_key / principal
# ----------------------------------------------------------------------
TID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
OID = "00000000-0000-0000-0000-0000000000a1"


def test_user_key_is_case_insensitive_sha256_of_tid_oid():
    k1 = compute_user_key(TID, OID)
    k2 = compute_user_key(TID.upper(), OID.upper())
    assert k1 == k2 and len(k1) == 64 and k1 == k1.lower()


def test_user_key_rejects_non_uuid():
    with pytest.raises(ValueError):
        compute_user_key("contoso", OID)


def test_same_email_different_oid_is_different_user():
    a = make_principal("same@contoso.com", object_id=OID)
    b = make_principal("same@contoso.com", object_id="00000000-0000-0000-0000-0000000000b2")
    assert a.user_key != b.user_key


def test_principal_rejects_bad_user_key():
    with pytest.raises(ValueError):
        Principal(user_key="../etc", tenant_id=TID, object_id=OID)


def test_require_principal_without_binding_fails():
    assert current_principal() is None
    with pytest.raises(SecurityError) as e:
        require_principal()
    assert _code(e) == ErrorCode.MISSING_PRINCIPAL


def test_bind_identity_resets_after_exception():
    alice = make_principal("alice@contoso.com")
    with pytest.raises(RuntimeError):
        with bound(alice):
            assert require_principal() is alice
            raise RuntimeError("boom")
    assert current_principal() is None


async def test_concurrent_bindings_do_not_leak_between_tasks():
    alice = make_principal("alice@contoso.com")
    bob = make_principal("bob@contoso.com")

    async def run(p):
        with bound(p):
            await asyncio.sleep(0)
            await asyncio.sleep(0.01)
            return require_principal().user_key

    a, b = await asyncio.gather(run(alice), run(bob))
    assert (a, b) == (alice.user_key, bob.user_key)


def test_security_error_is_tool_execution_error_with_fixed_payload():
    err = SecurityError(ErrorCode.IDENTITY_MISMATCH)
    assert isinstance(err, ToolExecutionError)
    assert err.payload["status"] == "error"
    assert err.payload["error"] == "identity_mismatch"
    assert SecurityError(ErrorCode.UNAUTHENTICATED).http_status == 401


def test_access_token_repr_hides_value():
    tok = AccessToken("SECRET-VALUE")
    assert "SECRET-VALUE" not in repr(tok)
    assert "SECRET-VALUE" not in str(tok)


# ----------------------------------------------------------------------
# user_email policy
# ----------------------------------------------------------------------
@pytest.mark.parametrize("given", [MISSING, "alice@contoso.com", " ALICE@Contoso.com ", "ａｌｉｃｅ@contoso.com"])
def test_assert_user_email_accepts_own_account(given):
    with bound(make_principal("alice@contoso.com")):
        assert assert_user_email(given) == "alice@contoso.com"


def test_assert_user_email_rejects_other_account():
    with bound(make_principal("alice@contoso.com")):
        with pytest.raises(SecurityError) as e:
            assert_user_email("bob@contoso.com")
    assert _code(e) == ErrorCode.IDENTITY_MISMATCH


@pytest.mark.parametrize("given", [None, "", "   ", 123, ["alice@contoso.com"]])
def test_assert_user_email_rejects_invalid_values(given):
    with bound(make_principal("alice@contoso.com")):
        with pytest.raises(SecurityError) as e:
            assert_user_email(given)
    assert _code(e) == ErrorCode.INVALID_USER_EMAIL


def test_assert_user_email_without_connected_account():
    with bound(make_principal(None)):
        with pytest.raises(SecurityError) as e:
            assert_user_email()
    assert _code(e) == ErrorCode.GRAPH_NOT_CONNECTED


def test_assert_owner_hides_other_users_resource():
    alice, bob = make_principal("alice@contoso.com"), make_principal("bob@contoso.com")
    with bound(alice):
        assert assert_owner(alice.user_key) is alice
        with pytest.raises(SecurityError) as e:
            assert_owner(bob.user_key)
    assert _code(e) == ErrorCode.NOT_FOUND


# ----------------------------------------------------------------------
# mode policy
# ----------------------------------------------------------------------
def test_default_mode_is_single_user():
    with single_user_mode():
        assert multi_user_enabled() is False
        assert startup_problems("stdio") == []


def test_multi_user_requires_absolute_data_root(monkeypatch):
    with single_user_mode():
        monkeypatch.setenv("MS365_MULTI_USER", "1")
        monkeypatch.setenv("MS365_DATA_ROOT", "relative/dir")
        from mcp_common.security_policy import reset_policy_cache

        reset_policy_cache()
        with pytest.raises(StartupConfigError):
            get_policy()
        monkeypatch.delenv("MS365_MULTI_USER")
        reset_policy_cache()


def test_multi_user_rejects_stdio(tmp_path):
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            assert_transport_allowed("stdio")
        assert_transport_allowed("http")


@pytest.mark.parametrize("key", ["MS365_DEFAULT_USER_EMAIL", "MCP_ALLOWED_PATHS", "MCP_DATA_DIR", "DB_PATH"])
def test_conflicting_env_blocks_startup(tmp_path, monkeypatch, key):
    monkeypatch.setenv(key, "x")
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            validate_startup("outlook", "http")


def test_validate_input_off_blocks_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_VALIDATE_INPUT", "0")
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            validate_startup("outlook", "http")


def test_missing_kek_provider_blocks_startup(tmp_path, monkeypatch):
    """KEK 미설정은 첫 토큰 접근이 아니라 기동 시점에 막혀야 한다 (②-12 5)."""
    from mcp_common.testing import TEST_AUTH_ENV

    for key, value in TEST_AUTH_ENV.items():
        monkeypatch.setenv(key, value)
    with multi_user_mode(tmp_path):
        validate_startup("outlook", "http")  # 설정이 갖춰지면 통과
    monkeypatch.delenv("MS365_KEK_PROVIDER")
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            validate_startup("outlook", "http")


def test_deployment_marker_is_created_once(tmp_path):
    with multi_user_mode(tmp_path):
        first = ensure_deployment()
        second = ensure_deployment()
    assert first["deployment_id"] == second["deployment_id"]


def test_foreign_marker_blocks_startup(tmp_path):
    (tmp_path / "system").mkdir()
    (tmp_path / "system" / "deployment.json").write_text('{"storage_format": "legacy"}', encoding="utf-8")
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            ensure_deployment()


# ----------------------------------------------------------------------
# paths
# ----------------------------------------------------------------------
def test_paths_are_disjoint_per_user(tmp_path):
    with multi_user_mode(tmp_path):
        a = paths_for(make_principal("alice@contoso.com"))
        b = paths_for(make_principal("bob@contoso.com"))
    assert a.root != b.root
    assert a.root.parent == b.root.parent == tmp_path.resolve() / "users"
    for field in ("auth_db", "onenote_db", "teams_db", "metadata_db", "outlook_db", "files"):
        assert getattr(a, field) != getattr(b, field)
    # 토큰·업무 DB 는 파일 도구 루트(files/) 밖
    assert a.files not in a.auth_db.parents and a.files not in a.onenote_db.parents


def test_paths_for_does_no_io(tmp_path):
    with multi_user_mode(tmp_path):
        p = paths_for(make_principal("alice@contoso.com"))
    assert not p.root.exists()
    ensure_user_dirs(p)
    assert p.files.is_dir() and p.auth_dir.is_dir() and p.tmp.is_dir()


@pytest.mark.parametrize("bad", ["../x", "", "A" * 64, "x" * 63])
def test_paths_for_rejects_bad_user_key(tmp_path, bad):
    with multi_user_mode(tmp_path):
        with pytest.raises(ValueError):
            paths_for(bad)


def test_request_tmp_rejects_traversal(tmp_path):
    with multi_user_mode(tmp_path):
        p = paths_for(make_principal())
    with pytest.raises(ValueError):
        p.request_tmp("../../x")
    assert p.request_tmp("abcdef0123456789").parent == p.tmp


# ----------------------------------------------------------------------
# service context / pool
# ----------------------------------------------------------------------
def test_service_for_mode0_returns_legacy():
    with single_user_mode():
        legacy = object()
        assert service_for("outlook", legacy=legacy) is legacy


def test_service_for_mode1_never_returns_legacy(tmp_path):
    with multi_user_mode(tmp_path):
        with pytest.raises(SecurityError):
            service_for("outlook", legacy=object())
        svc = object()
        with bind_service("outlook", svc):
            assert service_for("outlook", legacy=object()) is svc
        with pytest.raises(SecurityError):
            current_service("outlook")


def test_fake_token_provider_satisfies_protocol():
    assert isinstance(FakeTokenProvider(make_principal()), BoundTokenProvider)


async def test_fake_token_provider_rejects_other_email():
    p = FakeTokenProvider(make_principal("alice@contoso.com"))
    assert await p.validate_and_refresh_token("alice@contoso.com")
    with pytest.raises(SecurityError):
        await p.validate_and_refresh_token("bob@contoso.com")


class _Svc:
    instances = 0

    def __init__(self, principal, paths, tokens):
        _Svc.instances += 1
        self.principal, self.paths, self.tokens = principal, paths, tokens
        self.initialized = False
        self.closed = False

    async def initialize(self):
        await asyncio.sleep(0.01)
        self.initialized = True

    async def close(self):
        self.closed = True


async def _factory(principal, paths, tokens):
    return _Svc(principal, paths, tokens)


def _pool(**kw):
    pool = UserServicePool(token_provider_factory=FakeTokenProvider, **kw)
    pool.register("outlook", _factory)
    return pool


async def test_pool_isolates_users_and_dedupes_creation(tmp_path):
    alice, bob = make_principal("alice@contoso.com"), make_principal("bob@contoso.com")
    with multi_user_mode(tmp_path):
        pool = _pool()
        _Svc.instances = 0

        async def use(p):
            async with pool.lease("outlook", p) as svc:
                await asyncio.sleep(0.01)
                return svc

        a1, a2, b1 = await asyncio.gather(use(alice), use(alice), use(bob))
        assert a1 is a2 and a1 is not b1
        assert _Svc.instances == 2
        assert a1.initialized and a1.tokens.user_key == alice.user_key
        assert a1.paths.root != b1.paths.root and a1.paths.files.is_dir()
        await pool.close()
        assert a1.closed and b1.closed


async def test_pool_auth_epoch_change_retires_old_entry(tmp_path):
    with multi_user_mode(tmp_path):
        pool = _pool()
        p0 = make_principal("alice@contoso.com", auth_epoch=0)
        p1 = make_principal("alice@contoso.com", auth_epoch=1)
        async with pool.lease("outlook", p0) as old:
            pass
        async with pool.lease("outlook", p1) as new:
            assert new is not old
        assert old.closed and not new.closed
        await pool.close()


async def test_pool_invalidate_closes_only_that_user(tmp_path):
    with multi_user_mode(tmp_path):
        pool = _pool()
        alice, bob = make_principal("alice@contoso.com"), make_principal("bob@contoso.com")
        async with pool.lease("outlook", alice) as a:
            pass
        async with pool.lease("outlook", bob) as b:
            await pool.invalidate(alice.user_key)
            assert a.closed and a.tokens.closed
            assert not b.closed and not b.tokens.closed
        await pool.close()


async def test_pool_never_evicts_leased_entry_and_reports_overload(tmp_path):
    with multi_user_mode(tmp_path):
        pool = _pool(max_entries=1)
        alice, bob = make_principal("alice@contoso.com"), make_principal("bob@contoso.com")
        async with pool.lease("outlook", alice) as a:
            with pytest.raises(SecurityError) as e:
                async with pool.lease("outlook", bob):
                    pass
            assert e.value.code == ErrorCode.OVERLOADED
            assert not a.closed
        # 유휴가 되면 LRU 퇴거로 자리가 난다
        async with pool.lease("outlook", bob) as b:
            assert a.closed and not b.closed
        await pool.close()


async def test_pool_idle_ttl_eviction(tmp_path):
    now = [0.0]
    with multi_user_mode(tmp_path):
        pool = _pool(idle_ttl_seconds=10, clock=lambda: now[0])
        alice, bob = make_principal("alice@contoso.com"), make_principal("bob@contoso.com")
        async with pool.lease("outlook", alice) as a:
            pass
        now[0] = 11
        async with pool.lease("outlook", bob):
            pass
        assert a.closed
        await pool.close()


async def test_pool_failed_initialize_is_not_cached(tmp_path):
    calls = []

    class Broken:
        async def initialize(self):
            calls.append(1)
            return False

        async def close(self):
            pass

    async def factory(p, paths, tokens):
        return Broken()

    with multi_user_mode(tmp_path):
        pool = UserServicePool(token_provider_factory=FakeTokenProvider)
        pool.register("calendar", factory)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                async with pool.lease("calendar", make_principal()):
                    pass
        assert len(calls) == 2 and pool.stats()["entries"] == 0


# ----------------------------------------------------------------------
# Graph path segments (G01)
# ----------------------------------------------------------------------
from mcp_common.graph_paths import graph_drive_path, graph_error_summary, graph_segment  # noqa: E402


@pytest.mark.parametrize("bad", [None, "", "  ", ".", "..", "%2E%2E", "a\x00b", "a\nb"])
def test_graph_segment_rejects_dot_and_empty(bad):
    with pytest.raises(SecurityError) as e:
        graph_segment(bad)
    assert e.value.code == ErrorCode.NOT_FOUND


@pytest.mark.parametrize("value", ["../../users/bob@x.com", "..%2Fusers", "a/b?c#d", "https://graph.microsoft.com/v1.0/users/b"])
def test_graph_segment_never_contains_path_structure(value):
    out = graph_segment(value)
    assert "/" not in out and "?" not in out and "#" not in out


def test_graph_segment_keeps_plain_ids():
    assert graph_segment("AAMkAGI2TG93AAA=") == "AAMkAGI2TG93AAA%3D"
    assert graph_segment("19:abc@thread.v2") == "19%3Aabc%40thread.v2"


def test_graph_drive_path_encodes_each_component():
    assert graph_drive_path("/Docs/보고서 1.docx") == "Docs/%EB%B3%B4%EA%B3%A0%EC%84%9C%201.docx"
    for bad in ("../x", "a/../../users/b", "a\b", "./a"):
        with pytest.raises(SecurityError):
            graph_drive_path(bad)


def test_graph_error_summary_drops_message():
    s = graph_error_summary(500, {"error": {"code": "InternalServerError", "message": "secret detail"}})
    assert s == {"status_code": 500, "graph_error_code": "InternalServerError"}
    assert graph_error_summary(400, {"error": {"code": "bad code with spaces"}}) == {"status_code": 400}


# ----------------------------------------------------------------------
# migration freeze (R10)
# ----------------------------------------------------------------------
from mcp_common.security_policy import MIGRATION_LOCK_NAME, assert_legacy_store_not_frozen  # noqa: E402


def test_legacy_store_refused_while_migration_lock_present(tmp_path, monkeypatch):
    db = tmp_path / "database" / "auth.db"
    db.parent.mkdir()
    with single_user_mode():
        assert_legacy_store_not_frozen(db)  # 잠금 없음 → 통과
        (db.parent / MIGRATION_LOCK_NAME).write_text("{}", encoding="utf-8")
        with pytest.raises(StartupConfigError):
            assert_legacy_store_not_frozen(db)
        monkeypatch.setenv("MS365_MIGRATION_OVERRIDE", "1")
        assert_legacy_store_not_frozen(db)  # 운영자 명시 우회
    monkeypatch.delenv("MS365_MIGRATION_OVERRIDE")
    with multi_user_mode(tmp_path):
        assert_legacy_store_not_frozen(db)  # mode 1 은 legacy 저장소를 쓰지 않으므로 무관
