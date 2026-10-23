"""
파일 경로 허용 목록.

FileHandler / editor 는 호출자가 준 임의 경로를 그대로 열거나 생성한다.
네트워크에 노출된 서버에서는 곧바로 로컬 파일 유출/생성 경로가 된다.
여기서 허용 루트 밖의 경로를 거부한다.

## mode 0 (단일 운영자, 기본) — 기존 동작 그대로

허용 루트 결정:
  1. MCP_ALLOWED_PATHS (os.pathsep 로 구분, 예: Windows 는 ';')
  2. 없으면 프로젝트 루트 + (있다면) MCP_DATA_DIR

심볼릭 링크/`..` 는 realpath 로 해소한 뒤 비교하므로 traversal 로 우회할 수 없다.

## mode 1 (`MS365_MULTI_USER=1`, spec/spec_멀티유저.md ②-7.4, WP3)

- `allowed_roots()` 는 **현재 principal 의 `files/` 하나**만 돌려준다. `MCP_ALLOWED_PATHS`·
  `MCP_DATA_DIR` 은 읽지 않는다(기동 검사가 이미 거부하지만, 기동 뒤에 설정돼도 무시한다).
- `resolve_safe_path()`:
  1. 상대경로는 사용자 `files/` 기준, 절대경로는 그 안일 때만
  2. UNC(`\\\\server\\share`)·장치 경로(`\\\\?\\`, `\\\\.\\`, `\\??\\`)·ADS(`name:stream`)·NUL·
     제어문자·예약 장치명(`CON`, `nul.txt` …)·드라이브 상대경로(`C:foo`, Windows 의 `\\foo`)·
     `..` 성분·끝 점/공백 성분 거부 — **결합 전에 원문을 검사**한다
     (`ntpath.join(root, "a:b")` 는 드라이브를 바꿔 버린다)
  3. root 아래 링크·junction·reparse point 거부, realpath 재확인 (`secure_files.ensure_within`)
  4. 사용자 `auth/`·`db/`·`system/` 트리는 루트 설정이 잘못돼도 거부
  5. 거부는 `path.denied` 감사(경로 미기록) + `UserPathNotAllowedError`
- principal 이 없으면 `SecurityError(missing_principal)` — 다른 루트로 대체하지 않는다.

## 오류 호환

`PathNotAllowedError` 는 그대로 `Exception` 하위 클래스다(mode 0 런타임 경로 불변). mode 1 은
하위 클래스 `UserPathNotAllowedError(PathNotAllowedError, SecurityError)` 를 올린다 —
기존 `except PathNotAllowedError` 는 그대로 잡히고, 잡지 않으면 런타임이 고정 페이로드
`{"status":"error","error":"path_not_allowed","message":...,"reason":<코드>}` 로 내보낸다.
메시지·페이로드에 절대경로가 없다. mode 0 오류를 응답용으로 바꿀 때는
`exc.to_security_error()` 를 쓴다.

`resolve_safe_path()` 는 검증용이다. 실제 열기·저장은 `mcp_common.secure_files` 로 한다.
"""

import logging
import os
import re
from pathlib import Path, PurePath
from typing import Iterable, List, Optional, Union

from mcp_common import secure_files
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_IS_WINDOWS = os.name == "nt"

PathLike = Union[str, "os.PathLike[str]"]


class PathNotAllowedError(Exception):
    """허용되지 않은 경로 접근."""

    #: 공개용 사유 코드 (mode 1 에서만 값이 있다).
    reason: Optional[str] = None

    def to_security_error(self) -> SecurityError:
        """도구 응답용 `SecurityError(PATH_NOT_ALLOWED)` (mode 0 메시지의 절대경로는 버린다)."""
        if isinstance(self, SecurityError):
            return self
        return SecurityError(ErrorCode.PATH_NOT_ALLOWED)


class UserPathNotAllowedError(PathNotAllowedError, SecurityError):
    """mode 1 경로 거부. `PathNotAllowedError` 이면서 `SecurityError(path_not_allowed)`."""

    def __init__(self, reason: str):
        SecurityError.__init__(self, ErrorCode.PATH_NOT_ALLOWED, details={"reason": reason})
        self.reason = reason


# ----------------------------------------------------------------------
# mode 0 (기존 동작 — 바꾸지 않는다)
# ----------------------------------------------------------------------
def _legacy_allowed_roots() -> List[Path]:
    configured = os.environ.get("MCP_ALLOWED_PATHS")
    roots: List[Path] = []
    if configured:
        for entry in configured.split(os.pathsep):
            entry = entry.strip().strip('"')
            if entry:
                try:
                    roots.append(Path(entry).expanduser().resolve())
                except OSError:
                    continue
    if not roots:
        roots.append(_PROJECT_ROOT)
        data_dir = os.environ.get("MCP_DATA_DIR")
        if data_dir:
            try:
                roots.append(Path(data_dir).expanduser().resolve())
            except OSError:
                pass
    return roots


def allowed_roots() -> List[Path]:
    """현재 설정된 허용 루트 목록. mode 1 은 현재 사용자 `files/` 하나."""
    if multi_user_enabled():
        return [_user_paths().files]
    return _legacy_allowed_roots()


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def is_allowed(path: PathLike, roots: Optional[Iterable[Path]] = None) -> bool:
    if multi_user_enabled():
        try:
            resolved = _resolve_for_user(path, must_exist=False, audit_denial=False)
        except PathNotAllowedError:
            return False
        if roots is None:
            return True
        # mode 1 에서 roots 는 범위를 **좁히기만** 한다.
        return any(_is_within(resolved, Path(os.path.realpath(root))) for root in roots)
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError):
        return False
    return any(_is_within(resolved, root) for root in (roots or allowed_roots()))


def resolve_safe_path(path: PathLike, *, must_exist: bool = False) -> Path:
    """
    허용 루트 안의 절대 경로로 정규화해서 돌려준다.

    Raises:
        PathNotAllowedError: 허용 루트 밖이거나 해석할 수 없는 경로
            (mode 1 은 하위 클래스 `UserPathNotAllowedError` — 절대경로 비노출)
        FileNotFoundError: must_exist=True 인데 대상이 없음
        SecurityError: mode 1 인데 요청 principal 이 없음 (`missing_principal`)
    """
    if multi_user_enabled():
        return _resolve_for_user(path, must_exist=must_exist, audit_denial=True)

    if path is None or str(path).strip() == "":
        raise PathNotAllowedError("empty path")

    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise PathNotAllowedError(f"cannot resolve path: {path!r} ({exc})") from exc

    roots = allowed_roots()
    if not any(_is_within(resolved, root) for root in roots):
        raise PathNotAllowedError(
            f"path outside allowed roots: {resolved} "
            f"(allowed: {', '.join(str(r) for r in roots)}; "
            f"set MCP_ALLOWED_PATHS to widen)"
        )

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"path does not exist: {resolved}")

    return resolved


# ----------------------------------------------------------------------
# mode 1
# ----------------------------------------------------------------------
_SEPARATORS = "\\/" if _IS_WINDOWS else "/"
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _user_paths():
    from mcp_common.principal import require_principal
    from mcp_common.user_paths import paths_for

    return paths_for(require_principal())


def _raw_problem(raw: str) -> Optional[str]:
    """결합 전 원문 검사 — UNC·장치·드라이브 상대·ADS·성분 문제. 사유 코드 또는 None."""
    if "\x00" in raw:
        return "nul"
    if re.search(r"[\x01-\x1f\x7f]", raw):
        return "control_char"
    if not _IS_WINDOWS and "\\" in raw:
        return "invalid_char"  # POSIX 에서 역슬래시 이름은 Windows 이관 시 구분자가 된다
    head = raw[:4].replace("/", "\\")
    if head.startswith("\\??\\") or head.startswith("\\\\?\\") or head.startswith("\\\\.\\"):
        return "device_path"
    if len(raw) >= 2 and raw[0] in "\\/" and raw[1] in "\\/":
        return "unc"
    rest = raw
    if _IS_WINDOWS and _DRIVE_RE.match(raw):
        if len(raw) == 2 or raw[2] not in _SEPARATORS:
            return "drive_relative"  # "C:foo" — 그 드라이브의 현재 디렉터리 기준
        rest = raw[2:]
    elif _IS_WINDOWS and raw[0] in _SEPARATORS:
        return "drive_relative"  # "\\foo" — 현재 드라이브 루트 기준
    if ":" in rest:
        return "ads"
    for part in re.split(f"[{re.escape(_SEPARATORS)}]", rest):
        problem = secure_files._component_problem(part)
        if problem:
            return problem
    return None


def _protected_roots(up) -> List[Path]:
    from mcp_common.user_paths import system_paths

    roots = [Path(up.auth_dir), Path(up.db_dir)]
    try:
        roots.append(Path(system_paths().root))
    except Exception:
        pass
    expanded: List[Path] = []
    for root in roots:
        expanded.append(Path(os.path.abspath(root)))
        expanded.append(Path(os.path.realpath(root)))
    return expanded


def _check_user_path(path: PathLike, up, must_exist: bool) -> Path:
    if path is None:
        raise UserPathNotAllowedError("empty")
    try:
        raw = os.fspath(path)
    except TypeError:
        raise UserPathNotAllowedError("invalid_type") from None
    if not isinstance(raw, str):
        raise UserPathNotAllowedError("invalid_type")
    if raw.strip() == "":
        raise UserPathNotAllowedError("empty")
    problem = _raw_problem(raw)
    if problem:
        raise UserPathNotAllowedError(problem)

    files_root = Path(os.path.abspath(up.files))
    candidate = Path(raw) if PurePath(raw).is_absolute() else files_root / raw
    target = Path(os.path.abspath(candidate))
    if not _is_within(target, files_root):
        raise UserPathNotAllowedError("outside_root")
    for directory in (up.root, up.files):
        if secure_files._is_reparse_or_link(Path(directory)):
            raise UserPathNotAllowedError("link")
    try:
        target = secure_files.ensure_within(target, files_root)
    except secure_files.UnsafePathError as exc:
        raise UserPathNotAllowedError(exc.reason or "unsafe_path") from None
    real = Path(os.path.realpath(target))
    for protected in _protected_roots(up):
        if _is_within(target, protected) or _is_within(real, protected):
            raise UserPathNotAllowedError("protected")

    if must_exist and not real.exists():
        raise FileNotFoundError(f"path does not exist: {target.relative_to(files_root).as_posix() or '.'}")
    return real


def _audit_denied(reason: str) -> None:
    try:
        from mcp_common.audit import audit
        from mcp_common.principal import current_identity

        identity = current_identity()
        audit(
            "path.denied",
            outcome="denied",
            principal=identity.principal if identity else None,
            request_id=identity.request_id if identity else None,
            error_code=ErrorCode.PATH_NOT_ALLOWED,
        )
    except Exception as exc:  # 감사 실패가 거부 결과를 바꾸지 않는다
        logger.warning("path.denied audit failed (%s)", type(exc).__name__)
    logger.info("path denied (reason=%s)", reason)


def _resolve_for_user(path: PathLike, *, must_exist: bool, audit_denial: bool) -> Path:
    up = _user_paths()  # principal 없으면 여기서 missing_principal
    try:
        return _check_user_path(path, up, must_exist)
    except UserPathNotAllowedError as exc:
        if audit_denial:
            _audit_denied(exc.reason or "unknown")
        raise
