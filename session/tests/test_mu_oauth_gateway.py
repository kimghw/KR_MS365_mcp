"""WP2 — 중앙 auth gateway OAuth 연결: 역순 완료(O01), 다른 계정 로그인(O02), replay·만료·미지 state·
오류 콜백(O03), 브라우저·nonce·PKCE·서명(O04), 재시작(O05), bearer 엔드포인트."""

import logging
import sqlite3
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.user_paths import paths_for
from session import identity_registry as ir
from session._mu_common import iso, utcnow
from session.auth_gateway import create_app
from session.graph_connect import MAX_PENDING_ATTEMPTS
from session.tests.mu_support import ALICE, BOB, CLIENT_ID, OTHER_TENANT, Account, FakeEntra, register_with_key
from session.token_store import get_graph_access_token
from session.user_crypto import KIND_GRAPH_TOKENS, open_sealed


# ----------------------------------------------------------------------
# 도우미
# ----------------------------------------------------------------------
@pytest.fixture
def gw(fake_entra):
    return create_app(entra=fake_entra, jwks_client=fake_entra.jwks)


def browser(app) -> TestClient:
    return TestClient(app, base_url="http://localhost:5000")


def auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def start(client: TestClient, key: str) -> dict:
    resp = client.post("/auth/graph/start", headers=auth(key))
    assert resp.status_code == 201, resp.text
    return resp.json()


def connect(client: TestClient, connect_url: str) -> str:
    parts = urlsplit(connect_url)
    resp = client.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    return resp.headers["location"]


def callback(client: TestClient, **params):
    return client.get("/auth/callback", params=params)


def stored_access(user_key: str):
    p = paths_for(user_key)
    with sqlite3.connect(p.auth_db) as conn:
        row = conn.execute("SELECT ciphertext, nonce, token_version, dek_version FROM graph_tokens").fetchone()
    if row is None:
        return None
    return open_sealed(p, ciphertext=row[0], nonce=row[1], dek_version=row[3], app_id=CLIENT_ID,
                       kind=KIND_GRAPH_TOKENS, record_version=row[2])["access_token"]


def attempt_row(user_key: str, attempt_id: str) -> dict:
    with sqlite3.connect(paths_for(user_key).auth_db) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM oauth_attempts WHERE attempt_id = ?", (attempt_id,)).fetchone())


def flow(app, key: str):
    """시작 → 연결. (browser, attempt_id, authorize_url)."""
    client = browser(app)
    started = start(client, key)
    return client, started["attempt_id"], connect(client, started["connect_url"])


# ----------------------------------------------------------------------
# 정상 흐름·O01
# ----------------------------------------------------------------------
def test_authorize_redirect_has_pkce_nonce_state_and_cookie(gw, fake_entra):
    _, key = register_with_key(ALICE)
    client = browser(gw)
    started = start(client, key)
    assert started["expires_in"] == 300
    parts = urlsplit(started["connect_url"])
    resp = client.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert resp.status_code == 302
    q = {k: v[0] for k, v in parse_qs(urlsplit(resp.headers["location"]).query).items()}
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert len(q["state"]) >= 43 and len(q["nonce"]) >= 43 and q["redirect_uri"] == "http://localhost:5000/auth/callback"
    assert "login_hint" not in q and q["prompt"] == "select_account"
    cookie = resp.headers["set-cookie"]
    assert f"m365_oauth_{started['attempt_id']}=" in cookie
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower() and "Path=/auth/callback" in cookie
    assert "Secure" not in cookie  # http(loopback) 배포
    assert resp.headers["cache-control"] == "no-store" and resp.headers["referrer-policy"] == "no-referrer"
    # ticket 은 1회용
    again = client.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert again.status_code == 400


def test_cookie_is_secure_on_https_deployment(mu_root, fake_entra, monkeypatch):
    monkeypatch.setenv("AZURE_REDIRECT_URI", "https://mcp.example.com/auth/callback")
    app = create_app(entra=fake_entra, jwks_client=fake_entra.jwks)
    _, key = register_with_key(ALICE)
    client = TestClient(app, base_url="https://mcp.example.com")
    started = start(client, key)
    assert started["connect_url"].startswith("https://mcp.example.com/auth/graph/connect?ticket=")
    parts = urlsplit(started["connect_url"])
    resp = client.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert "Secure" in resp.headers["set-cookie"]


async def test_o01_two_users_complete_in_reverse_order(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    rec_b, key_b = register_with_key(BOB)
    ba, att_a, url_a = flow(gw, key_a)
    bb, att_b, url_b = flow(gw, key_b)
    code_a, state_a = fake_entra.login(url_a, ALICE)
    code_b, state_b = fake_entra.login(url_b, BOB)

    rb = callback(bb, code=code_b, state=state_b)
    assert rb.status_code == 200 and "bob@contoso.com" in rb.text
    ra = callback(ba, code=code_a, state=state_a)
    assert ra.status_code == 200 and "alice@contoso.com" in ra.text
    for resp in (ra, rb):
        assert "at-" not in resp.text and "rt-" not in resp.text  # 토큰 비노출

    assert fake_entra.access[stored_access(rec_a.user_key)] == ALICE
    assert fake_entra.access[stored_access(rec_b.user_key)] == BOB
    pa = await ir.authenticate_bearer(f"Bearer {key_a}", domain="outlook")
    pb = await ir.authenticate_bearer(f"Bearer {key_b}", domain="outlook")
    assert (pa.graph_email, pb.graph_email) == (ALICE.email, BOB.email)
    assert fake_entra.access[(await get_graph_access_token(pa)).value] == ALICE
    assert attempt_row(rec_a.user_key, att_a)["status"] == "completed"
    assert attempt_row(rec_a.user_key, att_a)["verifier_ciphertext"] is None
    status = ba.get(f"/auth/attempts/{att_a}", headers=auth(key_a)).json()
    assert status["status"] == "completed"


# ----------------------------------------------------------------------
# O02 — A 의 시도에 B 계정으로 로그인
# ----------------------------------------------------------------------
def test_o02_other_account_login_is_rejected_before_storing(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    rec_b, _ = register_with_key(BOB)
    client, att, url = flow(gw, key_a)
    code, state = fake_entra.login(url, BOB)
    resp = callback(client, code=code, state=state)
    assert resp.status_code == 400 and "다른 Microsoft 계정" in resp.text
    assert stored_access(rec_a.user_key) is None and stored_access(rec_b.user_key) is None
    assert ir.get_user(rec_a.user_key).status == "pending_link"
    assert attempt_row(rec_a.user_key, att)["error_code"] == "account_mismatch"


def test_o02_graph_me_id_mismatch_is_rejected(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    client, _, url = flow(gw, key_a)
    fake_entra.me_id_override = BOB.object_id
    code, state = fake_entra.login(url, ALICE)
    assert callback(client, code=code, state=state).status_code == 400
    assert stored_access(rec_a.user_key) is None


def test_o02_disallowed_tenant_is_rejected(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    client, att, url = flow(gw, key_a)
    code, state = fake_entra.login(url, Account(OTHER_TENANT, ALICE.object_id, ALICE.email))
    assert callback(client, code=code, state=state).status_code == 400
    assert attempt_row(rec_a.user_key, att)["error_code"] == "tenant_not_allowed"


# ----------------------------------------------------------------------
# O03 — replay·만료·없는 state·오류 콜백은 그 시도만
# ----------------------------------------------------------------------
def test_o03_replay_does_not_change_completed_attempt(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    client, att, url = flow(gw, key_a)
    code, state = fake_entra.login(url, ALICE)
    assert callback(client, code=code, state=state).status_code == 200
    before = stored_access(rec_a.user_key)
    assert callback(client, code=code, state=state).status_code == 400
    assert stored_access(rec_a.user_key) == before and fake_entra.exchange_calls == 1
    assert attempt_row(rec_a.user_key, att)["status"] == "completed"


def test_o03_unknown_state_and_error_callback_only_affect_that_attempt(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    rec_b, key_b = register_with_key(BOB)
    ba, att_a, url_a = flow(gw, key_a)
    bb, att_b, url_b = flow(gw, key_b)
    _, state_b = fake_entra.login(url_b, BOB)

    # 없는 state·state 없는 오류 → 아무 시도도 바뀌지 않음
    assert callback(ba, code="x", state="Z" * 43).status_code == 400
    assert callback(ba, error="access_denied").status_code == 400
    assert attempt_row(rec_a.user_key, att_a)["status"] == "pending"
    assert attempt_row(rec_b.user_key, att_b)["status"] == "pending"

    # B 의 유효 state 오류 콜백 → B 시도만 실패
    resp = callback(bb, error="access_denied", error_description="<script>x</script>", state=state_b)
    assert resp.status_code == 400 and "<script>" not in resp.text
    assert attempt_row(rec_b.user_key, att_b)["status"] == "failed"
    assert attempt_row(rec_a.user_key, att_a)["status"] == "pending"

    # A 는 그대로 완료된다
    code_a, state_a = fake_entra.login(url_a, ALICE)
    assert callback(ba, code=code_a, state=state_a).status_code == 200
    assert stored_access(rec_b.user_key) is None


def test_o03_expired_attempt_fails_only_itself(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    rec_b, key_b = register_with_key(BOB)
    ba, att_a, url_a = flow(gw, key_a)
    bb, att_b, url_b = flow(gw, key_b)
    with sqlite3.connect(paths_for(rec_a.user_key).auth_db) as conn:
        conn.execute("UPDATE oauth_attempts SET expires_at = ? WHERE attempt_id = ?",
                     (iso(utcnow() - timedelta(seconds=1)), att_a))
    code_a, state_a = fake_entra.login(url_a, ALICE)
    assert callback(ba, code=code_a, state=state_a).status_code == 400
    assert attempt_row(rec_a.user_key, att_a)["status"] == "expired" and fake_entra.exchange_calls == 0
    code_b, state_b = fake_entra.login(url_b, BOB)
    assert callback(bb, code=code_b, state=state_b).status_code == 200


def test_o03_expired_ticket(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    client = browser(gw)
    started = start(client, key_a)
    with sqlite3.connect(paths_for(rec_a.user_key).auth_db) as conn:
        conn.execute("UPDATE oauth_attempts SET ticket_expires_at = ?", (iso(utcnow() - timedelta(seconds=1)),))
    parts = urlsplit(started["connect_url"])
    resp = client.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert resp.status_code == 400 and "만료" in resp.text
    assert attempt_row(rec_a.user_key, started["attempt_id"])["status"] == "expired"


# ----------------------------------------------------------------------
# O04 — 다른 브라우저·nonce 불일치·PKCE·서명
# ----------------------------------------------------------------------
def test_o04_callback_from_other_browser_fails(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    _, att, url = flow(gw, key_a)
    code, state = fake_entra.login(url, ALICE)
    other_browser = browser(gw)
    assert callback(other_browser, code=code, state=state).status_code == 400
    assert attempt_row(rec_a.user_key, att)["error_code"] == "browser_mismatch"
    assert fake_entra.exchange_calls == 0 and stored_access(rec_a.user_key) is None


def test_o04_nonce_mismatch_fails(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    client, att, url = flow(gw, key_a)
    fake_entra.id_token_overrides = {"nonce": "not-the-nonce"}
    code, state = fake_entra.login(url, ALICE)
    assert callback(client, code=code, state=state).status_code == 400
    assert attempt_row(rec_a.user_key, att)["error_code"] == "nonce_mismatch"
    assert stored_access(rec_a.user_key) is None


def test_o04_intercepted_code_fails_pkce_in_other_attempt(gw, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    rec_b, key_b = register_with_key(BOB)
    ba, att_a, url_a = flow(gw, key_a)
    bb, att_b, url_b = flow(gw, key_b)
    code_a, state_a = fake_entra.login(url_a, ALICE)  # 피해자 A 의 code (A 의 challenge 에 묶임)
    _, state_b = fake_entra.login(url_b, BOB)
    # 공격자 B 가 자기 state·쿠키로 A 의 code 를 제출 → B 의 verifier 로는 교환 불가
    assert callback(bb, code=code_a, state=state_b).status_code == 400
    assert attempt_row(rec_b.user_key, att_b)["error_code"] == "token_exchange_failed"
    assert stored_access(rec_b.user_key) is None and stored_access(rec_a.user_key) is None
    # A 의 시도는 영향 없음
    assert callback(ba, code=code_a, state=state_a).status_code == 200


@pytest.mark.parametrize("override", [
    {"aud": "someone-else"},
    {"iss": "https://login.microsoftonline.com/evil/v2.0"},
    {"exp": 1000, "iat": 900, "nbf": 900},
])
def test_o04_invalid_id_token_claims_fail(gw, fake_entra, override):
    rec_a, key_a = register_with_key(ALICE)
    client, att, url = flow(gw, key_a)
    fake_entra.id_token_overrides = override
    code, state = fake_entra.login(url, ALICE)
    assert callback(client, code=code, state=state).status_code == 400
    assert attempt_row(rec_a.user_key, att)["error_code"] == "id_token_invalid"


def test_o04_id_token_signed_by_unknown_key_fails(mu_root, fake_entra):
    impostor = FakeEntra()
    app = create_app(entra=fake_entra, jwks_client=impostor.jwks)  # 같은 kid, 다른 공개키
    rec_a, key_a = register_with_key(ALICE)
    client, att, url = flow(app, key_a)
    code, state = fake_entra.login(url, ALICE)
    assert callback(client, code=code, state=state).status_code == 400
    assert attempt_row(rec_a.user_key, att)["error_code"] == "id_token_invalid"


# ----------------------------------------------------------------------
# O05 — 프로세스 재시작
# ----------------------------------------------------------------------
def test_o05_restart_recovers_pending_and_never_reuses_redeeming(mu_root, fake_entra):
    rec_a, key_a = register_with_key(ALICE)
    rec_b, key_b = register_with_key(BOB)
    first = create_app(entra=fake_entra, jwks_client=fake_entra.jwks)
    ba, att_a, url_a = flow(first, key_a)
    bb, att_b, url_b = flow(first, key_b)
    code_a, state_a = fake_entra.login(url_a, ALICE)
    code_b, state_b = fake_entra.login(url_b, BOB)
    # B 는 code 교환 직전(redeeming)에 프로세스가 죽었다고 가정
    with sqlite3.connect(paths_for(rec_b.user_key).auth_db) as conn:
        conn.execute("UPDATE oauth_attempts SET status = 'redeeming' WHERE attempt_id = ?", (att_b,))

    restarted = create_app(entra=fake_entra, jwks_client=fake_entra.jwks)
    ba2, bb2 = browser(restarted), browser(restarted)
    ba2.cookies = ba.cookies
    bb2.cookies = bb.cookies
    assert callback(ba2, code=code_a, state=state_a).status_code == 200  # pending 은 그대로 이어진다
    assert callback(bb2, code=code_b, state=state_b).status_code == 400  # redeeming 은 재사용하지 않는다
    assert fake_entra.access[stored_access(rec_a.user_key)] == ALICE
    assert stored_access(rec_b.user_key) is None and ir.get_user(rec_b.user_key).status == "pending_link"


# ----------------------------------------------------------------------
# bearer 엔드포인트
# ----------------------------------------------------------------------
def test_start_requires_bearer_and_accepts_any_scope(gw, fake_entra):
    _, key = register_with_key(ALICE, domains=["calendar"])
    client = browser(gw)
    resp = client.post("/auth/graph/start")
    assert resp.status_code == 401 and resp.headers["www-authenticate"] == "Bearer"
    assert client.post("/auth/graph/start", headers=auth("m365v1.bad.key")).status_code == 401
    assert start(client, key)["attempt_id"]


def test_attempt_status_is_own_only(gw, fake_entra):
    _, key_a = register_with_key(ALICE)
    _, key_b = register_with_key(BOB)
    client = browser(gw)
    att_a = start(client, key_a)["attempt_id"]
    assert client.get(f"/auth/attempts/{att_a}", headers=auth(key_a)).json()["status"] == "created"
    assert client.get(f"/auth/attempts/{att_a}", headers=auth(key_b)).status_code == 404
    assert client.get("/auth/attempts/../../x", headers=auth(key_a)).status_code == 404


def test_max_pending_attempts_supersedes_oldest(gw, fake_entra):
    rec, key = register_with_key(ALICE)
    client = browser(gw)
    started = [start(client, key) for _ in range(MAX_PENDING_ATTEMPTS + 1)]
    assert attempt_row(rec.user_key, started[0]["attempt_id"])["status"] == "superseded"
    parts = urlsplit(started[0]["connect_url"])
    assert client.get(f"{parts.path}?{parts.query}", follow_redirects=False).status_code == 400
    active = [s for s in started if attempt_row(rec.user_key, s["attempt_id"])["status"] == "created"]
    assert len(active) == MAX_PENDING_ATTEMPTS


async def test_disconnect_deletes_tokens_and_bumps_epoch(gw, fake_entra):
    rec, key = register_with_key(ALICE)
    client, _, url = flow(gw, key)
    code, state = fake_entra.login(url, ALICE)
    assert callback(client, code=code, state=state).status_code == 200
    before = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    resp = client.delete("/auth/graph/connection", headers=auth(key))
    assert resp.status_code == 200 and resp.json() == {"status": "disconnected"}
    assert stored_access(rec.user_key) is None
    after = await ir.authenticate_bearer(f"Bearer {key}", domain="outlook")
    assert after.auth_epoch == before.auth_epoch + 1 and after.graph_email is None
    with pytest.raises(SecurityError) as e:
        await ir.assert_active(before)
    assert e.value.code == ErrorCode.ACCOUNT_INACTIVE


def test_access_log_has_no_query_string_and_health_is_minimal(gw, fake_entra, caplog):
    _, key = register_with_key(ALICE)
    with caplog.at_level(logging.INFO, logger="session.auth_gateway"):
        client, _, url = flow(gw, key)
        code, state = fake_entra.login(url, ALICE)
        callback(client, code=code, state=state)
    assert "/auth/callback" in caplog.text
    assert state not in caplog.text and code not in caplog.text and "ticket=" not in caplog.text
    assert key not in caplog.text
    health = browser(gw).get("/health").json()
    assert health == {"status": "ok", "server": "auth_gateway", "version": "1.0.0"}
