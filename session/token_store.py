"""
사용자별 Graph 토큰 저장소와 **단일 refresh 진입점** (spec/spec_멀티유저.md ②-6.3, ②-7.6).

    async def get_graph_access_token(principal, *, minimum_ttl_seconds=120) -> AccessToken

순서:

1. 계정 상태·auth_epoch 확인 (pending_link → `graph_not_connected`, 비활성 → `account_inactive`)
2. 남은 수명이 충분하면 바로 반환 (lock 없음)
3. `(user_key, app_id)` 프로세스 내 asyncio lock
4. 같은 키의 프로세스 간 OS 파일 lock (기본 30초, 초과 → `overloaded` 재시도 가능)
5. 최신 토큰·`token_version` 재조회 — 다른 프로세스가 이미 갱신했으면 그것을 쓴다
6. 여전히 필요할 때만 token endpoint 호출 (SQLite 트랜잭션을 잡지 않은 채)
7. 계정 상태·epoch 재확인 — 그 사이 비활성·연결 해제·삭제됐으면 **저장하지 않는다**
8. `token_version` 조건부 저장 (새 refresh_token 이 오면 교체, 없으면 기존 유지)
9. 반환 직전 계정 상태·epoch 를 다시 확인

토큰 저장소의 확인은 **계정 상태·auth_epoch 만** 본다(키 폐기·만료는 보지 않는다). 서비스 풀이
`(user_key, domain, auth_epoch)` 로 공급자를 캐시하므로 공급자 principal 의 `credential_id` 는 첫
lease 의 키일 수 있다 — 그 키가 폐기돼도 같은 사용자의 다른 유효 키 요청은 계속 돼야 한다. 요청을
보낸 키 자체의 폐기·만료는 런타임(WP1)이 **요청 principal** 로 `assert_active()` 를 불러 막는다.
비활성·연결 해제·삭제는 epoch·상태를 바꾸므로 여기서 저장·반환이 막힌다.

다만 **지금 이 토큰을 쓰려는 요청**의 키는 따로 본다(R01). 요청이 풀 슬롯을 기다리는 사이 그 키가
폐기·만료될 수 있고, 공급자의 principal 로는 그것을 알 수 없다. 그래서 토큰을 돌려주기 직전에
`mcp_common.principal.current_identity()` 가 있으면 **그 요청 principal** 의 키·만료·계정·epoch 를
재검사한다(SQLite 읽기 2회). identity 가 없으면(백그라운드·서비스 내부) 계정 검사만 한다. 다른
사용자의 identity 가 묶인 채 호출되면 불변조건 위반이므로 거부한다.

OAuth 연결 확정(`commit_graph_connection`)은 같은 `(user_key, app_id)` lock 아래에서 **epoch 재검사 →
토큰 저장 → registry 확정** 을 한 단위로 한다(R03). 동시 완료 두 건 중 한 건만 확정되고, 다른 한 건은
토큰을 건드리지 않는다. 연결 해제(`registry_admin.disconnect_graph`)도 **같은 lock 을 epoch 를 올리기 전에**
잡고 그 안에서 epoch 증가 → 버전 조건부 DELETE 를 하므로(N02) 확정·갱신·해제는 어느 순서로든 직렬화되고
결과는 (active+토큰) 또는 (pending_link+토큰 없음) 둘 중 하나다. 확정 중 실패의 되돌림은 **버전 조건부
단일 DELETE** 라 뒤에 저장된 새 토큰을 지우지 않는다.

`invalid_grant` → 행을 `reauth_required` 로 표시하고 `graph_reauth_required`. 이후 호출은 token
endpoint 를 다시 두드리지 않는다. 토큰 없음 → `graph_not_connected`. 복호화 실패 → `internal_error`
(다른 키·사용자·평문으로 폴백하지 않음).

`BoundGraphTokenProvider` 는 한 principal 에 고정된 `BoundTokenProvider` 구현이다.
`mcp_common.auth.get_bound_token_provider(principal)` 가 이것을 만든다.
"""

import asyncio
import logging
import threading
import weakref
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from mcp_common.audit import audit
from mcp_common.principal import Principal, current_identity, normalize_email_for_compare
from mcp_common.security_contracts import AccessToken, ErrorCode, SecurityError

from . import _registry_db as reg
from ._mu_common import current_root, parse_iso, utcnow
from .app_settings import AppSettings, load_app_settings
from .entra_client import EntraError, get_entra_http, token_bundle
from .file_lock import DEFAULT_TIMEOUT_SECONDS, LockTimeout, async_file_lock, refresh_lock_path
from .identity_registry import check_active_sync
from .user_auth_store import StoreMissing, StoreOwnerMismatch, TokenRow, UserAuthStore
from .user_crypto import KIND_GRAPH_TOKENS, RecordDecryptError, open_sealed, seal

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS

_locks: "weakref.WeakValueDictionary[Tuple[Any, ...], asyncio.Lock]" = weakref.WeakValueDictionary()
_locks_guard = threading.Lock()


def _process_lock(user_key: str, app_id: str) -> asyncio.Lock:
    """`(loop, data_root, user_key, app_id)` 별 asyncio.Lock. 쓰이지 않으면 GC 된다(무제한 증가 없음)."""
    key = (id(asyncio.get_running_loop()), str(current_root()), user_key, app_id)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


def _store(principal: Principal) -> UserAuthStore:
    return UserAuthStore(principal.user_key, principal.tenant_id, principal.object_id)


def _internal(message: str = "저장된 Microsoft 365 인증 정보를 확인할 수 없습니다.") -> SecurityError:
    return SecurityError(ErrorCode.INTERNAL_ERROR, message)


def _busy() -> SecurityError:
    return SecurityError(ErrorCode.OVERLOADED, "토큰 저장·갱신이 지연되고 있습니다. 잠시 후 다시 시도하세요.")


def _open_row(store: UserAuthStore, row: TokenRow, app_id: str) -> Dict[str, Any]:
    try:
        return open_sealed(store.paths, ciphertext=row.ciphertext, nonce=row.nonce, dek_version=row.dek_version,
                           app_id=app_id, kind=KIND_GRAPH_TOKENS, record_version=row.token_version)
    except RecordDecryptError:
        logger.error("graph token record failed authentication (user_key=%s)", store.user_key[:12])
        raise _internal() from None


def _fresh(row: TokenRow, payload: Dict[str, Any], minimum_ttl_seconds: int) -> bool:
    if row.state != "ok" or not payload.get("access_token"):
        return False
    expires = parse_iso(row.expires_at)
    return bool(expires and expires - utcnow() >= timedelta(seconds=max(0, minimum_ttl_seconds)))


def _as_token(row: TokenRow, payload: Dict[str, Any]) -> AccessToken:
    return AccessToken(payload["access_token"], parse_iso(row.expires_at), row.token_version)


def _read(store: UserAuthStore, app_id: str) -> Optional[Tuple[TokenRow, Dict[str, Any]]]:
    try:
        row = store.get_token_row(app_id)
    except (StoreMissing, StoreOwnerMismatch):
        logger.error("user auth store unavailable (user_key=%s)", store.user_key[:12])
        raise _internal() from None
    if row is None:
        return None
    return row, _open_row(store, row, app_id)


def _check_account(principal: Principal) -> "reg.UserRecord":
    """계정 상태·auth_epoch·(tid, oid) 만 확인한다 — 키(credential) 는 보지 않는다(모듈 docstring 참고)."""
    return check_active_sync(principal, require_linked=True, check_credential=False)


def _check_request_identity(user_key: str) -> None:
    """현재 요청(RequestIdentity)이 묶여 있으면 **그 요청의** 키·만료·계정·epoch 를 재검사한다 (R01).

    공급자 principal 의 credential 은 풀의 첫 lease 키일 수 있어 보지 않는다. identity 가 없으면
    아무것도 하지 않는다(계정 검사는 호출자가 이미 했다).
    """
    identity = current_identity()
    if identity is None:
        return
    request_principal = identity.principal
    if request_principal.user_key != user_key:
        logger.error("token provider user does not match the bound request identity")
        raise SecurityError(ErrorCode.INTERNAL_ERROR, "요청 사용자와 토큰 공급자가 일치하지 않습니다.")
    check_active_sync(request_principal)


def _try_fresh(principal: Principal, app_id: str, minimum_ttl_seconds: int) -> Optional[AccessToken]:
    _check_account(principal)
    found = _read(_store(principal), app_id)
    if found and _fresh(found[0], found[1], minimum_ttl_seconds):
        return _as_token(*found)
    return None


async def get_graph_access_token(principal: Principal, *, minimum_ttl_seconds: int = 120) -> AccessToken:
    """principal 의 Graph access token. 실패는 전부 `SecurityError` (원문 비노출).

    반환 직전에 현재 요청 identity 의 키를 재검사한다(R01, `_check_request_identity`).
    """
    if not isinstance(principal, Principal):
        raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
    token = await _acquire_token(principal, minimum_ttl_seconds)
    await asyncio.to_thread(_check_request_identity, principal.user_key)
    return token


async def _acquire_token(principal: Principal, minimum_ttl_seconds: int) -> AccessToken:
    settings = load_app_settings()
    app_id = settings.app_id
    token = await asyncio.to_thread(_try_fresh, principal, app_id, minimum_ttl_seconds)
    if token is not None:
        return token
    async with _process_lock(principal.user_key, app_id):
        try:
            async with async_file_lock(refresh_lock_path(principal.user_key, app_id), timeout=LOCK_TIMEOUT_SECONDS):
                return await _refresh_locked(principal, settings, minimum_ttl_seconds)
        except LockTimeout:  # 획득 대기 초과만 해당 (본문은 LockTimeout 을 던지지 않는다)
            raise _busy() from None


async def _refresh_locked(principal: Principal, settings: AppSettings, minimum_ttl_seconds: int) -> AccessToken:
    app_id = settings.app_id
    store = _store(principal)
    found = await asyncio.to_thread(_read, store, app_id)
    if found is None:
        raise SecurityError(ErrorCode.GRAPH_NOT_CONNECTED)
    row, payload = found
    if _fresh(row, payload, minimum_ttl_seconds):
        await asyncio.to_thread(_check_account, principal)
        return _as_token(row, payload)
    if row.state == "reauth_required":
        raise SecurityError(ErrorCode.GRAPH_REAUTH_REQUIRED)
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        await asyncio.to_thread(store.mark_reauth_required, app_id, expected_version=row.token_version)
        raise SecurityError(ErrorCode.GRAPH_REAUTH_REQUIRED)

    try:
        data = await get_entra_http(settings).refresh(refresh_token=refresh_token)
        bundle = token_bundle(data, previous_refresh_token=refresh_token)
    except EntraError as exc:
        if exc.is_invalid_grant:
            await asyncio.to_thread(store.mark_reauth_required, app_id, expected_version=row.token_version)
            audit("token.refresh", outcome="failure", principal=principal, error_code=ErrorCode.GRAPH_REAUTH_REQUIRED)
            raise SecurityError(ErrorCode.GRAPH_REAUTH_REQUIRED) from None
        audit("token.refresh", outcome="failure", principal=principal, error_code=exc.code)
        raise _internal("Microsoft 토큰 갱신 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.") from None

    # 저장 전 재확인 — 비활성·연결 해제·삭제·epoch 변경이면 결과를 버린다(A05).
    try:
        await asyncio.to_thread(_check_account, principal)
    except SecurityError as exc:
        audit("token.refresh", outcome="denied", principal=principal, error_code=exc.code)
        raise

    new_version = row.token_version + 1
    saved = await asyncio.to_thread(_save, store, app_id, bundle, expected_version=row.token_version,
                                    new_version=new_version)
    if not saved:
        # 다른 경로(연결 해제·재연결)가 행을 바꿨다 — 그쪽 결과를 기준으로 다시 판단한다.
        await asyncio.to_thread(_check_account, principal)
        latest = await asyncio.to_thread(_read, store, app_id)
        if latest and _fresh(latest[0], latest[1], minimum_ttl_seconds):
            return _as_token(*latest)
        raise SecurityError(ErrorCode.GRAPH_REAUTH_REQUIRED)

    audit("token.refresh", outcome="success", principal=principal)
    await asyncio.to_thread(_check_account, principal)
    return AccessToken(bundle["access_token"], parse_iso(bundle["expires_at"]), new_version)


def _save(store: UserAuthStore, app_id: str, bundle: Dict[str, Any], *, expected_version: int,
          new_version: int) -> bool:
    sealed = seal(store.paths, {"access_token": bundle["access_token"], "refresh_token": bundle.get("refresh_token")},
                  app_id=app_id, kind=KIND_GRAPH_TOKENS, record_version=new_version)
    return store.replace_tokens_if_version(
        app_id,
        expected_version=expected_version,
        new_version=new_version,
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
        dek_version=sealed.dek_version,
        expires_at=bundle.get("expires_at"),
        scope=bundle.get("scope"),
    )


def _commit_locked(record: "reg.UserRecord", store: UserAuthStore, app_id: str, bundle: Dict[str, Any],
                   expected_epoch: int, graph_email: str) -> int:
    """lock 안: epoch 재검사 → 버전 조건부 저장 → registry 확정. 확정 실패는 조건부 DELETE 로 되돌린다."""
    current = reg.get_user(record.user_key)
    if current is None or not current.usable or current.auth_epoch != expected_epoch:
        raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)  # 동시 완료·해제·비활성·삭제가 먼저 확정됐다
    version = store.token_version(app_id)
    new_version = version + 1
    if not _save(store, app_id, bundle, expected_version=version, new_version=new_version):
        raise _busy()
    try:
        return reg.mark_graph_linked(record.user_key, graph_email, expected_epoch=expected_epoch)
    except LookupError:
        # 저장과 확정 사이에 비활성·삭제가 epoch 를 바꿨다 — 방금 저장한 버전만 지운다(단일 조건부 DELETE)
        store.delete_tokens_if_version(app_id, new_version)
        raise SecurityError(ErrorCode.ACCOUNT_INACTIVE) from None


async def commit_graph_connection(record: "reg.UserRecord", bundle: Dict[str, Any], *, expected_epoch: int,
                                  graph_email: str, settings: Optional[AppSettings] = None) -> int:
    """OAuth 연결 완료 확정 (R03). `(user_key, app_id)` lock 아래에서 epoch 재검사→저장→registry 확정.

    반환: 새 auth_epoch. `account_inactive` = 시작 시점 epoch 가 더 이상 현재가 아니다(다른 완료가 먼저
    확정됐거나 해제·비활성·삭제됨) — 토큰은 건드리지 않았다. `overloaded` = lock 대기·버전 충돌(재시도 가능).
    """
    settings = settings or load_app_settings()
    app_id = settings.app_id
    store = record.store()
    async with _process_lock(record.user_key, app_id):
        try:
            async with async_file_lock(refresh_lock_path(record.user_key, app_id), timeout=LOCK_TIMEOUT_SECONDS):
                return await asyncio.to_thread(_commit_locked, record, store, app_id, bundle, expected_epoch,
                                               graph_email)
        except LockTimeout:
            raise _busy() from None


async def store_connected_tokens(record: "reg.UserRecord", bundle: Dict[str, Any], *,
                                 settings: Optional[AppSettings] = None) -> int:
    """토큰 묶음 **저장만** (registry 확정 없음 — 테스트 seed·이전 도구용). OAuth 경로는 `commit_graph_connection`."""
    settings = settings or load_app_settings()
    app_id = settings.app_id
    store = record.store()
    async with _process_lock(record.user_key, app_id):
        try:
            async with async_file_lock(refresh_lock_path(record.user_key, app_id), timeout=LOCK_TIMEOUT_SECONDS):
                current = await asyncio.to_thread(store.token_version, app_id)
                new_version = current + 1
                ok = await asyncio.to_thread(_save, store, app_id, bundle, expected_version=current,
                                             new_version=new_version)
        except LockTimeout:
            raise _busy() from None
    if not ok:
        raise _busy()
    return new_version


def discard_tokens_version(record: "reg.UserRecord", version: int, *, settings: Optional[AppSettings] = None) -> bool:
    """`version` 이 그대로일 때만 지운다 — 단일 조건부 DELETE 라 그 뒤 저장된 새 버전은 지우지 않는다."""
    settings = settings or load_app_settings()
    try:
        return record.store().delete_tokens_if_version(settings.app_id, version)
    except StoreMissing:
        return False


# ----------------------------------------------------------------------
# BoundTokenProvider 구현
# ----------------------------------------------------------------------
class BoundGraphTokenProvider:
    """한 principal 에 고정된 토큰 공급자. 생성 후 사용자를 바꾸지 않는다."""

    def __init__(self, principal: Principal):
        if not isinstance(principal, Principal):
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
        self._principal = principal

    @property
    def user_key(self) -> str:
        return self._principal.user_key

    @property
    def principal(self) -> Principal:
        return self._principal

    def __repr__(self) -> str:
        return f"BoundGraphTokenProvider(user_key={self._principal.user_key[:12]}…)"

    async def get_graph_token(self, *, minimum_ttl_seconds: int = 120) -> AccessToken:
        return await get_graph_access_token(self._principal, minimum_ttl_seconds=minimum_ttl_seconds)

    def _check_email(self, email: Optional[str]) -> None:
        """과도기 어댑터 규칙: 일치 확인만, 계정 선택 없음 (`assert_user_email` 과 같은 판정)."""
        if email is None:
            return
        if not isinstance(email, str) or not email.strip():
            raise SecurityError(ErrorCode.INVALID_USER_EMAIL)
        if not self._principal.graph_email:
            raise SecurityError(ErrorCode.GRAPH_NOT_CONNECTED)
        if normalize_email_for_compare(email) != normalize_email_for_compare(self._principal.graph_email):
            raise SecurityError(ErrorCode.IDENTITY_MISMATCH)

    async def validate_and_refresh_token(self, email: Optional[str] = None, auto_reauth: bool = False) -> Optional[str]:
        """기존 GraphClient 시그니처 호환. `auto_reauth` 는 무시한다(서버가 브라우저를 열지 않음)."""
        self._check_email(email)
        return (await self.get_graph_token()).value

    async def get_token(self, email: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """`TokenProviderProtocol.get_token` 호환 — 고정 사용자의 토큰 요약만."""
        self._check_email(email)
        token = await self.get_graph_token()
        return {
            "email": self._principal.graph_email,
            "access_token": token.value,
            "expires_at": token.expires_at,
            "is_expired": False,
        }

    async def get_auth_url_for_login(self, email: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
        """legacy `auth_required` 응답 호환 — 서버를 띄우지 않고 중앙 연결 링크만 만든다."""
        from .graph_connect import graph_connect_details

        details = await asyncio.to_thread(graph_connect_details, self._principal)
        return {
            "status": "auth_required",
            **details,
            "message": "Microsoft 365 연결이 필요합니다. connect_url 을 브라우저에서 열어 로그인하세요.",
        }

    async def close(self) -> None:
        """no-op — 공용 인증 자원·다른 사용자 자원을 닫지 않는다."""
        return None


__all__ = [
    "LOCK_TIMEOUT_SECONDS",
    "get_graph_access_token",
    "commit_graph_connection",
    "store_connected_tokens",
    "discard_tokens_version",
    "BoundGraphTokenProvider",
]
