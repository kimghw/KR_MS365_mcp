"""WP2 — 단일 refresh 진입점: 다중 프로세스 직렬화(A03), 사용자 간 비직렬화(A04), 폐기 중 저장 차단(A05)."""

import asyncio
import multiprocessing
import secrets
import sqlite3
from dataclasses import asdict

import pytest

from mcp_common.security_contracts import AccessToken, BoundTokenProvider, ErrorCode, SecurityError
from mcp_common.user_paths import paths_for
from session import identity_registry as ir
from session import token_store
from session._mu_common import b64e
from session.file_lock import FileLock, refresh_lock_path
from session.tests.mu_support import ALICE, BOB, CLIENT_ID, register_with_key, seed_connected
from session.token_store import BoundGraphTokenProvider, get_graph_access_token
from session.user_crypto import KIND_GRAPH_TOKENS, open_sealed


async def _code(coro) -> str:
    with pytest.raises(SecurityError) as e:
        await coro
    return e.value.code


def _stored(principal):
    """DB 의 현재 토큰 묶음 (버전, payload)."""
    store = paths_for(principal.user_key)
    with sqlite3.connect(store.auth_db) as conn:
        row = conn.execute("SELECT ciphertext, nonce, token_version, dek_version, state FROM graph_tokens").fetchone()
    if row is None:
        return None
    payload = open_sealed(store, ciphertext=row[0], nonce=row[1], dek_version=row[3], app_id=CLIENT_ID,
                          kind=KIND_GRAPH_TOKENS, record_version=row[2])
    return row[2], payload, row[4]


# ----------------------------------------------------------------------
# 기본 동작
# ----------------------------------------------------------------------
async def test_fresh_token_is_returned_without_refresh(mu_root, fake_entra):
    principal, _, bundle = await seed_connected(ALICE, fake=fake_entra)
    token = await get_graph_access_token(principal)
    assert isinstance(token, AccessToken) and token.value == bundle["access_token"] and token.token_version == 1
    assert fake_entra.refresh_calls == 0


async def test_refresh_replaces_tokens_and_keeps_new_refresh_token(mu_root, fake_entra):
    principal, _, bundle = await seed_connected(ALICE, expires_in=30, fake=fake_entra)
    token = await get_graph_access_token(principal)
    assert token.value != bundle["access_token"] and token.token_version == 2
    version, payload, state = _stored(principal)
    assert version == 2 and state == "ok" and payload["refresh_token"] != bundle["refresh_token"]
    assert payload["refresh_token"] in fake_entra.refresh_tokens
    # 두 번째 호출은 새 토큰이 아직 유효하므로 endpoint 를 다시 부르지 않는다
    assert (await get_graph_access_token(principal)).value == token.value
    assert fake_entra.refresh_calls == 1


async def test_refresh_without_rotation_keeps_previous_refresh_token(mu_root, fake_entra):
    fake_entra.rotate_refresh = False
    principal, _, bundle = await seed_connected(ALICE, expires_in=30, fake=fake_entra)
    await get_graph_access_token(principal)
    assert _stored(principal)[1]["refresh_token"] == bundle["refresh_token"]


async def test_invalid_grant_marks_reauth_and_stops_hitting_endpoint(mu_root, fake_entra):
    principal, _, _ = await seed_connected(ALICE, expires_in=30, fake=fake_entra)
    fake_entra.refresh_error = "invalid_grant"
    assert await _code(get_graph_access_token(principal)) == ErrorCode.GRAPH_REAUTH_REQUIRED
    assert _stored(principal)[2] == "reauth_required"
    assert await _code(get_graph_access_token(principal)) == ErrorCode.GRAPH_REAUTH_REQUIRED
    assert fake_entra.refresh_calls == 1


async def test_transient_refresh_error_is_internal_without_detail(mu_root, fake_entra):
    principal, _, _ = await seed_connected(ALICE, expires_in=30, fake=fake_entra)
    fake_entra.refresh_error = "temporarily_unavailable"
    with pytest.raises(SecurityError) as e:
        await get_graph_access_token(principal)
    assert e.value.code == ErrorCode.INTERNAL_ERROR and "temporarily" not in str(e.value.payload)
    assert _stored(principal)[2] == "ok"  # 재인증 표시하지 않음


async def test_pending_link_user_is_not_connected(mu_root, fake_entra):
    _, key = register_with_key(ALICE)
    principal = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    assert await _code(get_graph_access_token(principal)) == ErrorCode.GRAPH_NOT_CONNECTED


async def test_lock_timeout_is_retryable_overloaded(mu_root, fake_entra, monkeypatch):
    principal, _, _ = await seed_connected(ALICE, expires_in=30, fake=fake_entra)
    monkeypatch.setattr(token_store, "LOCK_TIMEOUT_SECONDS", 0.2)
    holder = FileLock(refresh_lock_path(principal.user_key, CLIENT_ID))
    holder.acquire()
    try:
        assert await _code(get_graph_access_token(principal)) == ErrorCode.OVERLOADED
    finally:
        holder.release()
    assert fake_entra.refresh_calls == 0
    assert (await get_graph_access_token(principal)).token_version == 2


async def test_cancel_while_waiting_for_lock_does_not_leak_it(mu_root, fake_entra):
    principal, _, _ = await seed_connected(ALICE, expires_in=30, fake=fake_entra)
    path = refresh_lock_path(principal.user_key, CLIENT_ID)
    holder = FileLock(path)
    holder.acquire()
    task = asyncio.create_task(get_graph_access_token(principal))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    holder.release()
    probe = FileLock(path, timeout=1)
    probe.acquire()  # 취소된 대기자가 lock 을 쥐고 있지 않다
    probe.release()


# ----------------------------------------------------------------------
# A03 — 두 OS 프로세스가 같은 사용자를 동시에 갱신
# ----------------------------------------------------------------------
def test_a03_two_processes_refresh_once_and_keep_new_refresh_token(mu_root, monkeypatch, tmp_path):
    from session.tests.mu_proc import TokenEndpoint, refresh_worker

    kek = b64e(secrets.token_bytes(32))
    monkeypatch.setenv("MS365_KEK_PROVIDER", "env")
    monkeypatch.setenv("MS365_KEK_B64", kek)
    with TokenEndpoint(valid_refresh="rt-seed", delay=1.0) as endpoint:
        monkeypatch.setenv("MS365_ENTRA_AUTHORITY_HOST", endpoint.base_url)
        principal, _, _ = asyncio.run(seed_connected(ALICE, refresh="rt-seed", expires_in=30))
        import os

        env = {k: os.environ[k] for k in os.environ if k.startswith(("MS365_", "AZURE_"))}
        fields = asdict(principal)
        fields["scopes"] = sorted(fields["scopes"])
        go_file = str(tmp_path / "go")
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        procs = [ctx.Process(target=refresh_worker, args=(env, fields, go_file, queue)) for _ in range(2)]
        for proc in procs:
            proc.start()
        try:
            ready = [queue.get(timeout=60) for _ in procs]
            assert all(kind == "ready" for kind, _ in ready), ready
            open(go_file, "w").close()
            results = [queue.get(timeout=60) for _ in procs]
        finally:
            for proc in procs:
                proc.join(timeout=30)
                if proc.is_alive():
                    proc.kill()
        assert results == [("token", "at-new-1"), ("token", "at-new-1")], results
        assert len(endpoint.calls) == 1, "token endpoint 는 한 번만 호출돼야 한다"
        assert endpoint.calls[0]["refresh_token"] == "rt-seed"
    version, payload, _ = _stored(principal)
    assert version == 2 and payload["refresh_token"] == "rt-new-1"


# ----------------------------------------------------------------------
# A04 — A 와 B 의 갱신은 서로를 기다리지 않는다
# ----------------------------------------------------------------------
async def test_a04_refresh_of_a_and_b_is_not_serialized(mu_root, fake_entra):
    pa, _, _ = await seed_connected(ALICE, expires_in=30, fake=fake_entra)
    pb, _, _ = await seed_connected(BOB, expires_in=30, fake=fake_entra)
    arrived = []
    both_inside = asyncio.Event()

    async def barrier(_refresh_token):
        arrived.append(1)
        if len(arrived) == 2:
            both_inside.set()
        await asyncio.wait_for(both_inside.wait(), timeout=5)  # 직렬화되면 여기서 시간 초과

    fake_entra.on_refresh = barrier
    ta, tb = await asyncio.gather(get_graph_access_token(pa), get_graph_access_token(pb))
    assert ta.value.startswith("at-aaaaaaaa") and tb.value.startswith("at-bbbbbbbb")
    assert fake_entra.refresh_calls == 2


async def test_same_user_concurrent_calls_in_one_process_refresh_once(mu_root, fake_entra):
    principal, _, _ = await seed_connected(ALICE, expires_in=30, fake=fake_entra)

    async def slow(_rt):
        await asyncio.sleep(0.2)

    fake_entra.on_refresh = slow
    tokens = await asyncio.gather(*(get_graph_access_token(principal) for _ in range(5)))
    assert len({t.value for t in tokens}) == 1 and fake_entra.refresh_calls == 1


# ----------------------------------------------------------------------
# A05 — 갱신 도중 비활성·연결 해제·키 폐기
# ----------------------------------------------------------------------
async def test_a05_disable_during_refresh_blocks_save_and_new_calls(mu_root, fake_entra):
    principal, _, bundle = await seed_connected(ALICE, expires_in=30, fake=fake_entra)

    async def disable(_rt):
        ir.set_status(principal.user_key, "disabled")

    fake_entra.on_refresh = disable
    assert await _code(get_graph_access_token(principal)) == ErrorCode.ACCOUNT_INACTIVE
    version, payload, _ = _stored(principal)
    assert version == 1 and payload["refresh_token"] == bundle["refresh_token"]  # 저장되지 않음
    fake_entra.on_refresh = None
    assert await _code(get_graph_access_token(principal)) == ErrorCode.ACCOUNT_INACTIVE
    assert fake_entra.refresh_calls == 1  # 비활성 이후 token endpoint 호출 없음


async def test_a05_disconnect_during_refresh_waits_for_lock_then_wins(mu_root, fake_entra):
    """갱신이 lock 을 쥔 동안 들어온 연결 해제는 기다렸다가(N02) 그 뒤에 epoch 를 올리고 토큰을 지운다.
    갱신 결과가 되살아나지 않고 (pending_link + 토큰 없음) 으로 끝난다."""
    principal, _, _ = await seed_connected(ALICE, expires_in=30, fake=fake_entra)
    disconnect = {}

    async def disconnect_concurrently(_rt):
        disconnect["task"] = asyncio.create_task(asyncio.to_thread(ir.disconnect_graph, principal.user_key))
        await asyncio.sleep(0.3)
        assert not disconnect["task"].done()  # 해제는 갱신의 lock 을 기다리는 중이다

    fake_entra.on_refresh = disconnect_concurrently
    token = await get_graph_access_token(principal)  # 갱신은 끝까지 간다 (저장·반환)
    assert token.token_version == 2
    await disconnect["task"]
    assert _stored(principal) is None
    assert ir.get_user(principal.user_key).status == "pending_link"
    assert await _code(get_graph_access_token(principal)) == ErrorCode.ACCOUNT_INACTIVE
    assert fake_entra.refresh_calls == 1


async def test_a05_key_revoked_during_refresh_still_saves_rotated_token(mu_root, fake_entra):
    """키 폐기는 사용자 토큰 저장을 막지 않는다(회전된 refresh token 보존). 그 키로 온 요청의 차단은
    런타임이 요청 principal 로 부르는 `assert_active()` 의 몫이다."""
    principal, _, bundle = await seed_connected(ALICE, expires_in=30, fake=fake_entra)

    async def revoke(_rt):
        ir.revoke_key(principal.credential_id)

    fake_entra.on_refresh = revoke
    token = await get_graph_access_token(principal)
    version, payload, _ = _stored(principal)
    assert version == 2 and token.token_version == 2 and payload["refresh_token"] != bundle["refresh_token"]
    assert await _code(ir.assert_active(principal)) == ErrorCode.ACCOUNT_INACTIVE


async def test_token_store_is_credential_agnostic_for_cached_provider(mu_root, fake_entra):
    """풀에 캐시된 공급자의 principal 키가 폐기·만료돼도 같은 사용자·epoch 면 토큰을 준다."""
    principal, _, bundle = await seed_connected(ALICE, fake=fake_entra)
    second = ir.issue_key(principal.user_key, ["calendar"])
    provider = BoundGraphTokenProvider(principal)  # 첫 키 principal 로 만든 캐시 공급자
    ir.revoke_key(principal.credential_id)
    assert (await provider.get_graph_token()).value == bundle["access_token"]
    p2 = await ir.authenticate_bearer(f"Bearer {second.key}", domain="calendar")
    await ir.assert_active(p2)
    login = await provider.get_auth_url_for_login()
    assert "/auth/graph/connect?ticket=" in login["connect_url"]
    # 비활성은 여전히 막힌다
    ir.set_status(principal.user_key, "disabled")
    assert await _code(provider.get_graph_token()) == ErrorCode.ACCOUNT_INACTIVE


# ----------------------------------------------------------------------
# BoundGraphTokenProvider / mcp_common.auth
# ----------------------------------------------------------------------
async def test_bound_provider_contract(mu_root, fake_entra):
    principal, _, bundle = await seed_connected(ALICE, fake=fake_entra)
    provider = BoundGraphTokenProvider(principal)
    assert isinstance(provider, BoundTokenProvider) and provider.user_key == principal.user_key
    assert await provider.validate_and_refresh_token() == bundle["access_token"]
    assert await provider.validate_and_refresh_token(" ALICE@contoso.com ", auto_reauth=True) == bundle["access_token"]
    assert await _code(provider.validate_and_refresh_token("bob@contoso.com")) == ErrorCode.IDENTITY_MISMATCH
    assert await _code(provider.validate_and_refresh_token("")) == ErrorCode.INVALID_USER_EMAIL
    assert (await provider.get_graph_token()).value == bundle["access_token"]
    await provider.close()
    assert (await provider.get_graph_token()).value == bundle["access_token"]  # close 는 no-op
    login = await provider.get_auth_url_for_login("alice@contoso.com")
    assert login["status"] == "auth_required" and "/auth/graph/connect?ticket=" in login["connect_url"]
    assert principal.user_key[:12] in repr(provider) and bundle["access_token"] not in repr(provider)


async def test_mcp_common_auth_mode_guards(mu_root, fake_entra):
    from mcp_common import auth
    from mcp_common.testing import single_user_mode
    from session.mode_guard import LegacyAuthDisabledError

    principal, _, _ = await seed_connected(ALICE, fake=fake_entra)
    with pytest.raises(LegacyAuthDisabledError):
        auth.get_shared_auth_manager()
    provider = auth.get_bound_token_provider(principal)
    assert isinstance(provider, BoundTokenProvider)
    details = auth.graph_connect_details(principal)
    assert set(details) == {"connect_url", "expires_in"} and details["expires_in"] == 300
    assert details["connect_url"].startswith("http://localhost:5000/auth/graph/connect?ticket=")
    with single_user_mode():
        with pytest.raises(LegacyAuthDisabledError):
            auth.get_bound_token_provider(principal)


async def test_service_pool_default_factory_uses_bound_provider(mu_root, fake_entra):
    from mcp_common.service_pool import UserServicePool

    principal, _, bundle = await seed_connected(ALICE, fake=fake_entra)

    class Svc:
        def __init__(self, tokens):
            self.tokens = tokens

        async def close(self):
            pass

    async def factory(p, paths, tokens):
        return Svc(tokens)

    pool = UserServicePool()
    pool.register("outlook", factory)
    async with pool.lease("outlook", principal) as svc:
        assert isinstance(svc.tokens, BoundGraphTokenProvider)
        assert (await svc.tokens.get_graph_token()).value == bundle["access_token"]
    await pool.close()
