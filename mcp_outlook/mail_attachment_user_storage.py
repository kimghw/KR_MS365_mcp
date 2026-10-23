"""
mode 1 로컬 저장 Backend — 사용자 `files/` 전용 (spec/spec_멀티유저.md ②-7.4, WP4).

`LocalStorageBackend` 와 같은 인터페이스지만 다음이 다르다.

| 항목 | LocalStorageBackend (mode 0) | UserLocalStorageBackend (mode 1) |
|------|------|------|
| 기준 디렉터리 | 프로젝트 루트 기준 | `outlook_file_policy.resolve_save_dir()` 결과 (사용자 `files/` 안) |
| 폴더·파일 참조 (반환값·입력) | 절대경로 | `files/` 기준 상대경로 (`public_path`) — 응답에 절대경로 비노출 |
| 파일 생성 | `_1` 접미사 배타 생성, 본문은 덮어쓰기 | `secure_files.write_new_file(root=paths.files)` (최종 경로·handle 경계 확인 + 배타 생성, ` (1)` 접미사) |
| 누적 저장 quota | 없음 | 사용자 `files/` 전체 합계 ≤ `MAX_USER_DOWNLOAD_BYTES`(2 GiB), 초과는 `quota_exceeded` (N08; 호출자 지정 저장 폴더도 포함) |
| 원격 이름 | 구분자 제거 | 구분자 제거 + `safe_filename`/`write_new_file` 의 단일 이름 강제 |

폴더 참조가 사용자 `files/` 밖을 가리키면 `SecurityError(PATH_NOT_ALLOWED)` — 저장소 내부
배선 오류이므로 조용히 삼키지 않는다.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from mcp_common.secure_files import UnsafePathError, safe_filename, write_new_file
from mcp_common.user_paths import UserPaths

from . import outlook_security as limits
from .mail_attachment_storage import LocalStorageBackend, build_mail_content_text
from .outlook_file_policy import resolve_ref, to_public, within_files

logger = logging.getLogger(__name__)


class UserLocalStorageBackend(LocalStorageBackend):
    """사용자 `files/` 안에만 쓰는 로컬 저장소."""

    def __init__(self, paths: UserPaths, base_directory: Path):  # noqa: D401 - 부모 __init__ 미사용
        self.paths = paths
        base = within_files(paths, Path(base_directory))
        base.mkdir(parents=True, exist_ok=True)
        self.base_directory = within_files(paths, base)
        self._usage: Optional[int] = None  # 사용자 files/ 전체 누적 바이트 (첫 쓰기 때 계산)

    # ------------------------------------------------------------------
    def _scan_usage(self) -> int:
        """사용자 `files/` **전체**의 일반 파일 크기 합 (링크는 세지 않는다).

        Outlook 은 호출자가 준 `save_directory` 로 `files/` 아래 어디든 쓸 수 있으므로(astra 3차
        N08 gap 2) 집계 범위를 `downloads/outlook` 이 아니라 사용자 파일 루트 전체로 둔다 —
        Outlook 이 쓰는 모든 바이트가 quota 안에 들어오고, 다른 도메인이 채운 용량도 같은
        한도에서 빠진다(quota 는 "이 사용자 files/ 의 총량 ≤ MAX_USER_DOWNLOAD_BYTES").
        """
        root = Path(self.paths.files)
        total = 0
        if not root.is_dir():
            return 0
        for path in root.rglob("*"):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def _reserve(self, size: int) -> None:
        """누적 quota(N08) — 쓰기 전에 확인한다. 같은 저장소 인스턴스 안에서는 쓴 만큼 더해 간다.

        동시 요청끼리는 각자 첫 쓰기 때 스캔한 값에 자기 몫만 더하므로 한도를 다소 넘길 수 있다 —
        quota 는 정확한 계량이 아니라 상한 방어다.
        """
        if self._usage is None:
            self._usage = self._scan_usage()
        if self._usage + size > limits.MAX_USER_DOWNLOAD_BYTES:
            logger.warning("[LOCAL] user download quota exceeded")
            raise limits.quota_exceeded(limits.MAX_USER_DOWNLOAD_BYTES)
        self._usage += size

    # ------------------------------------------------------------------
    def _folder(self, folder_ref: Optional[Any]) -> Path:
        if folder_ref is None or str(folder_ref) == "":
            return self.base_directory
        return resolve_ref(self.paths, folder_ref)

    def public(self, path: Any) -> str:
        return to_public(self.paths, path)

    # ------------------------------------------------------------------
    async def create_folder(self, mail_data: Dict[str, Any]) -> str:
        folder = within_files(self.paths, self.base_directory / safe_filename(self.create_folder_name(mail_data)))
        folder.mkdir(parents=True, exist_ok=True)
        return self.public(folder)

    async def create_folder_flat(self, base_path: Optional[str] = None) -> str:
        folder = self._folder(base_path)
        folder.mkdir(parents=True, exist_ok=True)
        return self.public(folder)

    def folder_for_name(self, base_dir: Path, name: Optional[str]) -> Path:
        """`base_dir/<원격 이름 하나>` (생성까지). 원격 이름은 단일 성분으로 정화된다."""
        folder = within_files(self.paths, Path(base_dir) / safe_filename(self.sanitize_filename(name or "", 100)))
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_bytes(self, folder: Path, filename: Optional[str], content: bytes) -> Path:
        """배타 생성으로 쓰고 최종 경로를 돌려준다(절대경로 — 호출 측이 public 으로 바꾼다)."""
        target_dir = within_files(self.paths, Path(folder))
        safe_name = self.sanitize_filename(filename or "", max_length=100)
        self._reserve(len(content))
        path = write_new_file(target_dir, safe_name, content, root=self.paths.files)
        return within_files(self.paths, path)

    async def save_file(
        self,
        folder_path: str,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        folder = self._folder(folder_path)
        try:
            path = self.write_bytes(folder, filename, content)
        except UnsafePathError:
            logger.warning("[LOCAL] attachment save rejected: path boundary")
            return None
        except OSError as exc:
            logger.warning("[LOCAL] attachment save failed: %s", type(exc).__name__)
            return None
        logger.info("[LOCAL] saved attachment (%d bytes)", len(content))
        return self.public(path)

    async def save_mail_content(self, folder_path: str, mail_data: Dict[str, Any]) -> Optional[str]:
        folder = self._folder(folder_path)
        try:
            path = self.write_bytes(folder, "mail_content.txt", build_mail_content_text(mail_data).encode("utf-8"))
        except (UnsafePathError, OSError) as exc:
            logger.warning("[LOCAL] mail body save failed: %s", type(exc).__name__)
            return None
        logger.info("[LOCAL] saved mail_content.txt")
        return self.public(path)


__all__ = ["UserLocalStorageBackend"]
