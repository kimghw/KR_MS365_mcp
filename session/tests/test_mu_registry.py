"""WP2 — identity registry: bearer key 형식·digest·만료/폐기/scope(I07), 등록·상태·삭제, 관리 CLI."""

import io
import json
import re
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta

import pytest

from mcp_common.principal import compute_user_key
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.user_paths import paths_for, system_paths
from session import _registry_db as reg
from session import identity_registry as ir
from session._mu_common import deployment_id_for, iso, utcnow
from session.tests.mu_support import ALICE, BOB, OTHER_TENANT, TENANT, register_with_key


async def _code(coro) -> str:
    with pytest.raises(SecurityError) as e:
        await coro
    return e.value.code


# ----------------------------------------------------------------------
# key 형식·digest
# ----------------------------------------------------------------------
def test_issued_key_format_and_digest_storage(mu_root):
    record, key = register_with_key(ALICE)
    match = re.match(r"^m365v1\.([0-9a-f]{32})\.([A-Za-z0-9_-]{43})$", key)
    assert match, "m365v1.<128bit hex kid>.<256bit base64url secret>"
    kid, secret = match.groups()
    cred = record.store().get_credential(kid)
    assert cred["digest"] == reg.key_digest(deployment_id_for(), kid, secret)
    # 원문 secret 은 어디에도 저장되지 않는다
    for path in (record.store().paths.auth_db, system_paths().registry_db):
        assert secret.encode() not in path.read_bytes()
    # registry 에는 kid → user_key 위치만
    assert reg.user_for_kid(kid) == record.user_key


def test_digest_is_length_delimited():
    assert reg.key_digest("dep", "ab", "c") != reg.key_digest("dep", "a", "bc")
    assert reg.key_digest("dep1", "k", "s") != reg.key_digest("dep2", "k", "s")


def test_issued_key_repr_hides_raw_key(mu_root):
    record, _ = register_with_key(ALICE)
    issued = ir.issue_key(record.user_key, ["outlook"])
    assert issued.key not in repr(issued)


def test_at_most_two_active_keys(mu_root):
    record, _ = register_with_key(ALICE)
    second = ir.issue_key(record.user_key)
    with pytest.raises(ir.AdminError):
        ir.issue_key(record.user_key)
    ir.revoke_key(second.kid)
    ir.issue_key(record.user_key)  # 폐기하면 자리가 난다


def test_rotate_shortens_old_key(mu_root):
    record, key = register_with_key(ALICE)
    kid = key.split(".")[1]
    new = ir.rotate_key(kid)
    old = record.store().get_credential(kid)
    from session._mu_common import parse_iso

    assert parse_iso(old["expires_at"]) <= utcnow() + timedelta(hours=24, seconds=5)
    assert new.kid != kid and set(new.scopes) == set(old["scopes"])


def test_issue_rejects_unknown_domain_and_bad_days(mu_root):
    record, _ = register_with_key(ALICE)
    ir.revoke_key(ir.list_keys(record.user_key)[0]["kid"])
    with pytest.raises(ir.AdminError):
        ir.issue_key(record.user_key, ["admin"])
    with pytest.raises(ir.AdminError):
        ir.issue_key(record.user_key, days=0)


# ----------------------------------------------------------------------
# I07 — 만료·폐기·scope 부족·미지 키
# ----------------------------------------------------------------------
async def test_valid_key_returns_principal(mu_root):
    record, key = register_with_key(ALICE, domains=["outlook", "calendar"])
    p = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    assert p.user_key == record.user_key == compute_user_key(TENANT, ALICE.object_id)
    assert p.credential_id == key.split(".")[1]
    assert p.scopes == frozenset({"mcp:outlook", "mcp:calendar"})
    assert p.graph_email is None  # 아직 pending_link
    assert p.auth_epoch == 0
    # scheme 대소문자 무관, domain=None(gateway) 은 scope 검사 생략
    assert (await ir.authenticate_bearer(f"bearer {key}", domain=None)).user_key == record.user_key


@pytest.mark.parametrize("header", [
    None, "", "Bearer", "Basic abc", "Bearer m365v1.xyz.abc",
    "Bearer m365v1." + "0" * 32 + "." + "A" * 43,                # 형식은 맞지만 미지 kid
    "Bearer  m365v1." + "0" * 32 + "." + "A" * 43,               # 공백 2개
])
async def test_malformed_or_unknown_keys_are_unauthenticated(mu_root, header):
    register_with_key(ALICE)
    assert await _code(ir.authenticate_bearer(header, domain="outlook")) == ErrorCode.UNAUTHENTICATED


async def test_wrong_secret_is_unauthenticated(mu_root):
    _, key = register_with_key(ALICE)
    prefix, kid, secret = key.split(".")
    forged = f"{prefix}.{kid}.{'B' * 43}"
    assert await _code(ir.authenticate_bearer(f"Bearer {forged}", domain="outlook")) == ErrorCode.UNAUTHENTICATED


async def test_expired_key_is_unauthenticated(mu_root):
    record, key = register_with_key(ALICE)
    kid = key.split(".")[1]
    with sqlite3.connect(record.store().paths.auth_db) as conn:
        past = iso(utcnow() - timedelta(seconds=1))
        conn.execute("UPDATE api_credentials SET expires_at = ? WHERE kid = ?", (past, kid))
    assert await _code(ir.authenticate_bearer(f"Bearer {key}", domain="outlook")) == ErrorCode.UNAUTHENTICATED


async def test_revoked_key_is_unauthenticated_and_active_check_fails(mu_root):
    _, key = register_with_key(ALICE)
    p = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    await ir.assert_active(p)
    assert ir.revoke_key(p.credential_id) is True
    assert await _code(ir.authenticate_bearer(f"Bearer {key}", domain="outlook")) == ErrorCode.UNAUTHENTICATED
    assert await _code(ir.assert_active(p)) == ErrorCode.ACCOUNT_INACTIVE


async def test_wrong_scope_is_forbidden(mu_root):
    _, key = register_with_key(ALICE, domains=["calendar"])
    assert await _code(ir.authenticate_bearer(f"Bearer {key}", domain="outlook")) == ErrorCode.FORBIDDEN_SCOPE
    assert SecurityError(ErrorCode.FORBIDDEN_SCOPE).http_status == 403


async def test_disabled_account_is_inactive_and_epoch_change_invalidates(mu_root):
    record, key = register_with_key(ALICE)
    p = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    ir.set_status(record.user_key, "disabled")
    assert await _code(ir.authenticate_bearer(f"Bearer {key}", domain="outlook")) == ErrorCode.ACCOUNT_INACTIVE
    assert await _code(ir.assert_active(p)) == ErrorCode.ACCOUNT_INACTIVE
    ir.set_status(record.user_key, "enable")
    p2 = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    await ir.assert_active(p2)
    assert await _code(ir.assert_active(p)) == ErrorCode.ACCOUNT_INACTIVE  # 이전 epoch principal
    ir.bump_auth_epoch(record.user_key)
    assert await _code(ir.assert_active(p2)) == ErrorCode.ACCOUNT_INACTIVE


async def test_key_of_a_cannot_authenticate_as_b(mu_root):
    rec_a, key_a = register_with_key(ALICE)
    rec_b, _ = register_with_key(BOB)
    p = await ir.authenticate_bearer(f"Bearer {key_a}", domain="outlook")
    assert p.user_key == rec_a.user_key != rec_b.user_key
    # A 의 kid 를 B 의 credential 로 위조해 registry 에 넣어도 B 의 DB 에는 그 digest 가 없다
    with sqlite3.connect(system_paths().registry_db) as conn:
        conn.execute("UPDATE credential_index SET user_key = ? WHERE kid = ?", (rec_b.user_key, p.credential_id))
    assert await _code(ir.authenticate_bearer(f"Bearer {key_a}", domain="outlook")) == ErrorCode.UNAUTHENTICATED


# ----------------------------------------------------------------------
# 등록·삭제
# ----------------------------------------------------------------------
def test_register_validates_uuid_tenant_and_duplicates(mu_root):
    with pytest.raises(ir.AdminError):
        ir.register_user("contoso", ALICE.object_id)
    with pytest.raises(ir.AdminError):
        ir.register_user(OTHER_TENANT, ALICE.object_id)  # 허용 목록 밖
    record = ir.register_user(TENANT.upper(), ALICE.object_id.upper())
    assert record.status == "pending_link" and record.tenant_id == TENANT
    with pytest.raises(ir.AdminError):
        ir.register_user(TENANT, ALICE.object_id)
    paths = paths_for(record.user_key)
    assert paths.auth_db.is_file() and paths.wrapped_dek.is_file() and paths.files.is_dir()


async def test_delete_user_removes_data_and_leaves_tombstone(mu_root):
    record, key = register_with_key(ALICE)
    other, other_key = register_with_key(BOB)
    paths = paths_for(record.user_key)
    (paths.files / "note.txt").write_text("x", encoding="utf-8")
    ir.delete_user(record.user_key)
    assert not paths.root.exists()
    assert ir.get_user(record.user_key) is None
    assert await _code(ir.authenticate_bearer(f"Bearer {key}", domain="outlook")) == ErrorCode.UNAUTHENTICATED
    with sqlite3.connect(system_paths().registry_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tombstones WHERE user_key = ?", (record.user_key,)).fetchone()[0] == 1
        left = conn.execute("SELECT COUNT(*) FROM credential_index WHERE user_key = ?", (record.user_key,))
        assert left.fetchone()[0] == 0
    # 다른 사용자는 그대로
    assert (await ir.authenticate_bearer(f"Bearer {other_key}", domain="outlook")).user_key == other.user_key
    # tombstone — 명시 reinstate 없이는 재등록 불가
    with pytest.raises(ir.AdminError):
        ir.register_user(TENANT, ALICE.object_id)
    again = ir.register_user(TENANT, ALICE.object_id, reinstate=True)
    assert again.user_key == record.user_key and again.status == "pending_link"
    # epoch 는 이전 수명(삭제 시 +1 된 값) 다음부터 — 풀 캐시 키가 겹치지 않는다
    assert again.auth_epoch == record.auth_epoch + 2
    ir.delete_user(again.user_key)
    third = ir.register_user(TENANT, ALICE.object_id, reinstate=True)
    assert third.auth_epoch == again.auth_epoch + 2


def test_old_registry_tombstones_table_is_migrated(mu_root):
    from session._registry_db import ensure_registry, registry

    ensure_registry()
    with sqlite3.connect(system_paths().registry_db) as conn:
        conn.execute("DROP TABLE tombstones")
        conn.execute("CREATE TABLE tombstones (user_key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,"
                     " object_id TEXT NOT NULL, deleted_at TEXT NOT NULL)")
    with registry(create=True) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tombstones)")}
    assert "last_auth_epoch" in cols


def test_list_users_has_no_secrets(mu_root):
    register_with_key(ALICE)
    users = ir.list_users()
    assert len(users) == 1 and users[0]["active_keys"] == 1
    assert not any("digest" in k or "secret" in k for k in users[0])


# ----------------------------------------------------------------------
# 관리 CLI smoke
# ----------------------------------------------------------------------
def _cli(*argv):
    from session.admin_cli import main

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv), load_env=False)
    return code, out.getvalue(), err.getvalue()


async def test_admin_cli_smoke(mu_root):
    code, out, _ = _cli("init")
    assert code == 0 and json.loads(out)["status"] == "ok"
    code, out, _ = _cli("user", "add", "--tenant", TENANT, "--oid", ALICE.object_id)
    assert code == 0
    user_key = json.loads(out)["user_key"]
    code, out, err = _cli("key", "issue", user_key, "--domains", "outlook", "--days", "7")
    assert code == 0
    raw_key = out.strip().splitlines()[-1]
    assert raw_key.startswith("m365v1.") and raw_key not in err
    p = await ir.authenticate_bearer(f"Bearer {raw_key}", domain="outlook")
    assert p.user_key == user_key
    code, out, _ = _cli("key", "list", user_key)
    assert code == 0 and raw_key.split(".")[2] not in out
    code, out, _ = _cli("user", "list")
    assert code == 0 and json.loads(out)[0]["status"] == "pending_link"
    assert _cli("user", "disable", user_key)[0] == 0
    assert _cli("user", "enable", user_key)[0] == 0
    assert _cli("key", "revoke", p.credential_id)[0] == 0
    assert _cli("graph", "disconnect", user_key)[0] == 0
    assert _cli("user", "delete", user_key)[0] == 2  # --yes 없음
    assert _cli("user", "delete", user_key, "--yes")[0] == 0
    code, _, err = _cli("user", "add", "--tenant", "not-a-uuid", "--oid", ALICE.object_id)
    assert code == 1 and "UUID" in err


def test_admin_cli_refuses_mode0(monkeypatch):
    from mcp_common.testing import single_user_mode

    with single_user_mode():
        code, _, err = _cli("user", "list")
    assert code == 2
