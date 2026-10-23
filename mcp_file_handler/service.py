"""
FileHandler async 서비스 — 동기 `FileManager` 를 감싼 어댑터 (spec/spec_멀티유저.md ②-11.1).

mode 0 과 mode 1 이 같은 클래스를 쓴다.

| 모드 | 인스턴스 | 토큰 | 저장소·파일 |
|------|----------|------|-------------|
| mode 0 | 프로세스 전역 1개 (`FileHandlerService.legacy()`) | 공유 AuthManager (지연) | 기존 Settings 경로 |
| mode 1 | 사용자별 (`handlers.create_service` → 서비스 풀) | 주입된 `BoundTokenProvider` | `UserPaths` (`db/metadata.db`, `files/`) |

동기 작업(파일 변환·Graph 다운로드·SQLite)은 **작업 스레드**에서 돈다. 넘길 때
`contextvars.copy_context()` 로 principal 과 요청 scope(`request_scope.FileRequestScope`:
요청 전용 임시 디렉터리 + 이벤트 루프)를 같이 넘긴다 — 스레드 안에서 다른 사용자 상태로
바뀌지 않고, 누락되면 `missing_principal` 로 실패한다(C03). 토큰은 작업 스레드가
`SyncTokenBridge` 로 요청 이벤트 루프에 위임해 얻는다(`executor.submit(asyncio.run, …)` 없음).

요청 임시 디렉터리:
    - mode 1: `secure_files.request_temp_dir(paths, request_id)` → `files/tmp/<request_id>/`.
      끝나면 **그 디렉터리만** 지운다 — 다른 요청·다른 사용자의 temp 는 건드리지 않는다(F05).
    - mode 0: 요청마다 새 `tempfile.mkdtemp()` 를 만들고 그것만 지운다.
    - 디렉터리는 **작업 스레드가 열고 닫는다.** 호출 코루틴이 취소돼도(반복 취소·종료 포함)
      worker 가 끝난 뒤에야 지워지고, 그때까지 `_run` 이 상한 안에서 기다린다(R05).

메타데이터 도구(`save/get/delete_metadata`)는 `{"file_url": <정규화 참조>, ...}` 봉투를
돌려준다 — 응답은 호출자 입력이 아니라 정규화 결과를 반사한다(R14).

생성 계약 (서비스 풀): 생성자는 **검증과 보관만** 한다 — 사용자 일치 확인, 멀티유저 설정
위반(JSON 저장소·경로 설정) 거부. 저장소 초기화와 FileManager 생성은 `initialize()` 에서 한다.
"""

import asyncio
import contextvars
import logging
import shutil
import tempfile
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set

from mcp_common.principal import current_identity
from mcp_common.secure_files import request_temp_dir
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

from . import conversion_workers
from .config.settings import Settings
from .conversion_workers import WorkerGroup
from .file_manager import FileManager
from .limits import KEYWORD_MAX_LENGTH, KEYWORDS_MAX_ITEMS
from .request_scope import FileRequestScope, bind_scope
from .storage_schema import ensure_storage

logger = logging.getLogger(__name__)

#: worker 를 기다리는 상한 = conversion_timeout + 이 여유(초). 그 뒤에는 경고를 남기고 포기한다.
WORKER_JOIN_GRACE_SECONDS = 30.0


def _identity_request_id() -> Optional[str]:
    identity = current_identity()
    return identity.request_id if identity is not None else None


async def _join_worker(future: "asyncio.Future[Any]", timeout: float) -> int:
    """worker future 가 끝날 때까지(상한까지) 기다린다. **반복 취소가 와도 기다림을 끊지 않는다.**

    반환값은 기다리는 동안 흡수한 취소 횟수(테스트·로그용). 상한을 넘기면 경고만 남긴다 —
    스레드는 강제 종료할 수 없다.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    absorbed = 0
    while not future.done():
        remaining = deadline - loop.time()
        if remaining <= 0:
            logger.warning("file handler worker did not finish within the join limit; giving up")
            break
        try:
            await asyncio.wait({future}, timeout=remaining)
        except asyncio.CancelledError:
            absorbed += 1
            continue
    return absorbed


class FileHandlerService:
    """FileManager 의 async 어댑터. 도구 메서드 시그니처는 FileManager 와 같다."""

    def __init__(
        self,
        *,
        principal: Any = None,
        paths: Any = None,
        tokens: Any = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.multi_user = multi_user_enabled()
        self._principal = principal
        self._paths = paths
        self._tokens = tokens
        self._config = config
        self._settings: Optional[Settings] = None
        self._manager: Optional[FileManager] = None
        self.init_error: Optional[str] = None
        self._inflight: Set["asyncio.Future[Any]"] = set()
        self._groups: Set[WorkerGroup] = set()

        if self.multi_user:
            if principal is None or paths is None or tokens is None:
                raise SecurityError(
                    ErrorCode.CONFIG_ERROR,
                    "멀티유저 FileHandler 서비스에는 principal·사용자 경로·토큰 공급자가 필요합니다.",
                )
            if not (principal.user_key == paths.user_key == getattr(tokens, "user_key", None)):
                raise SecurityError(
                    ErrorCode.CONFIG_ERROR, "principal·경로·토큰 공급자의 사용자가 다릅니다."
                )
            # JSON 저장소·경로 확장 설정은 여기서 거부된다 (서비스 생성 오류)
            self._settings = Settings(config, paths=paths)

    @property
    def live_converter_threads(self) -> int:
        """이 서비스의 요청이 띄웠고 아직 도는 converter 스레드 수 (운영·테스트 관찰용)."""
        return sum(len(group.live()) for group in list(self._groups))

    @classmethod
    def legacy(cls, config: Optional[Dict[str, Any]] = None) -> "FileHandlerService":
        """mode 0 전역 인스턴스. 생성 실패는 import 실패가 아니라 health degraded 로 보고한다."""
        service = cls(config=config)
        service._build_legacy()
        return service

    @property
    def owner_key(self) -> Optional[str]:
        return self._paths.user_key if self.multi_user else None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def _build_legacy(self) -> None:
        try:
            self._manager = FileManager(self._config)
            self.init_error = None
        except Exception as exc:  # noqa: BLE001 - health 로 보고하고 계속 기동
            self._manager = None
            self.init_error = f"{type(exc).__name__}: {exc}"
            logger.error("FileManager 생성 실패: %s", type(exc).__name__)

    def _build_multi_user(self) -> None:
        try:
            ensure_storage(self._principal, self._paths)
            self._manager = FileManager(
                paths=self._paths, token_provider=self._tokens, settings=self._settings
            )
        except SecurityError:
            raise
        except Exception as exc:
            logger.error("FileManager 생성 실패: %s", type(exc).__name__)
            raise SecurityError(ErrorCode.INTERNAL_ERROR) from exc

    def initialize(self) -> None:
        """ServiceLifecycle(mode 0)·서비스 풀(mode 1)이 부른다. 실패는 예외."""
        if self._manager is not None:
            return
        if self.multi_user:
            self._build_multi_user()
            return
        self._build_legacy()
        if self._manager is None:
            raise RuntimeError(f"FileManager 초기화 실패: {self.init_error}")

    async def close(self) -> None:
        """자기 FileManager 만 놓는다. 토큰 공급자 반납은 서비스 풀이 한다.

        진행 중인 worker 가 있으면(요청 취소 뒤 종료·퇴거 등) 끝날 때까지 상한 안에서
        기다린다 — temp 와 FileManager 의 수명이 worker 를 넘긴다 (R05).
        """
        for future in [f for f in self._inflight if not f.done()]:
            await _join_worker(future, self._join_timeout)
        # 시간 초과로 버려졌지만 아직 도는 converter 스레드도 hard cap 까지 기다린다 (N03)
        for group in list(self._groups):
            if group.live():
                await asyncio.to_thread(group.join, conversion_workers.HARD_JOIN_CAP_SECONDS)
            if not group.live():
                self._groups.discard(group)
        still_alive = self.live_converter_threads
        if still_alive:
            # 성공으로 보고하지 않는다 — 풀이 close 실패를 기록하고 drain 이 False 가 되게 한다
            # (astra 3차 N03). 위임된 temp 정리는 그대로 유지되고, 다시 close() 하면 재검사한다.
            raise RuntimeError(f"converter threads still alive: {still_alive}")
        self._manager = None

    @property
    def manager(self) -> FileManager:
        if self._manager is None:
            if self.multi_user:
                raise SecurityError(ErrorCode.INTERNAL_ERROR, "FileHandler 서비스가 초기화되지 않았습니다.")
            raise RuntimeError(
                f"FileManager 를 사용할 수 없습니다: {self.init_error or 'not initialized'}"
            )
        return self._manager

    # ------------------------------------------------------------------
    # 요청 실행
    # ------------------------------------------------------------------
    @contextmanager
    def _request_work_dir(self, request_id: Optional[str]) -> Iterator[Path]:
        """이 요청만의 임시 디렉터리. 끝나면 이것만 지운다. **작업 스레드 안에서** 연다."""
        if self.multi_user:
            with ExitStack() as stack:
                directory: Optional[Path] = None
                if request_id:
                    try:
                        directory = stack.enter_context(request_temp_dir(self._paths, request_id))
                    except (FileExistsError, ValueError):
                        directory = None  # 같은 request_id 의 동시 작업·형식 불일치 → 새 id
                if directory is None:
                    directory = stack.enter_context(request_temp_dir(self._paths, uuid.uuid4().hex))
                yield directory
            return
        directory = Path(tempfile.mkdtemp(prefix="mcp_file_handler_"))
        try:
            yield directory
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    @property
    def _join_timeout(self) -> float:
        settings = self._settings or (self._manager.settings if self._manager is not None else None)
        timeout = settings.get('conversion_timeout', 300) if settings is not None else 300
        try:
            return float(timeout) + WORKER_JOIN_GRACE_SECONDS
        except (TypeError, ValueError):
            return 300.0 + WORKER_JOIN_GRACE_SECONDS

    async def _run(self, fn: Callable[..., Any], *args: Any, work_dir: bool = False, **kwargs: Any) -> Any:
        """동기 `fn` 을 작업 스레드에서 실행한다 (principal·요청 scope 를 명시적으로 전달).

        요청 디렉터리는 **작업 스레드가 소유한다** — `fn` 이 실제로 끝난 뒤 그 스레드가 지운다.
        호출 코루틴이 취소되면(반복 취소·서버 종료 포함) worker 가 끝날 때까지 상한 안에서
        기다린 뒤 취소를 올린다. 그래서 cleanup 과 lease 해제가 worker 보다 먼저 일어나지
        않는다 (astra 리뷰 R05).
        """
        loop = asyncio.get_running_loop()
        request_id = _identity_request_id() if (work_dir and self.multi_user) else None
        owner_key = self.owner_key
        group = WorkerGroup()
        self._groups.add(group)

        def runner() -> Any:
            cleanup = ExitStack()
            try:
                directory = cleanup.enter_context(self._request_work_dir(request_id)) if work_dir else None
                scope = FileRequestScope(owner_key=owner_key, work_dir=directory, loop=loop, workers=group)
                with bind_scope(scope):
                    return fn(*args, **kwargs)
            finally:
                # 실제 converter 스레드가 수명의 기준이다 (N03): 살아 있으면 hard cap 까지 기다리고,
                # 그래도 남으면 요청 디렉터리 정리를 마지막 스레드에 넘긴다(그때까지 디렉터리 유지).
                if not group.close(cleanup, conversion_workers.HARD_JOIN_CAP_SECONDS):
                    logger.warning("request cleanup deferred: a converter thread outlived the request")
                else:
                    self._groups.discard(group)

        ctx = contextvars.copy_context()
        future = loop.run_in_executor(None, ctx.run, runner)
        self._inflight.add(future)
        future.add_done_callback(self._inflight.discard)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            await _join_worker(future, self._join_timeout)
            raise

    # ------------------------------------------------------------------
    # 도구 메서드 (spec/param_spec/file_handler.yaml 의 service: 선언과 1:1)
    # ------------------------------------------------------------------
    async def process(self, input_path: str) -> Dict[str, Any]:
        return await self._run(self.manager.process, input_path, work_dir=True)

    async def process_directory(self, directory_path: str) -> List[Dict[str, Any]]:
        return await self._run(self.manager.process_directory, directory_path, work_dir=True)

    async def process_onedrive(self, url: str) -> Dict[str, Any]:
        return await self._run(self.manager.process_onedrive, url, work_dir=True)

    # 메타데이터 도구는 정규화한 참조(`file_url`)를 함께 돌려준다 — 핸들러는 입력값을
    # 반사하지 않고 이 값을 응답에 싣는다 (R14).
    @staticmethod
    def _clamp_keywords(keywords: Any) -> List[str]:
        """서비스 경계 상한 (R02): 최대 `KEYWORDS_MAX_ITEMS` 개, 항목당 `KEYWORD_MAX_LENGTH` 자, 문자열만."""
        if not isinstance(keywords, (list, tuple)):
            return []
        return [
            item[:KEYWORD_MAX_LENGTH]
            for item in list(keywords)[:KEYWORDS_MAX_ITEMS]
            if isinstance(item, str)
        ]

    def _save(self, file_url: str, keywords: List[str], additional: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        ref = self.manager.normalize_file_ref(file_url)
        saved = self.manager.save_metadata(ref, self._clamp_keywords(keywords), additional)
        return {"success": saved, "file_url": ref}

    def _search(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """저장 키 부분일치 검색. 응답에 반사하는 criteria 의 경로는 공개 참조로 바꾸거나 생략한다 (N10).

        mode 1 의 저장 키는 `files/` 기준 상대 참조 또는 URL 이다. 자기 files/ 안의 절대경로는
        상대 참조로 바꿔 검색·반사하고(그래야 매칭된다), 바꿀 수 없는 값(files/ 밖 절대경로 등)은
        원래 값으로 검색하되(매칭되지 않음) 응답에는 싣지 않는다. 단순 조각("report")과 URL 은 그대로다.
        """
        query = dict(criteria)
        echo = dict(criteria)
        if self.multi_user and 'file_url' in query:
            try:
                normalized = self.manager.normalize_file_ref(query['file_url'])
            except Exception:  # 사용자 files/ 밖 절대경로 등 — 반사하지 않는다
                echo.pop('file_url')
            else:
                query['file_url'] = echo['file_url'] = normalized
        return {"results": self.manager.search_metadata(**query), "criteria": echo}

    def _get(self, file_url: str) -> Dict[str, Any]:
        ref = self.manager.normalize_file_ref(file_url)
        metadata = self.manager.get_metadata(ref)
        return {"found": metadata is not None, "file_url": ref, "metadata": metadata}

    def _delete(self, file_url: str) -> Dict[str, Any]:
        ref = self.manager.normalize_file_ref(file_url)
        return {"deleted": self.manager.delete_metadata(ref), "file_url": ref}

    async def save_metadata(
        self,
        file_url: str,
        keywords: List[str],
        additional_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """→ `{"success": bool, "file_url": <정규화 참조>}`"""
        return await self._run(self._save, file_url, keywords, additional_metadata)

    async def search_metadata(self, **criteria: Any) -> Dict[str, Any]:
        """→ `{"results": [...], "criteria": <반사용 — file_url 은 공개 참조 또는 생략>}`"""
        return await self._run(self._search, dict(criteria))

    async def get_metadata(self, file_url: str) -> Dict[str, Any]:
        """→ `{"found": bool, "file_url": <정규화 참조>, "metadata": dict|None}`"""
        return await self._run(self._get, file_url)

    async def delete_metadata(self, file_url: str) -> Dict[str, Any]:
        """→ `{"deleted": bool, "file_url": <정규화 참조>}`"""
        return await self._run(self._delete, file_url)


__all__ = ["FileHandlerService"]
