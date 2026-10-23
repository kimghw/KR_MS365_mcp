"""
mode 1 경로 정책 — FileHandler 가 호출자의 `files/` 루트 밖을 열지 못하게 한다
(spec/spec_멀티유저.md ②-7.4).

- 상대경로는 사용자 `files/` 기준으로 해석한다(CWD 기준 아님).
- 절대경로는 같은 `files/` 안일 때만 허용한다. 자기 `auth/`·`db/` 도 거부한다(F06).
- UNC·장치 경로·ADS(`name:stream`)·드라이브 상대경로(`C:foo`)·예약 장치명·NUL·`~` 를 거부한다.
- `files/` 아래 경로 성분의 링크·junction·reparse point 는 `secure_files.ensure_within` 이 거부한다.
- 공용 관문 `mcp_common.paths.resolve_safe_path()` 도 함께 통과해야 한다
  (mode 1 에서는 그 관문 자체가 호출자 `files/` 로 범위를 좁힌다 — WP3).
- 응답에는 절대경로 대신 `files/` 기준 상대경로(`public_ref`)를 싣는다.

위반은 전부 `SecurityError(path_not_allowed)` 다. 메시지에 경로를 넣지 않는다.
"""

import os
from pathlib import Path
from typing import Any, Optional

from mcp_common.paths import PathNotAllowedError, resolve_safe_path
from mcp_common.secure_files import UnsafePathError, ensure_within, public_path
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.user_paths import UserPaths

_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

NOT_FOUND_MESSAGE = "파일을 찾을 수 없습니다."


def path_denied() -> SecurityError:
    return SecurityError(ErrorCode.PATH_NOT_ALLOWED)


def _parse(raw: str) -> Path:
    if not raw or not raw.strip() or "\x00" in raw:
        raise path_denied()
    if raw.startswith(("\\\\", "//")):  # UNC, \\?\ 및 \\.\ 장치 경로
        raise path_denied()
    if raw.lstrip().startswith("~"):  # 서비스 계정 홈으로 확장되지 않게
        raise path_denied()
    candidate = Path(raw)
    if candidate.drive and not candidate.is_absolute():  # 드라이브 상대 "C:foo"
        raise path_denied()
    parts = candidate.parts[1:] if candidate.anchor else candidate.parts
    for part in parts:
        if ":" in part:  # ADS "file.txt:stream"
            raise path_denied()
        if part.split(".")[0].strip().upper() in _RESERVED:
            raise path_denied()
    return candidate


def resolve_user_path(
    paths: UserPaths,
    value: Any,
    *,
    must_exist: bool = False,
    base: Optional[Path] = None,
) -> Path:
    """사용자 `files/` 안의 절대경로로 정규화한다.

    Args:
        paths: 서비스 소유자의 경로 (요청 principal 과 같은 사용자)
        value: 호출자가 준 경로
        must_exist: 대상이 있어야 하는지 (없으면 경로 없는 FileNotFoundError)
        base: 상대경로 기준 (기본 `files/`). 반드시 `files/` 안이어야 한다.
    """
    raw = os.fspath(value) if isinstance(value, os.PathLike) else ("" if value is None else str(value))
    parsed = _parse(raw)
    root = Path(paths.files)
    candidate = parsed if parsed.is_absolute() else Path(base or root) / parsed
    try:
        ensure_within(candidate, root)
    except UnsafePathError:
        raise path_denied() from None
    try:
        resolved = resolve_safe_path(candidate, must_exist=False)
    except PathNotAllowedError:
        raise path_denied() from None
    try:
        ensure_within(resolved, root)  # resolve() 결과(링크 해소 후)도 다시 확인
    except UnsafePathError:
        raise path_denied() from None
    if must_exist and not resolved.exists():
        raise FileNotFoundError(NOT_FOUND_MESSAGE)
    return resolved


def public_ref(paths: UserPaths, path: Any) -> str:
    """응답·메타데이터 키용 `files/` 기준 상대경로 (posix 표기)."""
    try:
        return public_path(paths, Path(path))
    except UnsafePathError:
        raise path_denied() from None


_PUBLIC_ERRORS = (
    (FileNotFoundError, NOT_FOUND_MESSAGE),
    (NotADirectoryError, "디렉터리가 아닙니다."),
    (IsADirectoryError, "파일이 아니라 디렉터리입니다."),
    (PermissionError, "접근할 수 없습니다."),
    (ImportError, "변환 라이브러리가 설치되어 있지 않습니다."),
    (TimeoutError, "시간 초과입니다."),
    (ValueError, "지원하지 않거나 잘못된 입력입니다."),
)


def public_error(exc: BaseException) -> str:
    """mode 1 응답용 오류 문구 — 예외 원문(경로·URL·외부 응답 본문)을 싣지 않는다."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return f"OneDrive 요청이 실패했습니다 (HTTP {status})."
    for cls, message in _PUBLIC_ERRORS:
        if isinstance(exc, cls):
            return f"{message} ({type(exc).__name__})"
    return f"처리 중 오류가 발생했습니다 ({type(exc).__name__})."


__all__ = [
    "NOT_FOUND_MESSAGE",
    "path_denied",
    "resolve_user_path",
    "public_ref",
    "public_error",
]
