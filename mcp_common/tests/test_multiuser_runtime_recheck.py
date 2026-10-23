"""lease 획득 후 현재 요청 키 재검사(R01)와 사용자 drain(R04) — astra 재검토 반영."""

import asyncio

import pytest

from mcp_common import service_pool
from mcp_common.runtime import ToolRuntime
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode

DOMAIN = "wp0recheck"
ALICE = make_principal("alice@contoso.com")
SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}


class _Svc:
    def __init__(self):
        self.calls = 0
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.fixture
def pool():
    p = UserServicePool(token_provider_factory=FakeTokenProvider, per_user_concurrency=1)
    service_pool.reset_service_pool_for_tests(p)
    yield p
    service_pool.reset_service_pool_for_tests()


async def test_key_revoked_while_waiting_for_slot_never_runs_handler(tmp_path, pool):
    """슬롯 대기 중 키가 폐기되면 핸들러(→ 외부 호출)가 실행되지 않아야 한다."""
    revoked = {"flag": False}
    checks = []

    async def active_checker(principal):
        checks.append(revoked["flag"])
        if revoked["flag"]:
            raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)

    svc = _Svc()

    async def factory(principal, paths, tokens):
        return svc

    pool.register(DOMAIN, factory)
    handler_ran = []

    async def handler(args):
        handler_ran.append(args)
        return {"ok": True}

    runtime = ToolRuntime(DOMAIN, [{"name": "t", "inputSchema": SCHEMA}], {"t": handler}, active_checker=active_checker)

    with multi_user_mode(tmp_path):
        # 첫 요청이 유일한 슬롯을 점유한 채 멈춘다
        holder_started = asyncio.Event()
        release = asyncio.Event()

        async def hold():
            async with pool.lease(DOMAIN, ALICE):
                holder_started.set()
                await release.wait()

        holder = asyncio.create_task(hold())
        await holder_started.wait()

        async def victim():
            with bound(ALICE):
                return await runtime.call("t", {"q": "x"})

        victim_task = asyncio.create_task(victim())
        await asyncio.sleep(0.05)  # 대기열 진입(진입 전 검사는 통과한 상태)
        revoked["flag"] = True  # 대기 중 폐기
        release.set()
        await holder

        with pytest.raises(SecurityError) as e:
            await victim_task
        assert e.value.code == ErrorCode.ACCOUNT_INACTIVE
        assert handler_ran == []  # 외부 호출로 이어지는 핸들러는 실행되지 않았다
        assert checks[0] is False and True in checks  # 진입 전 통과, lease 후 재검사에서 차단


async def test_drain_waits_for_inflight_then_closes(tmp_path, pool):
    svc = _Svc()

    async def factory(principal, paths, tokens):
        return svc

    pool.register(DOMAIN, factory)
    with multi_user_mode(tmp_path):
        inside = asyncio.Event()
        release = asyncio.Event()

        async def work():
            async with pool.lease(DOMAIN, ALICE):
                inside.set()
                await release.wait()

        task = asyncio.create_task(work())
        await inside.wait()
        assert pool.inflight(ALICE.user_key) == 1

        drain_task = asyncio.create_task(pool.drain(ALICE.user_key, timeout=2))
        await asyncio.sleep(0.05)
        assert not drain_task.done() and not svc.closed  # 사용 중이면 기다린다
        # drain 중에는 같은 사용자의 새 lease 가 기존(무효화된) 항목을 재사용하지 않는다
        release.set()
        await task
        assert await drain_task is True
        assert svc.closed and pool.inflight(ALICE.user_key) == 0


async def test_drain_times_out_without_closing_busy_entry(tmp_path, pool):
    svc = _Svc()

    async def factory(principal, paths, tokens):
        return svc

    pool.register(DOMAIN, factory)
    with multi_user_mode(tmp_path):
        inside, release = asyncio.Event(), asyncio.Event()

        async def work():
            async with pool.lease(DOMAIN, ALICE):
                inside.set()
                await release.wait()

        task = asyncio.create_task(work())
        await inside.wait()
        assert await pool.drain(ALICE.user_key, timeout=0.1) is False
        assert not svc.closed  # 실행 중 항목을 강제 퇴거하지 않는다
        release.set()
        await task
        assert svc.closed  # 마지막 lease 가 끝나면 무효화된 항목은 닫힌다


async def test_lease_refused_while_draining_and_invalid_entry_not_rejoined(tmp_path, pool):
    """astra 2차 N04 — drain 중 admission 차단, 무효 항목은 사용 중이라도 재lease 금지."""
    svc = _Svc()

    async def factory(principal, paths, tokens):
        return svc

    pool.register(DOMAIN, factory)
    with multi_user_mode(tmp_path):
        inside, release = asyncio.Event(), asyncio.Event()

        async def work():
            async with pool.lease(DOMAIN, ALICE):
                inside.set()
                await release.wait()

        task = asyncio.create_task(work())
        await inside.wait()
        await pool.invalidate(ALICE.user_key)  # 사용 중이라 항목은 남지만 invalid
        with pytest.raises(SecurityError) as e:
            async with pool.lease(DOMAIN, ALICE):
                pass
        assert e.value.code == ErrorCode.ACCOUNT_INACTIVE

        drain_task = asyncio.create_task(pool.drain(ALICE.user_key, timeout=2))
        await asyncio.sleep(0.02)
        with pytest.raises(SecurityError):
            async with pool.lease(DOMAIN, ALICE):
                pass
        release.set()
        await task
        assert await drain_task is True
        assert svc.closed


async def test_drain_waits_for_slow_close(tmp_path, pool):
    """마지막 lease 가 끝난 뒤 close() 가 오래 걸려도 drain 은 close 완료까지 기다린다."""
    closing = asyncio.Event()
    finish_close = asyncio.Event()

    class Slow:
        closed = False

        async def close(self):
            closing.set()
            await finish_close.wait()
            self.closed = True

    svc = Slow()

    async def factory(principal, paths, tokens):
        return svc

    pool.register(DOMAIN, factory)
    with multi_user_mode(tmp_path):
        inside, release = asyncio.Event(), asyncio.Event()

        async def work():
            async with pool.lease(DOMAIN, ALICE):
                inside.set()
                await release.wait()

        task = asyncio.create_task(work())
        await inside.wait()
        drain_task = asyncio.create_task(pool.drain(ALICE.user_key, timeout=2))
        await asyncio.sleep(0.02)
        release.set()
        await closing.wait()  # 마지막 lease 가 close() 에 들어갔다
        await asyncio.sleep(0.05)
        assert not drain_task.done()  # close 가 끝나기 전엔 drain 도 안 끝난다
        finish_close.set()
        await task
        assert await drain_task is True and svc.closed


async def test_drain_waits_for_lru_eviction_close_and_times_out(tmp_path):
    """astra 3차 N04 — LRU 퇴거로 시작된 close 도 drain 이 기다리고, 멈추면 timeout 으로 False."""
    pool = UserServicePool(token_provider_factory=FakeTokenProvider, max_entries=1)
    service_pool.reset_service_pool_for_tests(pool)
    finish_close = asyncio.Event()

    class Slow:
        closed = False

        async def close(self):
            await finish_close.wait()
            self.closed = True

    alice_svc = Slow()
    bob_svc = _Svc()

    async def factory(principal, paths, tokens):
        return alice_svc if principal.user_key == ALICE.user_key else bob_svc

    pool.register(DOMAIN, factory)
    bob = make_principal("bob@contoso.com")
    try:
        with multi_user_mode(tmp_path):
            async with pool.lease(DOMAIN, ALICE):
                pass
            # B 의 lease 가 유휴 A 를 LRU 퇴거 → A 의 close() 가 멈춘 채 진행 중
            bob_task = asyncio.create_task(pool.lease(DOMAIN, bob).__aenter__())
            await asyncio.sleep(0.05)
            assert pool.inflight(ALICE.user_key) == 1  # closing 집계
            assert await pool.drain(ALICE.user_key, timeout=0.2) is False
            finish_close.set()
            await bob_task
            await asyncio.sleep(0.05)
            assert alice_svc.closed and pool.inflight(ALICE.user_key) == 0
            assert await pool.drain(ALICE.user_key, timeout=1) is True
    finally:
        service_pool.reset_service_pool_for_tests()


async def test_drain_reports_failure_when_close_raises(tmp_path, pool):
    """close() 가 실패(변환 worker 생존 등)하면 drain 은 작업 종료를 보장할 수 없으므로 False."""

    class Stuck:
        async def close(self):
            raise RuntimeError("converter threads still alive")

    async def factory(principal, paths, tokens):
        return Stuck()

    pool.register(DOMAIN, factory)
    with multi_user_mode(tmp_path):
        async with pool.lease(DOMAIN, ALICE):
            pass
        assert await pool.drain(ALICE.user_key, timeout=1) is False
        assert pool.inflight(ALICE.user_key) == 0


async def test_failed_close_is_retried_and_keeps_drain_false_until_it_succeeds(tmp_path, pool):
    """astra 4차 N03 — close 실패 기록은 지워지지 않고 재시도된다. 성공할 때까지 drain 은 False."""
    state = {"alive": True, "closes": 0}

    class Converting:
        async def close(self):
            state["closes"] += 1
            if state["alive"]:
                raise RuntimeError("converter threads still alive")

    async def factory(principal, paths, tokens):
        return Converting()

    pool.register(DOMAIN, factory)
    with multi_user_mode(tmp_path):
        async with pool.lease(DOMAIN, ALICE):
            pass
        assert await pool.drain(ALICE.user_key, timeout=1) is False
        assert await pool.drain(ALICE.user_key, timeout=1) is False  # 즉시 재시도도 False
        assert state["closes"] >= 2  # 재시도마다 실제로 다시 닫아 본다
        state["alive"] = False
        assert await pool.drain(ALICE.user_key, timeout=1) is True


async def test_batch_ttl_eviction_tracks_every_entry(tmp_path):
    """astra 4차 N04 — A·B 가 TTL 로 함께 제거될 때 B 의 close 가 아직 시작 전이어도 B drain 은 기다린다."""
    now = [0.0]
    release_a = asyncio.Event()
    b_closed = asyncio.Event()

    class SlowA:
        async def close(self):
            await release_a.wait()

    class B:
        async def close(self):
            b_closed.set()

    pool = UserServicePool(token_provider_factory=FakeTokenProvider, idle_ttl_seconds=10, clock=lambda: now[0])
    service_pool.reset_service_pool_for_tests(pool)
    bob = make_principal("bob@contoso.com")
    carol = make_principal("carol@contoso.com")

    async def factory(principal, paths, tokens):
        return SlowA() if principal.user_key == ALICE.user_key else B()

    pool.register(DOMAIN, factory)
    try:
        with multi_user_mode(tmp_path):
            async with pool.lease(DOMAIN, ALICE):
                pass
            async with pool.lease(DOMAIN, bob):
                pass
            now[0] = 11  # 둘 다 TTL 만료
            carol_task = asyncio.create_task(pool.lease(DOMAIN, carol).__aenter__())
            await asyncio.sleep(0.05)
            # A 의 close 가 멈춰 있어도 B 는 이미 집계돼 있고 곧 닫힌다
            assert pool.inflight(bob.user_key) >= 0
            await asyncio.wait_for(b_closed.wait(), 1)
            assert await pool.drain(bob.user_key, timeout=1) is True
            assert await pool.drain(ALICE.user_key, timeout=0.2) is False  # A 는 close 진행 중
            release_a.set()
            await carol_task
            assert await pool.drain(ALICE.user_key, timeout=1) is True
    finally:
        service_pool.reset_service_pool_for_tests()


async def test_doomed_entries_are_closed_even_when_lease_raises(tmp_path):
    """astra 4차 N04 — TTL 로 뗀 A 가 있는데 B 의 lease 가 overloaded 로 빠져도 A 는 닫힌다."""
    now = [0.0]
    pool = UserServicePool(
        token_provider_factory=FakeTokenProvider, idle_ttl_seconds=10, max_entries=1, clock=lambda: now[0]
    )
    service_pool.reset_service_pool_for_tests(pool)
    a_svc, c_svc = _Svc(), _Svc()
    bob = make_principal("bob@contoso.com")
    carol = make_principal("carol@contoso.com")

    async def factory(principal, paths, tokens):
        return a_svc if principal.user_key == ALICE.user_key else c_svc

    pool.register(DOMAIN, factory)
    try:
        with multi_user_mode(tmp_path):
            async with pool.lease(DOMAIN, ALICE):
                pass
            now[0] = 11  # A 는 TTL 만료(유휴)
            inside, release = asyncio.Event(), asyncio.Event()

            async def hold_c():
                async with pool.lease(DOMAIN, carol):  # A 를 LRU 퇴거하고 자리를 차지한 채 멈춘다
                    inside.set()
                    await release.wait()

            task = asyncio.create_task(hold_c())
            await inside.wait()
            await asyncio.sleep(0.02)
            assert a_svc.closed  # LRU 퇴거된 A 는 닫혔다
            # 이제 C 가 유일한 슬롯을 점유 중 → B 의 lease 는 overloaded 로 빠진다
            with pytest.raises(SecurityError) as e:
                async with pool.lease(DOMAIN, bob):
                    pass
            assert e.value.code == ErrorCode.OVERLOADED
            assert pool.inflight(bob.user_key) == 0  # 실패한 lease 가 집계에 남지 않는다
            release.set()
            await task
            assert pool.inflight(ALICE.user_key) == 0
    finally:
        service_pool.reset_service_pool_for_tests()


async def test_cancelled_leaser_does_not_lose_close_tracking(tmp_path):
    """astra 4차 N04 — LRU 퇴거 close 중 lease task 가 취소돼도 close·집계는 끝까지 가고 lease 수가 새지 않는다."""
    release_a = asyncio.Event()
    a_closed = asyncio.Event()

    class SlowA:
        async def close(self):
            await release_a.wait()
            a_closed.set()

    pool = UserServicePool(token_provider_factory=FakeTokenProvider, max_entries=1)
    service_pool.reset_service_pool_for_tests(pool)
    bob = make_principal("bob@contoso.com")
    b_svc = _Svc()

    async def factory(principal, paths, tokens):
        return SlowA() if principal.user_key == ALICE.user_key else b_svc

    pool.register(DOMAIN, factory)
    try:
        with multi_user_mode(tmp_path):
            async with pool.lease(DOMAIN, ALICE):
                pass

            async def bob_lease():
                async with pool.lease(DOMAIN, bob):
                    pass

            task = asyncio.create_task(bob_lease())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert pool.inflight(bob.user_key) == 0  # 취소된 lease 가 남지 않는다
            assert pool.inflight(ALICE.user_key) == 1  # A 의 close 는 여전히 집계 중
            assert await pool.drain(ALICE.user_key, timeout=0.2) is False
            release_a.set()
            await asyncio.wait_for(a_closed.wait(), 1)
            assert await pool.drain(ALICE.user_key, timeout=1) is True
    finally:
        service_pool.reset_service_pool_for_tests()
