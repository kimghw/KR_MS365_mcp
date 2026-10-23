"""
사용자별 서비스 풀 (spec/spec_멀티유저.md ②-7.6, WP0).

전역 개인 서비스 인스턴스를 없애고, `(user_key, domain, auth_epoch)` 키로 사용자별
서비스·GraphClient 를 만들어 **제한된 캐시**로 관리한다.

| 항목 | 기본값 |
|------|------:|
| 프로세스별 항목 상한 | 128 |
| 유휴 TTL | 600초 |
| 사용자·도메인별 동시 작업 상한 | 8 (대기 30초 후 `overloaded`) |

- 같은 키의 중복 생성 금지 — 생성 중이면 뒤 요청은 그 결과를 기다린다.
- 사용 중(lease>0) 항목은 퇴거하지 않는다. 전부 사용 중이라 상한을 넘으면 `overloaded`.
- `auth_epoch` 가 바뀐 이전 항목은 새 lease 대상에서 빠지고, 마지막 lease 가 끝나면 닫힌다.
- 퇴거 시 서비스 `close()` 와 토큰 공급자 `close()`(차용 해제) 만 부른다 — 다른 사용자의
  자원이나 공용 인증 자원을 닫지 않는다.

factory 계약: `async def create_service(principal, paths, tokens) -> service` — **생성만**
한다. 풀이 `ensure_user_dirs(paths)` 를 먼저 부르고, 생성 뒤 `initialize()` 가 있으면
부른다(None·truthy 성공 / 명시적 falsy 실패 — `ServiceLifecycle` 과 같은 의미).
"""

import asyncio
import inspect
import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from mcp_common.principal import Principal
from mcp_common.security_contracts import BoundTokenProvider, ErrorCode, SecurityError
from mcp_common.user_paths import UserPaths, ensure_user_dirs, paths_for

logger = logging.getLogger(__name__)

ServiceFactory = Callable[[Principal, UserPaths, BoundTokenProvider], Awaitable[Any]]
TokenProviderFactory = Callable[[Principal], BoundTokenProvider]
PathsFactory = Callable[[Principal], UserPaths]

_Key = Tuple[str, str, int]  # (user_key, domain, auth_epoch)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _default_token_provider_factory(principal: Principal) -> BoundTokenProvider:
    # WP2 가 구현한다. import 를 늦춰 session 패키지 없이도 풀 단위 테스트가 돈다.
    from mcp_common.auth import get_bound_token_provider

    return get_bound_token_provider(principal)


@dataclass
class _Entry:
    key: _Key
    ready: "asyncio.Future[Any]"
    semaphore: asyncio.Semaphore
    service: Any = None
    tokens: Optional[BoundTokenProvider] = None
    leases: int = 0
    last_used: float = 0.0
    invalid: bool = False
    closed: bool = False
    created: bool = False
    close_failed: bool = False


class UserServicePool:
    def __init__(
        self,
        *,
        max_entries: int = 128,
        idle_ttl_seconds: float = 600.0,
        per_user_concurrency: int = 8,
        acquire_timeout_seconds: float = 30.0,
        token_provider_factory: Optional[TokenProviderFactory] = None,
        paths_factory: Optional[PathsFactory] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_entries = max_entries
        self.idle_ttl_seconds = idle_ttl_seconds
        self.per_user_concurrency = per_user_concurrency
        self.acquire_timeout_seconds = acquire_timeout_seconds
        self._token_provider_factory = token_provider_factory or _default_token_provider_factory
        self._paths_factory = paths_factory or paths_for
        self._clock = clock
        self._factories: Dict[str, ServiceFactory] = {}
        self._entries: Dict[_Key, _Entry] = {}
        self._lock: Optional[asyncio.Lock] = None
        #: drain 중인 사용자 — 새 lease 를 받지 않는다 (astra 2차 N04)
        self._draining: set = set()
        #: close() 진행 중인 항목 수 (사용자별, 모든 제거 경로) — drain 이 기다린다
        self._closing: Dict[str, int] = {}
        #: close() 가 실패한 항목(사용자별) — drain 이 재시도하고, 남아 있으면 성공으로 보고하지
        #: 않는다 (astra 3차 N03/N04, 4차). 풀에서 이미 제거된 항목이라 여기서만 추적한다.
        self._failed_entries: Dict[str, List[_Entry]] = {}
        #: 진행 중인 close task — 호출자가 취소돼도 close·집계는 끝까지 간다 (astra 4차)
        self._close_tasks: set = set()

    # ------------------------------------------------------------------
    def register(self, domain: str, factory: ServiceFactory) -> None:
        if not callable(factory):
            raise TypeError("factory 는 callable 이어야 합니다")
        self._factories[domain] = factory

    def has_factory(self, domain: str) -> bool:
        return domain in self._factories

    def stats(self) -> Dict[str, int]:
        return {
            "entries": len(self._entries),
            "leased": sum(1 for e in self._entries.values() if e.leases),
        }

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------
    def _collect_evictable(self, now: float) -> List[_Entry]:
        """lock 안에서 호출. 유휴 TTL 초과·무효 항목을 떼어 낸다(닫기는 lock 밖)."""
        doomed: List[_Entry] = []
        for key, entry in list(self._entries.items()):
            if entry.leases:
                continue
            if not entry.ready.done():
                continue
            if entry.invalid or (now - entry.last_used) > self.idle_ttl_seconds:
                doomed.append(self._entries.pop(key))
        return doomed

    def _pop_lru_idle(self) -> Optional[_Entry]:
        idle = [e for e in self._entries.values() if not e.leases and e.ready.done()]
        if not idle:
            return None
        victim = min(idle, key=lambda e: e.last_used)
        return self._entries.pop(victim.key)

    async def _close_entry(self, entry: _Entry) -> None:
        if entry.closed:
            return
        entry.closed = True
        if entry.service is not None:
            close = getattr(entry.service, "close", None)
            if close is not None:
                try:
                    await _maybe_await(close())
                except Exception as exc:  # 다른 사용자 처리에 영향을 주지 않는다
                    entry.close_failed = True
                    logger.warning("service close failed (%s): %s", entry.key[1], type(exc).__name__)
        if entry.tokens is not None:
            try:
                await _maybe_await(entry.tokens.close())
            except Exception as exc:
                entry.close_failed = True
                logger.warning("token provider release failed: %s", type(exc).__name__)

    def _schedule_close_locked(self, entries: List[_Entry]) -> List["asyncio.Future[None]"]:
        """lock 을 잡은 채 호출. 전 항목을 **먼저** `_closing` 에 등록하고 close task 를 띄운다.

        일괄 제거(TTL·종료)의 뒤 항목도 대기 중 집계되고, 등록 뒤 호출자가 예외·취소로 빠져도
        task 가 close·집계 해제·실패 기록을 끝까지 수행한다 (astra 4차 N03/N04).
        """
        tasks: List["asyncio.Future[None]"] = []
        for entry in entries:
            self._closing[entry.key[0]] = self._closing.get(entry.key[0], 0) + 1
            task = asyncio.ensure_future(self._close_and_untrack(entry))
            self._close_tasks.add(task)
            task.add_done_callback(self._close_tasks.discard)
            tasks.append(task)
        return tasks

    async def _close_tracked(self, entries: List[_Entry]) -> None:
        """모든 제거 경로(LRU·TTL·invalidate·마지막 lease·종료)의 close 를 집계하며 기다린다.

        drain 은 `inflight()`(= lease + closing) 가 0 이 될 때까지 기다리므로, 어느 경로로
        닫히든 close 가 끝나기 전엔 drain 이 성공하지 않는다 (astra 3차 N04). 호출자가 취소돼도
        close task 는 계속 돈다. 호출자는 lock 을 잡지 않은 상태여야 한다.
        """
        if not entries:
            return
        async with self._get_lock():
            tasks = self._schedule_close_locked(entries)
        await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))

    async def _close_and_untrack(self, entry: _Entry) -> None:
        user = entry.key[0]
        try:
            await self._close_entry(entry)
        finally:
            async with self._get_lock():
                remaining = self._closing.get(user, 1) - 1
                if remaining > 0:
                    self._closing[user] = remaining
                else:
                    self._closing.pop(user, None)
                if entry.close_failed:
                    self._failed_entries.setdefault(user, []).append(entry)

    async def _create(self, entry: _Entry, domain: str, principal: Principal) -> None:
        factory = self._factories[domain]
        tokens: Optional[BoundTokenProvider] = None
        try:
            paths = ensure_user_dirs(self._paths_factory(principal))
            tokens = self._token_provider_factory(principal)
            entry.tokens = tokens
            service = await _maybe_await(factory(principal, paths, tokens))
            if service is None:
                raise RuntimeError(f"[{domain}] factory 가 서비스를 돌려주지 않았습니다")
            entry.service = service
            initialize = getattr(service, "initialize", None)
            if initialize is not None:
                result = await _maybe_await(initialize())
                if result is not None and not result:
                    raise RuntimeError(f"[{domain}] initialize() returned {result!r}")
            entry.created = True
            entry.ready.set_result(service)
        except BaseException as exc:
            entry.ready.set_exception(exc)
            # 실패한 항목의 Future 예외를 아무도 안 읽어도 경고가 나지 않게
            entry.ready.exception()
            raise

    # ------------------------------------------------------------------
    @asynccontextmanager
    async def lease(self, domain: str, principal: Principal) -> AsyncIterator[Any]:
        if domain not in self._factories:
            raise RuntimeError(f"[{domain}] 등록된 서비스 factory 가 없습니다")
        if not isinstance(principal, Principal):
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)

        key: _Key = (principal.user_key, domain, principal.auth_epoch)
        lock = self._get_lock()
        doomed: List[_Entry] = []
        creator = False
        async with lock:
            try:
                if principal.user_key in self._draining:
                    raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)
                now = self._clock()
                # 같은 사용자·도메인의 이전 auth_epoch 항목은 새 lease 대상에서 뺀다
                for other in self._entries.values():
                    if other.key[:2] == key[:2] and other.key[2] != key[2]:
                        other.invalid = True
                entry = self._entries.get(key)
                if entry is not None and entry.invalid:
                    # 무효화된 항목(연결 해제·삭제)은 사용 중이라도 새 lease 를 받지 않는다
                    raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)
                doomed.extend(self._collect_evictable(now))
                if entry is None:
                    while len(self._entries) >= self.max_entries:
                        victim = self._pop_lru_idle()
                        if victim is None:
                            raise SecurityError(ErrorCode.OVERLOADED)
                        doomed.append(victim)
                    loop = asyncio.get_running_loop()
                    entry = _Entry(
                        key=key,
                        ready=loop.create_future(),
                        semaphore=asyncio.Semaphore(self.per_user_concurrency),
                        last_used=now,
                    )
                    self._entries[key] = entry
                    creator = True
                entry.leases += 1
            except BaseException:
                # 이미 풀에서 뗀 항목은 예외로 빠져도 반드시 닫는다 (astra 4차 N04)
                self._schedule_close_locked(doomed)
                raise

        acquired = False
        try:
            # lease 집계가 된 뒤이므로 여기서 취소돼도 finally 가 되돌린다; close 자체는 shield 로 계속
            await self._close_tracked(doomed)
            if creator:
                try:
                    await self._create(entry, domain, principal)
                except BaseException:
                    async with lock:
                        if self._entries.get(key) is entry:
                            self._entries.pop(key)
                    await self._close_tracked([entry])
                    raise
            service = await asyncio.shield(entry.ready)
            try:
                await asyncio.wait_for(entry.semaphore.acquire(), self.acquire_timeout_seconds)
            except asyncio.TimeoutError:
                raise SecurityError(ErrorCode.OVERLOADED) from None
            acquired = True
            yield service
        finally:
            if acquired:
                entry.semaphore.release()
            close_now = False
            async with lock:
                entry.leases -= 1
                entry.last_used = self._clock()
                if entry.invalid and entry.leases == 0 and self._entries.get(key) is entry:
                    self._entries.pop(key)
                    close_now = True
            if close_now:
                await self._close_tracked([entry])

    async def invalidate(self, user_key: str) -> None:
        """사용자 항목을 전부 무효화. 유휴 항목은 즉시, 사용 중 항목은 마지막 lease 뒤 닫힌다."""
        doomed: List[_Entry] = []
        async with self._get_lock():
            for key, entry in list(self._entries.items()):
                if key[0] != user_key:
                    continue
                entry.invalid = True
                if entry.leases == 0 and entry.ready.done():
                    doomed.append(self._entries.pop(key))
        await self._close_tracked(doomed)

    def inflight(self, user_key: str) -> int:
        """해당 사용자의 진행 중 lease 수 + close() 진행 중 항목 수 (이 프로세스 기준)."""
        leases = sum(e.leases for k, e in self._entries.items() if k[0] == user_key)
        return leases + self._closing.get(user_key, 0)

    async def drain(self, user_key: str, *, timeout: float = 30.0, poll: float = 0.05) -> bool:
        """사용자 항목을 무효화하고 진행 중 lease·close 가 끝날 때까지 기다린다 (계정 삭제·연결 해제용).

        대기 동안 그 사용자의 새 lease 는 `account_inactive` 로 거부된다(admission 차단). **이
        프로세스 안의** lease 만 안다 — 다른 도메인 프로세스는 각자 토큰 획득·응답 전
        `assert_active` 로 그 시점에 차단될 뿐, 이미 시작된 로컬 저장은 끝까지 간다(교차 프로세스
        drain 은 ④ 후속). 시간 안에 비면 True, 아니면 False (호출자가 강제 진행 여부를 정한다).
        """
        deadline = time.monotonic() + timeout
        async with self._get_lock():
            self._draining.add(user_key)
        try:
            # 유휴 항목 close 가 멈춰도 timeout 을 넘기지 않는다 — shield 로 close 자체는 계속 진행
            try:
                await asyncio.wait_for(asyncio.shield(self.invalidate(user_key)), timeout)
            except asyncio.TimeoutError:
                return False
            while self.inflight(user_key) > 0:
                if time.monotonic() >= deadline:
                    return False
                await asyncio.sleep(poll)
            await self.invalidate(user_key)  # 마지막 lease 가 닫은 뒤 남은 항목 정리
            # close() 가 실패했던 항목(예: 변환 worker 생존)은 **다시 닫아 본다** — 실패 기록을
            # 지우지 않고 재시도하므로, 여전히 실패하면 drain 도 실패다 (astra 4차 N03)
            async with self._get_lock():
                failed = self._failed_entries.pop(user_key, [])
            for entry in failed:
                entry.closed = False
                entry.close_failed = False
            remaining = max(0.0, deadline - time.monotonic())
            try:
                await asyncio.wait_for(asyncio.shield(self._close_tracked(failed)), remaining or 0.001)
            except asyncio.TimeoutError:
                return False
            async with self._get_lock():
                return user_key not in self._failed_entries
        finally:
            async with self._get_lock():
                self._draining.discard(user_key)

    async def close(self) -> None:
        async with self._get_lock():
            entries = list(self._entries.values())
            self._entries.clear()
        await self._close_tracked(entries)
        # 다른 경로(LRU·TTL·invalidate)가 띄워 둔 close task 도 끝까지 기다린다
        pending = list(self._close_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


# ----------------------------------------------------------------------
# process singleton
# ----------------------------------------------------------------------
_pool: Optional[UserServicePool] = None
_pool_guard = threading.Lock()


def get_service_pool() -> UserServicePool:
    global _pool
    with _pool_guard:
        if _pool is None:
            _pool = UserServicePool()
        return _pool


def register_service_factory(domain: str, factory: ServiceFactory) -> None:
    """도메인 handlers.py 가 import 시 1회 호출한다 (mode 0 에서도 등록만 해 둔다)."""
    get_service_pool().register(domain, factory)


def reset_service_pool_for_tests(pool: Optional[UserServicePool] = None) -> None:
    """**테스트 전용.** 등록된 factory 는 새 풀로 옮긴다."""
    global _pool
    with _pool_guard:
        factories = dict(_pool._factories) if _pool is not None else {}
        _pool = pool or UserServicePool()
        for domain, factory in factories.items():
            _pool._factories.setdefault(domain, factory)


__all__ = [
    "ServiceFactory",
    "TokenProviderFactory",
    "UserServicePool",
    "get_service_pool",
    "register_service_factory",
    "reset_service_pool_for_tests",
]
