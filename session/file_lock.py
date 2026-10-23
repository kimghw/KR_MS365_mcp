"""
프로세스 간 배타 lock (spec/spec_멀티유저.md ②-6.3).

- Windows: `msvcrt.locking(LK_NBLCK)` (파일 첫 1바이트 범위 lock)
- 그 외: `fcntl.flock(LOCK_EX | LOCK_NB)`

둘 다 **프로세스가 죽으면 OS 가 해제**한다(핸들 종료). 같은 프로세스 안의 다른 핸들끼리도
충돌하므로 스레드 사이에서도 배타적이다. 대기는 폴링이며 기본 30초 후 `LockTimeout`.

`async_file_lock()` 은 획득 대기를 스레드로 넘긴다. 대기 중 코루틴이 취소되면 스레드에
중단 신호를 주고, 그 사이 lock 을 이미 잡았다면 즉시 놓는다 — 취소가 lock 누수로 이어지지 않게.

lock 파일은 `<data_root>/system/locks/` 아래에 두며 지우지 않는다(내용 없음).
"""

import asyncio
import re
import sys
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import AsyncIterator, Iterator, Optional

DEFAULT_TIMEOUT_SECONDS = 30.0
_POLL_SECONDS = 0.02
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


class LockTimeout(Exception):
    """lock 대기 시간 초과 (재시도 가능)."""


class FileLock:
    def __init__(self, path: Path, *, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.path = Path(path)
        self.timeout = timeout
        self._fh = None

    @property
    def locked(self) -> bool:
        return self._fh is not None

    def _try_lock(self, fh) -> bool:
        if sys.platform == "win32":
            import msvcrt

            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        import fcntl

        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def acquire(self, *, cancel: Optional[threading.Event] = None) -> None:
        if self._fh is not None:
            raise RuntimeError("FileLock is not reentrant")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                if self._try_lock(fh):
                    self._fh = fh
                    return
                if cancel is not None and cancel.is_set():
                    raise LockTimeout("lock wait cancelled")
                if time.monotonic() >= deadline:
                    raise LockTimeout("lock wait timed out")
                time.sleep(_POLL_SECONDS)
        except BaseException:
            fh.close()
            raise

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def lock_path(name: str, *, root: Optional[Path] = None) -> Path:
    """`system/locks/<name>.lock`. 이름은 서버가 만든 식별자만(경로 문자 금지)."""
    from mcp_common.user_paths import system_paths

    if not _NAME_RE.match(name or ""):
        raise ValueError("lock name invalid")
    return system_paths(root).locks / f"{name}.lock"


def user_lock_path(user_key: str) -> Path:
    """사용자 저장소 단위 배타 lock (DEK 생성·키 발급 개수 확인·계정 삭제)."""
    return lock_path(f"user-{user_key}")


def refresh_lock_path(user_key: str, app_id: str) -> Path:
    """`(user_key, app_id)` 토큰 갱신 lock (②-6.3). 사용자마다 다르므로 A/B 가 서로 기다리지 않는다."""
    import hashlib

    app_tag = hashlib.sha256(app_id.encode("utf-8")).hexdigest()[:16]
    return lock_path(f"refresh-{user_key}-{app_tag}")


@contextmanager
def file_lock(path: Path, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Iterator[FileLock]:
    lock = FileLock(path, timeout=timeout)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


@asynccontextmanager
async def async_file_lock(path: Path, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> AsyncIterator[FileLock]:
    lock = FileLock(path, timeout=timeout)
    cancel = threading.Event()
    task = asyncio.ensure_future(asyncio.to_thread(lock.acquire, cancel=cancel))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        try:
            await task
        except BaseException:
            pass
        lock.release()  # 취소 직전에 잡혔다면 놓는다 (안 잡혔으면 no-op)
        raise
    try:
        yield lock
    finally:
        lock.release()


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "LockTimeout",
    "FileLock",
    "lock_path",
    "user_lock_path",
    "refresh_lock_path",
    "file_lock",
    "async_file_lock",
]

