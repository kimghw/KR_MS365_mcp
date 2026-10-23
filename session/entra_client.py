"""
Microsoft Entra ID / Graph 호출 — 토큰 교환·갱신, `/me`, ID token 검증 (spec/spec_멀티유저.md ②-6.3, ②-6.4).

- 토큰 endpoint 오류는 응답 본문을 로그·예외에 싣지 않는다. OAuth `error` 식별자
  (`invalid_grant` 등, 소문자·밑줄만)만 꺼내 `EntraError.oauth_error` 로 넘긴다.
- redirect 를 따라가지 않는다(Authorization·client secret 이 다른 호스트로 새지 않게).
- ID token 은 JWKS 서명(RS256)·issuer(`<authority>/<tid>/v2.0`)·audience(client_id)·exp/iat·
  nonce(저장된 해시와 상수 시간 비교)·tenant 허용 목록을 검증한다. 이메일·`preferred_username`
  은 소유권 판단에 쓰지 않는다.

테스트는 `set_entra_http_for_tests()` / `set_jwks_client_for_tests()` 로 가짜를 주입한다
(네트워크 없음). 운영 코드는 기본 구현만 쓴다.
"""

import asyncio
import hmac
import logging
import re
import threading
import uuid
from datetime import timedelta
from typing import Any, Dict, Optional

import aiohttp
import jwt

from ._mu_common import iso, sha256_hex, utcnow
from .app_settings import AppSettings

logger = logging.getLogger(__name__)

_OAUTH_ERROR_RE = re.compile(r"^[a-z_]{1,64}$")
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)
ID_TOKEN_LEEWAY_SECONDS = 120


class EntraError(Exception):
    """Entra/Graph 호출 실패. `code` 는 내부 분류, `oauth_error` 는 검증된 OAuth 오류 식별자."""

    def __init__(self, code: str, *, oauth_error: Optional[str] = None, status: Optional[int] = None):
        super().__init__(code)
        self.code = code
        self.oauth_error = oauth_error
        self.status = status

    @property
    def is_invalid_grant(self) -> bool:
        return self.oauth_error in ("invalid_grant", "interaction_required", "consent_required")


class IdTokenError(Exception):
    """ID token 검증 실패. code ∈ {id_token_invalid, nonce_mismatch, tenant_not_allowed}."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def token_bundle(data: Dict[str, Any], *, previous_refresh_token: Optional[str] = None) -> Dict[str, Any]:
    """토큰 응답 → 저장용 묶음. 새 refresh_token 이 없으면 이전 것을 유지한다."""
    access = data.get("access_token")
    if not isinstance(access, str) or not access:
        raise EntraError("token_response_invalid")
    try:
        expires_in = int(data.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600
    refresh = data.get("refresh_token") or previous_refresh_token
    return {
        "access_token": access,
        "refresh_token": refresh if isinstance(refresh, str) and refresh else None,
        "expires_at": iso(utcnow() + timedelta(seconds=max(60, expires_in))),
        "scope": data.get("scope") if isinstance(data.get("scope"), str) else None,
    }


class EntraHttp:
    """aiohttp 기반 기본 구현. 호출마다 세션을 열고 닫는다(갱신은 드물고 이벤트 루프에 묶이지 않게)."""

    def __init__(self, settings: AppSettings):
        self.settings = settings

    def _client_auth(self) -> Dict[str, str]:
        data = {"client_id": self.settings.client_id}
        if self.settings.client_secret:
            data["client_secret"] = self.settings.client_secret
        return data

    async def _token_request(self, form: Dict[str, str]) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
                async with session.post(self.settings.token_endpoint, data=form, allow_redirects=False) as resp:
                    try:
                        body = await resp.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError):
                        body = None
                    if resp.status != 200 or not isinstance(body, dict):
                        oauth_error = body.get("error") if isinstance(body, dict) else None
                        if not (isinstance(oauth_error, str) and _OAUTH_ERROR_RE.match(oauth_error)):
                            oauth_error = None
                        raise EntraError("token_endpoint_error", oauth_error=oauth_error, status=resp.status)
                    return body
        except EntraError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise EntraError("network_error") from exc

    async def exchange_code(self, *, code: str, code_verifier: str) -> Dict[str, Any]:
        form = {
            **self._client_auth(),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.redirect_uri,
            "code_verifier": code_verifier,
            "scope": " ".join(self.settings.scopes),
        }
        return await self._token_request(form)

    async def refresh(self, *, refresh_token: str) -> Dict[str, Any]:
        form = {
            **self._client_auth(),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(self.settings.scopes),
        }
        return await self._token_request(form)

    async def get_me(self, access_token: str) -> Dict[str, Any]:
        url = f"{self.settings.graph_base_url}/me?$select=id,mail,userPrincipalName"
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
                async with session.get(url, headers=headers, allow_redirects=False) as resp:
                    if resp.status != 200:
                        raise EntraError("graph_error", status=resp.status)
                    body = await resp.json(content_type=None)
        except EntraError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise EntraError("network_error") from exc
        if not isinstance(body, dict):
            raise EntraError("graph_error")
        return body


def _norm_uuid(value: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value))).lower()
    except (ValueError, TypeError, AttributeError):
        return None


class IdTokenValidator:
    def __init__(self, settings: AppSettings, *, jwks_client: Any = None, leeway: int = ID_TOKEN_LEEWAY_SECONDS):
        self.settings = settings
        self.jwks_client = jwks_client or _default_jwks_client(settings.jwks_uri)
        self.leeway = leeway

    async def validate(self, id_token: str, *, nonce_hash: Optional[str]) -> Dict[str, Any]:
        if not isinstance(id_token, str) or not id_token or not nonce_hash:
            raise IdTokenError("id_token_invalid")
        try:
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") != "RS256":
                raise IdTokenError("id_token_invalid")
            signing_key = await asyncio.to_thread(self.jwks_client.get_signing_key_from_jwt, id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.client_id,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud", "tid", "oid", "nonce"]},
            )
        except IdTokenError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise IdTokenError("id_token_invalid") from None
        tid = _norm_uuid(claims.get("tid"))
        oid = _norm_uuid(claims.get("oid"))
        if not tid or not oid:
            raise IdTokenError("id_token_invalid")
        if claims.get("iss") != self.settings.issuer_for(str(claims.get("tid"))):
            raise IdTokenError("id_token_invalid")
        if not self.settings.tenant_allowed(tid):
            raise IdTokenError("tenant_not_allowed")
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not hmac.compare_digest(sha256_hex(nonce), nonce_hash):
            raise IdTokenError("nonce_mismatch")
        return {**claims, "tid": tid, "oid": oid}


# ----------------------------------------------------------------------
# 기본 인스턴스·테스트 주입
# ----------------------------------------------------------------------
_jwks_clients: Dict[str, Any] = {}
_jwks_lock = threading.Lock()
_http_override: Optional[Any] = None
_jwks_override: Optional[Any] = None


def _default_jwks_client(uri: str) -> Any:
    if _jwks_override is not None:
        return _jwks_override
    with _jwks_lock:
        client = _jwks_clients.get(uri)
        if client is None:
            client = jwt.PyJWKClient(uri, cache_keys=True, lifespan=3600, timeout=15)
            _jwks_clients[uri] = client
        return client


def get_entra_http(settings: AppSettings) -> Any:
    return _http_override if _http_override is not None else EntraHttp(settings)


def get_id_token_validator(settings: AppSettings, *, jwks_client: Any = None) -> IdTokenValidator:
    return IdTokenValidator(settings, jwks_client=jwks_client)


def set_entra_http_for_tests(fake: Optional[Any]) -> None:
    """**테스트 전용.** `exchange_code/refresh/get_me` 를 가진 가짜 (None 이면 해제)."""
    global _http_override
    _http_override = fake


def set_jwks_client_for_tests(fake: Optional[Any]) -> None:
    """**테스트 전용.** `get_signing_key_from_jwt(token)` 를 가진 가짜 (None 이면 해제)."""
    global _jwks_override
    _jwks_override = fake


__all__ = [
    "EntraError",
    "IdTokenError",
    "EntraHttp",
    "IdTokenValidator",
    "token_bundle",
    "get_entra_http",
    "get_id_token_validator",
    "set_entra_http_for_tests",
    "set_jwks_client_for_tests",
]
