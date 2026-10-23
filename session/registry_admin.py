"""
identity registry 관리 기능 — 사용자 등록·bearer key 발급/회전/폐기·상태·연결 해제·삭제
(spec/spec_멀티유저.md ②-4.2, ②-4.3, ②-6.5). 공개 관문은 `session.identity_registry` 다.

이 함수들은 **로컬 관리 CLI(`python -m session.admin_cli`) 와 auth gateway 의 본인 연결 해제**
에서만 쓴다. 일반 MCP 도구·bearer 키에는 이 권한이 없다.

- 사용자 등록: `(tenant_id, object_id)` UUID + `MS365_ALLOWED_TENANTS` 허용 목록. 이메일로 만들지 않는다.
  같은 (tid, oid) 중복 등록 거부. 삭제 기록(tombstone)이 있으면 `reinstate=True` 일 때만 재등록.
- 키: 사용자별 활성 키 최대 2개, 기본 30일, 회전 시 이전 키는 최대 24시간 뒤 만료.
- 삭제 순서(②-6.5): deleting + epoch 증가 → (새 요청 차단) → **이 프로세스 서비스 풀의 사용자 작업
  drain**(`UserServicePool.drain()` 이 있으면; 없으면 `invalidate()`) → 사용자 lock·refresh lock 확보 →
  키 폐기·토큰·시도·DB·파일·wrapped DEK 삭제 → registry 위치 인덱스 정리 → tombstone 기록.
  drain 이 제한 시간 안에 끝나지 않으면 `deleting` 상태로 멈추고(`AdminError`) 같은 명령을 다시 실행한다.
  **다른 프로세스**의 진행 중 작업은 여기서 닿지 않는다 — 그쪽은 epoch·상태 재검사로 새 외부 호출·저장·
  응답만 막힌다(README "한계").
- 연결 해제(`disconnect_graph`)는 OAuth 확정·갱신과 **같은 `(user_key, app_id)` lock 을 epoch 를 올리기
  전에** 잡고, 그 안에서 epoch 증가 → lock 아래에서 읽은 버전에 조건부로 토큰 DELETE 를 한다(N02).
  확정(`token_store.commit_graph_connection`)도 같은 lock 안에서 epoch 재검사→저장→확정을 하므로 둘은
  어느 순서로든 직렬화되고, 결과는 (active+토큰) 또는 (pending_link+토큰 없음) 뿐이다. 갱신이 lock 을
  쥐고 있으면 해제는 그 갱신이 끝날 때까지 기다린다(최대 30초, 초과 시 `AdminBusyError`).
"""

import asyncio
import inspect
import logging
import os
import secrets
import shutil
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from mcp_common.audit import audit
from mcp_common.principal import DOMAINS, compute_user_key, scope_for_domain
from mcp_common.user_paths import ensure_user_dirs, paths_for

from . import _registry_db as reg
from ._mu_common import Tx, b64url_nopad, deployment_id_for, iso, parse_iso, utcnow
from .app_settings import allowed_tenants_from_env
from .file_lock import LockTimeout, file_lock, refresh_lock_path, user_lock_path
from .user_auth_store import StoreMissing, UserAuthStore
from .user_crypto import create_dek, forget_user_keys

logger = logging.getLogger(__name__)

MAX_ACTIVE_KEYS = 2
DRAIN_TIMEOUT_SECONDS = 30.0
DEFAULT_KEY_DAYS = 30
MAX_KEY_DAYS = 365
ROTATION_OVERLAP = timedelta(hours=24)


class AdminError(Exception):
    """관리 작업 거부 (메시지는 관리자 콘솔용 — 비밀 없음)."""


class AdminBusyError(AdminError):
    """다른 작업(토큰 갱신 등)이 lock 을 쥐고 있어 제한 시간 안에 시작하지 못했다 — 재시도 가능."""


@dataclass(frozen=True)
class IssuedKey:
    """발급 결과. `key` 는 이 객체로 **한 번만** 전달된다(저장되지 않음)."""

    kid: str
    scopes: tuple
    expires_at: str
    key: str = field(repr=False)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """사용자 lock. 다른 프로세스가 오래 쥐고 있으면(갱신 중 등) 관리자에게 재시도를 안내한다."""
    try:
        with file_lock(path):
            yield
    except LockTimeout:
        raise AdminBusyError("다른 작업(토큰 갱신 등)이 진행 중입니다. 잠시 후 다시 실행하세요.") from None


def _uuid(value: str, what: str) -> str:
    import uuid

    try:
        return str(uuid.UUID(str(value).strip())).lower()
    except (ValueError, AttributeError):
        raise AdminError(f"{what} 는 UUID 형식이어야 합니다.") from None


def _require_user(user_key: str) -> reg.UserRecord:
    record = reg.get_user(user_key)
    if record is None:
        raise AdminError("등록되지 않은 user_key 입니다.")
    return record


# ----------------------------------------------------------------------
# 사용자
# ----------------------------------------------------------------------
def register_user(tenant_id: str, object_id: str, *, reinstate: bool = False) -> reg.UserRecord:
    """`pending_link` 사용자를 만든다. 저장소(auth.db·wrapped DEK·디렉터리)도 이때 만든다."""
    tid = _uuid(tenant_id, "tenant_id")
    oid = _uuid(object_id, "object_id")
    if tid not in allowed_tenants_from_env():
        raise AdminError("허용되지 않은 tenant 입니다 (MS365_ALLOWED_TENANTS).")
    user_key = compute_user_key(tid, oid)

    reg.ensure_registry()
    with reg.registry() as conn:
        if conn.execute("SELECT 1 FROM users WHERE user_key = ? OR (tenant_id = ? AND object_id = ?)",
                        (user_key, tid, oid)).fetchone():
            raise AdminError("이미 등록된 사용자입니다.")
        tombstoned = conn.execute("SELECT 1 FROM tombstones WHERE user_key = ?", (user_key,)).fetchone()
        if tombstoned and not reinstate:
            raise AdminError("삭제된 사용자입니다. 다시 등록하려면 reinstate 를 명시하세요.")

    paths = ensure_user_dirs(paths_for(user_key))
    UserAuthStore(user_key, tid, oid).initialize()
    with _locked(user_lock_path(user_key)):
        create_dek(paths)

    now = iso(utcnow())
    with reg.registry(create=True) as conn, Tx(conn):
        if conn.execute("SELECT 1 FROM users WHERE user_key = ? OR (tenant_id = ? AND object_id = ?)",
                        (user_key, tid, oid)).fetchone():
            raise AdminError("이미 등록된 사용자입니다.")
        # reinstate 는 이전 수명의 마지막 epoch 다음부터 — 풀 캐시 키가 이전 수명과 겹치지 않게
        tomb = conn.execute("SELECT last_auth_epoch FROM tombstones WHERE user_key = ?", (user_key,)).fetchone()
        epoch = int(tomb["last_auth_epoch"]) + 1 if tomb else 0
        conn.execute(
            "INSERT INTO users (user_key, tenant_id, object_id, status, auth_epoch, graph_email, created_at,"
            " updated_at)"
            " VALUES (?, ?, ?, 'pending_link', ?, NULL, ?, ?)",
            (user_key, tid, oid, epoch, now, now),
        )
        conn.execute("DELETE FROM tombstones WHERE user_key = ?", (user_key,))
    audit("user.register", outcome="success", user_key=user_key)
    return _require_user(user_key)


def list_users() -> List[Dict[str, Any]]:
    """관리자용 목록. graph_email 은 호출자(CLI)가 표시 여부를 정한다."""
    out = []
    for record in reg.all_users():
        try:
            creds = record.store().list_credentials()
            active_keys = sum(1 for c in creds if _live(c))
        except StoreMissing:
            active_keys = 0
        out.append({
            "user_key": record.user_key,
            "tenant_id": record.tenant_id,
            "object_id": record.object_id,
            "status": record.status,
            "auth_epoch": record.auth_epoch,
            "graph_connected": record.status == "active",
            "graph_email": record.graph_email,
            "active_keys": active_keys,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        })
    return out


def set_status(user_key: str, status: str) -> reg.UserRecord:
    """관리자 상태 변경. `disabled`(epoch 증가) / `active`·`enable`(연결 여부에 따라 active·pending_link)."""
    record = _require_user(user_key)
    if status == "disabled":
        reg.bump_epoch(user_key, set_status="disabled", only_from=("pending_link", "active"))
        audit("user.disable", outcome="success", user_key=user_key)
    elif status in ("active", "enable", "pending_link"):
        if record.status != "disabled":
            raise AdminError("비활성(disabled) 사용자만 다시 활성화할 수 있습니다.")
        target = "active" if record.graph_email else "pending_link"
        if status == "active" and target != "active":
            raise AdminError("Graph 연결이 없는 사용자는 pending_link 로만 활성화됩니다.")
        reg.bump_epoch(user_key, set_status=target, only_from=("disabled",))
        audit("admin.config", outcome="success", user_key=user_key)
    else:
        raise AdminError("허용되지 않은 상태 변경입니다 (disabled | enable).")
    return _require_user(user_key)


def bump_auth_epoch(user_key: str) -> int:
    """auth_epoch 만 올린다 — 모든 프로세스의 캐시된 서비스·principal 을 무효화."""
    try:
        epoch = reg.bump_epoch(user_key)
    except LookupError:
        raise AdminError("대상 사용자가 없거나 상태가 맞지 않습니다.") from None
    audit("admin.config", outcome="success", user_key=user_key)
    return epoch


def _app_ids_for(record: reg.UserRecord) -> List[str]:
    """토큰 행이 있는 app_id + 현재 앱(AZURE_CLIENT_ID). lock·삭제 대상."""
    try:
        app_ids = record.store().token_app_ids()
    except StoreMissing:
        app_ids = []
    env_app = os.environ.get("AZURE_CLIENT_ID", "").strip()
    if env_app and env_app not in app_ids:
        app_ids.append(env_app)
    return sorted(app_ids)


def disconnect_graph(user_key: str) -> None:
    """Graph 연결 해제 (N02): `(user_key, app_id)` lock 안에서 epoch 증가 → 버전 조건부 토큰 삭제.

    lock 을 **epoch 를 올리기 전에** 잡는다 — 올린 뒤 새 epoch 로 확정된 연결(`commit_graph_connection`,
    같은 lock)이 끼어들어 그 토큰을 지우는 일이 없다. 순서는 epoch 먼저다: 중간에 죽어도
    (pending_link + 토큰) 이지 (active + 토큰 없음) 은 아니다. DELETE 는 lock 아래에서 읽은 버전에만 적용한다.
    """
    record = _require_user(user_key)
    app_ids = _app_ids_for(record)
    with ExitStack() as locks:
        for app_id in app_ids:
            locks.enter_context(_locked(refresh_lock_path(user_key, app_id)))
        try:
            store: Optional[UserAuthStore] = record.store()
            versions = {app_id: store.token_version(app_id) for app_id in app_ids}
        except StoreMissing:
            store, versions = None, {}
        try:
            reg.mark_graph_unlinked(user_key)
        except LookupError:
            raise AdminError("연결을 해제할 수 없는 상태입니다.") from None
        if store is not None:
            for app_id, version in versions.items():
                if version and not store.delete_tokens_if_version(app_id, version):
                    # lock 아래에서는 일어날 수 없다 — lock 을 우회한 쓰기가 있다는 뜻이므로 기록만 남긴다
                    logger.error("disconnect: token row changed under lock (user_key=%s)", user_key[:12])
            for attempt in store.active_attempts():
                store.fail_attempt(attempt["attempt_id"], "disconnected")
                reg.drop_attempt_indexes(user_key, attempt["attempt_id"])
    audit("graph.disconnect", outcome="success", user_key=user_key)


# ----------------------------------------------------------------------
# 키
# ----------------------------------------------------------------------
def _live(cred: Dict[str, Any]) -> bool:
    expires = parse_iso(cred.get("expires_at"))
    return not cred.get("revoked_at") and bool(expires and expires > utcnow())


def _scopes_for(domains: Optional[Iterable[str]]) -> List[str]:
    chosen = list(domains) if domains else list(DOMAINS)
    if not chosen:
        raise AdminError("도메인을 하나 이상 지정하세요.")
    unknown = [d for d in chosen if d not in DOMAINS]
    if unknown:
        raise AdminError(f"알 수 없는 도메인: {', '.join(unknown)} (허용: {', '.join(DOMAINS)})")
    return sorted({scope_for_domain(d) for d in chosen})


def _issue_locked(record: reg.UserRecord, scopes: List[str], days: int) -> IssuedKey:
    store = record.store()
    active = [c for c in store.list_credentials() if _live(c)]
    if len(active) >= MAX_ACTIVE_KEYS:
        raise AdminError(f"활성 키는 사용자당 최대 {MAX_ACTIVE_KEYS}개입니다. 기존 키를 폐기하세요.")
    kid = secrets.token_hex(16)
    secret = b64url_nopad(secrets.token_bytes(32))
    expires_at = iso(utcnow() + timedelta(days=days))
    store.add_credential(kid, reg.key_digest(deployment_id_for(), kid, secret), scopes, expires_at)
    with reg.registry(create=True) as conn, Tx(conn):
        conn.execute("INSERT INTO credential_index (kid, user_key, created_at) VALUES (?, ?, ?)",
                     (kid, record.user_key, iso(utcnow())))
    return IssuedKey(kid=kid, scopes=tuple(scopes), expires_at=expires_at, key=f"m365v1.{kid}.{secret}")


def issue_key(user_key: str, domains: Optional[Iterable[str]] = None, days: int = DEFAULT_KEY_DAYS) -> IssuedKey:
    """bearer key 발급. 원문은 반환값으로 1회만 전달된다."""
    if not isinstance(days, int) or not (1 <= days <= MAX_KEY_DAYS):
        raise AdminError(f"유효기간은 1~{MAX_KEY_DAYS}일이어야 합니다.")
    record = _require_user(user_key)
    if not record.usable:
        raise AdminError("활성 상태(pending_link/active)의 사용자에게만 키를 발급할 수 있습니다.")
    scopes = _scopes_for(domains)
    with _locked(user_lock_path(user_key)):
        issued = _issue_locked(record, scopes, days)
    audit("key.issue", outcome="success", user_key=user_key, credential_id=issued.kid)
    return issued


def rotate_key(kid: str, days: int = DEFAULT_KEY_DAYS) -> IssuedKey:
    """같은 scope 로 새 키를 발급하고 기존 키 만료를 최대 24시간 뒤로 당긴다."""
    user_key = reg.user_for_kid(kid)
    if user_key is None:
        raise AdminError("알 수 없는 kid 입니다.")
    record = _require_user(user_key)
    if not record.usable:
        raise AdminError("활성 상태의 사용자만 키를 회전할 수 있습니다.")
    store = record.store()
    with _locked(user_lock_path(user_key)):
        old = store.get_credential(kid)
        if not old or not _live(old):
            raise AdminError("이미 폐기되었거나 만료된 키입니다.")
        issued = _issue_locked(record, sorted(old["scopes"]), days)
        store.shorten_credential(kid, iso(utcnow() + ROTATION_OVERLAP))
    audit("key.rotate", outcome="success", user_key=user_key, credential_id=issued.kid)
    return issued


def revoke_key(kid: str) -> bool:
    user_key = reg.user_for_kid(kid)
    if user_key is None:
        raise AdminError("알 수 없는 kid 입니다.")
    record = _require_user(user_key)
    try:
        changed = record.store().revoke_credential(kid)
    except StoreMissing:
        changed = False
    audit("key.revoke", outcome="success" if changed else "failure", user_key=user_key, credential_id=kid)
    return changed


def list_keys(user_key: str) -> List[Dict[str, Any]]:
    record = _require_user(user_key)
    return [
        {"kid": c["kid"], "scopes": sorted(c["scopes"]), "expires_at": c["expires_at"],
         "revoked_at": c["revoked_at"], "created_at": c["created_at"], "live": _live(c)}
        for c in record.store().list_credentials()
    ]


# ----------------------------------------------------------------------
# 삭제
# ----------------------------------------------------------------------
def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def _rmtree(path: Path) -> None:
    def on_exc(func, target, _exc):
        # 읽기 전용 파일(Windows) 한 번 재시도. 그래도 실패하면 예외가 올라간다.
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if not path.exists():
        return
    if _is_link(path):
        raise AdminError("사용자 디렉터리가 링크/junction 입니다. 수동 확인이 필요합니다.")
    shutil.rmtree(path, onexc=on_exc)


def _run_maybe_async(call):
    """동기 관리 경로에서 풀의 (대개 async) 메서드를 실행한다. 루프 스레드 위면 별도 스레드의 루프에서."""
    result = call()
    if not inspect.isawaitable(result):
        return result

    async def _await():
        return await result

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await())
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, _await()).result()


def _drain_user_services(user_key: str, timeout: float) -> None:
    """이 프로세스 서비스 풀의 사용자 작업을 끝내고 기다린다 (R04). `drain()` 이 없으면 `invalidate()`.

    실패·시간 초과는 `AdminError` — 삭제를 진행하지 않는다(상태는 이미 `deleting`, 재실행으로 이어간다).
    """
    try:
        from mcp_common.service_pool import get_service_pool
    except ImportError:  # session 만 떼어 쓰는 경우
        return
    pool = get_service_pool()
    drain = getattr(pool, "drain", None)
    if drain is not None:
        call = lambda: drain(user_key, timeout=timeout)  # noqa: E731
    elif getattr(pool, "invalidate", None) is not None:
        call = lambda: pool.invalidate(user_key)  # noqa: E731
    else:
        return
    try:
        result = _run_maybe_async(call)
    except Exception as exc:  # noqa: BLE001 - 원인 유형만 관리자에게
        raise AdminError(
            f"진행 중인 사용자 작업 종료 대기에 실패했습니다({type(exc).__name__}). 잠시 후 다시 실행하세요."
        ) from None
    if result is False:
        raise AdminError("진행 중인 사용자 작업이 제한 시간 안에 끝나지 않았습니다. 잠시 후 다시 실행하세요.")


def delete_user(user_key: str, *, drain_timeout: float = DRAIN_TIMEOUT_SECONDS) -> None:
    """계정 삭제(②-6.5). 실패하면 `deleting` 상태로 남으므로 같은 명령을 다시 실행하면 이어서 진행한다."""
    record = _require_user(user_key)
    if record.status != "deleting":
        reg.bump_epoch(user_key, set_status="deleting", only_from=("pending_link", "active", "disabled"))
    _drain_user_services(user_key, drain_timeout)  # 새 요청은 위 상태·epoch 변경으로 이미 막혔다
    paths = paths_for(user_key)
    store = record.store()
    app_ids = _app_ids_for(record)

    with ExitStack() as locks:
        locks.enter_context(_locked(user_lock_path(user_key)))
        for app_id in app_ids:
            locks.enter_context(_locked(refresh_lock_path(user_key, app_id)))
        try:
            store.revoke_all_credentials()
            store.delete_tokens()
            store.delete_all_attempts()
        except StoreMissing:
            pass
        forget_user_keys(paths)
        try:
            _rmtree(paths.root)
        except OSError as exc:
            audit("user.delete", outcome="failure", user_key=user_key, error_code="delete_incomplete")
            raise AdminError(f"사용자 파일 삭제가 끝나지 않았습니다({type(exc).__name__}). 다시 실행하세요.") from None

    with reg.registry(create=True) as conn, Tx(conn):
        conn.execute("DELETE FROM credential_index WHERE user_key = ?", (user_key,))
        conn.execute("DELETE FROM oauth_state_index WHERE user_key = ?", (user_key,))
        conn.execute("DELETE FROM oauth_ticket_index WHERE user_key = ?", (user_key,))
        row = conn.execute("SELECT auth_epoch FROM users WHERE user_key = ?", (user_key,)).fetchone()
        last_epoch = int(row["auth_epoch"]) if row else record.auth_epoch
        conn.execute(
            "INSERT OR REPLACE INTO tombstones (user_key, tenant_id, object_id, deleted_at, last_auth_epoch)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_key, record.tenant_id, record.object_id, iso(utcnow()), last_epoch),
        )
        conn.execute("DELETE FROM users WHERE user_key = ?", (user_key,))
    audit("user.delete", outcome="success", user_key=user_key)


__all__ = [
    "MAX_ACTIVE_KEYS",
    "DEFAULT_KEY_DAYS",
    "DRAIN_TIMEOUT_SECONDS",
    "AdminError",
    "AdminBusyError",
    "IssuedKey",
    "register_user",
    "list_users",
    "set_status",
    "bump_auth_epoch",
    "disconnect_graph",
    "issue_key",
    "rotate_key",
    "revoke_key",
    "list_keys",
    "delete_user",
]
