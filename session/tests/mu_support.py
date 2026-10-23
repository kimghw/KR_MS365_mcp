"""멀티유저 인증(WP2) 테스트 지원 — 가짜 Entra(IdP·토큰 endpoint·Graph /me)·JWKS·사용자 준비.

네트워크를 쓰지 않는다. `FakeEntra` 는 실제 Entra 처럼 authorization code 를 PKCE challenge·nonce·
로그인 계정에 묶고, 토큰 교환 시 `S256(code_verifier) == challenge` 를 검사한다.
"""

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

TENANT = "11111111-2222-3333-4444-555555555555"
OTHER_TENANT = "99999999-8888-7777-6666-555555555555"
OID_A = "aaaaaaaa-0000-4000-8000-00000000000a"
OID_B = "bbbbbbbb-0000-4000-8000-00000000000b"
CLIENT_ID = "c1c1c1c1-0000-4000-8000-0000000000c1"
REDIRECT_URI = "http://localhost:5000/auth/callback"
AUTHORITY = "https://login.microsoftonline.com"

#: 테스트 기본 환경 (memory KEK, 허용 tenant 1개)
BASE_ENV = {
    "MS365_TESTING": "1",
    "MS365_KEK_PROVIDER": "memory",
    "AZURE_CLIENT_ID": CLIENT_ID,
    "AZURE_TENANT_ID": TENANT,
    "AZURE_REDIRECT_URI": REDIRECT_URI,
    "MS365_ALLOWED_TENANTS": TENANT,
}
CLEARED_ENV = (
    "AZURE_CLIENT_SECRET", "AZURE_CLIENT_SECRET_FILE", "AZURE_SCOPES", "AZURE_AUTHORITY", "MS365_PUBLIC_BASE_URL",
    "MS365_ENTRA_AUTHORITY_HOST", "MS365_GRAPH_BASE_URL", "MS365_KEK_B64", "MS365_KEK_KEY_ID",
    "MS365_DEFAULT_USER_EMAIL", "MCP_ALLOWED_PATHS", "MCP_DATA_DIR", "DB_PATH",
)


@dataclass(frozen=True)
class Account:
    tenant_id: str
    object_id: str
    email: str


ALICE = Account(TENANT, OID_A, "alice@contoso.com")
BOB = Account(TENANT, OID_B, "bob@contoso.com")


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


class FakeJWKS:
    def __init__(self, jwk: Dict[str, Any]):
        self.jwk = jwk

    def get_signing_key_from_jwt(self, token: str):
        header = jwt.get_unverified_header(token)
        if header.get("kid") != self.jwk["kid"]:
            raise jwt.PyJWKClientError("unknown kid")
        return jwt.PyJWK(self.jwk)


class FakeEntra:
    """IdP + token endpoint + Graph `/me` 가짜 (EntraHttp 와 같은 async 메서드)."""

    def __init__(self, *, client_id: str = CLIENT_ID, authority: str = AUTHORITY):
        self.client_id = client_id
        self.authority = authority
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = RSAAlgorithm.to_jwk(self._key.public_key(), as_dict=True)
        jwk.update({"kid": "fake-kid-1", "alg": "RS256", "use": "sig"})
        self.jwks = FakeJWKS(jwk)
        self.codes: Dict[str, Dict[str, Any]] = {}
        self.access: Dict[str, Account] = {}
        self.refresh_tokens: Dict[str, Account] = {}
        self.exchange_calls = 0
        self.refresh_calls = 0
        self.me_calls = 0
        self.id_token_overrides: Dict[str, Any] = {}
        self.me_id_override: Optional[str] = None
        self.on_refresh = None  # async callable(refresh_token) — 갱신 도중 끼어들기
        self.refresh_error: Optional[str] = None
        self.rotate_refresh = True

    # --- 브라우저가 authorize 에서 계정 X 로 로그인한 결과 code -------------------------
    def login(self, authorize_url: str, account: Account) -> Tuple[str, str]:
        """authorize URL 을 받아 (code, state) 를 돌려준다."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        assert q["code_challenge_method"] == "S256" and q["client_id"] == self.client_id
        code = "code-" + secrets.token_urlsafe(24)
        self.codes[code] = {"account": account, "nonce": q["nonce"], "challenge": q["code_challenge"], "used": False}
        return code, q["state"]

    def id_token(self, account: Account, nonce: str, overrides: Optional[Dict[str, Any]] = None) -> str:
        now = int(time.time())
        claims = {
            "iss": f"{self.authority}/{account.tenant_id}/v2.0",
            "aud": self.client_id,
            "iat": now,
            "nbf": now,
            "exp": now + 3600,
            "tid": account.tenant_id,
            "oid": account.object_id,
            "nonce": nonce,
            "preferred_username": account.email,
            "ver": "2.0",
        }
        claims.update(overrides or {})
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self.jwks.jwk["kid"]})

    def _issue(self, account: Account) -> Dict[str, Any]:
        n = secrets.token_hex(6)
        at = f"at-{account.object_id[:8]}-{n}"
        rt = f"rt-{account.object_id[:8]}-{n}"
        self.access[at] = account
        self.refresh_tokens[rt] = account
        return {"access_token": at, "refresh_token": rt, "expires_in": 3600, "token_type": "Bearer",
                "scope": "https://graph.microsoft.com/.default"}

    async def exchange_code(self, *, code: str, code_verifier: str) -> Dict[str, Any]:
        from session.entra_client import EntraError

        self.exchange_calls += 1
        entry = self.codes.get(code)
        if entry is None or entry["used"] or s256(code_verifier) != entry["challenge"]:
            raise EntraError("token_endpoint_error", oauth_error="invalid_grant", status=400)
        entry["used"] = True
        data = self._issue(entry["account"])
        data["id_token"] = self.id_token(entry["account"], entry["nonce"], self.id_token_overrides)
        return data

    async def refresh(self, *, refresh_token: str) -> Dict[str, Any]:
        from session.entra_client import EntraError

        self.refresh_calls += 1
        if self.on_refresh is not None:
            await self.on_refresh(refresh_token)
        if self.refresh_error:
            raise EntraError("token_endpoint_error", oauth_error=self.refresh_error, status=400)
        account = self.refresh_tokens.get(refresh_token)
        if account is None:
            raise EntraError("token_endpoint_error", oauth_error="invalid_grant", status=400)
        data = self._issue(account)
        if not self.rotate_refresh:
            data.pop("refresh_token")
        return data

    async def get_me(self, access_token: str) -> Dict[str, Any]:
        from session.entra_client import EntraError

        self.me_calls += 1
        account = self.access.get(access_token)
        if account is None:
            raise EntraError("graph_error", status=401)
        return {"id": self.me_id_override or account.object_id, "mail": account.email,
                "userPrincipalName": account.email}


# ----------------------------------------------------------------------
# 사용자 준비
# ----------------------------------------------------------------------
def register_with_key(account: Account, *, domains=None, days: int = 30):
    """등록 + 키 발급. (UserRecord, raw_key) 반환."""
    from session import identity_registry as ir

    record = ir.register_user(account.tenant_id, account.object_id)
    issued = ir.issue_key(record.user_key, domains, days=days)
    return record, issued.key


async def seed_connected(account: Account, *, access: Optional[str] = None, refresh: Optional[str] = None,
                         expires_in: int = 3600, fake: Optional[FakeEntra] = None, domains=None):
    """OAuth 없이 '연결 완료' 상태를 만든다. (principal, raw_key, bundle) 반환."""
    from datetime import timedelta

    from session import _registry_db as reg
    from session._mu_common import iso, utcnow
    from session.identity_registry import authenticate_bearer
    from session.token_store import store_connected_tokens

    record, key = register_with_key(account, domains=domains)
    access = access or f"at-{account.object_id[:8]}-seed"
    refresh = refresh or f"rt-{account.object_id[:8]}-seed"
    if fake is not None:
        fake.access[access] = account
        fake.refresh_tokens[refresh] = account
    bundle = {"access_token": access, "refresh_token": refresh,
              "expires_at": iso(utcnow() + timedelta(seconds=expires_in)), "scope": "x"}
    await store_connected_tokens(record, bundle)
    reg.mark_graph_linked(record.user_key, account.email, expected_epoch=record.auth_epoch)
    principal = await authenticate_bearer(f"Bearer {key}", domain="outlook")
    return principal, key, bundle


def scan_files_for(root, needle: bytes):
    """root 아래 모든 파일(DB·WAL·SHM·JSON·로그)에서 needle 을 찾는다. 발견된 경로 목록."""
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                with open(path, "rb") as fh:
                    if needle in fh.read():
                        hits.append(path)
            except OSError:
                pass
    return hits
