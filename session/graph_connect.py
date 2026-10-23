"""
Graph 연결 시도(OAuth authorization code + PKCE + OIDC) 수명 관리 (spec/spec_멀티유저.md ②-6.4, ②-12.4).

    graph_connect_details(principal) -> {"connect_url": ..., "expires_in": 300}

흐름 (모든 상태는 사용자 auth.db 의 `oauth_attempts` 한 행 — 전역 Event·전역 이메일 없음):

1. **시작** (`create_connect_attempt`): bearer 로 확인된 principal·auth_epoch·예상 (tid, oid) 를
   담은 시도(`created`)와 1회용 browser ticket(300초, 해시 저장)을 만든다. URL 에 bearer 를 넣지 않는다.
   사용자별 진행 중 시도는 최대 3개 — 넘으면 가장 오래된 미진행 시도를 `superseded` 로 닫는다.
   정리·상한 확인·삽입은 **사용자 lock(`system/locks/user-<user_key>`) 아래** 한 단위다(R13) —
   병렬 start 가 각각 "여유 있음"으로 판단해 상한을 넘기지 못한다.
2. **브라우저 바인딩** (`begin_browser_flow`): ticket 을 1회 소비하고 시도별 쿠키 값,
   256비트 state, PKCE verifier(S256), OIDC nonce 를 만든다. state·쿠키·nonce 는 해시로, verifier 는
   암호화해 저장하고 `pending` 으로 바꾼다. 시도 수명은 생성 후 10분.
3. **콜백** (`complete_callback`): state 해시 → (user_key, attempt_id) 위치 → 시도 행. 만료·쿠키·
   계정 상태·epoch 확인 후 `pending → redeeming` 을 원자적으로 바꾼 한 요청만 code 를 교환한다.
   ID token(서명·issuer·aud·시간·nonce·tenant)과 Graph `/me.id` 가 등록된 (tid, oid) 와 같아야
   `token_store.commit_graph_connection()` 으로 **lock 아래에서 epoch 재검사→암호화 토큰 저장→`active`
   확정** 을 한 단위로 한다(R03). 같은 사용자의 동시 완료는 한 건만 확정된다. 결과에는 상태와 계정
   표시만 — 토큰 없음.

잘못된 state·만료·재사용·OAuth 오류는 **그 시도만** 실패시키고 다른 시도는 건드리지 않는다.
code 교환 이후 결과가 불명확해지면 같은 code 를 재사용하지 않는다(새 연결 필요).
"""

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlencode

from mcp_common.audit import audit
from mcp_common.principal import Principal
from mcp_common.security_contracts import ErrorCode, SecurityError

from . import _registry_db as reg
from ._mu_common import b64url_nopad, iso, parse_iso, sha256_hex, utcnow
from .app_settings import AppSettings, load_app_settings
from .entra_client import EntraError, IdTokenError, get_entra_http, get_id_token_validator, token_bundle
from .file_lock import LockTimeout, file_lock, user_lock_path
from .identity_registry import check_active_sync
from .token_store import commit_graph_connection
from .user_auth_store import ACTIVE_ATTEMPT_STATUSES, StoreMissing, StoreOwnerMismatch, UserAuthStore
from .user_crypto import KIND_PKCE_VERIFIER, RecordDecryptError, open_sealed, seal

logger = logging.getLogger(__name__)

CONNECT_TICKET_TTL_SECONDS = 300
ATTEMPT_TTL_SECONDS = 600
MAX_PENDING_ATTEMPTS = 3
ATTEMPT_RETENTION = timedelta(hours=24)
COOKIE_PREFIX = "m365_oauth_"

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,256}$")
_ATTEMPT_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class ConnectError(Exception):
    """브라우저 연결 단계 거부. code 는 공개 식별자(비밀 없음)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ConnectLink:
    attempt_id: str
    expires_in: int
    connect_url: str = field(repr=False)  # 1회용 ticket 포함


@dataclass(frozen=True)
class BrowserRedirect:
    attempt_id: str
    cookie_name: str
    cookie_path: str
    max_age: int
    secure: bool
    authorize_url: str = field(repr=False)
    cookie_value: str = field(repr=False)


@dataclass(frozen=True)
class CallbackResult:
    ok: bool
    code: str
    attempt_id: Optional[str] = None
    account: Optional[str] = None
    cookie_name: Optional[str] = None


def _norm_uuid(value: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value))).lower()
    except (ValueError, TypeError, AttributeError):
        return None


def _expired(value: Optional[str]) -> bool:
    when = parse_iso(value)
    return when is None or when <= utcnow()


# ----------------------------------------------------------------------
# 1. 시작
# ----------------------------------------------------------------------
def _housekeeping(store: UserAuthStore) -> None:
    for attempt in store.active_attempts():
        if _expired(attempt["expires_at"]):
            store.fail_attempt(attempt["attempt_id"], "expired", to_status="expired")
            reg.drop_attempt_indexes(store.user_key, attempt["attempt_id"])
    store.prune_attempts(older_than=iso(utcnow() - ATTEMPT_RETENTION))
    reg.prune_indexes()


def _make_room(store: UserAuthStore) -> None:
    active = store.active_attempts()
    while len(active) >= MAX_PENDING_ATTEMPTS:
        victim = next((a for a in active if a["status"] in ("created", "pending")), None)
        if victim is None:
            raise SecurityError(ErrorCode.OVERLOADED, "진행 중인 연결 시도가 많습니다. 잠시 후 다시 시도하세요.")
        store.fail_attempt(victim["attempt_id"], "superseded", from_statuses=("created", "pending"),
                           to_status="superseded")
        reg.drop_attempt_indexes(store.user_key, victim["attempt_id"])
        active = store.active_attempts()


def create_connect_attempt(principal: Principal) -> ConnectLink:
    """본인 연결 시도 + 1회용 browser ticket. principal 은 bearer 로 확인된 것이어야 한다."""
    settings = load_app_settings()
    # 계정 상태·epoch 만 확인한다. 요청 키의 폐기 여부는 호출 경로(gateway 의 bearer 인증,
    # 런타임의 요청 principal assert_active)가 이미 확인했다 — 캐시된 공급자 principal 의
    # 오래된 credential_id 때문에 다른 유효 키 사용자의 연결 링크가 막히지 않게 한다.
    record = check_active_sync(principal, check_credential=False)
    store = record.store()
    now = utcnow()
    attempt_id = secrets.token_hex(16)
    ticket = secrets.token_urlsafe(32)
    ticket_hash = sha256_hex(ticket)
    ticket_expires = iso(now + timedelta(seconds=CONNECT_TICKET_TTL_SECONDS))
    try:
        # 정리·상한 확인·삽입을 사용자 lock 아래 한 단위로 (R13)
        with file_lock(user_lock_path(record.user_key)):
            _housekeeping(store)
            _make_room(store)
            store.insert_attempt({
                "attempt_id": attempt_id,
                "status": "created",
                "created_at": iso(now),
                "updated_at": iso(now),
                "expires_at": iso(now + timedelta(seconds=ATTEMPT_TTL_SECONDS)),
                "ticket_hash": ticket_hash,
                "ticket_expires_at": ticket_expires,
                "expected_tenant_id": record.tenant_id,
                "expected_object_id": record.object_id,
                "auth_epoch": record.auth_epoch,
                "credential_id": principal.credential_id or None,
            })
            reg.index_ticket(ticket_hash, record.user_key, attempt_id, ticket_expires)
    except LockTimeout:
        raise SecurityError(ErrorCode.OVERLOADED, "연결 시도 생성이 지연되고 있습니다. 잠시 후 다시 시도하세요.") from None
    except (StoreMissing, StoreOwnerMismatch):
        raise SecurityError(ErrorCode.INTERNAL_ERROR) from None
    audit("oauth.start", outcome="success", principal=principal)
    return ConnectLink(
        attempt_id=attempt_id,
        expires_in=CONNECT_TICKET_TTL_SECONDS,
        connect_url=f"{settings.public_base_url}/auth/graph/connect?{urlencode({'ticket': ticket})}",
    )


def graph_connect_details(principal: Principal) -> Dict[str, Any]:
    """런타임(WP1)이 `graph_not_connected`/`graph_reauth_required` 오류에 붙이는 연결 안내."""
    link = create_connect_attempt(principal)
    return {"connect_url": link.connect_url, "expires_in": link.expires_in}


# ----------------------------------------------------------------------
# 2. 브라우저 바인딩
# ----------------------------------------------------------------------
def begin_browser_flow(ticket: Optional[str], *, settings: Optional[AppSettings] = None) -> BrowserRedirect:
    settings = settings or load_app_settings()
    if not isinstance(ticket, str) or not _TOKEN_RE.match(ticket):
        raise ConnectError("invalid_ticket")
    ticket_hash = sha256_hex(ticket)
    location = reg.take_ticket(ticket_hash)  # 1회 소비 — 이후 같은 ticket 은 위치부터 없다
    if location is None:
        raise ConnectError("invalid_ticket")
    user_key, attempt_id, _ = location
    record = reg.get_user(user_key)
    if record is None or not record.usable:
        raise ConnectError("account_inactive")
    store = record.store()
    try:
        attempt = store.get_attempt(attempt_id)
        if (
            attempt is None
            or attempt["status"] != "created"
            or not hmac.compare_digest(attempt["ticket_hash"] or "", ticket_hash)
        ):
            raise ConnectError("invalid_ticket")
        if _expired(attempt["ticket_expires_at"]) or _expired(attempt["expires_at"]):
            store.fail_attempt(attempt_id, "ticket_expired", to_status="expired")
            raise ConnectError("ticket_expired")
        if record.auth_epoch != attempt["auth_epoch"]:
            store.fail_attempt(attempt_id, "account_changed")
            raise ConnectError("account_changed")

        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = b64url_nopad(hashlib.sha256(verifier.encode("ascii")).digest())
        nonce = secrets.token_urlsafe(32)
        binding = secrets.token_urlsafe(32)
        sealed = seal(store.paths, {"code_verifier": verifier}, app_id=settings.app_id, kind=KIND_PKCE_VERIFIER,
                      record_version=1, record_id=attempt_id)
        state_hash = sha256_hex(state)
        moved = store.transition_attempt(
            attempt_id, from_status="created", to_status="pending", match={"ticket_hash": ticket_hash},
            ticket_hash=None, state_hash=state_hash, browser_binding_hash=sha256_hex(binding),
            nonce_hash=sha256_hex(nonce), verifier_ciphertext=sealed.ciphertext, verifier_nonce=sealed.nonce,
            dek_version=sealed.dek_version,
        )
        if not moved:
            raise ConnectError("invalid_ticket")
    except (StoreMissing, StoreOwnerMismatch, RecordDecryptError):
        raise ConnectError("internal_error") from None
    reg.index_state(state_hash, user_key, attempt_id, attempt["expires_at"])

    params = {
        "client_id": settings.client_id,
        "response_type": "code",
        "redirect_uri": settings.redirect_uri,
        "response_mode": "query",
        "scope": " ".join(settings.scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    if record.graph_email:
        params["login_hint"] = record.graph_email
    remaining = int((parse_iso(attempt["expires_at"]) - utcnow()).total_seconds())
    return BrowserRedirect(
        attempt_id=attempt_id,
        cookie_name=COOKIE_PREFIX + attempt_id,
        cookie_path=settings.callback_path,
        max_age=max(1, remaining),
        secure=settings.uses_https,
        authorize_url=f"{settings.authorize_endpoint}?{urlencode(params)}",
        cookie_value=binding,
    )


# ----------------------------------------------------------------------
# 3. 콜백
# ----------------------------------------------------------------------
def _reject(code: str, *, user_key: Optional[str] = None) -> CallbackResult:
    audit("oauth.fail", outcome="denied", error_code=code, user_key=user_key)
    return CallbackResult(False, code)


async def complete_callback(
    query: Mapping[str, str],
    cookies: Mapping[str, str],
    *,
    settings: Optional[AppSettings] = None,
    entra: Any = None,
    jwks_client: Any = None,
) -> CallbackResult:
    """콜백 1건 처리. 예외를 올리지 않고 결과만 돌려준다(응답 페이지는 gateway 몫)."""
    settings = settings or load_app_settings()
    state = query.get("state")
    if not isinstance(state, str) or not _TOKEN_RE.match(state):
        return _reject("invalid_state")
    state_hash = sha256_hex(state)
    location = await asyncio.to_thread(reg.lookup_state, state_hash)
    if location is None:
        return _reject("invalid_state")  # 아무 시도도 바꾸지 않는다
    user_key, attempt_id, _ = location
    record = await asyncio.to_thread(reg.get_user, user_key)
    if record is None:
        return _reject("invalid_state")
    store = record.store()
    cookie_name = COOKIE_PREFIX + attempt_id
    try:
        attempt = await asyncio.to_thread(store.get_attempt, attempt_id)
    except (StoreMissing, StoreOwnerMismatch):
        return _reject("invalid_state", user_key=user_key)
    if attempt is None or not hmac.compare_digest(attempt["state_hash"] or "", state_hash):
        return _reject("invalid_state", user_key=user_key)
    if attempt["status"] != "pending":
        return _reject("replayed", user_key=user_key)  # 완료·실패·진행 중 시도는 그대로 둔다

    async def fail(code: str, *, to_status: str = "failed") -> CallbackResult:
        await asyncio.to_thread(store.fail_attempt, attempt_id, code, to_status=to_status)
        await asyncio.to_thread(reg.drop_attempt_indexes, user_key, attempt_id)
        audit("oauth.fail", outcome="failure", error_code=code, user_key=user_key)
        return CallbackResult(False, code, attempt_id=attempt_id, cookie_name=cookie_name)

    if _expired(attempt["expires_at"]):
        return await fail("expired", to_status="expired")
    cookie = cookies.get(cookie_name)
    binding_hash = attempt["browser_binding_hash"] or ""
    if not isinstance(cookie, str) or not hmac.compare_digest(sha256_hex(cookie), binding_hash):
        return await fail("browser_mismatch")
    if query.get("error"):
        return await fail("oauth_error")  # 오류 원문은 기록·표시하지 않는다
    code = query.get("code")
    if not isinstance(code, str) or not code or len(code) > 8192:
        return await fail("missing_code")
    if not record.usable or record.auth_epoch != attempt["auth_epoch"]:
        return await fail("account_changed")

    moved = await asyncio.to_thread(store.transition_attempt, attempt_id, from_status="pending",
                                    to_status="redeeming", match={"state_hash": state_hash})
    if not moved:
        return _reject("replayed", user_key=user_key)
    await asyncio.to_thread(reg.drop_state, state_hash)
    return await _redeem(settings, record, store, attempt, code, fail, entra=entra, jwks_client=jwks_client)


async def _redeem(settings: AppSettings, record: "reg.UserRecord", store: UserAuthStore, attempt: Dict[str, Any],
                  code: str, fail, *, entra: Any, jwks_client: Any) -> CallbackResult:
    attempt_id = attempt["attempt_id"]
    try:
        verifier = open_sealed(store.paths, ciphertext=attempt["verifier_ciphertext"] or b"",
                               nonce=attempt["verifier_nonce"] or b"", dek_version=attempt["dek_version"] or 0,
                               app_id=settings.app_id, kind=KIND_PKCE_VERIFIER, record_version=1,
                               record_id=attempt_id)["code_verifier"]
    except (RecordDecryptError, KeyError, TypeError):
        return await fail("internal_error")

    entra = entra or get_entra_http(settings)
    try:
        data = await entra.exchange_code(code=code, code_verifier=verifier)
        bundle = token_bundle(data)
    except EntraError:
        return await fail("token_exchange_failed")
    id_token = data.get("id_token")
    try:
        claims = await get_id_token_validator(settings, jwks_client=jwks_client).validate(
            id_token, nonce_hash=attempt["nonce_hash"]
        )
    except IdTokenError as exc:
        return await fail(exc.code)
    expected = (attempt["expected_tenant_id"], attempt["expected_object_id"])
    if (claims["tid"], claims["oid"]) != expected or expected != (record.tenant_id, record.object_id):
        return await fail("account_mismatch")
    try:
        me = await entra.get_me(bundle["access_token"])
    except EntraError:
        return await fail("graph_profile_failed")
    if _norm_uuid(me.get("id")) != claims["oid"]:
        return await fail("account_mismatch")
    email = me.get("mail") or me.get("userPrincipalName") or claims.get("preferred_username")
    if not isinstance(email, str) or not email.strip():
        return await fail("graph_profile_failed")

    # epoch 재검사 → 토큰 저장 → registry 확정을 (user, app) lock 아래 한 단위로 (R03)
    try:
        await commit_graph_connection(record, bundle, expected_epoch=attempt["auth_epoch"],
                                      graph_email=email.strip(), settings=settings)
    except SecurityError as exc:
        return await fail("account_changed" if exc.code == ErrorCode.ACCOUNT_INACTIVE else "store_busy")
    await asyncio.to_thread(store.transition_attempt, attempt_id, from_status="redeeming", to_status="completed",
                            verifier_ciphertext=None, verifier_nonce=None)
    await asyncio.to_thread(reg.drop_attempt_indexes, record.user_key, attempt_id)
    audit("oauth.complete", outcome="success", user_key=record.user_key)
    return CallbackResult(True, "connected", attempt_id=attempt_id, account=email.strip(),
                          cookie_name=COOKIE_PREFIX + attempt_id)


# ----------------------------------------------------------------------
# 조회·해제 (bearer 본인 전용)
# ----------------------------------------------------------------------
def attempt_status(principal: Principal, attempt_id: str) -> Optional[Dict[str, Any]]:
    """본인 시도의 상태만. 다른 사용자의 시도는 다른 DB 에 있으므로 None(=not found)."""
    if not isinstance(attempt_id, str) or not _ATTEMPT_ID_RE.match(attempt_id):
        return None
    record = check_active_sync(principal)
    store = record.store()
    try:
        attempt = store.get_attempt(attempt_id)
        if attempt is None:
            return None
        if attempt["status"] in ACTIVE_ATTEMPT_STATUSES and _expired(attempt["expires_at"]):
            store.fail_attempt(attempt_id, "expired", to_status="expired")
            attempt = store.get_attempt(attempt_id) or attempt
    except (StoreMissing, StoreOwnerMismatch):
        raise SecurityError(ErrorCode.INTERNAL_ERROR) from None
    return {
        "attempt_id": attempt["attempt_id"],
        "status": attempt["status"],
        "error": attempt["error_code"],
        "created_at": attempt["created_at"],
        "expires_at": attempt["expires_at"],
    }


def disconnect(principal: Principal) -> None:
    """본인 Graph 연결 해제 — 토큰 삭제, auth_epoch 증가, pending_link 로."""
    from .registry_admin import AdminBusyError, AdminError, disconnect_graph

    check_active_sync(principal)
    try:
        disconnect_graph(principal.user_key)
    except AdminBusyError:
        raise SecurityError(ErrorCode.OVERLOADED, "연결 해제가 지연되고 있습니다. 잠시 후 다시 시도하세요.") from None
    except AdminError:
        raise SecurityError(ErrorCode.ACCOUNT_INACTIVE) from None


__all__ = [
    "CONNECT_TICKET_TTL_SECONDS",
    "ATTEMPT_TTL_SECONDS",
    "MAX_PENDING_ATTEMPTS",
    "COOKIE_PREFIX",
    "ConnectError",
    "ConnectLink",
    "BrowserRedirect",
    "CallbackResult",
    "create_connect_attempt",
    "graph_connect_details",
    "begin_browser_flow",
    "complete_callback",
    "attempt_status",
    "disconnect",
]
