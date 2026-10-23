"""
Outlook 로컬 파일 배치 정책 (spec/spec_멀티유저.md ②-7.3·7.4, WP4).

mode 1 에서 Outlook 이 만들거나 읽는 로컬 파일은 전부 이 모듈을 거친다. 서비스에
`UserPaths` 가 주입되면 mode 1 동작, 없으면 mode 0(기존) 동작이다.

| 항목 | mode 0 (`paths` 없음) | mode 1 (`UserPaths` 주입) |
|------|------|------|
| 기본 저장 위치 (`save_directory` 생략·`"downloads"`) | `<프로젝트 루트>/downloads` | `files/downloads/outlook/` |
| 호출자가 준 저장 위치 | 상대경로는 프로젝트 루트 기준 (기존) | `mcp_common.paths.resolve_safe_path` + 사용자 `files/` 경계. 상대경로는 `files/` 기준 |
| 원격 첨부 이름 | 구분자 제거 후 같은 폴더에 배타 생성(`_1` 접미사) | 구분자 제거 + `secure_files.write_new_file(..., root=paths.files)` (배타 생성, ` (1)` 접미사) |
| 응답에 싣는 경로 | 절대경로 (기존) | `files/` 기준 상대경로 (`public_path`) |
| 발송 첨부(로컬 파일 읽기) | 제한 없음 (기존) | `resolve_safe_path` + 사용자 `files/` 경계 |

`"downloads"` 는 param_spec 의 `save_directory` 기본값이다. mode 1 에서는 이것을 "도메인
다운로드 영역" 으로 해석해 `files/downloads/outlook/` 으로 보낸다(사용자 사이에 공유되지
않는다 — ②-7.3 downloads 행). 경계 위반은 `SecurityError(PATH_NOT_ALLOWED)` 이고,
메시지·로그에 절대경로를 싣지 않는다.
"""

from pathlib import Path
from typing import Any, Optional

from mcp_common import paths as common_paths
from mcp_common.secure_files import UnsafePathError, ensure_within, public_path
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.user_paths import UserPaths

DOMAIN = "outlook"
LEGACY_DOWNLOADS = "downloads"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _deny() -> None:
    raise SecurityError(ErrorCode.PATH_NOT_ALLOWED)


def legacy_dir(raw: Optional[Any]) -> Path:
    """mode 0: 상대경로는 프로젝트 루트 기준 (기존 동작 그대로)."""
    path = Path(str(raw) if raw else LEGACY_DOWNLOADS)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path


def within_files(paths: UserPaths, path: Path) -> Path:
    """사용자 `files/` 안의 경로인지(링크·reparse point 포함) 확인한다."""
    try:
        return ensure_within(Path(path), paths.files)
    except (UnsafePathError, OSError, ValueError):
        _deny()


def _gate(raw: Any, *, must_exist: bool = False) -> Path:
    """공용 관문 `mcp_common.paths.resolve_safe_path` (mode 1: 허용 루트 = 요청 principal 의 files/).

    상대경로는 `files/` 기준, UNC·장치·드라이브 상대·ADS·예약명·`..`·링크·`auth/`·`db/` 는
    관문이 거부한다(`UserPathNotAllowedError` = `SecurityError(path_not_allowed)`, 경로 비노출).
    """
    if raw is None or str(raw).strip() == "":
        _deny()
    try:
        return Path(common_paths.resolve_safe_path(str(raw).strip(), must_exist=must_exist))
    except SecurityError:
        raise
    except FileNotFoundError:
        raise
    except (common_paths.PathNotAllowedError, PermissionError, OSError, ValueError, TypeError):
        _deny()


def resolve_save_dir(paths: UserPaths, raw: Optional[Any]) -> Path:
    """mode 1 저장 디렉터리 (생성까지). 기본값은 `files/downloads/outlook/`.

    관문 결과를 다시 **이 서비스의** `paths.files` 로 확인한다 — 요청 principal 과 서비스
    소유자가 어긋나면(배선 오류) 거부된다.
    """
    if raw is None or str(raw).strip() in ("", LEGACY_DOWNLOADS):
        target = within_files(paths, paths.downloads_for(DOMAIN))
    else:
        target = within_files(paths, _gate(raw))
    target.mkdir(parents=True, exist_ok=True)
    return within_files(paths, target)


def resolve_read_file(paths: UserPaths, raw: Any) -> Path:
    """mode 1 에서 읽을 로컬 파일(발송 첨부). 없으면 ValueError(경로 비노출)."""
    try:
        resolved = within_files(paths, _gate(raw, must_exist=True))
    except FileNotFoundError:
        raise ValueError("첨부파일을 찾을 수 없음") from None
    if not resolved.is_file():
        raise ValueError("첨부파일을 찾을 수 없음")
    return resolved


def resolve_ref(paths: UserPaths, ref: Any) -> Path:
    """저장소가 돌려준 폴더 참조(`files/` 기준 상대경로 또는 절대경로) → 절대경로."""
    path = Path(str(ref))
    if not path.is_absolute():
        path = paths.files / path
    return within_files(paths, path)


def to_public(paths: UserPaths, path: Any) -> str:
    """응답용 상대경로 (`files/` 기준 posix)."""
    try:
        return public_path(paths, Path(path))
    except UnsafePathError:
        _deny()


__all__ = [
    "DOMAIN",
    "LEGACY_DOWNLOADS",
    "legacy_dir",
    "within_files",
    "resolve_save_dir",
    "resolve_read_file",
    "resolve_ref",
    "to_public",
]
