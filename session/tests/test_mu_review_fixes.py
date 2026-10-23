"""WP2 — Astra 보안 검토(spec/reviews/멀티유저_astra_2026-10-23.md) 회귀:
R01 현재 요청 키 재검사, R03 동시 OAuth 완료 직렬화, R13 pending 상한 원자성, R04 삭제 전 drain."""

import asyncio
import sqlite3
import threading
import time
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_pool import UserServicePool, reset_service_pool_for_tests
from mcp_common.testing import bound
from mcp_common.user_paths import paths_for
from session import _registry_db as reg
from session import graph_connect, token_store
from session import identity_registry as ir
from session._mu_common import iso, utcnow
from session.app_settings import load_app_settings
from session.auth_gateway import create_app
from session.graph_connect import COOKIE_PREFIX, MAX_PENDING_ATTEMPTS
from session.tests.mu_support import ALICE, BOB, CLIENT_ID, register_with_key, seed_connected
from session.token_store import BoundGraphTokenProvider, get_graph_access_token
from session.user_crypto import KIND_GRAPH_TOKENS, open_sealed


async def _code(coro) -> str:
    with pytest.raises(SecurityError) as e:
        await coro
    return e.value.code


def _token_rows(user_key: str):
    with sqlite3.connect(paths_for(user_key).auth_db) as conn:
        return conn.execute("SELECT token_version, ciphertext, nonce, dek_version FROM graph_tokens").fetchall()


def _stored_access(user_key: str):
    rows = _token_rows(user_key)
    if not rows:
        return None
    version, ciphertext, nonce, dek_version = rows[0]
    return open_sealed(paths_for(user_key), ciphertext=ciphertext, nonce=nonce, dek_version=dek_version,
                       app_id=CLIENT_ID, kind=KIND_GRAPH_TOKENS, record_version=version)["access_token"]


# ----------------------------------------------------------------------
# R01 — 토큰 반환 직전 현재 요청 identity 의 키 재검사
# ----------------------------------------------------------------------
async def test_r01_revoked_request_key_is_refused_even_with_warm_provider(mu_root, fake_entra):
    """풀 공급자는 첫 lease 키(p1)에 묶여 있고 그 키는 유효하다. 슬롯을 기다리던 요청의 키(p2)가
    폐기되면 그 요청은 토큰을 받지 못해야 한다 — 공급자 키를 봐서는 알 수 없는 상황."""
    p1, _, bundle = await seed_connected(ALICE, fake=fake_entra)
    second = ir.issue_key(p1.user_key, ["calendar"])
    p2 = await ir.authenticate_bearer(f"Bearer {second.key}", domain="calendar")
    provider = BoundGraphTokenProvider(p1)
    assert (await provider.get_graph_token()).value == bundle["access_token"]  # warm

    ir.revoke_key(p2.credential_id)
    with bound(p2):
        assert await _code(provider.get_graph_token()) == ErrorCode.ACCOUNT_INACTIVE
        assert await _code(provider.validate_and_refresh_token("alice@contoso.com")) == ErrorCode.ACCOUNT_INACTIVE
        assert await _code(provider.get_token()) == ErrorCode.ACCOUNT_INACTIVE
        assert await _code(get_graph_access_token(p1)) == ErrorCode.ACCOUNT_INACTIVE
    # 공급자 키(p1)로 들어온 다른 요청과 identity 없는 호출(백그라운드)은 그대로 된다
    with bound(p1):
        assert (await provider.get_graph_token()).value == bundle["access_token"]
    assert (await provider.get_graph_token()).value == bundle["access_token"]
    assert fake_entra.refresh_calls == 0


async def test_r01_expired_request_key_and_stale_epoch_are_refused(mu_root, fake_entra):
    p1, _, _ = await seed_connected(ALICE, fake=fake_entra)
    second = ir.issue_key(p1.user_key, ["calendar"])
    p2 = await ir.authenticate_bearer(f"Bearer {second.key}", domain="calendar")
    provider = BoundGraphTokenProvider(p1)
    ir.get_user(p1.user_key).store().shorten_credential(p2.credential_id, iso(utcnow() - timedelta(seconds=1)))
    with bound(p2):
        assert await _code(provider.get_graph_token()) == ErrorCode.ACCOUNT_INACTIVE
    with bound(p1):
        await provider.get_graph_token()


async def test_r01_bound_identity_of_another_user_is_refused(mu_root, fake_entra):
    pa, _, _ = await seed_connected(ALICE, fake=fake_entra)
    pb, _, _ = await seed_connected(BOB, fake=fake_entra)
    provider = BoundGraphTokenProvider(pa)
    with bound(pb):
        assert await _code(provider.get_graph_token()) == ErrorCode.INTERNAL_ERROR
        assert await _code(get_graph_access_token(pa)) == ErrorCode.INTERNAL_ERROR
    with bound(pa):
        await provider.get_graph_token()


# ----------------------------------------------------------------------
# R03 — 같은 사용자의 동시 OAuth 완료
# ----------------------------------------------------------------------
def _start_and_connect(app, key: str):
    client = TestClient(app, base_url="http://localhost:5000")
    started = client.post("/auth/graph/start", headers={"Authorization": f"Bearer {key}"}).json()
    from urllib.parse import urlsplit

    parts = urlsplit(started["connect_url"])
    resp = client.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert resp.status_code == 302
    cookie_name = COOKIE_PREFIX + started["attempt_id"]
    return started["attempt_id"], resp.headers["location"], {cookie_name: client.cookies.get(cookie_name)}


async def test_r03_interleaved_double_completion_keeps_one_token_and_active_registry(mu_root, fake_entra):
    record, key = register_with_key(ALICE)
    app = create_app(entra=fake_entra, jwks_client=fake_entra.jwks)
    att1, url1, cookies1 = _start_and_connect(app, key)
    att2, url2, cookies2 = _start_and_connect(app, key)
    code1, state1 = fake_entra.login(url1, ALICE)
    code2, state2 = fake_entra.login(url2, ALICE)

    # 두 콜백 모두 토큰 교환·ID token 검증·/me 까지 끝낸 뒤에야 저장 단계로 들어가게 한다
    original_me = fake_entra.get_me
    gate, arrived = asyncio.Event(), []

    async def gated_me(access_token):
        arrived.append(1)
        if len(arrived) == 2:
            gate.set()
        await asyncio.wait_for(gate.wait(), 5)
        return await original_me(access_token)

    fake_entra.get_me = gated_me
    settings = load_app_settings()
    results = await asyncio.gather(
        graph_connect.complete_callback({"code": code1, "state": state1}, cookies1, settings=settings,
                                        entra=fake_entra, jwks_client=fake_entra.jwks),
        graph_connect.complete_callback({"code": code2, "state": state2}, cookies2, settings=settings,
                                        entra=fake_entra, jwks_client=fake_entra.jwks),
    )
    assert sorted(r.code for r in results) == ["account_changed", "connected"]
    rows = _token_rows(record.user_key)
    assert len(rows) == 1 and rows[0][0] == 1  # 정확히 하나, 두 번째 완료는 저장하지 않았다
    assert fake_entra.access[_stored_access(record.user_key)] == ALICE
    user = ir.get_user(record.user_key)
    assert user.status == "active" and user.auth_epoch == 1 and user.graph_email == ALICE.email
    statuses = sorted(record.store().get_attempt(a)["status"] for a in (att1, att2))
    assert statuses == ["completed", "failed"]
    principal = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    assert fake_entra.access[(await get_graph_access_token(principal)).value] == ALICE


async def test_r03_commit_is_serialized_and_second_never_touches_tokens(mu_root, fake_entra):
    record, _ = register_with_key(ALICE)
    bundles = []
    for n in (1, 2):
        at, rt = f"at-commit-{n}", f"rt-commit-{n}"
        fake_entra.access[at] = ALICE
        fake_entra.refresh_tokens[rt] = ALICE
        bundles.append({"access_token": at, "refresh_token": rt, "expires_at": iso(utcnow() + timedelta(hours=1)),
                        "scope": "x"})
    outcomes = await asyncio.gather(
        *(token_store.commit_graph_connection(record, b, expected_epoch=0, graph_email=ALICE.email)
          for b in bundles),
        return_exceptions=True,
    )
    epochs = [o for o in outcomes if isinstance(o, int)]
    errors = [o for o in outcomes if isinstance(o, SecurityError)]
    assert epochs == [1] and len(errors) == 1 and errors[0].code == ErrorCode.ACCOUNT_INACTIVE
    rows = _token_rows(record.user_key)
    assert len(rows) == 1 and rows[0][0] == 1
    assert _stored_access(record.user_key) in ("at-commit-1", "at-commit-2")
    assert ir.get_user(record.user_key).auth_epoch == 1


def _in_thread(fn, *args):
    """스레드에서 실행하고 (thread, outcome dict) 를 돌려준다 — 예외는 outcome["error"]."""
    outcome = {}

    def run():
        try:
            outcome["result"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - 테스트에서 검사
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


async def test_r03_disconnect_during_commit_waits_for_lock_then_wins(mu_root, fake_entra, monkeypatch):
    """확정이 lock 을 쥐고 저장하는 동안 들어온 해제는 기다렸다가 확정 뒤에 실행된다 → (pending_link, 토큰 없음)."""
    record, _ = register_with_key(ALICE)
    original_save = token_store._save
    disconnect = {}

    def save_with_concurrent_disconnect(store, app_id, bundle, **kw):
        if "thread" not in disconnect:
            disconnect["thread"], disconnect["outcome"] = _in_thread(ir.disconnect_graph, record.user_key)
            time.sleep(0.3)
            assert disconnect["thread"].is_alive()  # 해제는 확정의 lock 을 기다리는 중
        return original_save(store, app_id, bundle, **kw)

    monkeypatch.setattr(token_store, "_save", save_with_concurrent_disconnect)
    bundle = {"access_token": "at-x", "refresh_token": "rt-x", "expires_at": iso(utcnow() + timedelta(hours=1)),
              "scope": "x"}
    assert await token_store.commit_graph_connection(record, bundle, expected_epoch=0, graph_email=ALICE.email) == 1
    await asyncio.to_thread(disconnect["thread"].join)
    assert "error" not in disconnect["outcome"]
    assert _token_rows(record.user_key) == []
    user = ir.get_user(record.user_key)
    assert user.status == "pending_link" and user.graph_email is None and user.auth_epoch == 2
    # 이후 정상 확정은 된다
    assert await token_store.commit_graph_connection(user, bundle, expected_epoch=2, graph_email=ALICE.email) == 3
    assert len(_token_rows(record.user_key)) == 1 and ir.get_user(record.user_key).status == "active"


async def test_n02_new_epoch_commit_during_disconnect_never_leaves_active_without_tokens(mu_root, fake_entra,
                                                                                         monkeypatch):
    """해제가 epoch 를 올린 직후 새 epoch 로 시작한 확정이 들어와도 해제의 삭제 단계가 그 토큰을 지우지 못한다.

    해제는 lock 을 epoch 를 올리기 전에 잡으므로 확정은 해제가 끝난 뒤 실행되고 (active + 토큰) 으로 끝난다.
    어느 쪽이 이기든 (active + 토큰) 또는 (pending_link + 토큰 없음) 이어야 한다."""
    principal, _, _ = await seed_connected(ALICE, fake=fake_entra)
    user = ir.get_user(principal.user_key)
    assert user.status == "active" and user.auth_epoch == 1
    original_unlink = reg.mark_graph_unlinked
    bundle = {"access_token": "at-n02", "refresh_token": "rt-n02",
              "expires_at": iso(utcnow() + timedelta(hours=1)), "scope": "x"}
    commit = {}

    def unlink_then_commit_for_new_epoch(user_key):
        new_epoch = original_unlink(user_key)  # 해제의 epoch 증가 (lock 안)
        commit["thread"], commit["outcome"] = _in_thread(
            lambda: asyncio.run(token_store.commit_graph_connection(
                user, bundle, expected_epoch=new_epoch, graph_email=ALICE.email)))
        time.sleep(0.3)
        assert commit["thread"].is_alive()  # 새 epoch 확정은 해제의 lock 을 기다린다 — 삭제 단계 전에 끼어들 수 없다
        return new_epoch

    monkeypatch.setattr(reg, "mark_graph_unlinked", unlink_then_commit_for_new_epoch)
    await asyncio.to_thread(ir.disconnect_graph, principal.user_key)
    await asyncio.to_thread(commit["thread"].join)
    assert "error" not in commit["outcome"] and commit["outcome"]["result"] == 3

    final = ir.get_user(principal.user_key)
    rows = _token_rows(principal.user_key)
    assert (final.status == "active" and len(rows) == 1) or (final.status == "pending_link" and rows == [])
    assert final.status == "active" and rows[0][0] == 1 and _stored_access(principal.user_key) == "at-n02"


def test_r03_discard_is_version_conditional(mu_root, fake_entra):
    record, _ = register_with_key(ALICE)
    bundle = {"access_token": "at-y", "refresh_token": "rt-y", "expires_at": iso(utcnow() + timedelta(hours=1)),
              "scope": "x"}
    v1 = asyncio.run(token_store.store_connected_tokens(record, bundle))
    v2 = asyncio.run(token_store.store_connected_tokens(record, bundle))
    assert (v1, v2) == (1, 2)
    assert token_store.discard_tokens_version(record, v1) is False  # 더 새 버전이 있으면 지우지 않는다
    assert len(_token_rows(record.user_key)) == 1
    assert token_store.discard_tokens_version(record, v2) is True
    assert _token_rows(record.user_key) == []


# ----------------------------------------------------------------------
# R13 — 병렬 start 도 pending 상한을 넘기지 못한다
# ----------------------------------------------------------------------
async def test_r13_parallel_starts_never_exceed_pending_cap(mu_root, fake_entra):
    record, key = register_with_key(ALICE)
    principal = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    links = await asyncio.gather(*(asyncio.to_thread(graph_connect.create_connect_attempt, principal)
                                   for _ in range(8)))
    assert len({link.attempt_id for link in links}) == 8
    active = record.store().active_attempts()
    assert len(active) == MAX_PENDING_ATTEMPTS
    with sqlite3.connect(paths_for(record.user_key).auth_db) as conn:
        superseded = conn.execute("SELECT COUNT(*) FROM oauth_attempts WHERE status = 'superseded'").fetchone()[0]
    assert superseded == 8 - MAX_PENDING_ATTEMPTS
    # 살아남은 3개의 ticket 은 소비할 수 있고, 밀려난 것은 안 된다
    alive = {a["attempt_id"] for a in active}
    for link in links:
        from urllib.parse import parse_qs, urlsplit

        ticket = parse_qs(urlsplit(link.connect_url).query)["ticket"][0]
        if link.attempt_id in alive:
            graph_connect.begin_browser_flow(ticket)
        else:
            with pytest.raises(graph_connect.ConnectError):
                graph_connect.begin_browser_flow(ticket)


# ----------------------------------------------------------------------
# R04 — 삭제 전 이 프로세스 풀의 사용자 작업 drain
# ----------------------------------------------------------------------
class _DrainPool(UserServicePool):
    def __init__(self, *, outcome):
        super().__init__()
        self.outcome = outcome
        self.calls = []

    async def drain(self, user_key, *, timeout):
        self.calls.append((user_key, timeout))
        await asyncio.sleep(0)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


@pytest.fixture
def pool_reset():
    yield
    reset_service_pool_for_tests()


async def test_r04_delete_drains_pool_before_removing_files(mu_root, fake_entra, pool_reset):
    principal, _, _ = await seed_connected(ALICE, fake=fake_entra)
    pool = _DrainPool(outcome=True)
    reset_service_pool_for_tests(pool)
    ir.delete_user(principal.user_key, drain_timeout=7)
    assert pool.calls == [(principal.user_key, 7)]
    assert not paths_for(principal.user_key).root.exists() and ir.get_user(principal.user_key) is None


@pytest.mark.parametrize("outcome", [False, TimeoutError("drain")])
async def test_r04_drain_failure_stops_before_deleting_and_is_resumable(mu_root, fake_entra, pool_reset, outcome):
    principal, key, _ = await seed_connected(ALICE, fake=fake_entra)
    pool = _DrainPool(outcome=outcome)
    reset_service_pool_for_tests(pool)
    with pytest.raises(ir.AdminError):
        ir.delete_user(principal.user_key)
    paths = paths_for(principal.user_key)
    assert paths.auth_db.exists() and ir.get_user(principal.user_key).status == "deleting"
    # 새 요청은 이미 막혀 있다
    assert await _code(ir.authenticate_bearer(f"Bearer {key}", domain="outlook")) == ErrorCode.ACCOUNT_INACTIVE
    assert await _code(ir.assert_active(principal)) == ErrorCode.ACCOUNT_INACTIVE
    # drain 이 되면 같은 명령으로 이어서 끝난다
    pool.outcome = True
    ir.delete_user(principal.user_key)
    assert not paths.root.exists() and ir.get_user(principal.user_key) is None


def test_r04_pool_without_drain_falls_back_to_invalidate(mu_root, fake_entra, pool_reset):
    record, _ = register_with_key(ALICE)
    calls = []

    class _NoDrainPool(UserServicePool):
        drain = None  # drain() 이 없는 풀 (구버전 계약)

        async def invalidate(self, user_key):
            calls.append(user_key)

    pool = _NoDrainPool()
    reset_service_pool_for_tests(pool)
    ir.delete_user(record.user_key)
    assert calls == [record.user_key] and ir.get_user(record.user_key) is None
