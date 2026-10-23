"""
KEK(Key Encryption Key) provider — 사용자별 DEK 를 wrap/unwrap 한다 (spec/spec_멀티유저.md ②-6.2, ②-12.5).

provider 는 `MS365_KEK_PROVIDER` 로 **명시 선택**한다. 미설정·알 수 없는 값이면 멀티유저
기동을 막는다(`StartupConfigError`). 다른 provider 나 평문 파일 키로 **자동 폴백하지 않는다.**

| 값 | 용도 | 필요한 설정 |
|----|------|-------------|
| `azure_keyvault` | 운영 권고. Key Vault RSA 키로 `RSA-OAEP-256` wrap | `MS365_KEK_KEY_ID`(키 식별자 URL), |
|                  |                                                   | 선택 `MS365_KEK_MI_CLIENT_ID`. azure SDK 2종 설치 필요 |
| `dpapi` | Windows 단일 호스트. 서비스 OS 계정에 바인딩된 DPAPI | Windows 전용. entropy = 배포 ID + user_key |
| `env` | **개발 전용**. AES-256-GCM key wrap | `MS365_KEK_B64` = 32바이트 난수 base64 |
| `memory` | 테스트 전용. 프로세스 수명 동안만 유효 | `MS365_TESTING=1` |

wrap 결과(dict)는 `wrapped_dek.json` 의 `kek` 필드에 그대로 저장된다. 키 원문은 어떤
provider 도 파일·DB·로그에 남기지 않는다.

Key Vault 자격증명은 **managed identity 만** 쓴다(`ManagedIdentityCredential`).
`DefaultAzureCredential` 은 이 프로젝트의 `AZURE_CLIENT_ID`/`AZURE_CLIENT_SECRET`
(Graph 앱 자격증명)을 EnvironmentCredential 로 집어 Key Vault 에 그 앱으로 접근하므로 쓰지 않는다.
"""

import hashlib
import logging
import os
import secrets
import sys
import threading
from typing import Any, Callable, Dict, Optional, Protocol, Tuple

from mcp_common.security_contracts import StartupConfigError

from ._mu_common import b64d, b64e, length_delimited

logger = logging.getLogger(__name__)

ENV_KEK_PROVIDER = "MS365_KEK_PROVIDER"
ENV_KEK_KEY_ID = "MS365_KEK_KEY_ID"
ENV_KEK_MI_CLIENT_ID = "MS365_KEK_MI_CLIENT_ID"
ENV_KEK_B64 = "MS365_KEK_B64"
ENV_TESTING = "MS365_TESTING"

PROVIDERS = ("azure_keyvault", "dpapi", "env", "memory")

_TRUE = {"1", "true", "yes", "on"}


class KeyUnwrapError(Exception):
    """DEK 를 풀 수 없다(키 불일치·손상·권한). 원인 원문은 싣지 않는다."""


class KeyProvider(Protocol):
    name: str

    def wrap_dek(self, dek: bytes, *, context: bytes) -> Dict[str, Any]: ...

    def unwrap_dek(self, record: Dict[str, Any], *, context: bytes) -> bytes: ...


def wrap_context(deployment_id: str, user_key: str) -> bytes:
    """wrap 에 묶는 문맥(AAD/entropy). 다른 배포·다른 사용자의 wrapped DEK 를 쓰지 못하게 한다."""
    return length_delimited("ms365-dek-wrap", 1, deployment_id, user_key)


def _aesgcm_wrap(kek: bytes, dek: bytes, context: bytes) -> Tuple[bytes, bytes]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(12)
    return nonce, AESGCM(kek).encrypt(nonce, dek, context)


def _aesgcm_unwrap(kek: bytes, nonce: bytes, wrapped: bytes, context: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        return AESGCM(kek).decrypt(nonce, wrapped, context)
    except InvalidTag as exc:
        raise KeyUnwrapError("DEK unwrap failed") from exc


def _fingerprint(kek: bytes) -> str:
    # KEK 불일치를 "손상"과 구분해 안내하기 위한 지문. 키를 복원할 수 없는 단방향 값.
    return hashlib.sha256(b"ms365-kek-fingerprint\x00" + kek).hexdigest()[:16]


# ----------------------------------------------------------------------
# env (개발 전용)
# ----------------------------------------------------------------------
class EnvKeyProvider:
    name = "env"

    def __init__(self, kek_b64: str):
        try:
            kek = b64d(kek_b64.strip())
        except Exception as exc:
            raise StartupConfigError(f"{ENV_KEK_B64} 가 올바른 base64 가 아닙니다.") from exc
        if len(kek) != 32:
            raise StartupConfigError(f"{ENV_KEK_B64} 는 32바이트(256비트) 난수여야 합니다.")
        self._kek = kek
        self._fp = _fingerprint(kek)
        logger.warning(
            "KEK provider 'env' 는 개발 전용입니다. 운영에서는 azure_keyvault 또는 dpapi 를 사용하세요."
        )

    def wrap_dek(self, dek: bytes, *, context: bytes) -> Dict[str, Any]:
        nonce, wrapped = _aesgcm_wrap(self._kek, dek, context)
        return {"provider": self.name, "alg": "A256GCM-KW", "kek_fp": self._fp,
                "nonce": b64e(nonce), "wrapped": b64e(wrapped)}

    def unwrap_dek(self, record: Dict[str, Any], *, context: bytes) -> bytes:
        if record.get("kek_fp") != self._fp:
            raise KeyUnwrapError("KEK fingerprint mismatch")
        return _aesgcm_unwrap(self._kek, b64d(record["nonce"]), b64d(record["wrapped"]), context)


# ----------------------------------------------------------------------
# memory (테스트 전용)
# ----------------------------------------------------------------------
class MemoryKeyProvider(EnvKeyProvider):
    """프로세스 수명 동안만 유효한 KEK. 재기동하면 이전 DEK 를 풀 수 없다(테스트 전용)."""

    name = "memory"
    _process_kek: Optional[bytes] = None
    _kek_lock = threading.Lock()

    def __init__(self):  # noqa: D401 - 부모 초기화(env 경고)를 쓰지 않는다
        with MemoryKeyProvider._kek_lock:
            if MemoryKeyProvider._process_kek is None:
                MemoryKeyProvider._process_kek = secrets.token_bytes(32)
            self._kek = MemoryKeyProvider._process_kek
        self._fp = _fingerprint(self._kek)


# ----------------------------------------------------------------------
# dpapi (Windows)
# ----------------------------------------------------------------------
class DpapiKeyProvider:
    """Windows DPAPI(CryptProtectData). 서비스가 도는 OS 계정에 바인딩된다.

    entropy 로 배포 ID·user_key 문맥을 넣어 다른 배포·사용자의 blob 을 풀지 못하게 한다.
    같은 OS 계정의 다른 프로세스는 풀 수 있다 — OS 수준 격리는 범위 밖이다(②-1.1).
    """

    name = "dpapi"
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self):
        if sys.platform != "win32":
            raise StartupConfigError("KEK provider 'dpapi' 는 Windows 에서만 사용할 수 있습니다.")
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        self._ctypes = ctypes
        self._BLOB = DATA_BLOB
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        blob_p = ctypes.POINTER(DATA_BLOB)
        self._protect = crypt32.CryptProtectData
        self._protect.argtypes = [blob_p, wintypes.LPCWSTR, blob_p, ctypes.c_void_p, ctypes.c_void_p,
                                  wintypes.DWORD, blob_p]
        self._protect.restype = wintypes.BOOL
        self._unprotect = crypt32.CryptUnprotectData
        self._unprotect.argtypes = [blob_p, ctypes.POINTER(wintypes.LPWSTR), blob_p, ctypes.c_void_p,
                                    ctypes.c_void_p, wintypes.DWORD, blob_p]
        self._unprotect.restype = wintypes.BOOL
        self._local_free = kernel32.LocalFree
        self._local_free.argtypes = [ctypes.c_void_p]
        self._local_free.restype = ctypes.c_void_p

    def _blob(self, data: bytes):
        ctypes = self._ctypes
        buf = ctypes.create_string_buffer(data, len(data))
        blob = self._BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        return blob, buf  # buf 를 함께 돌려 GC 로 해제되지 않게 한다

    def _take(self, out) -> bytes:
        ctypes = self._ctypes
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            self._local_free(ctypes.cast(out.pbData, ctypes.c_void_p))

    def wrap_dek(self, dek: bytes, *, context: bytes) -> Dict[str, Any]:
        ctypes = self._ctypes
        data_in, _b1 = self._blob(dek)
        entropy, _b2 = self._blob(context)
        out = self._BLOB()
        ok = self._protect(ctypes.byref(data_in), "ms365-dek", ctypes.byref(entropy), None, None,
                           self._CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
        if not ok:
            raise StartupConfigError("DPAPI CryptProtectData 실패")
        return {"provider": self.name, "alg": "DPAPI-USER", "blob": b64e(self._take(out))}

    def unwrap_dek(self, record: Dict[str, Any], *, context: bytes) -> bytes:
        ctypes = self._ctypes
        data_in, _b1 = self._blob(b64d(record["blob"]))
        entropy, _b2 = self._blob(context)
        out = self._BLOB()
        ok = self._unprotect(ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
                             self._CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
        if not ok:
            raise KeyUnwrapError("DPAPI unwrap failed")
        return self._take(out)


# ----------------------------------------------------------------------
# azure_keyvault (운영 권고)
# ----------------------------------------------------------------------
def _default_kv_client_factory(mi_client_id: Optional[str]) -> Callable[[str], Any]:
    try:
        from azure.identity import ManagedIdentityCredential  # type: ignore
        from azure.keyvault.keys.crypto import CryptographyClient  # type: ignore
    except ImportError as exc:
        raise StartupConfigError(
            "KEK provider 'azure_keyvault' 에는 azure-identity, azure-keyvault-keys 패키지가 필요합니다 "
            "(설치되어 있지 않음). 자동으로 다른 provider 로 대체하지 않습니다."
        ) from exc
    credential = ManagedIdentityCredential(client_id=mi_client_id) if mi_client_id else ManagedIdentityCredential()

    def factory(key_id: str) -> Any:
        return CryptographyClient(key_id, credential)

    return factory


def _rsa_oaep_256() -> Any:
    try:
        from azure.keyvault.keys.crypto import KeyWrapAlgorithm  # type: ignore

        return KeyWrapAlgorithm.rsa_oaep_256
    except ImportError:
        return "RSA-OAEP-256"


class AzureKeyVaultKeyProvider:
    """Key Vault RSA 키로 DEK 를 wrap. 저장소에는 wrapped DEK 와 **버전 포함 key id** 만 남긴다.

    RSA-OAEP 는 AAD 를 받지 않는다. 사용자·배포 바인딩은 레코드 암호화 AAD(user_crypto)가
    담당하므로 다른 사용자의 wrapped DEK 를 복사해도 그 사용자 레코드만 풀린다.
    """

    name = "azure_keyvault"

    def __init__(self, key_id: str, *, mi_client_id: Optional[str] = None,
                 client_factory: Optional[Callable[[str], Any]] = None):
        key_id = (key_id or "").strip()
        if not key_id.startswith("https://") or "/keys/" not in key_id:
            raise StartupConfigError(
                f"{ENV_KEK_KEY_ID} 는 Key Vault 키 식별자"
                "(https://<vault>.vault.azure.net/keys/<name>[/<version>])여야 합니다."
            )
        self._key_id = key_id
        self._client_factory = client_factory or _default_kv_client_factory(mi_client_id)
        self._clients: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def _client(self, key_id: str) -> Any:
        with self._lock:
            client = self._clients.get(key_id)
            if client is None:
                client = self._client_factory(key_id)
                self._clients[key_id] = client
            return client

    def wrap_dek(self, dek: bytes, *, context: bytes) -> Dict[str, Any]:
        result = self._client(self._key_id).wrap_key(_rsa_oaep_256(), dek)
        return {"provider": self.name, "alg": "RSA-OAEP-256",
                "key_id": getattr(result, "key_id", None) or self._key_id,
                "wrapped": b64e(result.encrypted_key)}

    def unwrap_dek(self, record: Dict[str, Any], *, context: bytes) -> bytes:
        key_id = record.get("key_id") or ""
        if not key_id.startswith("https://") or "/keys/" not in key_id:
            raise KeyUnwrapError("invalid key reference")
        try:
            result = self._client(key_id).unwrap_key(_rsa_oaep_256(), b64d(record["wrapped"]))
        except KeyUnwrapError:
            raise
        except Exception as exc:  # SDK 예외 원문은 싣지 않는다
            raise KeyUnwrapError("Key Vault unwrap failed") from exc
        return bytes(result.key)


# ----------------------------------------------------------------------
# 선택
# ----------------------------------------------------------------------
_cache: Dict[Tuple[str, ...], KeyProvider] = {}
_cache_lock = threading.Lock()
_override: Optional[KeyProvider] = None


def _env_signature() -> Tuple[str, ...]:
    return tuple(os.environ.get(k, "") for k in (ENV_KEK_PROVIDER, ENV_KEK_KEY_ID, ENV_KEK_MI_CLIENT_ID,
                                                  ENV_KEK_B64, ENV_TESTING))


def _build(name: str) -> KeyProvider:
    if name == "azure_keyvault":
        return AzureKeyVaultKeyProvider(os.environ.get(ENV_KEK_KEY_ID, ""),
                                        mi_client_id=os.environ.get(ENV_KEK_MI_CLIENT_ID) or None)
    if name == "dpapi":
        return DpapiKeyProvider()
    if name == "env":
        raw = os.environ.get(ENV_KEK_B64, "")
        if not raw.strip():
            raise StartupConfigError(f"KEK provider 'env' 에는 {ENV_KEK_B64} 가 필요합니다.")
        return EnvKeyProvider(raw)
    if name == "memory":
        if os.environ.get(ENV_TESTING, "").strip().lower() not in _TRUE:
            raise StartupConfigError("KEK provider 'memory' 는 테스트(MS365_TESTING=1)에서만 쓸 수 있습니다.")
        return MemoryKeyProvider()
    raise StartupConfigError(
        f"{ENV_KEK_PROVIDER} 값이 올바르지 않습니다 (허용: {', '.join(PROVIDERS)})."
    )


def get_key_provider() -> KeyProvider:
    """현재 설정의 KEK provider. 미설정이면 `StartupConfigError` — 자동 폴백 없음."""
    if _override is not None:
        return _override
    name = os.environ.get(ENV_KEK_PROVIDER, "").strip().lower()
    if not name:
        raise StartupConfigError(
            f"멀티유저 모드에는 {ENV_KEK_PROVIDER} 설정이 필요합니다 (허용: {', '.join(PROVIDERS)})."
        )
    sig = _env_signature()
    with _cache_lock:
        provider = _cache.get(sig)
        if provider is None:
            provider = _build(name)
            _cache[sig] = provider
        return provider


def set_key_provider_for_tests(provider: Optional[KeyProvider]) -> None:
    """**테스트 전용.** 가짜 provider 를 주입한다(None 이면 해제)."""
    global _override
    _override = provider


def kek_startup_problems() -> list:
    """멀티유저 기동 점검용. provider 를 만들고 wrap/unwrap 왕복을 확인한다."""
    try:
        provider = get_key_provider()
    except StartupConfigError as exc:
        return [str(exc)]
    if getattr(provider, "name", "") == "azure_keyvault":
        return []  # 네트워크 왕복은 기동 점검에서 하지 않는다(첫 사용 시 확인)
    try:
        ctx = wrap_context("startup-check", "0" * 64)
        probe = secrets.token_bytes(32)
        if provider.unwrap_dek(provider.wrap_dek(probe, context=ctx), context=ctx) != probe:
            return ["KEK provider 자체 점검(wrap/unwrap 왕복)에 실패했습니다."]
    except Exception as exc:  # noqa: BLE001 - 원인 유형만 보고
        return [f"KEK provider 자체 점검 실패: {type(exc).__name__}"]
    return []


__all__ = [
    "ENV_KEK_PROVIDER",
    "ENV_KEK_KEY_ID",
    "ENV_KEK_B64",
    "PROVIDERS",
    "KeyProvider",
    "KeyUnwrapError",
    "EnvKeyProvider",
    "MemoryKeyProvider",
    "DpapiKeyProvider",
    "AzureKeyVaultKeyProvider",
    "wrap_context",
    "get_key_provider",
    "set_key_provider_for_tests",
    "kek_startup_problems",
]
