"""
identity registry — 호출자 bearer 인증·계정 상태 확인의 관문 (spec/spec_멀티유저.md ②-4.3~4.4, ②-6.5, ②-12.6).

WP1(HTTP 인증 관문)·auth gateway 가 쓰는 공개 계약:

    async def authenticate_bearer(authorization: str | None, *, domain: str | None) -> Principal
    async def assert_active(principal: Principal) -> None

## bearer key

    m365v1.<kid>.<secret>      kid = 128비트 소문자 hex(32자), secret = 256비트 base64url(43자, padding 없음)

- registry 에는 `kid → user_key` 위치만 있다. digest·scope·만료·폐기는 사용자 auth.db.
- digest = SHA-256(길이 구분 결합("m365v1-key", deployment_id, kid, secret)), 상수 시간 비교.
  고엔트로피 난수 키이므로 비밀번호 해시(느린 KDF)를 쓰지 않는다.
- 원문 키는 발급 시 1회 표시 외에는 저장·로그·URL·오류 응답에 남기지 않는다.

## 오류

| 상황 | 코드 |
|------|------|
| 헤더 없음·형식 오류·미지 kid·digest 불일치·만료·폐기·사용자 저장소 없음 | `unauthenticated` (401) |
| 계정 disabled/deleting | `account_inactive` (403) — digest 가 맞은 뒤에만 알린다 |
| 유효 키지만 도메인 scope 없음 | `forbidden_scope` (403) |

`domain=None` 은 auth gateway(연결 API) 용 — 그 사용자의 어떤 scope 키든 허용한다.

관리 함수(사용자 등록·키 발급/폐기·상태·삭제)는 위성 모듈 `registry_admin` 에 있고 여기서
재수출한다. 모든 성공·실패는 `mcp_common.audit` 허용 필드로만 기록한다(키·이메일·state 없음).
"""

import asyncio
import hmac
import logging
import re
from typing import Optional, Tuple

from mcp_common.audit import audit
from mcp_common.principal import Principal, scope_for_domain
from mcp_common.security_contracts import ErrorCode, SecurityError

from . import _registry_db as reg
from ._mu_common import deployment_id_for, parse_iso, utcnow
from ._registry_db import key_digest
from .user_auth_store import StoreMissing, StoreOwnerMismatch

logger = logging.getLogger(__name__)

KEY_PREFIX = "m365v1"
_KEY_RE = re.compile(r"^m365v1\.([0-9a-f]{32})\.([A-Za-z0-9_-]{43})$")
_MAX_HEADER_LEN = 512


def parse_bearer(authorization: Optional[str]) -> Tuple[str, str]:
    """`Bearer m365v1.<kid>.<secret>` → (kid, secret). 어떤 형식 오류든 `unauthenticated`."""
    if not isinstance(authorization, str) or not authorization or len(authorization) > _MAX_HEADER_LEN:
        raise SecurityError(ErrorCode.UNAUTHENTICATED)
    parts = authorization.strip().split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise SecurityError(ErrorCode.UNAUTHENTICATED)
    match = _KEY_RE.match(parts[1])
    if not match:
        raise SecurityError(ErrorCode.UNAUTHENTICATED)
    return match.group(1), match.group(2)


def _credential_live(cred: Optional[dict]) -> bool:
    if not cred or cred.get("revoked_at"):
        return False
    expires = parse_iso(cred.get("expires_at"))
    return bool(expires and expires > utcnow())


def _fail(code: str, *, domain: Optional[str], user_key: Optional[str] = None,
          kid: Optional[str] = None, outcome: str = "failure") -> SecurityError:
    audit("auth.bearer", outcome=outcome, error_code=code, domain=domain, user_key=user_key, credential_id=kid)
    return SecurityError(code)


def _authenticate_sync(authorization: Optional[str], domain: Optional[str]) -> Principal:
    try:
        kid, secret = parse_bearer(authorization)
    except SecurityError:
        raise _fail(ErrorCode.UNAUTHENTICATED, domain=domain) from None
    user_key = reg.user_for_kid(kid)
    if user_key is None:
        raise _fail(ErrorCode.UNAUTHENTICATED, domain=domain)
    record = reg.get_user(user_key)
    if record is None or record.status == "deleted":
        raise _fail(ErrorCode.UNAUTHENTICATED, domain=domain, user_key=user_key, kid=kid)
    try:
        cred = record.store().get_credential(kid)
    except (StoreMissing, StoreOwnerMismatch):
        logger.warning("bearer auth: user auth store unavailable (user_key=%s)", user_key[:12])
        raise _fail(ErrorCode.UNAUTHENTICATED, domain=domain, user_key=user_key, kid=kid) from None
    expected = key_digest(deployment_id_for(), kid, secret)
    if not cred or not hmac.compare_digest(expected, str(cred.get("digest", ""))):
        raise _fail(ErrorCode.UNAUTHENTICATED, domain=domain, user_key=user_key, kid=kid)
    if not _credential_live(cred):
        raise _fail(ErrorCode.UNAUTHENTICATED, domain=domain, user_key=user_key, kid=kid)
    if not record.usable:
        raise _fail(ErrorCode.ACCOUNT_INACTIVE, domain=domain, user_key=user_key, kid=kid, outcome="denied")
    scopes = frozenset(cred["scopes"])
    if domain is not None and scope_for_domain(domain) not in scopes:
        raise _fail(ErrorCode.FORBIDDEN_SCOPE, domain=domain, user_key=user_key, kid=kid, outcome="denied")
    principal = Principal(
        user_key=record.user_key,
        tenant_id=record.tenant_id,
        object_id=record.object_id,
        graph_email=record.graph_email if record.status == "active" else None,
        credential_id=kid,
        scopes=scopes,
        auth_epoch=record.auth_epoch,
    )
    audit("auth.bearer", outcome="success", principal=principal, domain=domain)
    return principal


async def authenticate_bearer(authorization: Optional[str], *, domain: Optional[str]) -> Principal:
    """Authorization 헤더 값 → `Principal`. 실패는 `SecurityError(unauthenticated|forbidden_scope|account_inactive)`.

    Args:
        authorization: `Authorization` 헤더 값 그대로 (없으면 None). 여러 개 온 경우의 거부는 호출자(WP1) 몫.
        domain: MCP 서버 도메인(`SERVER_NAME`). None 이면 scope 검사 생략(auth gateway 전용).
    """
    return await asyncio.to_thread(_authenticate_sync, authorization, domain)


def check_active_sync(principal: Principal, *, require_linked: bool = False,
                      check_credential: bool = True) -> "reg.UserRecord":
    """동기 버전. require_linked=True 면 Graph 연결(active)까지 요구 — 아니면 `graph_not_connected`.

    check_credential=False 는 토큰 저장 직전 검사용이다(키 폐기는 사용자 토큰 저장을 막지 않고,
    그 키로 들어온 요청에 결과를 돌려주는 것만 막는다).
    """
    record = reg.get_user(principal.user_key)
    if (
        record is None
        or not record.usable
        or record.auth_epoch != principal.auth_epoch
        or record.tenant_id != principal.tenant_id.lower()
        or record.object_id != principal.object_id.lower()
    ):
        raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)
    if check_credential and principal.credential_id:
        try:
            cred = record.store().get_credential(principal.credential_id)
        except (StoreMissing, StoreOwnerMismatch):
            logger.error("active check: user auth store unavailable (user_key=%s)", record.user_key[:12])
            raise SecurityError(ErrorCode.ACCOUNT_INACTIVE) from None
        if not _credential_live(cred):
            raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)
    if require_linked and record.status != "active":
        raise SecurityError(ErrorCode.GRAPH_NOT_CONNECTED)
    return record


async def assert_active(principal: Principal) -> None:
    """요청 처리 중 재확인 — 계정 usable(active·pending_link), auth_epoch 불변, 키 미폐기·미만료.

    아니면 `SecurityError(account_inactive)`. 런타임(WP1)은 핸들러 전·응답 전에 부른다.
    """
    await asyncio.to_thread(check_active_sync, principal)


# 관리 함수 재수출 (위성 모듈)
from .registry_admin import (  # noqa: E402  - 관문 재수출
    AdminError,
    IssuedKey,
    bump_auth_epoch,
    delete_user,
    disconnect_graph,
    issue_key,
    list_keys,
    list_users,
    register_user,
    revoke_key,
    rotate_key,
    set_status,
)

get_user = reg.get_user
UserRecord = reg.UserRecord
ensure_registry = reg.ensure_registry

__all__ = [
    "KEY_PREFIX",
    "key_digest",
    "parse_bearer",
    "authenticate_bearer",
    "assert_active",
    "check_active_sync",
    "AdminError",
    "IssuedKey",
    "UserRecord",
    "ensure_registry",
    "get_user",
    "register_user",
    "issue_key",
    "rotate_key",
    "revoke_key",
    "list_keys",
    "set_status",
    "bump_auth_epoch",
    "disconnect_graph",
    "delete_user",
    "list_users",
]
