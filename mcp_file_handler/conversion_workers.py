"""
변환 worker 수명·슬롯 관리 (astra 2차 리뷰 N03).

변환기는 스레드에서 돌고 강제 종료할 수 없다. 그래서 **실제 converter 스레드**가 추적 단위다:

- `UserSlots` — **프로세스 전역, user_key 별** 세마포어(mode 0 은 `LEGACY_KEY` 하나). 서비스
  인스턴스가 퇴거·재생성돼도 같은 사용자의 살아 있는 converter 스레드 수는 `max_workers` 를
  넘지 못한다(구 스레드가 슬롯을 쥔 채로 남아 있으면 새 서비스도 `overloaded`).
- `WorkerGroup` — 요청 하나가 띄운 converter 스레드 집합. 요청 디렉터리 정리는 `close()` 에
  넘긴 `ExitStack` 으로만 일어나며, **모든 스레드가 끝난 뒤**에 실행된다: 요청이 끝날 때
  살아 있는 스레드가 있으면 `HARD_JOIN_CAP_SECONDS` 까지 join 하고, 그래도 남으면 정리를
  마지막으로 끝나는 스레드에 위임한다(그동안 디렉터리는 남는다).

서비스(`service.py`)는 요청마다 group 을 만들어 scope 에 싣고, `close()` 때 group 의 스레드를
hard cap 까지 기다린다. `FileManager._run_converter` 는 슬롯을 얻고 스레드를 group 에 등록한다.
"""

import logging
import threading
import time
from contextlib import ExitStack
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def _now() -> float:
    return time.monotonic()

LEGACY_KEY = "legacy"
#: 요청이 끝난 뒤 살아 있는 converter 스레드를 기다리는 상한(초). 넘기면 정리를 스레드에 위임한다.
HARD_JOIN_CAP_SECONDS = 30.0


class UserSlots:
    """사용자별 동시 변환 슬롯."""

    def __init__(self, max_workers: int):
        self.max_workers = max(1, int(max_workers))
        self._semaphore = threading.BoundedSemaphore(self.max_workers)
        self._lock = threading.Lock()
        self.live = 0

    def acquire(self, timeout: float) -> bool:
        if not self._semaphore.acquire(timeout=max(0.0, timeout)):
            return False
        with self._lock:
            self.live += 1
        return True

    def release(self) -> None:
        with self._lock:
            self.live -= 1
        self._semaphore.release()


_registry: Dict[str, UserSlots] = {}
_registry_lock = threading.Lock()


def slots_for(user_key: Optional[str], max_workers: int) -> UserSlots:
    """사용자(user_key, mode 0 은 LEGACY_KEY)의 슬롯. 처음 만든 상한이 유지된다."""
    key = user_key or LEGACY_KEY
    with _registry_lock:
        slots = _registry.get(key)
        if slots is None:
            slots = _registry[key] = UserSlots(max_workers)
        return slots


def live_workers(user_key: Optional[str]) -> int:
    with _registry_lock:
        slots = _registry.get(user_key or LEGACY_KEY)
    return slots.live if slots is not None else 0


def reset_registry_for_tests() -> None:
    """**테스트 전용.** 살아 있는 스레드는 자기 `UserSlots` 객체를 그대로 참조하므로 안전하다."""
    with _registry_lock:
        _registry.clear()


class WorkerGroup:
    """요청 하나의 converter 스레드 집합과, 그 스레드들이 모두 끝난 뒤 실행할 정리."""

    def __init__(self):
        self._lock = threading.Lock()
        self._threads: Set[threading.Thread] = set()
        self._deferred: Optional[ExitStack] = None

    def register(self, thread: threading.Thread) -> None:
        with self._lock:
            self._threads.add(thread)

    def finished(self, thread: threading.Thread) -> None:
        """스레드가 끝날 때(예외 포함) 반드시 부른다. 마지막 스레드면 위임된 정리를 실행한다."""
        run: Optional[ExitStack] = None
        with self._lock:
            self._threads.discard(thread)
            if not self._threads and self._deferred is not None:
                run, self._deferred = self._deferred, None
        if run is not None:
            try:
                run.close()
            finally:
                logger.info("deferred request cleanup completed by the last converter thread")

    def live(self) -> List[threading.Thread]:
        with self._lock:
            return [t for t in self._threads if t.is_alive()]

    @property
    def cleanup_deferred(self) -> bool:
        with self._lock:
            return self._deferred is not None

    def join(self, timeout: float) -> bool:
        """살아 있는 스레드를 상한 안에서 기다린다. 전부 끝났으면 True."""
        deadline = threading.TIMEOUT_MAX if timeout is None else _now() + max(0.0, timeout)
        for thread in self.live():
            remaining = deadline - _now()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        return not self.live()

    def close(self, cleanup: ExitStack, join_timeout: float) -> bool:
        """요청 종료. 스레드가 다 끝났으면 즉시 정리하고 True, 아니면 마지막 스레드에 넘기고 False."""
        self.join(join_timeout)
        with self._lock:
            if any(t.is_alive() for t in self._threads):
                self._deferred = cleanup
                return False
        cleanup.close()
        return True


__all__ = [
    "LEGACY_KEY",
    "HARD_JOIN_CAP_SECONDS",
    "UserSlots",
    "WorkerGroup",
    "slots_for",
    "live_workers",
    "reset_registry_for_tests",
]
