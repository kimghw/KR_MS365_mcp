"""
첨부 변환 worker 수명·슬롯 관리 (astra 3차 리뷰 P01).

`mcp_file_handler/conversion_workers.py` 와 **같은 모양**이다 — 도메인 간 import 가 금지돼
사본을 두며, 오케스트레이터가 나중에 공용으로 올릴 수 있게 이름·시그니처를 바꾸지 않는다.

변환기는 스레드에서 돌고 강제 종료할 수 없다. 그래서 **실제 converter 스레드**가 추적 단위다:

- `UserSlots` — **프로세스 전역, user_key 별** 세마포어(mode 0 은 `LEGACY_KEY` 하나). 서비스
  인스턴스가 퇴거·재생성돼도 같은 사용자의 살아 있는 converter 스레드 수는 `max_workers` 를
  넘지 못한다(구 스레드가 슬롯을 쥔 채로 남아 있으면 새 서비스도 `overloaded`). 슬롯은
  스레드를 띄우기 전에 얻고 **스레드가 실제로 끝날 때** 놓는다.
- `WorkerGroup` — 서비스 하나가 띄운 converter 스레드 집합. `MailService.close()` 가
  `HARD_JOIN_CAP_SECONDS` 까지 join 하고, 그래도 남으면 실패를 올려 풀이 drain 실패를 보고한다.
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
#: 서비스 종료 시 살아 있는 converter 스레드를 기다리는 상한(초). 넘기면 종료 실패로 보고한다.
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
    """converter 스레드 집합과, 그 스레드들이 모두 끝난 뒤 실행할 정리."""

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
                logger.info("deferred cleanup completed by the last converter thread")

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
        """종료. 스레드가 다 끝났으면 즉시 정리하고 True, 아니면 마지막 스레드에 넘기고 False."""
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
