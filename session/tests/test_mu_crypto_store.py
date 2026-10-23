"""WP2 — KEK provider·사용자별 DEK·레코드 암호화: ciphertext 교차 복사(A01), 평문 canary 부재(A02)."""

import json
import logging
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError
from mcp_common.user_paths import paths_for
from session import key_provider as kp
from session._mu_common import b64e
from session.tests.mu_support import ALICE, BOB, scan_files_for, seed_connected
from session.token_store import get_graph_access_token
from session.user_crypto import KIND_GRAPH_TOKENS, RecordDecryptError, open_sealed, seal


# ----------------------------------------------------------------------
# KEK provider 선택 — 명시, 자동 폴백 없음
# ----------------------------------------------------------------------
def test_provider_unset_or_unknown_fails(monkeypatch):
    monkeypatch.delenv("MS365_KEK_PROVIDER", raising=False)
    with pytest.raises(StartupConfigError):
        kp.get_key_provider()
    monkeypatch.setenv("MS365_KEK_PROVIDER", "plaintext")
    with pytest.raises(StartupConfigError):
        kp.get_key_provider()


def test_memory_provider_requires_testing_flag(monkeypatch):
    monkeypatch.setenv("MS365_KEK_PROVIDER", "memory")
    monkeypatch.delenv("MS365_TESTING", raising=False)
    with pytest.raises(StartupConfigError):
        kp.get_key_provider()


def test_env_provider_validates_length_and_warns(monkeypatch, caplog):
    import secrets

    monkeypatch.setenv("MS365_KEK_PROVIDER", "env")
    monkeypatch.setenv("MS365_KEK_B64", b64e(b"short"))
    with pytest.raises(StartupConfigError):
        kp.get_key_provider()
    monkeypatch.setenv("MS365_KEK_B64", b64e(secrets.token_bytes(32)))
    with caplog.at_level(logging.WARNING):
        provider = kp.get_key_provider()
    assert provider.name == "env" and "개발 전용" in caplog.text
    ctx = kp.wrap_context("dep", "a" * 64)
    record = provider.wrap_dek(b"k" * 32, context=ctx)
    assert provider.unwrap_dek(record, context=ctx) == b"k" * 32
    with pytest.raises(kp.KeyUnwrapError):
        provider.unwrap_dek(record, context=kp.wrap_context("dep", "b" * 64))
    other = kp.EnvKeyProvider(b64e(secrets.token_bytes(32)))
    with pytest.raises(kp.KeyUnwrapError):
        other.unwrap_dek(record, context=ctx)


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI 는 Windows 전용")
def test_dpapi_roundtrip_bound_to_context():
    provider = kp.DpapiKeyProvider()
    ctx = kp.wrap_context("dep", "a" * 64)
    record = provider.wrap_dek(b"d" * 32, context=ctx)
    assert "d" * 32 not in json.dumps(record)
    assert provider.unwrap_dek(record, context=ctx) == b"d" * 32
    with pytest.raises(kp.KeyUnwrapError):
        provider.unwrap_dek(record, context=kp.wrap_context("other-deployment", "a" * 64))


def test_azure_keyvault_provider_with_fake_client():
    store = {}

    class FakeCrypto:
        def __init__(self, key_id):
            self.key_id = key_id

        def wrap_key(self, alg, key):
            token = f"w{len(store)}".encode()
            store[token] = key
            return SimpleNamespace(key_id=self.key_id if self.key_id.endswith("/v1") else self.key_id + "/v1",
                                   encrypted_key=token)

        def unwrap_key(self, alg, wrapped):
            return SimpleNamespace(key=store[wrapped])

    provider = kp.AzureKeyVaultKeyProvider("https://vault.vault.azure.net/keys/kek", client_factory=FakeCrypto)
    record = provider.wrap_dek(b"z" * 32, context=b"ignored")
    assert record["alg"] == "RSA-OAEP-256" and record["key_id"].endswith("/v1")
    assert provider.unwrap_dek(record, context=b"ignored") == b"z" * 32
    with pytest.raises(StartupConfigError):
        kp.AzureKeyVaultKeyProvider("not-a-url", client_factory=FakeCrypto)


def test_azure_keyvault_without_sdk_is_a_clear_startup_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("azure"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.setenv("MS365_KEK_PROVIDER", "azure_keyvault")
    monkeypatch.setenv("MS365_KEK_KEY_ID", "https://vault.vault.azure.net/keys/kek")
    with pytest.raises(StartupConfigError) as e:
        kp.get_key_provider()
    assert "azure-keyvault-keys" in str(e.value)


def test_kek_startup_problems_reports_missing_provider(monkeypatch):
    monkeypatch.delenv("MS365_KEK_PROVIDER", raising=False)
    assert kp.kek_startup_problems()


# ----------------------------------------------------------------------
# 레코드 암호화
# ----------------------------------------------------------------------
def test_wrapped_dek_file_has_no_raw_key_and_is_per_user(mu_root):
    from session.tests.mu_support import register_with_key
    from session.user_crypto import load_dek

    rec_a, _ = register_with_key(ALICE)
    rec_b, _ = register_with_key(BOB)
    pa, pb = paths_for(rec_a.user_key), paths_for(rec_b.user_key)
    doc = json.loads(pa.wrapped_dek.read_text(encoding="utf-8"))
    assert doc["user_key"] == rec_a.user_key and doc["kek"]["provider"] == "memory"
    dek_a, dek_b = load_dek(pa), load_dek(pb)
    assert dek_a != dek_b
    assert dek_a not in pa.wrapped_dek.read_bytes()


def test_aad_binds_kind_version_and_record(mu_root):
    from session.tests.mu_support import register_with_key

    rec, _ = register_with_key(ALICE)
    paths = paths_for(rec.user_key)
    sealed = seal(paths, {"v": 1}, app_id="app", kind=KIND_GRAPH_TOKENS, record_version=3)
    common = dict(ciphertext=sealed.ciphertext, nonce=sealed.nonce, dek_version=sealed.dek_version)
    assert open_sealed(paths, app_id="app", kind=KIND_GRAPH_TOKENS, record_version=3, **common) == {"v": 1}
    for change in ({"record_version": 2}, {"app_id": "other"}, {"kind": "pkce_verifier"}):
        args = dict(app_id="app", kind=KIND_GRAPH_TOKENS, record_version=3, **common)
        args.update(change)
        with pytest.raises(RecordDecryptError):
            open_sealed(paths, **args)


# ----------------------------------------------------------------------
# A01 — B 의 ciphertext 를 A 의 DB 로 복사
# ----------------------------------------------------------------------
async def _code(coro) -> str:
    with pytest.raises(SecurityError) as e:
        await coro
    return e.value.code


async def test_a01_ciphertext_swap_between_users_fails(mu_root, fake_entra):
    pa, _, _ = await seed_connected(ALICE, fake=fake_entra)
    pb, _, bundle_b = await seed_connected(BOB, fake=fake_entra)
    a_db, b_db = paths_for(pa.user_key).auth_db, paths_for(pb.user_key).auth_db

    with sqlite3.connect(b_db) as conn:
        row = conn.execute("SELECT ciphertext, nonce, token_version, dek_version FROM graph_tokens").fetchone()
    with sqlite3.connect(a_db) as conn:
        conn.execute("UPDATE graph_tokens SET ciphertext = ?, nonce = ?, token_version = ?, dek_version = ?", row)
    assert await _code(get_graph_access_token(pa)) == ErrorCode.INTERNAL_ERROR

    # wrapped DEK 까지 같이 복사해도 AAD(user_key) 가 달라 풀리지 않는다
    shutil.copyfile(paths_for(pb.user_key).wrapped_dek, paths_for(pa.user_key).wrapped_dek)
    assert await _code(get_graph_access_token(pa)) == ErrorCode.INTERNAL_ERROR
    assert fake_entra.refresh_calls == 0
    # B 는 영향 없음
    assert (await get_graph_access_token(pb)).value == bundle_b["access_token"]


async def test_a01_whole_db_copy_fails_owner_check(mu_root, fake_entra):
    pa, _, _ = await seed_connected(ALICE, fake=fake_entra)
    pb, _, _ = await seed_connected(BOB, fake=fake_entra)
    shutil.copyfile(paths_for(pb.user_key).auth_db, paths_for(pa.user_key).auth_db)
    for suffix in ("-wal", "-shm"):
        (paths_for(pa.user_key).auth_db.parent / f"auth.db{suffix}").unlink(missing_ok=True)
    # store_owner 불일치 — 키 확인 단계에서 이미 거부된다(B 의 토큰을 돌려주지 않음)
    assert await _code(get_graph_access_token(pa)) in (ErrorCode.ACCOUNT_INACTIVE, ErrorCode.INTERNAL_ERROR)
    assert fake_entra.refresh_calls == 0


# ----------------------------------------------------------------------
# A02 — 평문 토큰 canary 가 DB·WAL·로그 어디에도 없다
# ----------------------------------------------------------------------
async def test_a02_plaintext_canary_absent_from_storage_and_logs(mu_root, fake_entra, caplog):
    from datetime import timedelta

    from session import _registry_db as reg
    from session._mu_common import iso, utcnow
    from session.identity_registry import authenticate_bearer
    from session.tests.mu_support import register_with_key
    from session.token_store import store_connected_tokens

    access_canary = "CANARY-ACCESS-7f3a9c"
    refresh_canary = "CANARY-REFRESH-1b2d4e"
    fake_entra.refresh_tokens[refresh_canary] = ALICE
    record, key = register_with_key(ALICE)
    db = paths_for(record.user_key).auth_db
    holder = sqlite3.connect(db)  # 연결을 열어 둬 WAL 파일이 checkpoint 후 지워지지 않게 한다
    try:
        holder.execute("SELECT 1 FROM graph_tokens").fetchall()
        with caplog.at_level(logging.DEBUG):
            bundle = {"access_token": access_canary, "refresh_token": refresh_canary,
                      "expires_at": iso(utcnow() + timedelta(seconds=30)), "scope": "x"}
            await store_connected_tokens(record, bundle)
            reg.mark_graph_linked(record.user_key, ALICE.email, expected_epoch=0)
            principal = await authenticate_bearer(f"Bearer {key}", domain="outlook")
            token = await get_graph_access_token(principal)  # 만료 임박 → refresh 경로까지
        assert token.value != access_canary and fake_entra.refresh_calls == 1
        assert db.with_name("auth.db-wal").exists()
        secret = key.split(".")[2]
        for canary in (access_canary, refresh_canary, token.value, secret):
            assert scan_files_for(mu_root, canary.encode()) == [], canary
            assert canary not in caplog.text
    finally:
        holder.close()
