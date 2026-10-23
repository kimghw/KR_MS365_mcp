"""Main entry point for file conversion and management.

보안 주의:
    이 모듈은 MCP 도구를 통해 **호출자가 준 임의 경로**를 받는다.

    - mode 0: 파일/디렉터리를 여는 모든 진입점은 `mcp_common.paths.resolve_safe_path()`
      허용 루트(기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장) 안이어야 한다.
    - mode 1 (`MS365_MULTI_USER=1`): 허용 범위는 서비스 소유자의 `files/` 하나다
      (`path_policy.resolve_user_path`). 자기 `auth/`·`db/` 도 거부한다. 응답과
      메타데이터 키에는 절대경로 대신 `files/` 기준 상대경로를 싣고, 오류 문구에
      예외 원문(경로·URL·외부 응답 본문)을 싣지 않는다. 경로 위반은 `path_not_allowed`.

    OneDrive 다운로드는 **요청 전용 디렉터리**(mode 1: `files/tmp/<request_id>/` 아래)에만
    쓰고 그 디렉터리만 지운다. 다운로드한 파일은 그 디렉터리 안인지 다시 확인한다 —
    허용 루트를 넓히던 `trusted_roots` 예외는 없다 (spec/spec_멀티유저.md ②-2.5, ②-7.4).

    mode 1 의 로컬 입력은 검증한 handle(`secure_files.open_for_read`)에서 **요청 디렉터리로
    배타 복사**한 뒤 그 복사본을 변환기에 준다 — 경로만 받는 변환기가 원래 경로를 다시 열지
    않는다 (astra 리뷰 R12).

    자원 상한(`limits.RequestLimits`, R09): 파일 바이트·요청 예산·파일 수·폴더 깊이·결과 문자 수·
    변환 시간. 변환기는 서비스당 `max_workers` 개로 제한된 스레드에서 돌고, 시간을 넘기면 결과를
    버린다(스레드는 강제 종료할 수 없어 끝날 때까지 슬롯을 점유한다 — 그래서 슬롯이 상한이다).

    mode 1 의 모든 작업은 요청 scope(`request_scope`)와 principal 이 서비스 소유자와
    같을 때만 돈다. AuthManager 를 만들지 않는다 — 토큰은 주입된 사용자 공급자에서만 얻는다.
"""

import contextvars
import os
import shutil
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from mcp_common.paths import PathNotAllowedError, allowed_roots, resolve_safe_path
from mcp_common.secure_files import UnsafePathError, create_exclusive, ensure_within, open_for_read
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

from . import conversion_workers
from .config.settings import Settings
from .limits import LimitExceeded, RequestLimits, StreamGuard
from .metadata.manager import MetadataManager
from .onedrive.processor import OneDriveProcessor
from .path_policy import path_denied, public_error, public_ref, resolve_user_path
from .request_scope import current_scope, require_scope, scope_work_dir
from .utils import FileDetector, setup_logger

logger = setup_logger('file_manager')

# 로컬 경로가 아니라 원격 참조로 취급할 접두사 (경로 검증 대상 아님)
_REMOTE_PREFIXES = ('http://', 'https://', 'onedrive:')
_COPY_CHUNK = 256 * 1024
#: 변환 슬롯을 기다리는 최대 시간(초) — 그 뒤는 `overloaded`
_SLOT_WAIT_SECONDS = 30.0


def _is_remote_ref(value: Any) -> bool:
    """metadata file_url 등이 로컬 경로가 아닌 원격 URL 인지 판정."""
    return isinstance(value, str) and value.strip().lower().startswith(_REMOTE_PREFIXES)


def _allowed_roots_text() -> str:
    """mode 0 오류 메시지용. mode 1 은 경로를 응답에 싣지 않는다(이중 잠금으로 빈 문자열)."""
    if multi_user_enabled():
        return ''
    return ', '.join(str(root) for root in allowed_roots())


def _empty_result() -> Dict[str, Any]:
    return {'success': False, 'text': '', 'metadata': {}, 'errors': []}


class FileManager:
    """Central manager for file conversion operations."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        paths: Any = None,
        token_provider: Any = None,
        auth_manager: Any = None,
        settings: Optional[Settings] = None,
    ):
        """Initialize FileManager.

        Args:
            config: Optional configuration dictionary
            paths: mode 1 필수 — 서비스 소유자의 `UserPaths`
            token_provider: mode 1 필수 — 같은 사용자에 고정된 `BoundTokenProvider`
            auth_manager: mode 0 전용 (없으면 첫 OneDrive 토큰 요청 때 공유 AuthManager)
            settings: 이미 검증한 Settings (없으면 config 로 만든다)
        """
        self.multi_user = multi_user_enabled()
        if self.multi_user and (paths is None or token_provider is None):
            raise SecurityError(
                ErrorCode.CONFIG_ERROR,
                "멀티유저 FileManager 에는 사용자 경로와 토큰 공급자가 필요합니다.",
            )
        self.paths = paths if self.multi_user else None
        self.owner_key: Optional[str] = paths.user_key if self.multi_user else None

        self.settings = settings or Settings(config, paths=self.paths)
        self.file_detector = FileDetector()
        self.metadata_manager = MetadataManager(self.settings, owner_key=self.owner_key)
        self.auth_manager = auth_manager
        self.onedrive_processor = OneDriveProcessor(
            auth_manager,
            token_provider=token_provider,
            files_root=self.paths.files if self.multi_user else None,
        )

        # mode 1 은 프로세스 로깅을 bootstrap 이 정한다(사용자별 인스턴스가 전역 logger 를
        # 재구성하거나 사용자별 로그 파일을 열지 않게 한다).
        if not self.multi_user:
            setup_logger(
                level=self.settings.get('log_level', 'INFO'),
                log_file=self.settings.get('log_file')
            )

    # ------------------------------------------------------------------
    # 경로 검증 헬퍼
    # ------------------------------------------------------------------
    def _resolve_path(self, path: Any, *, must_exist: bool) -> Path:
        """mode 1: 사용자 files/ 루트 / mode 0: mcp_common.paths 허용 루트."""
        if self.multi_user:
            return resolve_user_path(self.paths, path, must_exist=must_exist)
        return resolve_safe_path(path, must_exist=must_exist)

    def _resolve_readable_path(self, path: Any, *, must_exist: bool = True) -> Path:
        """읽기 대상 경로를 허용 범위 안의 절대 경로로 정규화한다.

        Raises:
            SecurityError: mode 1 경계 위반 (`path_not_allowed`)
            PathNotAllowedError: mode 0 허용 루트 밖이거나 해석 불가한 경로
            FileNotFoundError: must_exist=True 인데 대상이 없음
        """
        return self._resolve_path(path, must_exist=must_exist)

    def _public(self, path: Any) -> str:
        """응답·메타데이터 키에 싣는 경로 표기."""
        return public_ref(self.paths, path) if self.multi_user else str(path)

    def _display_name(self, path: Path) -> str:
        return path.name if self.multi_user else str(path)

    def _error_text(self, exc: BaseException) -> str:
        if isinstance(exc, LimitExceeded):
            return exc.message  # 고정 공개 문구
        return public_error(exc) if self.multi_user else str(exc)

    def _limits_for(self, kwargs: Dict[str, Any]) -> RequestLimits:
        """요청 상한 — 한 도구 호출의 모든 하위 작업이 같은 객체를 공유한다(`_limits` kwarg)."""
        limits = kwargs.get('_limits')
        if limits is None:
            limits = RequestLimits.from_settings(self.settings)
            kwargs['_limits'] = limits
        return limits

    def normalize_file_ref(self, file_url: str) -> str:
        """메타데이터 키·응답에 쓸 파일 참조 (R14 — 응답은 입력이 아니라 이 값을 반사한다).

        원격 URL 은 그대로 두고, 로컬 경로는 허용 범위 검증 후 mode 0 은 절대 경로,
        mode 1 은 `files/` 기준 상대경로로 바꾼다. 위반은 그대로 올린다. 멱등이다.
        """
        if _is_remote_ref(file_url):
            return file_url
        return self._public(self._resolve_path(file_url, must_exist=False))

    _normalize_file_ref = normalize_file_ref

    def _rejected_path_result(self, result: Dict[str, Any], exc: PathNotAllowedError,
                              label: str = '경로') -> Dict[str, Any]:
        """mode 0 의 경로 거부 응답(기존 동작). mode 1 은 `path_not_allowed` 로 올린다."""
        if self.multi_user:
            raise path_denied() from None
        logger.warning("Rejected a path outside the allowed roots")
        result['errors'].append(
            f"허용되지 않은 {label}입니다: {exc} (허용 루트: {_allowed_roots_text()})"
        )
        return result

    # ------------------------------------------------------------------
    # 변환
    # ------------------------------------------------------------------
    def process(self, input_path: str, **kwargs) -> Dict[str, Any]:
        """Process file or URL for text extraction.

        Args:
            input_path: File path or URL to process
            **kwargs: Additional options

        Returns:
            Dictionary with extracted text and metadata
        """
        require_scope(self.owner_key)
        self._limits_for(kwargs)
        result = _empty_result()

        try:
            # Check if input is URL
            if self.file_detector.is_url(input_path):
                if self.file_detector.is_onedrive_url(input_path):
                    return self._process_onedrive_url(input_path, **kwargs)
                result['errors'].append(f"Unsupported URL type: {input_path}")
                return result

            # Process local file
            return self._process_local_file(input_path, **kwargs)

        except SecurityError:
            raise
        except PathNotAllowedError as e:
            return self._rejected_path_result(result, e)
        except Exception as e:
            logger.error("Error processing input: %s", type(e).__name__)
            result['errors'].append(self._error_text(e))
            return result

    def _process_local_file(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """Process local file (허용 범위 검증 + 존재 확인 → 변환)."""
        result = _empty_result()

        try:
            resolved = self._resolve_readable_path(file_path, must_exist=True)
        except SecurityError:
            raise
        except PathNotAllowedError as e:
            return self._rejected_path_result(result, e)
        except FileNotFoundError as e:
            result['errors'].append(self._error_text(e))
            return result

        limits = self._limits_for(kwargs)
        source = resolved
        try:
            if self.multi_user:
                # 검증한 handle 에서 요청 디렉터리로 배타 복사 — 변환기는 복사본만 연다 (R12)
                source = self._stage_input(resolved, limits)
            else:
                size = resolved.stat().st_size
                limits.check_file_size(size)
                limits.budget.consume(size)  # 로컬 입력도 요청 예산을 쓴다 (N08)
        except UnsafePathError:
            raise path_denied() from None
        except (FileNotFoundError, IsADirectoryError, LimitExceeded) as e:
            result['errors'].append(self._error_text(e))
            return result

        return self._convert_resolved(source, result, metadata_ref=resolved, **kwargs)

    def _stage_input(self, resolved: Path, limits: RequestLimits) -> Path:
        """`open_for_read` 로 연 handle 을 요청 디렉터리 `input/` 에 배타 복사한다 (크기 상한 적용)."""
        work_dir = scope_work_dir()
        guard = StreamGuard(limits)
        with open_for_read(resolved, self.paths.files) as src:
            limits.check_file_size(os.fstat(src.fileno()).st_size)
            copy_path, handle = create_exclusive(work_dir / 'input', resolved.name, root=work_dir)
            try:
                with handle:
                    while True:
                        chunk = src.read(_COPY_CHUNK)
                        if not chunk:
                            break
                        guard.add(len(chunk))
                        handle.write(chunk)
            except BaseException:
                try:
                    copy_path.unlink()
                except OSError:
                    pass
                raise
        return copy_path

    def _run_converter(self, converter: Any, file_path: str, limits: RequestLimits) -> str:
        """변환기를 사용자별 슬롯 제한 스레드에서 돌리고 요청 마감까지만 기다린다 (R09·N03).

        스레드는 강제 종료할 수 없다. 마감을 넘기면 결과를 버리고 `conversion_timeout` 을
        올리되, 스레드는 요청 scope 의 `WorkerGroup` 에 등록돼 있어 요청 디렉터리 정리와
        서비스 종료가 그 스레드가 끝날 때까지 기다린다. 슬롯은 **프로세스 전역 user_key 별**
        (`conversion_workers.slots_for`)이라 서비스가 재생성돼도 상한을 넘지 못한다.
        """
        remaining = limits.remaining_seconds()
        if remaining <= 0:
            raise LimitExceeded('conversion_timeout')
        slots = conversion_workers.slots_for(self.owner_key, limits.max_workers)
        if not slots.acquire(timeout=min(remaining, _SLOT_WAIT_SECONDS)):
            raise SecurityError(ErrorCode.OVERLOADED)
        scope = current_scope()
        group = scope.workers if scope is not None else None
        outcome: Dict[str, Any] = {}
        holder: Dict[str, threading.Thread] = {}

        def work() -> None:
            try:
                outcome['text'] = converter.convert(file_path)
            except BaseException as exc:  # noqa: BLE001 - 호출 스레드로 그대로 넘긴다
                outcome['error'] = exc
            finally:
                slots.release()
                if group is not None:
                    group.finished(holder['thread'])

        # principal·요청 scope 를 변환 스레드에도 명시적으로 전달한다 (C03)
        thread = threading.Thread(
            target=contextvars.copy_context().run, args=(work,), name='fh-convert', daemon=True
        )
        holder['thread'] = thread
        if group is not None:
            group.register(thread)
        thread.start()
        thread.join(timeout=limits.remaining_seconds())
        if thread.is_alive():
            logger.warning("conversion exceeded the request time limit; worker result discarded")
            raise LimitExceeded('conversion_timeout')
        if 'error' in outcome:
            raise outcome['error']
        return outcome['text']

    def _convert_resolved(
        self, path: Path, result: Dict[str, Any], *, metadata_ref: Optional[Path] = None, **kwargs
    ) -> Dict[str, Any]:
        """이미 검증된 경로를 변환한다. 경로 검증은 호출자가 끝낸 상태여야 한다.

        Args:
            path: 변환기에 줄 파일 (mode 1 로컬 입력은 요청 디렉터리의 복사본)
            metadata_ref: 메타데이터 키로 쓸 원래 경로 (없으면 `path`)
        """
        file_path = str(path)
        limits = self._limits_for(kwargs)

        converter = self.file_detector.get_converter(file_path)
        if not converter:
            result['errors'].append(f"No converter available for: {self._display_name(path)}")
            return result

        try:
            limits.check_deadline()
            text = self._run_converter(converter, file_path, limits)
            metadata = converter.get_metadata(file_path)

            text, truncated = limits.cap_output(text)
            if truncated:
                metadata['truncated'] = True
                result['errors'].append(LimitExceeded('output_truncated').message)

            # Store metadata if requested
            if kwargs.get('save_metadata', False):
                keywords = kwargs.get('keywords', [])
                self.metadata_manager.save(self._public(metadata_ref or path), keywords, metadata)

            result.update({
                'success': True,
                'text': text,
                'metadata': metadata
            })

        except SecurityError:
            raise
        except Exception as e:
            logger.error("Conversion failed: %s", type(e).__name__)
            result['errors'].append(self._error_text(e))

        return result

    # ------------------------------------------------------------------
    # OneDrive
    # ------------------------------------------------------------------
    @contextmanager
    def _download_dir(self, output_dir: Optional[str]) -> Iterator[Path]:
        """OneDrive 다운로드 위치.

        - `output_dir` 지정: 그 디렉터리(지우지 않는다). mode 1 은 상대경로를
          `files/downloads/file_handler/` 기준으로 풀고 `files/` 밖을 거부한다.
        - 미지정: 요청 작업 디렉터리 아래 새 하위 디렉터리를 만들고 끝나면 **그것만** 지운다.
          mode 1 에서 요청 scope 가 없으면 실패한다(시스템 temp 금지).
        """
        if output_dir:
            if self.multi_user:
                target = resolve_user_path(
                    self.paths, output_dir, must_exist=False,
                    base=Path(self.settings.get('download_dir')),
                )
            else:
                target = resolve_safe_path(output_dir, must_exist=False)
            target.mkdir(parents=True, exist_ok=True)
            yield target
            return

        scope = current_scope()
        base = scope.work_dir if scope is not None else None
        if base is None and self.multi_user:
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
        target = Path(tempfile.mkdtemp(prefix='onedrive_', dir=str(base) if base else None))
        try:
            yield target
        finally:
            shutil.rmtree(target, ignore_errors=True)

    def _check_download(self, local_path: Any, target: Path) -> Path:
        """다운로드 결과가 이 요청의 다운로드 디렉터리 안인지 확인한다.

        mode 1 은 공용 관문(`resolve_safe_path` — 호출자 files/ 범위)도 다시 통과시킨다.
        mode 0 은 다운로드 디렉터리가 허용 루트 밖(시스템 temp)일 수 있으므로, 허용 루트를
        넓히는 대신 **이 요청이 만든 디렉터리 안**으로만 좁혀 신뢰한다.
        """
        path = Path(local_path)
        try:
            ensure_within(path, target)
        except UnsafePathError:
            if self.multi_user:
                raise path_denied() from None
            raise PathNotAllowedError("downloaded file escaped the download directory") from None
        if self.multi_user:
            path = resolve_user_path(self.paths, path, must_exist=True)
        if not path.is_file():
            raise FileNotFoundError("downloaded file is missing")
        return path

    def _process_onedrive_url(self, url: str, **kwargs) -> Dict[str, Any]:
        """Process OneDrive URL (요청 전용 디렉터리로 받아 변환한 뒤 그 디렉터리만 정리)."""
        result = _empty_result()
        recursive = kwargs.get('recursive', True)
        limits = self._limits_for(kwargs)

        try:
            with self._download_dir(kwargs.get('output_dir')) as target:
                items = self.onedrive_processor.download(
                    url, target, recursive=recursive, limits=limits
                )

                if not items:
                    result['errors'].append("No files downloaded from OneDrive")
                    return result

                all_text: List[str] = []
                all_metadata: List[Dict[str, Any]] = []

                for item in items:
                    if item.get('type') != 'file':
                        continue
                    local = self._check_download(item['local_path'], target)
                    file_result = self._convert_resolved(local, _empty_result(), **kwargs)
                    if file_result['success']:
                        all_text.append(f"--- {item['name']} ---")
                        all_text.append(file_result['text'])
                        all_metadata.append(file_result['metadata'])
                    else:
                        result['errors'].extend(file_result['errors'])

                result.update({
                    'success': len(all_text) > 0,
                    'text': '\n\n'.join(all_text),
                    'metadata': {
                        'source': 'onedrive',
                        'url': url,
                        'files_processed': len(all_metadata),
                        'file_metadata': all_metadata
                    }
                })

        except SecurityError:
            raise
        except PathNotAllowedError as e:
            return self._rejected_path_result(result, e, 'output_dir 또는 다운로드 경로')
        except UnsafePathError:
            # 원격 이름으로 만든 경로가 다운로드 디렉터리를 벗어남 (safe_join 이 막음)
            if self.multi_user:
                raise path_denied() from None
            result['errors'].append("다운로드 경로가 허용 범위를 벗어났습니다.")
        except Exception as e:
            logger.error("OneDrive processing failed: %s", type(e).__name__)
            result['errors'].append(self._error_text(e))

        return result

    def process_onedrive(self, url: str, **kwargs) -> Dict[str, Any]:
        """Process OneDrive URL for text extraction."""
        require_scope(self.owner_key)
        self._limits_for(kwargs)
        return self._process_onedrive_url(url, **kwargs)

    # ------------------------------------------------------------------
    # 디렉터리
    # ------------------------------------------------------------------
    def process_directory(self, directory_path: str, **kwargs) -> List[Dict[str, Any]]:
        """Process all files in a directory.

        Raises:
            SecurityError: mode 1 경계 위반 (`path_not_allowed`)
            PathNotAllowedError: mode 0 허용 루트 밖의 디렉터리
            FileNotFoundError: 존재하지 않는 경로
            NotADirectoryError: 디렉터리가 아님
            ValueError: pattern 이 절대 경로일 때

        조용히 빈 목록을 돌려주면 실패가 성공처럼 보이므로, 잘못된 입력은 예외로 올린다.
        """
        require_scope(self.owner_key)
        limits = self._limits_for(kwargs)
        results: List[Dict[str, Any]] = []

        dir_path = self._resolve_path(directory_path, must_exist=True)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {self._display_name(dir_path)}")

        # Get file pattern from kwargs
        pattern = kwargs.get('pattern', '*') or '*'
        recursive = kwargs.get('recursive', False)

        # 절대 경로 패턴은 허용 루트 밖을 노릴 수 있으므로 거부한다.
        if Path(pattern).is_absolute():
            raise ValueError("pattern must be relative")

        files = dir_path.rglob(pattern) if recursive else dir_path.glob(pattern)

        for file_path in files:
            if not file_path.is_file():
                continue
            limits.check_deadline()  # 요청 마감이 지나면 남은 파일을 처리하지 않는다
            limits.count_file()      # 다운로드와 같은 요청당 파일 수 상한 (N08)

            # 패턴/심볼릭 링크로 허용 범위를 벗어난 항목은 건너뛴다.
            try:
                safe_path = self._resolve_path(file_path, must_exist=True)
            except (SecurityError, PathNotAllowedError, FileNotFoundError):
                logger.warning("Skipped a directory entry outside the allowed roots")
                continue

            result = self.process(str(safe_path), **kwargs)
            result['file'] = self._public(safe_path)
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # 메타데이터 (mode 1: 소유자 격리 저장소 — 모든 SQL 에 owner 조건)
    # ------------------------------------------------------------------
    def save_metadata(self, file_url: str, keywords: List[str],
                      additional_metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Save metadata for a file.

        Raises:
            SecurityError / PathNotAllowedError: 허용 범위 밖의 로컬 경로
        """
        require_scope(self.owner_key)
        file_url = self._normalize_file_ref(file_url)
        try:
            return self.metadata_manager.save(file_url, keywords, additional_metadata)
        except Exception as e:
            logger.error("Failed to save metadata: %s", type(e).__name__)
            return False

    def search_metadata(self, **search_criteria) -> List[Dict[str, Any]]:
        """Search metadata (호출자 소유 항목만)."""
        require_scope(self.owner_key)
        # DB 예외는 삼키지 않는다: "결과 0건"은 storage 가 정상적으로 빈 리스트를
        # 반환하며, 실제 DB 예외는 상위 런타임에서 isError 로 승격되도록 전파한다.
        return self.metadata_manager.search(**search_criteria)

    def get_metadata(self, file_url: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a file (미존재·타 사용자 항목 → None)."""
        require_scope(self.owner_key)
        file_url = self._normalize_file_ref(file_url)
        # 미존재는 None(정상 "결과 없음"), 실제 DB 예외는 실패로 전파한다.
        return self.metadata_manager.get(file_url)

    def delete_metadata(self, file_url: str) -> bool:
        """Delete metadata for a file (타 사용자 항목은 건드리지 않는다 → False)."""
        require_scope(self.owner_key)
        file_url = self._normalize_file_ref(file_url)
        # 미존재/멱등 재삭제는 False(정상), 실제 DB 예외는 실패로 전파한다.
        return self.metadata_manager.delete(file_url)


def main():
    """CLI entry point (mode 0 전용)."""
    import argparse

    parser = argparse.ArgumentParser(description='File to Text Converter')
    parser.add_argument('input', help='File path or URL to process')
    parser.add_argument('--output', '-o', help='Output file path')
    parser.add_argument('--keywords', '-k', nargs='+', help='Keywords for metadata')
    parser.add_argument('--save-metadata', action='store_true',
                        help='Save metadata to storage')
    parser.add_argument('--recursive', '-r', action='store_true',
                        help='Process directory recursively')
    parser.add_argument('--pattern', '-p', default='*',
                        help='File pattern for directory processing')

    args = parser.parse_args()

    # Initialize manager
    manager = FileManager()

    # Process input
    if Path(args.input).is_dir():
        try:
            results = manager.process_directory(
                args.input,
                recursive=args.recursive,
                pattern=args.pattern,
                keywords=args.keywords or [],
                save_metadata=args.save_metadata
            )
        except (PathNotAllowedError, OSError, ValueError) as e:
            print(f"Directory processing failed: {e}")
            sys.exit(1)

        for result in results:
            if result['success']:
                print(f"[OK] {result['file']}")
            else:
                print(f"[FAIL] {result['file']}: {result['errors']}")

    else:
        result = manager.process(
            args.input,
            keywords=args.keywords or [],
            save_metadata=args.save_metadata
        )

        if result['success']:
            if args.output:
                try:
                    output_path = resolve_safe_path(args.output, must_exist=False)
                except PathNotAllowedError as e:
                    print(f"Output path rejected: {e}")
                    sys.exit(1)
                output_path.write_text(result['text'], encoding='utf-8')
                print(f"Text saved to: {output_path}")
            else:
                print(result['text'])
        else:
            print(f"Conversion failed: {result['errors']}")
            sys.exit(1)


if __name__ == '__main__':
    main()
