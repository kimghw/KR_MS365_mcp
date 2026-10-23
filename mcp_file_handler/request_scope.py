"""
요청 범위 작업 컨텍스트 — FileHandler 의 동기 코드(작업 스레드)가 쓰는 요청별 상태.

`FileManager` 는 사용자당 하나(mode 1)거나 프로세스당 하나(mode 0)다. 요청별 값을 인스턴스
속성에 두면 동시 요청끼리 섞인다 — 예전 `downloader.temp_dir` 가 그랬다(공유 temp 를 한
요청이 지우면 다른 요청의 파일이 사라지는 race, spec/spec_멀티유저.md ②-2.5). 그래서 요청별
값(임시 디렉터리, 토큰 공급자가 사는 이벤트 루프)은 **이 ContextVar 로만** 전달한다.

`FileHandlerService` 가 동기 작업을 스레드로 넘길 때 `contextvars.copy_context()` 로
principal(`mcp_common.principal`)과 이 scope 를 함께 넘긴다(②-5.2). mode 1 에서 scope 없이
스레드가 돌면 다른 사용자 상태로 대체하지 않고 `missing_principal` 로 실패한다(테스트 C03).
"""

import asyncio
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from mcp_common.principal import current_principal
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled


@dataclass(frozen=True)
class FileRequestScope:
    """한 도구 호출의 작업 상태. 서비스가 만들고 요청이 끝나면 버린다."""

    #: mode 1 = 서비스 소유자의 user_key, mode 0 = None
    owner_key: Optional[str]
    #: 요청 전용 임시 디렉터리 (mode 1: `files/tmp/<request_id>/`). 메타데이터 작업엔 없다.
    work_dir: Optional[Path] = None
    #: 토큰 공급자 코루틴을 돌릴 이벤트 루프 (작업 스레드 → 루프로 위임할 때 쓴다)
    loop: Optional[asyncio.AbstractEventLoop] = None
    #: 이 요청이 띄운 converter 스레드 집합 (`conversion_workers.WorkerGroup`). 요청 디렉터리
    #: 정리는 이 스레드들이 모두 끝난 뒤에만 일어난다 (N03). 서비스 밖 직접 호출에는 없다.
    workers: Optional[Any] = None


_scope_var: contextvars.ContextVar[Optional[FileRequestScope]] = contextvars.ContextVar(
    "mcp_file_handler_request_scope", default=None
)


@contextmanager
def bind_scope(scope: FileRequestScope) -> Iterator[FileRequestScope]:
    """현재 컨텍스트에 scope 를 묶는다. 예외·취소에도 `finally` 에서 되돌린다."""
    token = _scope_var.set(scope)
    try:
        yield scope
    finally:
        _scope_var.reset(token)


def current_scope() -> Optional[FileRequestScope]:
    return _scope_var.get()


def require_scope(owner_key: Optional[str]) -> Optional[FileRequestScope]:
    """작업 진입점 검사.

    - mode 1: scope 와 principal 이 **둘 다** 있고 서비스 소유자(`owner_key`)와 같아야 한다.
      아니면 `missing_principal` — 전역 상태나 다른 사용자로 대체하지 않는다.
    - mode 0: 있으면 돌려주고, 없어도 된다(CLI·직접 호출).
    """
    scope = _scope_var.get()
    if not multi_user_enabled():
        return scope
    principal = current_principal()
    if (
        scope is None
        or principal is None
        or not owner_key
        or scope.owner_key != owner_key
        or principal.user_key != owner_key
    ):
        raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
    return scope


def scope_work_dir() -> Optional[Path]:
    """변환 라이브러리 임시파일을 둘 요청 디렉터리.

    mode 1 에서 없으면 실패한다(시스템 temp 로 새지 않게). mode 0 에서 없으면 None —
    호출자는 기존 동작(시스템 temp)을 쓴다.
    """
    scope = _scope_var.get()
    if scope is not None and scope.work_dir is not None:
        return scope.work_dir
    if multi_user_enabled():
        raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
    return None


__all__ = [
    "FileRequestScope",
    "bind_scope",
    "current_scope",
    "require_scope",
    "scope_work_dir",
]
