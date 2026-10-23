"""
안전한 파일 열기·저장 (spec/spec_멀티유저.md ②-7.4, WP0 계약 / WP3 강화).

`resolve_safe_path()` 는 검증용이고, **실제 파일 생성·저장·읽기는 이 모듈로 모은다.**
도메인 코드(Outlook 첨부, FileHandler 다운로드·변환, OneDrive 저장)는 원격 파일명을
경로에 직접 결합하지 않고 `safe_join()` / `write_new_file()` / `open_for_read()` 를 쓴다.

공개 함수 시그니처는 WP0 계약이다 — WP3 은 내부 구현만 강화했고, 기존 인자는 그대로 두고
**선택 키워드 `root=` 만 더했다**(주면 그 루트 기준으로 경계를 검사한다).

| 함수 | 용도 |
|------|------|
| `safe_filename(name)` | 원격 파일명을 **단일 이름**으로 정화 (구분자·`..`·ADS·예약 장치명·제어문자·bidi 제거, NFC, 바이트 길이 상한) |
| `is_reserved_name(name)` | Windows 예약 장치명 여부 (`CON`, `nul.txt`, `COM¹` …) |
| `safe_join(base, name)` | `base / safe_filename(name)` + 최종 경계 확인 |
| `ensure_within(path, root)` | 경계 확인 + root 아래 모든 성분의 링크·reparse point·ADS·예약명 거부 + realpath 재확인 |
| `create_exclusive(directory, filename, *, root=None)` | 배타 생성(O_EXCL). 같은 이름이 있으면 ` (n)` 접미사. 연 뒤 handle 검증 |
| `write_new_file(directory, filename, data, *, root=None)` | 배타 생성 후 쓰기 → 최종 경로 |
| `atomic_write_bytes(path, data, *, root=None)` | 같은 디렉터리 임시파일에 쓴 뒤 `os.replace` (링크 대상이면 거부) |
| `open_for_read(path, root)` | 검증 후 읽기 전용 binary 파일 객체 (일반 파일·단일 링크만) |
| `request_temp_dir(paths, request_id)` | 요청별 `files/tmp/<request_id>/` 생성·정리 (자기 것만, 링크면 지우지 않음) |
| `public_path(paths, path)` | 응답용 사용자 파일 루트 기준 상대경로 (절대경로 비노출) |

## TOCTOU 방어

경로 검사 후 다른 경로를 열게 되는 경합(검사와 열기 사이에 디렉터리를 링크로 바꿔치기)을
막기 위해 **연 handle 자체를 다시 검증**한다.

- POSIX: root 를 디렉터리 fd 로 열고 성분마다 `openat(..., O_NOFOLLOW)` 로 내려간다 —
  중간 성분이 링크로 바뀌어도 따라가지 않는다.
- Windows: `GetFinalPathNameByHandleW` 로 handle 의 실제 경로를 얻어 root 의 realpath
  안인지 확인한다(junction·symlink·mount point 를 거쳐 열렸으면 여기서 걸린다).
- 공통: `fstat(fd)` 와 `lstat(path)` 의 (st_dev, st_ino) 가 같아야 한다.

## 한계 (정직하게)

- reparse point 는 **종류를 가리지 않고** 거부한다. 데이터 루트를 OneDrive 동기화 폴더·
  Windows 중복 제거(dedup) 볼륨에 두면 정상 파일도 거부된다 — 그런 위치에 두지 않는다.
- `request_temp_dir()` 정리는 stdlib `shutil.rmtree` 를 쓴다. 3.12 의 Windows 구현은
  junction·symlink 를 따라가지 않지만, OS 수준 권한을 가진 공격자가 정리 도중 하위
  디렉터리를 바꿔치기하는 경합까지 막지는 못한다(사용자에게 링크 생성 API 는 없다).
- 이 모듈의 오류 메시지에는 경로를 넣지 않는다. 호출자도 응답에 절대경로를 싣지 않는다.
"""

import errno
import logging
import os
import re
import shutil
import stat
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, Optional, Tuple

from mcp_common.user_paths import UserPaths

logger = logging.getLogger(__name__)

_IS_WINDOWS = os.name == "nt"

#: Windows 예약 장치명. 확장자가 붙어도("CON.txt"), 확장자 앞에 공백이 있어도("NUL .txt")
#: 예약이다. 위첨자 숫자(COM¹)도 Windows 가 장치로 해석한다.
_RESERVED = frozenset(
    {
        "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
        *(f"COM{i}" for i in "123456789¹²³"),
        *(f"LPT{i}" for i in "123456789¹²³"),
    }
)
#: 파일 이름에 둘 수 없는 문자 — 제어문자, Windows 금지 문자, 경로 구분자, ADS 콜론.
_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
#: 표시 순서 위장(RLO 등) — "evil\u202Efdp.exe" 가 "evilexe.pdf" 로 보이는 것을 막는다.
_BIDI_CHARS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
#: ANSI 코드페이지 best-fit 변환에서 구분자·콜론으로 바뀌는 유사 문자 (WorstFit).
#: cp932 의 ¥, cp949 의 ₩ 는 0x5C(역슬래시)로 변환된다.
_LOOKALIKE_CHARS = re.compile("[\uff0f\uff3c\u2215\u2216\u29f5\u29f8\u29f9\uff1a\u2236\ufe55\u00a5\u20a9]")
#: 이름 하나의 UTF-8 바이트 상한. NTFS(255 UTF-16 단위)·ext4(255 바이트) 모두 안쪽이고,
#: ` (999)` 접미사·`.<name>.<8hex>.tmp` 임시 이름을 붙일 여유를 남긴다.
_MAX_NAME_BYTES = 200
_MAX_EXT_BYTES = 20
#: 하위 호환 — 예전 코드가 문자 수 상한으로 참조했다.
_MAX_NAME = _MAX_NAME_BYTES

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOINHERIT = getattr(os, "O_NOINHERIT", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
#: POSIX 에서 openat 으로 성분별 O_NOFOLLOW 탐색이 가능한가.
_USE_DIR_FD = (not _IS_WINDOWS) and bool(_O_NOFOLLOW and _O_DIRECTORY) and os.open in os.supports_dir_fd


class UnsafePathError(PermissionError):
    """사용자 파일 루트 탈출·링크·특수 경로. 메시지에 경로를 넣지 않는다.

    `reason` 은 공개해도 되는 사유 코드다 (`outside_root`, `link`, `ads`, `reserved_name` …).
    """

    def __init__(self, message: str = "unsafe path", reason: str = "unsafe_path"):
        super().__init__(message)
        self.reason = reason

    def to_security_error(self):
        """도구 응답용 `SecurityError(PATH_NOT_ALLOWED)` 로 바꾼다 (원문·경로 비노출)."""
        from mcp_common.security_contracts import ErrorCode, SecurityError

        return SecurityError(ErrorCode.PATH_NOT_ALLOWED)


# ----------------------------------------------------------------------
# 이름 검사·정화
# ----------------------------------------------------------------------
def is_reserved_name(name: str) -> bool:
    """Windows 예약 장치명인가 (`CON`, `con.txt`, `NUL .log`, `COM¹` …). 대소문자 무시."""
    stem = str(name).partition(".")[0].rstrip(" ").upper()
    return stem in _RESERVED


def _component_problem(part: str) -> Optional[str]:
    """경로 성분 하나의 문제 사유 코드. 문제 없으면 None.

    `mcp_common.paths` 도 같은 판정을 쓴다(검사 기준을 두 벌 두지 않는다).
    `.` 은 허용하고 `..` 은 `traversal` 로 본다.
    """
    if part in ("", "."):
        return None
    if part == "..":
        return "traversal"
    if "\x00" in part:
        return "nul"
    if re.search(r"[\x01-\x1f\x7f]", part):
        return "control_char"
    if ":" in part:
        return "ads"
    if re.search(r'[<>"|?*]', part):
        return "invalid_char"
    if part != part.rstrip(". "):
        return "trailing_dot_space"
    if is_reserved_name(part):
        return "reserved_name"
    return None


def _truncate_utf8(text: str, limit: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def _cap_length(name: str) -> str:
    """UTF-8 바이트 상한. 짧은 확장자는 살린다. 멀티바이트 문자를 반으로 자르지 않는다."""
    if len(name.encode("utf-8")) <= _MAX_NAME_BYTES:
        return name
    root, ext = os.path.splitext(name)
    if not ext or len(ext.encode("utf-8")) > _MAX_EXT_BYTES:
        root, ext = name, ""
    root = _truncate_utf8(root, _MAX_NAME_BYTES - len(ext.encode("utf-8")))
    return root.rstrip(". ") + ext


def _clean_name(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw)
    # 경로 구분자 뒤의 마지막 성분만 남긴다 ("../../x" → "x", "C:\\a\\b" → "b")
    text = re.split(r"[\\/]", text)[-1]
    text = _BIDI_CHARS.sub("", text)
    text = _LOOKALIKE_CHARS.sub("_", text)
    text = _BAD_CHARS.sub("_", text)
    # Windows 는 끝의 점·공백을 조용히 버린다 → 다른 파일을 가리키게 되므로 미리 제거
    text = text.strip().rstrip(". ")
    if text in ("", ".", ".."):
        return ""
    if is_reserved_name(text):
        text = "_" + text
    return _cap_length(text)


def safe_filename(name: Optional[str], *, default: str = "file") -> str:
    """원격에서 온 이름을 경로가 아닌 **파일 이름 하나**로 만든다.

    결과는 항상 비어 있지 않고, 구분자·`..`·콜론(ADS)·제어문자·예약 장치명이 없으며,
    UTF-8 200바이트 이하다. `default` 도 같은 규칙으로 정화한다.
    """
    cleaned = _clean_name("" if name is None else str(name))
    if not cleaned:
        cleaned = _clean_name(str(default)) or "file"
    return cleaned


# ----------------------------------------------------------------------
# 링크·경계 검사
# ----------------------------------------------------------------------
def _stat_is_link(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _is_reparse_or_link(path: Path) -> bool:
    """symlink·junction·mount point 등 reparse point 인가. 확인할 수 없으면 True (fail closed)."""
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except (OSError, ValueError):
        return True
    return _stat_is_link(st)


def _realpath(path: Path) -> Path:
    try:
        return Path(os.path.realpath(path))
    except (OSError, ValueError):
        raise UnsafePathError("cannot resolve path", "invalid_path") from None


def _abspath(path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, ValueError, TypeError):
        raise UnsafePathError("invalid path", "invalid_path") from None


def _is_within(candidate: Path, root: Path) -> bool:
    # PureWindowsPath 비교는 대소문자를 무시한다. POSIX 는 구분한다.
    try:
        return candidate == root or candidate.is_relative_to(root)
    except (TypeError, ValueError):
        return False


def ensure_within(path: Path, root: Path) -> Path:
    """`path` 가 `root` 안인지 확인하고 정규화된 절대경로를 돌려준다.

    1. 정규화(abspath) 기준으로 root 안이어야 한다 (`..` 탈출 차단)
    2. root 아래 각 성분: ADS 콜론·예약 장치명·제어문자·끝 점/공백 거부, 링크·reparse point 거부
    3. 링크 해소(realpath) 결과도 root 의 realpath 안이어야 한다

    root 자체와 그 상위의 링크는 검사하지 않는다(운영자가 정한 위치). 돌려준 경로를 써야 한다
    — 검사에 쓴 원래 문자열을 다시 열지 않는다.
    """
    root_abs = _abspath(root)
    target = _abspath(path)
    if not _is_within(target, root_abs):
        raise UnsafePathError("path outside root", "outside_root")
    rel = target.relative_to(root_abs)
    current = root_abs
    for part in rel.parts:
        problem = _component_problem(part)
        if problem:
            raise UnsafePathError(f"unsafe path component ({problem})", problem)
        current = current / part
        if _is_reparse_or_link(current):
            raise UnsafePathError("link or reparse point in path", "link")
    if not _is_within(_realpath(target), _realpath(root_abs)):
        raise UnsafePathError("path outside root", "outside_root")
    return target


def safe_join(base: Path, name: Optional[str], *, default: str = "file") -> Path:
    return ensure_within(Path(base) / safe_filename(name, default=default), Path(base))


# ----------------------------------------------------------------------
# handle 검증 (TOCTOU)
# ----------------------------------------------------------------------
_get_final_path = None


def _final_path_from_fd(fd: int) -> Optional[Path]:
    """Windows: 열린 handle 의 실제 경로 (`\\\\?\\` 접두 제거). 얻지 못하면 None."""
    global _get_final_path
    if not _IS_WINDOWS:
        return None
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        if _get_final_path is None:
            fn = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
            fn.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
            fn.restype = wintypes.DWORD
            _get_final_path = fn
        handle = msvcrt.get_osfhandle(fd)
        size = 512
        for _ in range(3):
            buf = ctypes.create_unicode_buffer(size)
            n = _get_final_path(handle, buf, size, 0)  # FILE_NAME_NORMALIZED | VOLUME_NAME_DOS
            if n == 0:
                return None
            if n < size:
                value = buf.value
                if value.startswith("\\\\?\\UNC\\"):
                    value = "\\\\" + value[8:]
                elif value.startswith("\\\\?\\"):
                    value = value[4:]
                return Path(value)
            size = n + 1
    except Exception:
        return None
    return None


def _verify_fd(fd: int, target: Path, root_real: Path) -> None:
    """연 handle 이 검사한 경로의 그 객체이고 root 안에 있는지. 아니면 UnsafePathError."""
    fst = os.fstat(fd)
    try:
        lst = os.lstat(target)
    except OSError:
        raise UnsafePathError("path changed during open", "changed_during_open") from None
    if _stat_is_link(lst):
        raise UnsafePathError("link or reparse point in path", "link")
    if fst.st_ino and lst.st_ino and (fst.st_dev, fst.st_ino) != (lst.st_dev, lst.st_ino):
        raise UnsafePathError("path changed during open", "changed_during_open")
    if _IS_WINDOWS:
        final = _final_path_from_fd(fd)
        if final is None:
            raise UnsafePathError("cannot verify opened file", "unverifiable")
        if not _is_within(final, root_real):
            raise UnsafePathError("path outside root", "outside_root")


def _open_beneath(root_abs: Path, parts: Tuple[str, ...], flags: int, mode: int) -> int:
    """POSIX: root fd 에서 성분마다 O_NOFOLLOW 로 내려가 연다 (중간 링크를 따라가지 않음)."""
    dfd = os.open(root_abs, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC)
    try:
        for part in parts[:-1]:
            nfd = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=dfd)
            os.close(dfd)
            dfd = nfd
        return os.open(parts[-1], flags | _O_NOFOLLOW | _O_CLOEXEC, mode, dir_fd=dfd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
            raise UnsafePathError("link or reparse point in path", "link") from None
        raise
    finally:
        os.close(dfd)


def _open_within(path: Path, root: Path, flags: int, mode: int = 0o600) -> int:
    """경계 검사 → 열기 → handle 재검증. 반환값은 OS fd (호출자가 닫는다)."""
    root_abs = _abspath(root)
    target = ensure_within(path, root_abs)
    parts = target.relative_to(root_abs).parts
    if not parts:
        raise UnsafePathError("root itself is not a file", "not_regular_file")
    if _USE_DIR_FD:
        fd = _open_beneath(root_abs, parts, flags, mode)
    else:
        fd = os.open(target, flags | _O_BINARY | _O_NOINHERIT | _O_NOFOLLOW, mode)
    try:
        _verify_fd(fd, target, _realpath(root_abs))
    except BaseException:
        os.close(fd)
        # 배타 생성한 빈 파일이 남을 수 있지만, 바뀐 경로를 따라 지우지 않는다(다른 파일일 수 있음).
        raise
    return fd


def _strict_mode() -> bool:
    """멀티유저면 사용자 디렉터리 자체가 링크인 것도 거부한다 (mode 0 동작은 그대로)."""
    try:
        from mcp_common.security_policy import multi_user_enabled

        return multi_user_enabled()
    except Exception:
        return True  # 정책을 읽을 수 없으면 엄격하게


# ----------------------------------------------------------------------
# 생성·저장·읽기
# ----------------------------------------------------------------------
def _candidates(filename: str) -> Iterator[str]:
    yield filename
    root, ext = os.path.splitext(filename)
    for i in range(1, 1000):
        yield f"{root} ({i}){ext}"
    yield f"{root}-{uuid.uuid4().hex[:8]}{ext}"


def _prepare_directory(directory: Path, root: Optional[Path]) -> Path:
    base = Path(root) if root is not None else directory
    if root is not None:
        ensure_within(directory, base)  # 탈출 경로에 mkdir 하지 않도록 생성 전에 한 번
    directory.mkdir(parents=True, exist_ok=True)
    if root is None and _strict_mode() and _is_reparse_or_link(directory):
        raise UnsafePathError("link or reparse point in path", "link")
    ensure_within(directory, base)
    return base


def create_exclusive(
    directory: Path, filename: Optional[str], *, root: Optional[Path] = None
) -> Tuple[Path, BinaryIO]:
    """배타 생성. 존재 검사 후 열기(TOCTOU) 대신 O_EXCL 로 한 번에 만들고, 연 handle 을 검증한다.

    `root` 를 주면 `directory` 가 그 안이어야 한다(멀티유저에서는 `paths.files` 를 준다).
    """
    directory = _abspath(directory)
    base = _prepare_directory(directory, root)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY
    for candidate in _candidates(safe_filename(filename)):
        path = directory / candidate
        try:
            fd = _open_within(path, base, flags, 0o600)
        except FileExistsError:
            continue
        return path, os.fdopen(fd, "wb")
    raise FileExistsError("could not allocate a unique file name")


def write_new_file(
    directory: Path, filename: Optional[str], data: bytes, *, root: Optional[Path] = None
) -> Path:
    path, fh = create_exclusive(directory, filename, root=root)
    with fh:
        fh.write(data)
    return path


def atomic_write_bytes(path: Path, data: bytes, *, root: Optional[Path] = None) -> None:
    """같은 디렉터리의 임시파일에 쓴 뒤 `os.replace`. 대상이 링크·reparse point 면 거부한다."""
    path = _abspath(path)
    base = Path(root) if root is not None else path.parent
    ensure_within(path, base)
    if _is_reparse_or_link(path):
        raise UnsafePathError("refusing to replace a link", "link")
    tmp, fh = create_exclusive(path.parent, f".{path.name}.{uuid.uuid4().hex[:8]}.tmp", root=root)
    try:
        with fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        ensure_within(path, base)  # 쓰는 동안 경로가 바뀌지 않았는지 교체 직전에 다시
        if _is_reparse_or_link(path):
            raise UnsafePathError("refusing to replace a link", "link")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def open_for_read(path: Path, root: Path) -> BinaryIO:
    """`root` 안의 **일반 파일**을 읽기 전용 binary 로 연다.

    `ensure_within()` 검사 + 연 handle 재검증(TOCTOU) + 일반 파일·하드링크 1개 확인.
    디렉터리면 `IsADirectoryError`, 없으면 `FileNotFoundError`, 그 밖의 경계 위반은
    `UnsafePathError`. 어느 메시지에도 경로를 넣지 않는다.
    """
    target = ensure_within(path, root)
    if os.path.isdir(target):
        raise IsADirectoryError("is a directory")
    try:
        fd = _open_within(target, root, os.O_RDONLY | _O_BINARY | _O_NONBLOCK)
    except FileNotFoundError:
        raise FileNotFoundError("file not found") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise UnsafePathError("not a regular file", "not_regular_file")
        if st.st_nlink > 1:
            # 하드링크로 auth.db 등 보호 파일을 파일 루트 안에 비춰 두는 우회를 막는다
            raise UnsafePathError("hard-linked file", "hardlink")
        if _O_NONBLOCK:
            os.set_blocking(fd, True)
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


# ----------------------------------------------------------------------
# 요청별 임시 디렉터리
# ----------------------------------------------------------------------
def _identity(path: Path) -> Optional[Tuple[int, int]]:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino) if st.st_ino else None


def _rmtree_onexc(func, path, exc) -> None:
    # 읽기 전용 파일(Windows)은 권한을 풀고 한 번 더 시도한다. 그 밖은 기록만 한다.
    if isinstance(exc, PermissionError):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
            return
        except OSError:
            pass
    logger.warning("request temp cleanup: %s failed (%s)", getattr(func, "__name__", "op"), type(exc).__name__)


def _remove_own_dir(directory: Path, ident: Optional[Tuple[int, int]]) -> None:
    """만든 그 디렉터리일 때만 지운다. 링크로 바뀌었거나 다른 객체면 손대지 않는다."""
    try:
        st = os.lstat(directory)
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("request temp cleanup skipped (%s)", type(exc).__name__)
        return
    if _stat_is_link(st) or not stat.S_ISDIR(st.st_mode):
        logger.warning("request temp dir was replaced by a link or file; not removed")
        return
    if ident is not None and st.st_ino and (st.st_dev, st.st_ino) != ident:
        logger.warning("request temp dir was replaced; not removed")
        return
    try:
        shutil.rmtree(directory, onexc=_rmtree_onexc)
    except OSError as exc:
        logger.warning("request temp cleanup failed (%s)", type(exc).__name__)


@contextmanager
def request_temp_dir(paths: UserPaths, request_id: Optional[str] = None) -> Iterator[Path]:
    """요청별 임시 디렉터리 `files/tmp/<request_id>/`. 끝나면 **이 디렉터리만** 지운다.

    - 같은 request_id 디렉터리가 이미 있으면 `FileExistsError` (남의 것을 넘겨받지 않음)
    - `files/`·`tmp/` 가 링크면 만들지 않는다
    - 정리 시점에 디렉터리가 링크·다른 객체로 바뀌었으면 지우지 않고 경고만 남긴다
    """
    rid = request_id or uuid.uuid4().hex
    directory = _abspath(paths.request_tmp(rid))
    for existing in (paths.root, paths.files, paths.tmp):
        if _is_reparse_or_link(existing):
            raise UnsafePathError("link or reparse point in path", "link")
    paths.tmp.mkdir(parents=True, exist_ok=True)
    if _is_reparse_or_link(paths.tmp):
        raise UnsafePathError("link or reparse point in path", "link")
    directory.mkdir(parents=False, exist_ok=False)
    try:
        ensure_within(directory, paths.files)
        ident = _identity(directory)
    except BaseException:
        try:
            os.rmdir(directory)  # 빈 디렉터리(또는 그 자리의 링크 자체)만 지운다
        except OSError:
            pass
        raise
    try:
        yield directory
    finally:
        _remove_own_dir(directory, ident)


def public_path(paths: UserPaths, path: Path) -> str:
    """응답용: 사용자 파일 루트 기준 상대경로(posix). 루트 밖이면 오류."""
    target = _abspath(path)
    try:
        return target.relative_to(_abspath(paths.files)).as_posix()
    except ValueError:
        raise UnsafePathError("path outside user files root", "outside_root") from None


__all__ = [
    "UnsafePathError",
    "safe_filename",
    "is_reserved_name",
    "ensure_within",
    "safe_join",
    "create_exclusive",
    "write_new_file",
    "atomic_write_bytes",
    "open_for_read",
    "request_temp_dir",
    "public_path",
]
