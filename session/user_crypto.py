"""
사용자별 DEK·레코드 암호화 (spec/spec_멀티유저.md ②-6.2).

- 사용자마다 독립 256비트 DEK. KEK provider 로 wrap 해 `UserPaths.wrapped_dek` 에
  원자적으로 저장한다(임시파일 → fsync → `os.replace`). 최초 생성은 사용자 lock 아래에서만.
- 레코드는 AES-256-GCM, 암호화마다 새 96비트 nonce.
- AAD = 길이 구분 결합(`ms365-record`, deployment_id, user_key, app_id, kind, schema_version,
  record_version[, record_id]). 따라서 B 의 ciphertext 를 A 의 DB 로 옮기거나 이전 버전 행을
  되돌려 넣으면 복호화가 실패한다.
- 평문은 SQL 파라미터에 들어가기 전에 이 모듈에서 암호화된다. 복호화 실패 시 다른 키·사용자·
  평문 방식으로 폴백하지 않는다(`RecordDecryptError`).
"""

import json
import logging
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mcp_common.user_paths import UserPaths

from ._mu_common import atomic_write_bytes, deployment_id_for, iso, length_delimited, sha256_hex, utcnow
from .key_provider import KeyUnwrapError, get_key_provider, wrap_context

logger = logging.getLogger(__name__)

RECORD_SCHEMA_VERSION = 1
WRAPPED_DEK_FORMAT = "ms365-wrapped-dek"
DEK_VERSION = 1

# 레코드 종류 (AAD 의 kind)
KIND_GRAPH_TOKENS = "graph_tokens"
KIND_PKCE_VERIFIER = "pkce_verifier"


class RecordDecryptError(Exception):
    """레코드·DEK 를 풀 수 없다. 원인(키 불일치/위조/손상)을 구분해 노출하지 않는다."""


@dataclass(frozen=True)
class SealedRecord:
    ciphertext: bytes
    nonce: bytes
    dek_version: int


# ----------------------------------------------------------------------
# DEK
# ----------------------------------------------------------------------
_dek_cache: "OrderedDict[Tuple[str, str], bytes]" = OrderedDict()
_dek_cache_lock = threading.Lock()
_DEK_CACHE_MAX = 512


def _cache_get(key: Tuple[str, str]) -> Optional[bytes]:
    with _dek_cache_lock:
        dek = _dek_cache.get(key)
        if dek is not None:
            _dek_cache.move_to_end(key)
        return dek


def _cache_put(key: Tuple[str, str], dek: bytes) -> None:
    with _dek_cache_lock:
        _dek_cache[key] = dek
        _dek_cache.move_to_end(key)
        while len(_dek_cache) > _DEK_CACHE_MAX:
            _dek_cache.popitem(last=False)


def forget_user_keys(paths: UserPaths) -> None:
    """사용자 삭제 시 이 프로세스의 unwrap 된 DEK 캐시를 비운다."""
    prefix = str(paths.wrapped_dek)
    with _dek_cache_lock:
        for key in [k for k in _dek_cache if k[0] == prefix]:
            del _dek_cache[key]


def _read_wrapped(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _unwrap(raw: bytes, paths: UserPaths, deployment_id: str) -> bytes:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RecordDecryptError("wrapped DEK unreadable") from exc
    if (
        doc.get("format") != WRAPPED_DEK_FORMAT
        or doc.get("user_key") != paths.user_key
        or doc.get("deployment_id") != deployment_id
        or not isinstance(doc.get("kek"), dict)
    ):
        raise RecordDecryptError("wrapped DEK owner mismatch")
    try:
        dek = get_key_provider().unwrap_dek(doc["kek"], context=wrap_context(deployment_id, paths.user_key))
    except KeyUnwrapError as exc:
        raise RecordDecryptError("DEK unwrap failed") from exc
    if len(dek) != 32:
        raise RecordDecryptError("DEK length invalid")
    return dek


def load_dek(paths: UserPaths, *, root: Optional[Path] = None) -> bytes:
    """기존 DEK 를 연다. 없으면 `RecordDecryptError` — 새로 만들지 않는다."""
    raw = _read_wrapped(paths.wrapped_dek)
    if raw is None:
        raise RecordDecryptError("wrapped DEK missing")
    key = (str(paths.wrapped_dek), sha256_hex(raw))
    cached = _cache_get(key)
    if cached is not None:
        return cached
    dek = _unwrap(raw, paths, deployment_id_for(root))
    _cache_put(key, dek)
    return dek


def create_dek(paths: UserPaths, *, root: Optional[Path] = None) -> bytes:
    """DEK 를 처음 만든다. 호출자는 사용자 lock 을 잡고 있어야 한다. 이미 있으면 그것을 연다."""
    if paths.wrapped_dek.exists():
        return load_dek(paths, root=root)
    deployment_id = deployment_id_for(root)
    dek = secrets.token_bytes(32)
    record = get_key_provider().wrap_dek(dek, context=wrap_context(deployment_id, paths.user_key))
    doc = {
        "format": WRAPPED_DEK_FORMAT,
        "version": 1,
        "user_key": paths.user_key,
        "deployment_id": deployment_id,
        "dek_version": DEK_VERSION,
        "kek": record,
        "created_at": iso(utcnow()),
    }
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    atomic_write_bytes(paths.wrapped_dek, raw)
    _cache_put((str(paths.wrapped_dek), sha256_hex(raw)), dek)
    return dek


# ----------------------------------------------------------------------
# 레코드
# ----------------------------------------------------------------------
def record_aad(
    *,
    deployment_id: str,
    user_key: str,
    app_id: str,
    kind: str,
    record_version: int,
    record_id: str = "",
    schema_version: int = RECORD_SCHEMA_VERSION,
) -> bytes:
    return length_delimited(
        "ms365-record", deployment_id, user_key, app_id, kind, schema_version, record_version, record_id
    )


def seal(
    paths: UserPaths,
    payload: Dict[str, Any],
    *,
    app_id: str,
    kind: str,
    record_version: int,
    record_id: str = "",
    root: Optional[Path] = None,
) -> SealedRecord:
    dek = load_dek(paths, root=root)
    aad = record_aad(deployment_id=deployment_id_for(root), user_key=paths.user_key, app_id=app_id,
                     kind=kind, record_version=record_version, record_id=record_id)
    nonce = secrets.token_bytes(12)
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return SealedRecord(AESGCM(dek).encrypt(nonce, plaintext, aad), nonce, DEK_VERSION)


def open_sealed(
    paths: UserPaths,
    *,
    ciphertext: bytes,
    nonce: bytes,
    dek_version: int,
    app_id: str,
    kind: str,
    record_version: int,
    record_id: str = "",
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    if int(dek_version) != DEK_VERSION:
        raise RecordDecryptError("unknown DEK version")
    dek = load_dek(paths, root=root)
    aad = record_aad(deployment_id=deployment_id_for(root), user_key=paths.user_key, app_id=app_id,
                     kind=kind, record_version=record_version, record_id=record_id)
    try:
        plaintext = AESGCM(dek).decrypt(bytes(nonce), bytes(ciphertext), aad)
    except InvalidTag as exc:
        raise RecordDecryptError("record authentication failed") from exc
    try:
        value = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RecordDecryptError("record payload invalid") from exc
    if not isinstance(value, dict):
        raise RecordDecryptError("record payload invalid")
    return value


__all__ = [
    "RECORD_SCHEMA_VERSION",
    "KIND_GRAPH_TOKENS",
    "KIND_PKCE_VERIFIER",
    "RecordDecryptError",
    "SealedRecord",
    "load_dek",
    "create_dek",
    "forget_user_keys",
    "record_aad",
    "seal",
    "open_sealed",
]
