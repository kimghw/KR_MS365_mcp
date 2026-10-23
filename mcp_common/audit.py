"""
감사 로그 (spec/spec_멀티유저.md ②-9, WP0 계약 / WP10 확장).

**허용 필드만** 기록한다. 이메일·토큰·state·경로·메일 제목·외부 오류 원문은 이 함수로
넘길 수 있는 인자 자체가 없다. 리소스 식별자가 꼭 필요하면 `resource_hmac()` 결과만 싣는다.

    timestamp, deployment_id, request_id, user_key, credential_id, auth_epoch,
    domain, tool, event, outcome, error_code, duration_ms   (+ resource: HMAC 값)

## 값 검증 (이름만이 아니라 값도 허용 목록)

인자 이름을 막아도 값에 이메일·토큰을 실으면 새어 나간다. 그래서 값마다 형식을 강제한다.

| 필드 | 허용 형식 | 어긋나면 |
|------|-----------|----------|
| user_key | 소문자 hex 64자 | 버린다 |
| credential_id | `[A-Za-z0-9_-]{1,64}` (kid) | 버린다 (bearer 키 원문은 `.` 이 있어 걸린다) |
| request_id | `[A-Za-z0-9_.:-]{1,128}` | `x-<HMAC 16자>` 로 치환 (추적은 되고 원문은 없음) |
| domain | `[a-z][a-z0-9_]{0,31}` | `"invalid"` |
| tool, error_code | `[A-Za-z][A-Za-z0-9_.-]{0,63}` | `"invalid"` |
| auth_epoch | int | 버린다 |
| duration_ms | 0 이상 숫자 → int | 버린다 |
| resource | HMAC 32 hex | 원문이면 그 자리에서 `resource_hmac()` 로 바꾼다 |

`event`·`outcome` 이 목록 밖이면 `ValueError` — 호출 코드의 버그이므로 테스트에서 드러나게 한다.

`principal`·`request_id` 를 생략하면 현재 요청 컨텍스트(`bind_identity`)에서 채운다.
principal 이 아직 없는 사건(bearer 인증 실패 등)은 `user_key`/`credential_id` 를 직접 준다.

## sink

- 항상 logger `ms365.audit` (stderr 핸들러를 타므로 stdio JSON-RPC 를 오염시키지 않는다)
- 멀티유저 모드면 `<MS365_DATA_ROOT>/system/audit/audit-YYYYMMDD.jsonl`(UTC 날짜)에도
  한 줄씩 추가 (사용자 파일 루트 밖, 관리자 전용). 8개 도메인 프로세스가 같은 파일에 쓰므로
  **OS 수준 append**(Windows `FILE_APPEND_DATA` 전용 handle, POSIX `O_APPEND`)로 한 번의
  write 에 한 줄을 쓴다 — 줄이 섞이거나 덮이지 않는다. 프로세스 안에서는 lock 으로 순서를 지킨다.

감사 실패가 요청을 실패시키지는 않는다(로그 경고만, 예외 미전파).
"""

import hashlib
import hmac
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("ms365.audit")

#: 기록 사건 이름. 새 사건은 여기에 더한다.
EVENTS = frozenset(
    {
        "auth.bearer",          # bearer 인증 성공/실패/scope 거부
        "auth.identity_mismatch",
        "path.denied",
        "oauth.start",
        "oauth.complete",
        "oauth.fail",
        "token.refresh",
        "key.issue",
        "key.rotate",
        "key.revoke",
        "user.register",
        "user.disable",
        "user.delete",
        "graph.disconnect",
        "migration",
        "admin.config",
        "tool.call",
    }
)

OUTCOMES = frozenset({"success", "failure", "denied"})

#: 감사 레코드에 실을 수 있는 필드 (②-9). 순서는 문서 순서.
FIELDS = (
    "timestamp",
    "deployment_id",
    "request_id",
    "user_key",
    "credential_id",
    "auth_epoch",
    "domain",
    "tool",
    "event",
    "outcome",
    "error_code",
    "duration_ms",
)
#: 허용 필드 밖이지만 HMAC 값만 싣는 예외 필드.
EXTRA_FIELDS = ("resource",)
_ALLOWED_KEYS = frozenset(FIELDS + EXTRA_FIELDS)

_USER_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_HMAC_RE = re.compile(r"^[0-9a-f]{32}$")
_DEPLOYMENT_RE = re.compile(r"^[0-9A-Za-z_-]{16,64}$")

_INVALID = "invalid"
_IS_WINDOWS = os.name == "nt"

_file_lock = threading.Lock()
_deployment_cache: Dict[str, str] = {}


# ----------------------------------------------------------------------
# 환경
# ----------------------------------------------------------------------
def _multi_user() -> bool:
    try:
        from mcp_common.security_policy import multi_user_enabled

        return multi_user_enabled()
    except Exception:
        return False


def _audit_file() -> Optional[str]:
    try:
        if not _multi_user():
            return None
        from mcp_common.user_paths import system_paths

        directory = system_paths().audit
        directory.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return str(directory / f"audit-{day}.jsonl")
    except Exception:
        return None


def _deployment_id() -> Optional[str]:
    """배포 ID. marker 를 **읽기만** 한다(감사가 marker 를 만들지 않는다). 경로별로 캐시."""
    try:
        if not _multi_user():
            return None
        from mcp_common.user_paths import system_paths

        marker_path = system_paths().deployment_json
        key = str(marker_path)
        cached = _deployment_cache.get(key)
        if cached:
            return cached
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        value = marker.get("deployment_id")
        if isinstance(value, str) and _DEPLOYMENT_RE.match(value):
            _deployment_cache[key] = value
            return value
    except Exception:
        return None
    return None


def _context():
    try:
        from mcp_common.principal import current_identity

        return current_identity()
    except Exception:
        return None


# ----------------------------------------------------------------------
# 값 정화
# ----------------------------------------------------------------------
def _clean_user_key(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and _USER_KEY_RE.match(value) else None


def _clean_credential(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and _CREDENTIAL_RE.match(value) else None


def _clean_request_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, str) and _REQUEST_ID_RE.match(value):
        return value
    return "x-" + resource_hmac(str(value))[:16]


def _clean_name(value: Any, pattern: "re.Pattern[str]") -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) and pattern.match(value) else _INVALID


def _clean_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _clean_duration(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value < 0 or value == float("inf"):  # NaN·음수·무한
        return None
    return int(round(value))


def _clean_resource(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str) and _HMAC_RE.match(value):
        return value
    return resource_hmac(str(value))  # 원문이 넘어와도 원문을 싣지 않는다


# ----------------------------------------------------------------------
# sink
# ----------------------------------------------------------------------
_win32 = None


def _win32_api():
    """kernel32 함수 3개를 argtypes 와 함께 한 번만 준비한다 (handle 이 64비트라 필수)."""
    global _win32
    if _win32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateFileW
        create.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        create.restype = wintypes.HANDLE
        write = kernel32.WriteFile
        write.argtypes = (
            wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
        )
        write.restype = wintypes.BOOL
        close = kernel32.CloseHandle
        close.argtypes = (wintypes.HANDLE,)
        close.restype = wintypes.BOOL
        _win32 = (create, write, close, wintypes.HANDLE(-1).value)
    return _win32


def _append_windows(path: str, data: bytes) -> None:
    """`FILE_APPEND_DATA` 만 가진 handle 로 쓴다 — OS 가 매 write 를 파일 끝에 원자적으로 붙인다."""
    import ctypes
    from ctypes import wintypes

    create, write, close, invalid = _win32_api()
    file_append_data, synchronize = 0x0004, 0x00100000
    share_all = 0x1 | 0x2 | 0x4
    open_always, attr_normal = 4, 0x80
    handle = create(path, file_append_data | synchronize, share_all, None, open_always, attr_normal, None)
    if handle is None or handle == invalid:
        raise OSError(ctypes.get_last_error(), "CreateFileW failed")
    try:
        written = wintypes.DWORD(0)
        if not write(handle, data, len(data), ctypes.byref(written), None):
            raise OSError(ctypes.get_last_error(), "WriteFile failed")
        if written.value != len(data):
            raise OSError("short audit write")
    finally:
        close(handle)


def _append_posix(path: str, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if os.write(fd, data) != len(data):
            raise OSError("short audit write")
    finally:
        os.close(fd)


def _append_line(path: str, line: str) -> None:
    data = (line + "\n").encode("utf-8")
    with _file_lock:
        if _IS_WINDOWS:
            try:
                _append_windows(path, data)
                return
            except (ImportError, AttributeError):
                pass  # ctypes 를 쓸 수 없는 환경 — 아래 일반 append 로
            with open(path, "ab") as fh:
                fh.write(data)
        else:
            _append_posix(path, data)


# ----------------------------------------------------------------------
# 공개 API
# ----------------------------------------------------------------------
def audit(
    event: str,
    *,
    outcome: str,
    principal: Any = None,
    request_id: Optional[str] = None,
    error_code: Optional[str] = None,
    domain: Optional[str] = None,
    tool: Optional[str] = None,
    duration_ms: Optional[int] = None,
    user_key: Optional[str] = None,
    credential_id: Optional[str] = None,
    resource: Optional[str] = None,
) -> Dict[str, Any]:
    """감사 레코드 1건. 반환값은 기록한 dict (테스트용).

    `principal` 을 주면 user_key·credential_id·auth_epoch 를 거기서 꺼낸다. principal 이
    아직 없는 사건(예: bearer 인증 실패)은 `user_key`/`credential_id` 를 직접 줄 수 있다.
    셋 다 없으면 현재 요청 컨텍스트의 principal 을, `request_id` 가 없으면 컨텍스트의 값을 쓴다.
    `resource` 는 `resource_hmac()` 를 거친 값이어야 한다(원문이면 여기서 HMAC 한다).
    """
    if event not in EVENTS:
        raise ValueError(f"unknown audit event: {event}")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown audit outcome: {outcome}")

    identity = None
    if request_id is None or (principal is None and user_key is None and credential_id is None):
        identity = _context()
    if principal is None and user_key is None and credential_id is None and identity is not None:
        principal = identity.principal
    if request_id is None and identity is not None:
        request_id = identity.request_id

    auth_epoch = None
    if principal is not None:
        user_key = getattr(principal, "user_key", user_key)
        credential_id = getattr(principal, "credential_id", credential_id) or credential_id
        auth_epoch = getattr(principal, "auth_epoch", None)

    record: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "deployment_id": _deployment_id(),
        "request_id": _clean_request_id(request_id),
        "user_key": _clean_user_key(user_key),
        "credential_id": _clean_credential(credential_id),
        "auth_epoch": _clean_int(auth_epoch),
        "domain": _clean_name(domain, _DOMAIN_RE),
        "tool": _clean_name(tool, _NAME_RE),
        "event": event,
        "outcome": outcome,
        "error_code": _clean_name(error_code, _NAME_RE),
        "duration_ms": _clean_duration(duration_ms),
        "resource": _clean_resource(resource),
    }
    # 허용 목록 밖 키는 어떤 경로로도 싣지 않는다. 필드를 늘릴 때는 FIELDS 와 사양서 ②-9 를 함께 고친다.
    record = {k: v for k, v in record.items() if v is not None and k in _ALLOWED_KEYS}

    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    try:
        logger.info(line)
    except Exception:
        pass
    path = _audit_file()
    if path:
        try:
            _append_line(path, line)
        except Exception as exc:
            try:
                logger.warning("audit sink write failed: %s", type(exc).__name__)
            except Exception:
                pass
    return record


def resource_hmac(value: str) -> str:
    """리소스 식별자를 감사 키로 HMAC 한 값 (원문 비기록). 키는 `MS365_AUDIT_HMAC_KEY`."""
    key = os.environ.get("MS365_AUDIT_HMAC_KEY", "")
    if not key:
        key = _deployment_id() or "ms365-audit"
    return hmac.new(key.encode("utf-8"), str(value).encode("utf-8"), hashlib.sha256).hexdigest()[:32]


__all__ = ["EVENTS", "OUTCOMES", "FIELDS", "audit", "resource_hmac"]
