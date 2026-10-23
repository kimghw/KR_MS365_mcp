"""
멀티유저(mode 1) Entra 앱 설정 — 환경변수에서만 읽는다 (spec/spec_멀티유저.md ②-6.1, ②-6.4).

legacy `AzureConfig` 와 달리 **어떤 DB 에도 저장하지 않는다.** 특히 client secret 은
프로세스 환경(또는 운영자가 주입한 secret 파일)에서만 읽고 SQLite·로그·응답에 남기지 않는다.

| 환경변수 | 필수 | 설명 |
|----------|------|------|
| `AZURE_CLIENT_ID` | O | Entra 앱(클라이언트) ID — `app_id` 로도 쓴다(AAD·토큰 행 키) |
| `AZURE_REDIRECT_URI` | O | 중앙 콜백 URL (예: `https://mcp.example.com/auth/callback`). http 는 loopback 만 |
| `AZURE_TENANT_ID` | - | authority tenant 구간(`organizations` 기본, UUID·`common` 가능) |
| `MS365_ALLOWED_TENANTS` | △ | 허용 tenant UUID 목록(쉼표/공백). 미설정이면 `AZURE_TENANT_ID` 가 UUID 일 때 그것 하나 |
| `AZURE_CLIENT_SECRET` / `AZURE_CLIENT_SECRET_FILE` | - | confidential client secret (없으면 PKCE public client) |
| `AZURE_SCOPES` | - | 공백 구분. `openid`·`offline_access` 는 항상 포함 |
| `MS365_PUBLIC_BASE_URL` | - | 브라우저 연결 링크의 origin. 없으면 `AZURE_REDIRECT_URI` 의 origin |
| `MS365_ENTRA_AUTHORITY_HOST` | - | 기본 `https://login.microsoftonline.com` (테스트는 loopback http 허용) |
| `MS365_GRAPH_BASE_URL` | - | 기본 `https://graph.microsoft.com/v1.0` |
"""

import ipaddress
import os
import uuid
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, Tuple
from urllib.parse import urlsplit

from mcp_common.security_contracts import StartupConfigError

DEFAULT_AUTHORITY_HOST = "https://login.microsoftonline.com"
DEFAULT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = ("https://graph.microsoft.com/.default", "offline_access", "openid")
REQUIRED_SCOPES = ("openid", "offline_access")
DEFAULT_CALLBACK_PATH = "/auth/callback"


def _is_loopback_host(host: Optional[str]) -> bool:
    if not host:
        return False
    host = host.strip("[]").lower()
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_url(name: str, value: str, *, allow_path: bool = True) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise StartupConfigError(f"{name} 는 http(s) 절대 URL 이어야 합니다.")
    if parts.scheme == "http" and not _is_loopback_host(parts.hostname):
        raise StartupConfigError(f"{name} 는 https 여야 합니다 (http 는 loopback 에서만 허용).")
    if parts.username or parts.password or parts.fragment or parts.query:
        raise StartupConfigError(f"{name} 에 사용자 정보·query·fragment 를 넣을 수 없습니다.")
    if not allow_path and parts.path not in ("", "/"):
        raise StartupConfigError(f"{name} 에는 경로를 넣을 수 없습니다(origin 만).")
    return value.rstrip("/") if not allow_path else value


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _normalize_uuid(value: str) -> Optional[str]:
    try:
        return str(uuid.UUID(value.strip())).lower()
    except (ValueError, AttributeError):
        return None


def _read_secret() -> Optional[str]:
    path = os.environ.get("AZURE_CLIENT_SECRET_FILE", "").strip()
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
        except OSError as exc:
            raise StartupConfigError("AZURE_CLIENT_SECRET_FILE 을 읽을 수 없습니다.") from exc
        return value or None
    value = os.environ.get("AZURE_CLIENT_SECRET", "").strip()
    return value or None


@dataclass(frozen=True)
class AppSettings:
    client_id: str
    tenant: str
    redirect_uri: str
    scopes: Tuple[str, ...]
    allowed_tenants: FrozenSet[str]
    public_base_url: str
    authority_host: str
    graph_base_url: str
    client_secret: Optional[str] = field(default=None, repr=False)

    @property
    def app_id(self) -> str:
        return self.client_id

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.authority_host}/{self.tenant}/oauth2/v2.0/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.authority_host}/{self.tenant}/oauth2/v2.0/token"

    @property
    def jwks_uri(self) -> str:
        return f"{self.authority_host}/{self.tenant}/discovery/v2.0/keys"

    def issuer_for(self, tenant_id: str) -> str:
        return f"{self.authority_host}/{tenant_id}/v2.0"

    @property
    def callback_path(self) -> str:
        return urlsplit(self.redirect_uri).path or DEFAULT_CALLBACK_PATH

    @property
    def uses_https(self) -> bool:
        return urlsplit(self.public_base_url).scheme == "https"

    def tenant_allowed(self, tenant_id: str) -> bool:
        norm = _normalize_uuid(tenant_id or "")
        return bool(norm) and norm in self.allowed_tenants


def allowed_tenants_from_env() -> FrozenSet[str]:
    """`MS365_ALLOWED_TENANTS` (없으면 UUID 형식의 `AZURE_TENANT_ID` 하나). 잘못된 값은 기동 오류."""
    raw = os.environ.get("MS365_ALLOWED_TENANTS", "").replace(",", " ").split()
    tenants = set()
    for item in raw:
        norm = _normalize_uuid(item)
        if not norm:
            raise StartupConfigError("MS365_ALLOWED_TENANTS 에는 tenant UUID 만 넣을 수 있습니다.")
        tenants.add(norm)
    if not tenants:
        norm = _normalize_uuid(os.environ.get("AZURE_TENANT_ID", ""))
        if norm:
            tenants.add(norm)
    return frozenset(tenants)


def load_app_settings() -> AppSettings:
    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
    if not client_id:
        raise StartupConfigError("멀티유저 모드에는 AZURE_CLIENT_ID 가 필요합니다.")
    redirect_uri = os.environ.get("AZURE_REDIRECT_URI", "").strip()
    if not redirect_uri:
        raise StartupConfigError("멀티유저 모드에는 AZURE_REDIRECT_URI (중앙 콜백 URL)가 필요합니다.")
    redirect_uri = _check_url("AZURE_REDIRECT_URI", redirect_uri)

    tenant = os.environ.get("AZURE_TENANT_ID", "").strip() or "organizations"
    if tenant not in ("organizations", "common") and not _normalize_uuid(tenant):
        raise StartupConfigError("AZURE_TENANT_ID 는 tenant UUID, organizations, common 중 하나여야 합니다.")
    tenant = _normalize_uuid(tenant) or tenant

    allowed = allowed_tenants_from_env()
    if not allowed:
        raise StartupConfigError("멀티유저 모드에는 MS365_ALLOWED_TENANTS (허용 tenant UUID 목록)가 필요합니다.")

    scopes: List[str] = (os.environ.get("AZURE_SCOPES", "").split() or list(DEFAULT_SCOPES))
    for required in REQUIRED_SCOPES:
        if required not in scopes:
            scopes.append(required)

    base = os.environ.get("MS365_PUBLIC_BASE_URL", "").strip()
    public_base = _check_url("MS365_PUBLIC_BASE_URL", base, allow_path=False) if base else _origin(redirect_uri)

    authority = os.environ.get("MS365_ENTRA_AUTHORITY_HOST", "").strip() or DEFAULT_AUTHORITY_HOST
    authority = _check_url("MS365_ENTRA_AUTHORITY_HOST", authority, allow_path=False)
    graph = os.environ.get("MS365_GRAPH_BASE_URL", "").strip() or DEFAULT_GRAPH_BASE_URL
    graph = _check_url("MS365_GRAPH_BASE_URL", graph).rstrip("/")

    return AppSettings(
        client_id=client_id,
        tenant=tenant,
        redirect_uri=redirect_uri,
        scopes=tuple(scopes),
        allowed_tenants=allowed,
        public_base_url=public_base,
        authority_host=authority,
        graph_base_url=graph,
        client_secret=_read_secret(),
    )


def auth_startup_problems() -> List[str]:
    """멀티유저 인증 계층 기동 점검 — 앱 설정 + KEK provider. mode 0 이면 빈 목록."""
    from mcp_common.security_policy import multi_user_enabled

    if not multi_user_enabled():
        return []
    from .key_provider import kek_startup_problems

    problems: List[str] = []
    try:
        load_app_settings()
    except StartupConfigError as exc:
        problems.append(str(exc))
    problems.extend(kek_startup_problems())
    return problems


__all__ = [
    "AppSettings",
    "load_app_settings",
    "allowed_tenants_from_env",
    "auth_startup_problems",
    "DEFAULT_CALLBACK_PATH",
]
