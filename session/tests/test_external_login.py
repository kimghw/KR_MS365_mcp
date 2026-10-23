"""외부 로그인 위임(mode 0 라이브러리 계약, spec/spec_멀티유저.md ② '모드 0 외부 로그인 위임 계약(AIP)').

HTTP 는 전부 가짜(aiohttp 세션 대역) — 토큰 교환 요청 본문(redirect_uri·scope)·/me 헤더를 기록하고 응답을 미리 넣는다.
검증: complete_external_login(저장·save=False·오류 코드 EXCHANGE_FAILED·USERINFO_FAILED·ACCOUNT_MISMATCH·토큰 비노출 · 저장 실패는
예외가 아니라 error='SAVE_FAILED' 반환 · expect_email 저장 전 대조) · connection_state 4상태 · features 판정 · 구형 행(scope 없음) None ·
갱신 거부(invalid_grant) 표식과 reason 코드 · 선택 컬럼 idempotent 보강 · mode 1 거부.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import aiohttp
import pytest

from mcp_common.testing import multi_user_mode, single_user_mode
from session import external_login
from session.external_login import ExternalLoginError, FEATURES

GRAPH = "https://graph.microsoft.com/"
FULL_SCOPE = " ".join(
    GRAPH + p
    for p in ("Mail.Read", "Mail.Send", "Chat.ReadWrite", "Notes.ReadWrite.All", "Calendars.ReadWrite", "Tasks.ReadWrite", "User.Read")
) + " openid profile email"
BASIC_SCOPE = "openid profile email " + GRAPH + "User.Read"
DEFAULT_SCOPES = "https://graph.microsoft.com/.default offline_access openid"
REDIRECT = "https://aip.example.test/auth/callback"
ME = {
    "id": "oid-1",
    "displayName": "홍길동",
    "mail": "Hong@Contoso.com",
    "userPrincipalName": "hong@contoso.com",
    "jobTitle": "연구원",
}
PAST = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
FUTURE = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


# ----------------------------------------------------------------------
# aiohttp 대역
# ----------------------------------------------------------------------
class _Resp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return json.dumps(self._payload)


class FakeSession:
    """post(토큰 endpoint)·get(/me) 응답 큐 + 요청 기록. 큐가 비면 테스트 결함이므로 IndexError 로 드러난다."""

    def __init__(self):
        self.posts = []
        self.gets = []
        self.post_queue = []
        self.get_queue = []
        self.closed = False

    def post(self, url, data=None, **kwargs):
        self.posts.append((url, dict(data or {})))
        return self.post_queue.pop(0)

    def get(self, url, headers=None, **kwargs):
        self.gets.append((url, dict(headers or {})))
        return self.get_queue.pop(0)

    async def close(self):
        self.closed = True


def tok(scope=FULL_SCOPE, refresh="r-1", access="a-1"):
    payload = {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "scope": scope}
    if refresh:
        payload["refresh_token"] = refresh
    return payload


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """mode 0 AuthManager — 임시 auth.db·가짜 Entra 앱 설정·가짜 HTTP 세션. 실 .env 값은 전부 덮는다."""
    env = {
        "AZURE_CLIENT_ID": "app-test",
        "AZURE_CLIENT_SECRET": "SECRET-CANARY",
        "AZURE_TENANT_ID": "tenant-test",
        "AZURE_REDIRECT_URI": "http://localhost:5000/callback",
        "AZURE_SCOPES": DEFAULT_SCOPES,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("DB_PATH", "MS365_DEFAULT_USER_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    from session.auth_manager import AuthManager

    with single_user_mode():
        manager = AuthManager(db_path=str(tmp_path / "auth.db"))
        fake = FakeSession()

        async def _get_session():
            return fake

        manager.auth_service._get_session = _get_session
        manager.fake = fake
        yield manager


def _set_refresh_expiry(db_path, email, value):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE azure_token_info SET refresh_token_expires_at = ? WHERE user_email = ?", (value, email))
    conn.commit()
    conn.close()


# ----------------------------------------------------------------------
# complete_external_login
# ----------------------------------------------------------------------
async def test_external_login_saves_and_returns_identity_only(mgr):
    mgr.fake.post_queue = [_Resp(200, tok())]
    mgr.fake.get_queue = [_Resp(200, ME)]

    result = await mgr.complete_external_login("code-1", REDIRECT, scopes=DEFAULT_SCOPES)

    assert result["email"] == "hong@contoso.com"  # 소문자
    assert result["display_name"] == "홍길동"
    assert set(result["user_info"]) == set(external_login.USER_INFO_KEYS) and "jobTitle" not in result["user_info"]
    assert result["saved"] is True and result["has_refresh"] is True
    assert "Mail.Read" in result["granted_scopes"] and "openid" in result["granted_scopes"]
    assert result["state"] == "connected"
    dumped = json.dumps(result, ensure_ascii=False)
    assert "a-1" not in dumped and "r-1" not in dumped and "SECRET" not in dumped

    # 교환 요청: 이 저장소의 client secret + 외부 앱의 redirect_uri·scope
    url, data = mgr.fake.posts[0]
    assert "tenant-test" in url and url.endswith("/oauth2/v2.0/token")
    assert data["redirect_uri"] == REDIRECT and data["scope"] == DEFAULT_SCOPES
    assert data["client_id"] == "app-test" and data["client_secret"] == "SECRET-CANARY"
    assert data["grant_type"] == "authorization_code" and data["code"] == "code-1"
    # /me 는 받은 access token 으로
    assert mgr.fake.gets[0][1]["Authorization"] == "Bearer a-1"

    # auth.db: save_user → save_token, scope 저장, 거부 표식 'ok'
    row = mgr.auth_db.get_token("hong@contoso.com")
    assert row["refresh_token"] == "r-1" and row["scope"] == FULL_SCOPE and row["refresh_state"] == "ok"
    assert mgr.auth_db.get_user("hong@contoso.com")["display_name"] == "홍길동"

    state = mgr.connection_state("hong@contoso.com")
    assert state["state"] == "connected"
    assert state["features"] == {f: True for f in FEATURES}
    assert state["refresh_token_expired"] is False and isinstance(state["access_token_expires_at"], str)


async def test_external_login_scope_defaults_and_list(mgr):
    mgr.fake.post_queue = [_Resp(200, tok()), _Resp(200, tok())]
    mgr.fake.get_queue = [_Resp(200, ME), _Resp(200, ME)]

    await mgr.complete_external_login("c1", REDIRECT)  # scopes=None → config.default_scopes
    await mgr.complete_external_login("c2", REDIRECT, scopes=["openid", " profile ", "User.Read"])

    assert mgr.fake.posts[0][1]["scope"] == " ".join(mgr.config.default_scopes)
    assert mgr.fake.posts[1][1]["scope"] == "openid profile User.Read"


async def test_external_login_identity_only_does_not_store(mgr):
    mgr.fake.post_queue = [_Resp(200, tok(scope=BASIC_SCOPE, refresh=None, access="a-basic"))]
    mgr.fake.get_queue = [_Resp(200, ME)]

    result = await mgr.complete_external_login("code-basic", REDIRECT, scopes="openid profile email User.Read", save=False)

    assert result["email"] == "hong@contoso.com" and result["saved"] is False and result["has_refresh"] is False
    assert result["granted_scopes"] == ["openid", "profile", "email", "User.Read"]
    assert result["state"] == "not_connected"
    assert mgr.auth_db.get_token("hong@contoso.com") is None and mgr.auth_db.list_users() == []


async def test_external_login_without_refresh_still_saves_access(mgr):
    """refresh 없는 응답도 access 는 저장(기존 refresh 는 COALESCE 유지) — 상태는 reauth_required 로 드러난다."""
    mgr.fake.post_queue = [_Resp(200, tok(refresh=None))]
    mgr.fake.get_queue = [_Resp(200, ME)]
    result = await mgr.complete_external_login("c", REDIRECT)
    assert result["saved"] is True and result["has_refresh"] is False and result["state"] == "reauth_required"


async def test_exchange_failure_code_without_detail(mgr):
    mgr.fake.post_queue = [_Resp(400, {"error": "invalid_grant", "error_description": "SECRET-DETAIL AADSTS70008"})]

    with pytest.raises(ExternalLoginError) as e:
        await mgr.complete_external_login("bad-code", REDIRECT)
    assert e.value.code == "EXCHANGE_FAILED" and str(e.value).startswith("EXCHANGE_FAILED|")
    assert e.value.oauth_error == "invalid_grant" and e.value.http_status == 400
    assert "SECRET-DETAIL" not in str(e.value)
    assert mgr.fake.gets == [] and mgr.auth_db.list_users() == []


async def test_exchange_transport_failure_and_empty_inputs(mgr):
    def _boom(*args, **kwargs):
        raise aiohttp.ClientConnectionError("dns SECRET-HOST")

    mgr.fake.post = _boom
    with pytest.raises(ExternalLoginError) as e:
        await mgr.complete_external_login("c", REDIRECT)
    assert e.value.code == "EXCHANGE_FAILED" and "SECRET-HOST" not in str(e.value)

    for code, redirect in (("", REDIRECT), ("c", "")):
        with pytest.raises(ExternalLoginError) as e2:
            await mgr.complete_external_login(code, redirect)
        assert e2.value.code == "EXCHANGE_FAILED"


async def test_userinfo_failure_code(mgr):
    mgr.fake.post_queue = [_Resp(200, tok()), _Resp(200, tok())]
    mgr.fake.get_queue = [_Resp(401, {"error": {"code": "InvalidAuthenticationToken"}}), _Resp(200, {"id": "oid-x"})]

    with pytest.raises(ExternalLoginError) as e:
        await mgr.complete_external_login("c1", REDIRECT)
    assert e.value.code == "USERINFO_FAILED" and str(e.value).startswith("USERINFO_FAILED|")

    with pytest.raises(ExternalLoginError) as e2:  # /me 에 mail·userPrincipalName 없음
        await mgr.complete_external_login("c2", REDIRECT)
    assert e2.value.code == "USERINFO_FAILED"
    assert mgr.auth_db.list_users() == []


async def test_save_failure_returns_identity_with_error_key(mgr, monkeypatch):
    """저장 실패(save=True)는 예외가 아니다 — 신원은 돌려주고 saved=False·error='SAVE_FAILED'·state 는 DB 기준(2026-10-23 codex 교차 검토 2)."""
    mgr.fake.post_queue = [_Resp(200, tok()), _Resp(200, tok()), _Resp(200, tok(refresh="r-2", access="a-2"))]
    mgr.fake.get_queue = [_Resp(200, ME), _Resp(200, ME), _Resp(200, ME)]
    real_user, real_token = mgr.auth_db.save_user, mgr.auth_db.save_token

    # save_token 이 False — 행 없음 → not_connected
    monkeypatch.setattr(mgr.auth_db, "save_token", lambda *a, **k: False)
    r1 = await mgr.complete_external_login("c1", REDIRECT)
    assert r1["email"] == "hong@contoso.com" and r1["display_name"] == "홍길동"
    assert r1["saved"] is False and r1["error"] == "SAVE_FAILED" and r1["state"] == "not_connected"
    assert r1["has_refresh"] is True and "Mail.Read" in r1["granted_scopes"]
    assert set(r1) == {"email", "display_name", "user_info", "saved", "has_refresh", "granted_scopes", "state", "error"}
    assert mgr.auth_db.get_token("hong@contoso.com") is None
    assert "a-1" not in json.dumps(r1, ensure_ascii=False) and "r-1" not in json.dumps(r1, ensure_ascii=False)

    # save_user 가 예외(잠김) — 같은 꼴, 예외 종류·경로는 결과에 없다
    def _raise(*a, **k):
        raise sqlite3.OperationalError("database is locked /secret/path")

    monkeypatch.setattr(mgr.auth_db, "save_user", _raise)
    r2 = await mgr.complete_external_login("c2", REDIRECT)
    assert r2["saved"] is False and r2["error"] == "SAVE_FAILED" and r2["state"] == "not_connected"
    assert "/secret/path" not in json.dumps(r2) and "OperationalError" not in json.dumps(r2)

    # 기존 정상 행이 있는 계정의 저장 실패 — state 는 기존 행 기준(connected), 행은 그대로
    monkeypatch.setattr(mgr.auth_db, "save_user", real_user)
    real_token("hong@contoso.com", {"access_token": "a-old", "refresh_token": "r-old", "expires_at": FUTURE, "scope": FULL_SCOPE})
    r3 = await mgr.complete_external_login("c3", REDIRECT)
    assert r3["saved"] is False and r3["error"] == "SAVE_FAILED" and r3["state"] == "connected"
    assert mgr.auth_db.get_token("hong@contoso.com")["refresh_token"] == "r-old"

    # 정상 저장·save=False 에는 error 키가 없다(기존 테스트의 반환 키 집합과 같다)
    monkeypatch.setattr(mgr.auth_db, "save_token", real_token)
    mgr.fake.post_queue = [_Resp(200, tok(refresh="r-3", access="a-3")), _Resp(200, tok(scope=BASIC_SCOPE, refresh=None))]
    mgr.fake.get_queue = [_Resp(200, ME), _Resp(200, ME)]
    assert "error" not in await mgr.complete_external_login("c4", REDIRECT)
    assert "error" not in await mgr.complete_external_login("c5", REDIRECT, save=False)


async def test_account_mismatch_before_save_stores_nothing(mgr, monkeypatch):
    """expect_email 과 /me 메일이 다르면 저장 **전**에 ACCOUNT_MISMATCH — save_user·save_token 미호출(2026-10-23 codex 교차 검토 1)."""
    calls = []
    real_user, real_token = mgr.auth_db.save_user, mgr.auth_db.save_token
    monkeypatch.setattr(mgr.auth_db, "save_user", lambda *a, **k: calls.append("user") or real_user(*a, **k))
    monkeypatch.setattr(mgr.auth_db, "save_token", lambda *a, **k: calls.append("token") or real_token(*a, **k))

    mgr.fake.post_queue = [_Resp(200, tok())]
    mgr.fake.get_queue = [_Resp(200, ME)]
    with pytest.raises(ExternalLoginError) as e:
        await mgr.complete_external_login("c1", REDIRECT, expect_email="Other@Contoso.com")
    assert e.value.code == "ACCOUNT_MISMATCH" and str(e.value).startswith("ACCOUNT_MISMATCH|")
    assert e.value.expected_email == "other@contoso.com" and e.value.actual_email == "hong@contoso.com"
    assert "hong@contoso.com" not in str(e.value) and "a-1" not in str(e.value) and "SECRET" not in str(e.value)
    assert calls == []
    assert mgr.auth_db.get_token("hong@contoso.com") is None and mgr.auth_db.list_users() == []
    assert mgr.connection_state("hong@contoso.com")["state"] == "not_connected"

    # 같은 계정(대소문자·공백 차이)은 종전대로 저장
    mgr.fake.post_queue = [_Resp(200, tok())]
    mgr.fake.get_queue = [_Resp(200, ME)]
    ok = await mgr.complete_external_login("c2", REDIRECT, expect_email="  HONG@contoso.COM ")
    assert ok["saved"] is True and ok["state"] == "connected" and "error" not in ok
    assert calls == ["user", "token"]

    # save=False 여도 대조는 한다(신원만 로그인도 다른 계정이면 거부)
    mgr.fake.post_queue = [_Resp(200, tok(scope=BASIC_SCOPE, refresh=None))]
    mgr.fake.get_queue = [_Resp(200, ME)]
    with pytest.raises(ExternalLoginError) as e2:
        await mgr.complete_external_login("c3", REDIRECT, save=False, expect_email="other@contoso.com")
    assert e2.value.code == "ACCOUNT_MISMATCH"

    # expect_email=None·빈 문자열 = 종전(무검증)
    mgr.fake.post_queue = [_Resp(200, tok(refresh="r-4", access="a-4"))]
    mgr.fake.get_queue = [_Resp(200, ME)]
    assert (await mgr.complete_external_login("c4", REDIRECT, expect_email=""))["saved"] is True


async def test_account_mismatch_leaves_existing_row_of_other_account_untouched(mgr):
    """A 의 재연결 화면에서 B 를 고른 경우 — B 의 기존 정상 연결(토큰 행)은 갱신도 삭제도 되지 않는다."""
    db = mgr.auth_db
    db.save_token("hong@contoso.com", {"access_token": "a-old", "refresh_token": "r-old", "expires_at": FUTURE, "scope": FULL_SCOPE})
    before = db.get_token("hong@contoso.com")

    mgr.fake.post_queue = [_Resp(200, tok(refresh="r-new", access="a-new"))]
    mgr.fake.get_queue = [_Resp(200, ME)]  # /me = hong(B), 기대 = a(A)
    with pytest.raises(ExternalLoginError) as e:
        await mgr.complete_external_login("c", REDIRECT, expect_email="a@contoso.com")
    assert e.value.code == "ACCOUNT_MISMATCH"

    after = db.get_token("hong@contoso.com")
    assert after["access_token"] == "a-old" and after["refresh_token"] == "r-old" and after["updated_at"] == before["updated_at"]
    assert db.get_user("hong@contoso.com") is None  # 신규 사용자 행도 없다
    assert mgr.connection_state("hong@contoso.com")["state"] == "connected"
    assert mgr.connection_state("a@contoso.com")["state"] == "not_connected"


# ----------------------------------------------------------------------
# connection_state · features
# ----------------------------------------------------------------------
def test_connection_state_four_states(mgr, monkeypatch):
    db = mgr.auth_db
    assert mgr.connection_state("nobody@contoso.com")["state"] == "not_connected"
    assert mgr.connection_state("")["state"] == "not_connected"

    # connected — 대소문자 다른 저장 표기도 찾는다(canonical_email)
    db.save_token("Hong@Contoso.com", {"access_token": "a", "refresh_token": "r", "expires_at": FUTURE, "scope": FULL_SCOPE})
    state = mgr.connection_state("hong@contoso.com")
    assert state["state"] == "connected" and state["email"] == "hong@contoso.com"
    assert state["features"]["mail"] is True and state["granted_scopes"][0] == "Mail.Read"

    # reauth_required — refresh 없음 / 만료 / 거부 표식
    db.save_token("norefresh@contoso.com", {"access_token": "a", "expires_at": FUTURE, "scope": FULL_SCOPE})
    assert mgr.connection_state("norefresh@contoso.com")["state"] == "reauth_required"

    _set_refresh_expiry(db.db_path, "Hong@Contoso.com", PAST)
    expired = mgr.connection_state("hong@contoso.com")
    assert expired["state"] == "reauth_required" and expired["refresh_token_expired"] is True
    _set_refresh_expiry(db.db_path, "Hong@Contoso.com", FUTURE)
    assert mgr.connection_state("hong@contoso.com")["state"] == "connected"

    assert db.mark_refresh_state("Hong@Contoso.com", "reauth_required") is True
    assert mgr.connection_state("hong@contoso.com")["state"] == "reauth_required"
    # 새 refresh_token 저장 → 표식 해제
    db.save_token("Hong@Contoso.com", {"access_token": "a2", "refresh_token": "r2", "expires_at": FUTURE})
    assert mgr.connection_state("hong@contoso.com")["state"] == "connected"
    # access 만 갱신(refresh 없음)은 표식을 건드리지 않는다
    db.mark_refresh_state("Hong@Contoso.com", "reauth_required")
    db.save_token("Hong@Contoso.com", {"access_token": "a3", "expires_at": FUTURE})
    assert mgr.connection_state("hong@contoso.com")["state"] == "reauth_required"

    # unavailable — DB 를 읽지 못함(예외 종류 이름만)
    def _locked(email, strict=False):
        raise sqlite3.OperationalError("database is locked /secret/path")

    monkeypatch.setattr(db, "get_token", _locked)
    unavailable = mgr.connection_state("hong@contoso.com")
    assert unavailable["state"] == "unavailable" and unavailable["error"] == "OperationalError"
    assert "/secret/path" not in json.dumps(unavailable)


def test_features_mapping_and_legacy_rows(mgr):
    db = mgr.auth_db
    # 구형 행(scope 모름) → features·granted_scopes None, 상태는 refresh 기준
    db.save_token("legacy@contoso.com", {"access_token": "a", "refresh_token": "r", "expires_at": FUTURE})
    state = mgr.connection_state("legacy@contoso.com")
    assert state["state"] == "connected" and state["features"] is None and state["granted_scopes"] is None
    # 빈 문자열 scope 는 NULL 로 — 기존 scope 를 지우지 않는다
    db.save_token("legacy@contoso.com", {"access_token": "a", "expires_at": FUTURE, "scope": ""})
    assert mgr.connection_state("legacy@contoso.com")["granted_scopes"] is None

    # 신원만 범위 → 전부 False (None 이 아니다)
    assert external_login.features_from_scopes(BASIC_SCOPE) == {f: False for f in FEATURES}
    # 대안 묶음: Mail.ReadWrite 도 읽기 대안, 발송은 Mail.Send 필수 / teams 는 Chat.Read + ChatMessage.Send 조합도 가능
    f = external_login.features_from_scopes(f"{GRAPH}Mail.ReadWrite {GRAPH}Chat.Read {GRAPH}ChatMessage.Send {GRAPH}Notes.ReadWrite {GRAPH}Tasks.ReadWrite.Shared")
    assert f == {"mail": False, "teams": True, "onenote": True, "calendar": False, "todo": False}
    assert external_login.features_from_scopes(f"{GRAPH}Mail.Read {GRAPH}Mail.Send")["mail"] is True
    # 접두 제거·중복 제거·순서 유지, 목록 입력도 받는다
    assert external_login.parse_granted_scopes(f"{GRAPH}Mail.Read openid {GRAPH}Mail.Read") == ["Mail.Read", "openid"]
    assert external_login.parse_granted_scopes(["Tasks.ReadWrite"]) == ["Tasks.ReadWrite"]
    assert external_login.parse_granted_scopes("   ") is None and external_login.features_from_scopes(None) is None


# ----------------------------------------------------------------------
# 인증 오류 분류 — 갱신 거부 표식과 reason 코드
# ----------------------------------------------------------------------
async def test_refresh_invalid_grant_marks_reauth_and_transient_does_not(mgr):
    db = mgr.auth_db
    db.save_token("a@contoso.com", {"access_token": "old", "refresh_token": "r", "expires_at": PAST, "scope": FULL_SCOPE})
    db.save_token("b@contoso.com", {"access_token": "old", "refresh_token": "r", "expires_at": PAST, "scope": FULL_SCOPE})

    mgr.fake.post_queue = [_Resp(400, {"error": "invalid_grant", "error_description": "AADSTS50173 SECRET"})]
    result = await mgr.refresh_token("a@contoso.com")
    assert result["status"] == "reauth_required" and result["reason"] == "reauth_required"
    assert "SECRET" not in json.dumps(result)
    assert mgr.connection_state("a@contoso.com")["state"] == "reauth_required"
    status = mgr.get_token_status("a@contoso.com")
    assert status["state"] == "reauth_required" and status["refresh_state"] == "reauth_required"
    assert status["needs_reauth"] is False  # 기존 키의 의미는 바꾸지 않는다(refresh 만료 전) — state 가 정확한 값
    token = await mgr.get_token("a@contoso.com")
    assert token["refresh_state"] == "reauth_required"

    # 일시 장애(503) → transient, 표식 없음, 상태는 여전히 connected(갱신 재시도 가능)
    mgr.fake.post_queue = [_Resp(503, {"error": "temporarily_unavailable"})]
    result_b = await mgr.refresh_token("b@contoso.com")
    assert result_b["status"] == "error" and result_b["reason"] == "transient"
    assert mgr.connection_state("b@contoso.com")["state"] == "connected"

    # validate_and_refresh_token 은 종전대로 None (반환 형태 불변), 표식은 유지
    mgr.fake.post_queue = [_Resp(400, {"error": "invalid_grant"})]
    assert await mgr.validate_and_refresh_token("a@contoso.com") is None
    assert mgr.connection_state("a@contoso.com")["state"] == "reauth_required"

    # 재로그인(외부 위임, 새 refresh) → 표식 해제 → connected
    mgr.fake.post_queue = [_Resp(200, tok(refresh="r-new", access="a-new"))]
    mgr.fake.get_queue = [_Resp(200, {**ME, "mail": "a@contoso.com", "userPrincipalName": "a@contoso.com"})]
    relogin = await mgr.complete_external_login("code", REDIRECT)
    assert relogin["email"] == "a@contoso.com" and relogin["state"] == "connected"
    assert mgr.connection_state("a@contoso.com")["state"] == "connected"


async def test_check_and_refresh_reason_keys(mgr):
    svc = mgr.auth_service
    db = mgr.auth_db

    none = await svc.check_and_refresh_if_needed("nobody@contoso.com")
    assert none["status"] == "error" and none["reason"] == "not_connected"

    db.save_token("ok@contoso.com", {"access_token": "a", "refresh_token": "r", "expires_at": FUTURE})
    assert (await svc.check_and_refresh_if_needed("ok@contoso.com"))["reason"] == "ok"

    db.save_token("norefresh@contoso.com", {"access_token": "a", "expires_at": PAST})
    needs = await svc.check_and_refresh_if_needed("norefresh@contoso.com")
    assert needs["status"] == "auth_required" and needs["reason"] == "reauth_required"

    db.save_token("revoked@contoso.com", {"access_token": "a", "refresh_token": "r", "expires_at": PAST})
    mgr.fake.post_queue = [_Resp(400, {"error": "invalid_grant"})]
    revoked = await svc.check_and_refresh_if_needed("revoked@contoso.com")
    assert revoked["status"] == "error" and revoked["reason"] == "reauth_required"
    assert mgr.connection_state("revoked@contoso.com")["state"] == "reauth_required"

    db.save_token("flaky@contoso.com", {"access_token": "a", "refresh_token": "r", "expires_at": PAST})
    mgr.fake.post_queue = [_Resp(500, {"error": "server_error"})]
    flaky = await svc.check_and_refresh_if_needed("flaky@contoso.com")
    assert flaky["status"] == "error" and flaky["reason"] == "transient"
    assert mgr.connection_state("flaky@contoso.com")["state"] == "connected"

    mgr.fake.post_queue = [_Resp(200, {**tok(refresh="r2", access="a2")})]
    refreshed = await svc.check_and_refresh_if_needed("flaky@contoso.com")
    assert refreshed["status"] == "refreshed" and refreshed["reason"] == "ok"


def test_token_refresh_error_classification():
    from session.auth_service import TokenRefreshError, refresh_failure_reason

    assert TokenRefreshError("x", code="invalid_grant").reauth_required is True
    assert TokenRefreshError("x", code="interaction_required").reauth_required is True
    assert TokenRefreshError("x", code="temporarily_unavailable").reauth_required is False
    assert refresh_failure_reason(TokenRefreshError("x", code="invalid_grant")) == "reauth_required"
    assert refresh_failure_reason(RuntimeError("socket closed")) == "transient"
    assert refresh_failure_reason(Exception("Refresh token expired or revoked (invalid_grant)")) == "reauth_required"


# ----------------------------------------------------------------------
# auth.db 선택 컬럼 보강 — idempotent, mode 0 전용
# ----------------------------------------------------------------------
OLD_SCHEMA = """
CREATE TABLE azure_user_info (user_email TEXT PRIMARY KEY, object_id TEXT UNIQUE, display_name TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE azure_token_info (user_email TEXT PRIMARY KEY, access_token TEXT NOT NULL, refresh_token TEXT,
  access_token_expires_at TIMESTAMP NOT NULL, refresh_token_expires_at TIMESTAMP, id_token TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
"""


def _columns(path):
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(azure_token_info)")}
    finally:
        conn.close()


def _old_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO azure_token_info (user_email, access_token, refresh_token, access_token_expires_at) VALUES (?, ?, ?, ?)",
                 ("old@contoso.com", "a", "r", FUTURE))
    conn.commit()
    conn.close()


def test_optional_columns_added_idempotently_in_mode0(tmp_path, monkeypatch):
    from session.auth_database import AuthDatabase

    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    path = str(tmp_path / "old.db")
    _old_db(path)
    assert "scope" not in _columns(path)

    with single_user_mode():
        db = AuthDatabase(path)
        assert _columns(path) >= {"scope", "refresh_state"}
        assert db._optional_columns == {"scope", "refresh_state"}
        AuthDatabase(path)  # 두 번째 열기 — 오류 없음
        # 기존 행은 scope 모름 → None, 저장은 그대로 동작
        row = db.get_token("old@contoso.com")
        assert row["scope"] is None and row["refresh_state"] is None
        assert db.save_token("old@contoso.com", {"access_token": "a2", "refresh_token": "r2", "expires_at": FUTURE, "scope": FULL_SCOPE})
        assert db.get_token("old@contoso.com")["refresh_state"] == "ok"
        assert db.mark_refresh_state("old@contoso.com", "reauth_required") is True
        assert db.mark_refresh_state("old@contoso.com", "weird") is False
        assert db.mark_refresh_state("missing@contoso.com", "ok") is False
        assert db.canonical_email("OLD@contoso.com") == "old@contoso.com" and db.canonical_email("x@y") is None


def test_optional_columns_not_added_in_multi_user_legacy_read(tmp_path, monkeypatch):
    """mode 1 에서 이전 도구가 여는 명시 legacy 경로는 고치지 않는다(fingerprint 보존)."""
    from session.auth_database import AuthDatabase

    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    path = str(tmp_path / "legacy" / "auth.db")
    (tmp_path / "legacy").mkdir()
    _old_db(path)
    with multi_user_mode(tmp_path / "data"):
        db = AuthDatabase(path)
    assert "scope" not in _columns(path) and "refresh_state" not in _columns(path)
    assert db._optional_columns == set()


def test_mark_refresh_state_without_column_is_noop(tmp_path, monkeypatch):
    from session.auth_database import AuthDatabase

    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    with single_user_mode():
        db = AuthDatabase(str(tmp_path / "auth.db"))
        db.save_token("u@contoso.com", {"access_token": "a", "refresh_token": "r", "expires_at": FUTURE})
        db._optional_columns = set()  # 컬럼 추가에 실패한 상황을 흉내
        assert db.mark_refresh_state("u@contoso.com", "reauth_required") is False
        assert db.save_token("u@contoso.com", {"access_token": "a2", "expires_at": FUTURE})  # SQL 에 refresh_state 미포함


# ----------------------------------------------------------------------
# mode 1 거부
# ----------------------------------------------------------------------
async def test_external_login_refuses_in_multi_user(tmp_path):
    from session.mode_guard import LegacyAuthDisabledError

    with multi_user_mode(tmp_path / "data"):
        with pytest.raises(LegacyAuthDisabledError):
            external_login.connection_state(object(), "a@contoso.com")
        with pytest.raises(LegacyAuthDisabledError):
            await external_login.complete_external_login(object(), "code", REDIRECT)
