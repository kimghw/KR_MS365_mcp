"""
멀티유저 테스트 도구 (WP0). 운영 코드는 이 모듈을 import 하지 않는다.

    from mcp_common.testing import make_principal, multi_user_mode, bound, FakeTokenProvider

    def test_x(tmp_path):
        alice = make_principal("alice@contoso.com")
        with multi_user_mode(tmp_path), bound(alice):
            ...
"""

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from mcp_common.principal import (
    DOMAINS,
    Principal,
    RequestIdentity,
    assert_user_email,
    bind_identity,
    compute_user_key,
    scope_for_domain,
)
from mcp_common.security_contracts import AccessToken, ErrorCode, SecurityError
from mcp_common.security_policy import ENV_DATA_ROOT, ENV_MULTI_USER, reset_policy_cache

ALL_SCOPES = frozenset(scope_for_domain(d) for d in DOMAINS)

#: `make_principal()` 기본 이메일 도메인(contoso.com)의 tenant. 허용 tenant 목록에 쓴다.
TEST_TENANT_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "tenant.contoso.com"))

#: mode 1 기동 검사(`validate_startup` → `session.app_settings.auth_startup_problems`)를
#: 통과시키는 테스트용 인증 계층 설정 — memory KEK + 가짜 앱 등록. 네트워크를 쓰지 않는다.
TEST_AUTH_ENV = {
    "MS365_TESTING": "1",
    "MS365_KEK_PROVIDER": "memory",
    "AZURE_CLIENT_ID": "00000000-0000-0000-0000-00000000c11e",
    "AZURE_TENANT_ID": "organizations",
    "AZURE_REDIRECT_URI": "http://localhost:5000/auth/callback",
    "MS365_ALLOWED_TENANTS": TEST_TENANT_ID,
}


def make_principal(
    email: Optional[str] = "alice@contoso.com",
    *,
    tenant_id: Optional[str] = None,
    object_id: Optional[str] = None,
    scopes: Iterable[str] = ALL_SCOPES,
    auth_epoch: int = 0,
    credential_id: str = "0" * 32,
) -> Principal:
    """이메일에서 결정적으로 tid/oid 를 만든다(같은 이메일 → 같은 사용자)."""
    seed = email or "anonymous"
    tid = tenant_id or str(uuid.uuid5(uuid.NAMESPACE_DNS, "tenant." + seed.split("@")[-1]))
    oid = object_id or str(uuid.uuid5(uuid.NAMESPACE_DNS, "user." + seed))
    return Principal(
        user_key=compute_user_key(tid, oid),
        tenant_id=tid,
        object_id=oid,
        graph_email=email,
        credential_id=credential_id,
        scopes=frozenset(scopes),
        auth_epoch=auth_epoch,
    )


def make_identity(principal: Principal, request_id: Optional[str] = None) -> RequestIdentity:
    return RequestIdentity(principal=principal, request_id=request_id or uuid.uuid4().hex)


@contextmanager
def bound(principal: Principal, request_id: Optional[str] = None) -> Iterator[RequestIdentity]:
    with bind_identity(make_identity(principal, request_id)) as identity:
        yield identity


@contextmanager
def multi_user_mode(data_root: Path, **extra_env: str) -> Iterator[Path]:
    """MS365_MULTI_USER=1 + 데이터 루트로 정책 캐시를 다시 읽고, 끝나면 원복."""
    keys = {ENV_MULTI_USER: "1", ENV_DATA_ROOT: str(Path(data_root).resolve()), **extra_env}
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    reset_policy_cache()
    try:
        yield Path(data_root).resolve()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        reset_policy_cache()


@contextmanager
def single_user_mode() -> Iterator[None]:
    saved = os.environ.pop(ENV_MULTI_USER, None)
    reset_policy_cache()
    try:
        yield
    finally:
        if saved is not None:
            os.environ[ENV_MULTI_USER] = saved
        reset_policy_cache()


class FakeTokenProvider:
    """`BoundTokenProvider` 가짜. 한 principal 에 고정되고 호출을 기록한다."""

    def __init__(self, principal: Principal, token: Optional[str] = None, *, connected: bool = True):
        self.principal = principal
        self.token = token or f"fake-token-{principal.user_key[:8]}"
        self.connected = connected
        self.calls: List[str] = []
        self.closed = False

    @property
    def user_key(self) -> str:
        return self.principal.user_key

    async def get_graph_token(self, *, minimum_ttl_seconds: int = 120) -> AccessToken:
        self.calls.append("get_graph_token")
        if not self.connected:
            raise SecurityError(ErrorCode.GRAPH_NOT_CONNECTED)
        return AccessToken(self.token, datetime.now(timezone.utc) + timedelta(hours=1), 1)

    async def validate_and_refresh_token(self, email=None, auto_reauth: bool = False):
        self.calls.append("validate_and_refresh_token")
        if email is not None:
            # 과도기 어댑터 계약: 일치 확인만, 계정 선택 없음
            with bound(self.principal):
                assert_user_email(email)
        return (await self.get_graph_token()).value

    async def close(self) -> None:
        self.closed = True


__all__ = [
    "ALL_SCOPES",
    "TEST_TENANT_ID",
    "TEST_AUTH_ENV",
    "make_principal",
    "make_identity",
    "bound",
    "multi_user_mode",
    "single_user_mode",
    "FakeTokenProvider",
]
