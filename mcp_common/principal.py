"""
요청 범위 호출자(principal) — 누가 이 요청을 보냈는가 (spec/spec_멀티유저.md ②-5, WP0).

멀티유저 모드에서 사용자 데이터·토큰 선택의 **유일한 근거**는 요청에 묶인 `Principal`
이다. 이메일·도구 인자·MCP 세션 ID·헤더는 근거가 아니다.

- HTTP 인증 관문(WP1)이 bearer 를 검증해 `RequestIdentity` 를 만들고,
  도구 실행마다 `bind_identity()` 로 묶는다.
- 서비스·저장소 코드는 `require_principal()` 로 꺼내 쓴다. 없으면 `missing_principal`
  로 실패한다 — 다른 계정으로 대체하지 않는다.

## user_key

    canonical_subject = "entra:v1:" + lower(UUID(tid)) + ":" + lower(UUID(oid))
    user_key = sha256(utf-8(canonical_subject)).hexdigest()   # 소문자 hex 64자

이메일은 바뀔 수 있으므로 user_key 에 쓰지 않는다. 같은 이메일이라도 (tid, oid) 가
다르면 다른 사용자다.
"""

import contextvars
import hashlib
import re
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import FrozenSet, Iterator, Literal, Optional

from mcp_common.security_contracts import ErrorCode, SecurityError

_USER_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class _Missing:
    """`assert_user_email()` 에서 '인자 자체가 없음'을 None·빈 문자열과 구분하는 표식."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


@dataclass(frozen=True)
class Principal:
    """검증된 호출자. 토큰·키·secret 을 담지 않는다."""

    user_key: str
    tenant_id: str
    object_id: str
    graph_email: Optional[str] = None
    credential_id: str = ""          # bearer key 의 kid (감사·폐기 확인용)
    scopes: FrozenSet[str] = field(default_factory=frozenset)
    auth_epoch: int = 0

    def __post_init__(self):
        if not is_valid_user_key(self.user_key):
            raise ValueError("user_key 형식이 올바르지 않습니다 (소문자 hex 64자)")
        if not isinstance(self.scopes, frozenset):
            object.__setattr__(self, "scopes", frozenset(self.scopes))

    def has_scope(self, domain: str) -> bool:
        return scope_for_domain(domain) in self.scopes


@dataclass(frozen=True)
class RequestIdentity:
    principal: Principal
    request_id: str
    transport: Literal["http"] = "http"
    authenticated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    credential_expires_at: Optional[datetime] = None


# ----------------------------------------------------------------------
# user_key / scope
# ----------------------------------------------------------------------
def canonical_subject(tenant_id: str, object_id: str) -> str:
    """UUID 형식이 아니면 ValueError."""
    tid = str(uuid.UUID(str(tenant_id))).lower()
    oid = str(uuid.UUID(str(object_id))).lower()
    return f"entra:v1:{tid}:{oid}"


def compute_user_key(tenant_id: str, object_id: str) -> str:
    return hashlib.sha256(canonical_subject(tenant_id, object_id).encode("utf-8")).hexdigest()


def is_valid_user_key(value: object) -> bool:
    return isinstance(value, str) and bool(_USER_KEY_RE.match(value))


#: bearer key scope 이름. 도메인 = handlers 의 SERVER_NAME (param_spec server.name).
DOMAINS = ("outlook", "calendar", "teams", "onedrive", "onenote", "todo", "file_handler", "time")


def scope_for_domain(domain: str) -> str:
    return f"mcp:{domain}"


# ----------------------------------------------------------------------
# context
# ----------------------------------------------------------------------
_identity_var: contextvars.ContextVar[Optional[RequestIdentity]] = contextvars.ContextVar(
    "ms365_request_identity", default=None
)


def current_identity() -> Optional[RequestIdentity]:
    return _identity_var.get()


def current_principal() -> Optional[Principal]:
    identity = _identity_var.get()
    return identity.principal if identity is not None else None


def require_principal() -> Principal:
    principal = current_principal()
    if principal is None:
        raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
    return principal


@contextmanager
def bind_identity(identity: RequestIdentity) -> Iterator[RequestIdentity]:
    """요청 범위로 identity 를 묶는다. 예외·취소에도 `finally` 에서 반드시 되돌린다."""
    if not isinstance(identity, RequestIdentity):
        raise TypeError("bind_identity() 에는 RequestIdentity 가 필요합니다")
    token = _identity_var.set(identity)
    try:
        yield identity
    finally:
        _identity_var.reset(token)


# ----------------------------------------------------------------------
# ownership / user_email
# ----------------------------------------------------------------------
def assert_owner(owner_key: str) -> Principal:
    """로컬 리소스의 소유자가 현재 principal 인지. 아니면 `not_found` (존재 여부 비노출)."""
    principal = require_principal()
    if owner_key != principal.user_key:
        raise SecurityError(ErrorCode.NOT_FOUND)
    return principal


def normalize_email_for_compare(value: str) -> str:
    """NFKC → strip → casefold. **비교 전용** — 계정 병합·소유권 판단에 쓰지 않는다."""
    return unicodedata.normalize("NFKC", value).strip().casefold()


def assert_user_email(explicit: object = MISSING) -> str:
    """도구 인자 `user_email` 정책 (②-5.3).

    1. 인자가 **없으면**(MISSING) principal 의 연결 계정 이메일
    2. 있으면 비어 있지 않은 문자열이어야 함 — None·""·공백·비문자열은 `invalid_user_email`
    3. 정규화 비교가 principal 의 연결 계정과 같아야 함 — 아니면 `identity_mismatch`
       (다른 계정의 존재 여부는 조회하지 않는다)
    4. 연결 계정 이메일이 없으면 `graph_not_connected`

    반환값은 principal 의 `graph_email` (호출자가 준 표기가 아니라 저장된 표기).
    저장소·토큰 선택은 이 값이 아니라 `user_key` 로 한다.
    """
    principal = require_principal()
    if explicit is not MISSING:
        if not isinstance(explicit, str) or not explicit.strip():
            raise SecurityError(ErrorCode.INVALID_USER_EMAIL)
    if not principal.graph_email:
        raise SecurityError(ErrorCode.GRAPH_NOT_CONNECTED)
    if explicit is not MISSING:
        if normalize_email_for_compare(explicit) != normalize_email_for_compare(principal.graph_email):
            raise SecurityError(ErrorCode.IDENTITY_MISMATCH)
    return principal.graph_email


__all__ = [
    "MISSING",
    "Principal",
    "RequestIdentity",
    "DOMAINS",
    "canonical_subject",
    "compute_user_key",
    "is_valid_user_key",
    "scope_for_domain",
    "current_identity",
    "current_principal",
    "require_principal",
    "bind_identity",
    "assert_owner",
    "normalize_email_for_compare",
    "assert_user_email",
]
