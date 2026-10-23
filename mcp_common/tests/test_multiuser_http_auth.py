"""WP1 멀티유저 HTTP 인증 관문·stateless 정책·SDK identity 브리지 (spec/spec_멀티유저.md ②-4.4, ②-10).

실제 SDK 경로(`StreamableHTTPSessionManager(stateless=True)` → lowlevel `Server` →
`ToolRuntime`)를 Starlette `TestClient` 로 통과시킨다. registry 는 키 문자열 → principal
가짜(`FakeRegistry`)를 주입한다.

| ID | 검증 |
|----|------|
| I01 | 무인증 initialize/list/call/notification/GET/DELETE → 401, 핸들러·factory 0회 |
| I02 | A 키 + B `user_email` → `identity_mismatch` |
| I04 | `user_email` null·""·공백·비문자열 → `invalid_user_email` |
| I06 | `db_path`·`user_key` 등 추가 인자 → `unexpected_argument` |
| I07 | scope 부족·비활성 → 403 |
| I08 | `Mcp-Session-Id` → 400, 위조 `X-User-*` 헤더 무시 |
"""

import json
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

import pytest
from mcp.server.lowlevel import Server
from starlette.testclient import TestClient

from mcp_common import http_identity, mcp_identity_bridge, service_pool
from mcp_common.http_transport import build_starlette_app
from mcp_common.mcp_identity_bridge import identity_from_request_context
from mcp_common.principal import bind_identity, current_identity, require_principal, scope_for_domain
from mcp_common.runtime import ToolRuntime
from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError
from mcp_common.security_policy import CONFLICTING_ENV
from mcp_common.service_context import current_service
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import TEST_AUTH_ENV, FakeTokenProvider, make_principal, multi_user_mode, single_user_mode
from mcp_common.user_resolver import resolve_user_email


@pytest.fixture(autouse=True)
def _auth_layer_env(monkeypatch):
    """mode 1 기동 검사가 인증 계층(KEK·앱 설정)까지 보므로 테스트용 설정을 깐다."""
    for key, value in TEST_AUTH_ENV.items():
        monkeypatch.setenv(key, value)


SERVER = "wp1http"
SCOPES = {scope_for_domain(SERVER)}

ALICE = make_principal("alice@contoso.com", scopes=SCOPES)
BOB = make_principal("bob@fabrikam.com", scopes=SCOPES)
CAROL = make_principal("carol@contoso.com", scopes={scope_for_domain("calendar")})  # 다른 도메인 키
DAVE = make_principal("dave@contoso.com", scopes=SCOPES)  # 비활성 계정

KEY_A = "m365v1." + "a" * 32 + ".alice-SECRET-value"
KEY_B = "m365v1." + "b" * 32 + ".bob-SECRET-value"
KEY_C = "m365v1." + "c" * 32 + ".carol-SECRET-value"
KEY_D = "m365v1." + "d" * 32 + ".dave-SECRET-value"

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT_PARAMS = {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {"name": "t", "version": "0"},
}

TOOLS = [
    {
        "name": "whoami",
        "description": "현재 호출자",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_email": {"type": "string", "description": "본인 계정"},
                "note": {"type": "string", "description": "테스트 동작 선택"},
            },
        },
    }
]

# 허용 목록·충돌 설정이 개발 환경 값에 흔들리지 않게 비운다
_ENV_TO_CLEAR = (
    *CONFLICTING_ENV,
    "MCP_VALIDATE_INPUT",
    "MS365_MAX_REQUEST_BYTES",
    "MCP_BIND_HOST",
    "MCP_ALLOWED_HOSTS",
    "MCP_ALLOWED_ORIGINS",
)


class FakeRegistry:
    """`session.identity_registry` 가짜 — 키 문자열 → principal."""

    def __init__(self) -> None:
        self.keys = {KEY_A: ALICE, KEY_B: BOB, KEY_C: CAROL, KEY_D: DAVE}
        self.inactive = {DAVE.user_key}
        self.revoked = set()  # 인증 뒤(런타임 재확인)에만 보이는 폐기
        self.auth_calls: List[str] = []
        self.active_calls: List[str] = []

    async def authenticate(self, authorization: str, *, domain: str):
        self.auth_calls.append(domain)
        _, _, key = authorization.partition(" ")
        principal = self.keys.get(key.strip())
        if principal is None:
            # 예외 문구에 키를 넣어도 응답으로 새면 안 된다
            raise SecurityError(ErrorCode.UNAUTHENTICATED, f"unknown key {key}")
        if principal.user_key in self.inactive:
            raise SecurityError(ErrorCode.ACCOUNT_INACTIVE, f"inactive {principal.graph_email}")
        if not principal.has_scope(domain):
            raise SecurityError(ErrorCode.FORBIDDEN_SCOPE)
        return principal

    async def assert_active(self, principal) -> None:
        self.active_calls.append(principal.user_key)
        if principal.user_key in self.inactive or principal.user_key in self.revoked:
            raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)


class _Service:
    def __init__(self, principal) -> None:
        self.principal = principal
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Lifecycle:
    server_name = SERVER
    errors = ["C:\\secret\\path failed"]  # mode 1 health 가 싣지 않아야 한다
    healthy = False

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


class Harness:
    def __init__(self) -> None:
        self.registry = FakeRegistry()
        self.handler_calls: List[Dict[str, Any]] = []
        self.factory_calls: List[str] = []
        self.services: List[_Service] = []
        self.client: Optional[TestClient] = None

    async def create_service(self, principal, paths, tokens):
        self.factory_calls.append(principal.user_key)
        assert tokens.user_key == principal.user_key
        service = _Service(principal)
        self.services.append(service)
        return service

    def whoami(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self.handler_calls.append(dict(args))
        note = args.get("note")
        if note == "boom":
            raise RuntimeError("C:\\Users\\alice\\secret.db token=abc123")
        if note == "revoke":
            self.registry.revoked.add(require_principal().user_key)
        service = current_service(SERVER)
        identity = current_identity()
        bridged = identity_from_request_context()
        return {
            "user_key": require_principal().user_key,
            "service_user": service.principal.user_key,
            "email": resolve_user_email(args.get("user_email"), required=True),
            "request_id": identity.request_id,
            "bridged": bridged is not None and bridged.request_id == identity.request_id,
        }


def _mcp_server(runtime: ToolRuntime) -> Server:
    server = Server(SERVER)
    tool_objects = runtime.build_tool_objects()

    @server.list_tools()
    async def _list_tools():
        return tool_objects

    @server.call_tool(validate_input=False)
    async def _call_tool(name, arguments):
        return await runtime.dispatch(name, arguments)

    return server


@contextmanager
def running(tmp_path, monkeypatch, **env: str) -> Iterator[Harness]:
    for key in _ENV_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    harness = Harness()
    pool = UserServicePool(token_provider_factory=FakeTokenProvider)
    pool.register(SERVER, harness.create_service)
    monkeypatch.setattr(service_pool, "_pool", pool)
    with multi_user_mode(tmp_path):
        runtime = ToolRuntime(SERVER, TOOLS, {"whoami": harness.whoami})
        app = build_starlette_app(
            SERVER,
            _mcp_server(runtime),
            runtime,
            _Lifecycle(),
            version="9.9.9",
            authenticator=harness.registry.authenticate,
            active_checker=harness.registry.assert_active,
        )
        with TestClient(app, base_url="http://127.0.0.1:5999") as client:
            harness.client = client
            yield harness


@pytest.fixture
def h(tmp_path, monkeypatch) -> Iterator[Harness]:
    with running(tmp_path, monkeypatch) as harness:
        yield harness


def rpc(method: str, params: Optional[Dict[str, Any]] = None, msg_id: Optional[int] = 1) -> Dict[str, Any]:
    message: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        message["id"] = msg_id
    if params is not None:
        message["params"] = params
    return message


def post(client: TestClient, body: Any, key: Optional[str] = None, **extra: str):
    headers = dict(HEADERS)
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    headers.update(extra)
    return client.post("/mcp", json=body, headers=headers)


def rpc_result(response) -> Dict[str, Any]:
    """stateless 응답(SSE `data:` 또는 JSON)에서 JSON-RPC 메시지를 꺼낸다."""
    assert response.status_code == 200, response.text
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return response.json()


def call_tool(client: TestClient, key: str, arguments: Optional[Dict[str, Any]] = None, name: str = "whoami"):
    message = rpc_result(post(client, rpc("tools/call", {"name": name, "arguments": arguments or {}}), key))
    result = message["result"]
    payload = json.loads(result["content"][0]["text"])
    return result.get("isError", False), payload


def _assert_auth_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == code
    assert "SECRET" not in response.text and "@" not in response.text


# ----------------------------------------------------------------------
# I01 — 무인증 요청은 SDK·핸들러·factory 에 닿지 않는다
# ----------------------------------------------------------------------
UNAUTHENTICATED_REQUESTS = [
    ("POST", rpc("initialize", INIT_PARAMS)),
    ("POST", rpc("tools/list")),
    ("POST", rpc("tools/call", {"name": "whoami", "arguments": {}})),
    ("POST", rpc("notifications/initialized", msg_id=None)),
    ("GET", None),
    ("DELETE", None),
]

BAD_AUTHORIZATION = [
    None,
    "",
    "Bearer",
    "Bearer ",
    "Basic YWxpY2U6cHc=",
    "Bearer m365v1." + "e" * 32 + ".unknown-SECRET",
    f"Bearer {KEY_A} trailing",
    f"Token {KEY_A}",
]


@pytest.mark.parametrize("method,body", UNAUTHENTICATED_REQUESTS)
@pytest.mark.parametrize("authorization", BAD_AUTHORIZATION)
def test_i01_unauthenticated_requests_never_reach_sdk(h, method, body, authorization):
    headers = dict(HEADERS)
    if authorization is not None:
        headers["Authorization"] = authorization
    if method == "POST":
        r = h.client.post("/mcp", json=body, headers=headers)
    else:
        r = h.client.request(method, "/mcp", headers=headers)
    _assert_auth_error(r, 401, ErrorCode.UNAUTHENTICATED)
    assert r.headers.get("www-authenticate") == "Bearer"
    assert h.handler_calls == [] and h.factory_calls == []
    assert h.registry.active_calls == []


def test_i01_duplicate_authorization_headers_rejected(h):
    headers = [(k, v) for k, v in HEADERS.items()]
    headers += [("Authorization", f"Bearer {KEY_A}"), ("Authorization", f"Bearer {KEY_B}")]
    r = h.client.post("/mcp", json=rpc("tools/list"), headers=headers)
    _assert_auth_error(r, 401, ErrorCode.UNAUTHENTICATED)
    assert h.registry.auth_calls == []  # 형식 단계에서 끝난다


def test_host_and_origin_checked_before_authentication(h):
    r = post(h.client, rpc("tools/list"), KEY_A, Host="evil.example:5999")
    assert r.status_code == 421
    r = post(h.client, rpc("tools/list"), KEY_A, Origin="http://evil.example")
    assert r.status_code == 403
    assert h.registry.auth_calls == []


def test_oversized_request_rejected_before_authentication(tmp_path, monkeypatch):
    with running(tmp_path, monkeypatch, MS365_MAX_REQUEST_BYTES="256") as h:
        big = rpc("tools/call", {"name": "whoami", "arguments": {"note": "x" * 1024}})
        r = post(h.client, big)  # 키 없음 — 그래도 413 이 먼저
        assert r.status_code == 413
        assert r.json()["error"] == "request_too_large"
        assert h.registry.auth_calls == []
        # 작은 요청은 정상 처리
        assert call_tool(h.client, KEY_A)[0] is False


def test_unauthenticated_error_does_not_leak_registry_message(h):
    r = post(h.client, rpc("tools/list"), "m365v1." + "f" * 32 + ".zzz-SECRET")
    _assert_auth_error(r, 401, ErrorCode.UNAUTHENTICATED)
    assert "unknown key" not in r.text


# ----------------------------------------------------------------------
# I07 — scope 부족·비활성 → 403
# ----------------------------------------------------------------------
def test_i07_scope_insufficient_is_403(h):
    r = post(h.client, rpc("tools/call", {"name": "whoami", "arguments": {}}), KEY_C)
    _assert_auth_error(r, 403, ErrorCode.FORBIDDEN_SCOPE)
    assert h.handler_calls == [] and h.factory_calls == []


def test_i07_inactive_account_is_403(h):
    r = post(h.client, rpc("tools/call", {"name": "whoami", "arguments": {}}), KEY_D)
    _assert_auth_error(r, 403, ErrorCode.ACCOUNT_INACTIVE)
    assert h.handler_calls == [] and h.factory_calls == []


def test_authenticator_returning_wrong_scope_principal_is_rejected(tmp_path, monkeypatch):
    """registry 가 scope 를 확인하지 않아도 관문이 한 번 더 막는다."""
    with running(tmp_path, monkeypatch) as h:

        async def lax(authorization, *, domain):
            return CAROL

        h.client.app.router.routes[0].app._authenticate = lax  # Route("/mcp") → BearerAuthMiddleware
        r = post(h.client, rpc("tools/list"), KEY_A)
        _assert_auth_error(r, 403, ErrorCode.FORBIDDEN_SCOPE)


def test_authenticator_crash_is_generic_500(tmp_path, monkeypatch):
    with running(tmp_path, monkeypatch) as h:

        async def broken(authorization, *, domain):
            raise RuntimeError("db at C:\\data\\registry.db is locked")

        h.client.app.router.routes[0].app._authenticate = broken
        r = post(h.client, rpc("tools/list"), KEY_A)
        _assert_auth_error(r, 500, ErrorCode.INTERNAL_ERROR)
        assert "registry.db" not in r.text


# ----------------------------------------------------------------------
# I08 — stateless 정책·위조 헤더
# ----------------------------------------------------------------------
def test_i08_session_id_header_rejected_after_auth(h):
    r = post(h.client, rpc("tools/list"), KEY_A, **{"Mcp-Session-Id": "b-session-123"})
    assert r.status_code == 400
    assert r.json()["error"] == "session_not_supported"
    assert h.handler_calls == []


@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_get_and_delete_are_405_after_auth(h, method):
    r = h.client.request(method, "/mcp", headers={**HEADERS, "Authorization": f"Bearer {KEY_A}"})
    assert r.status_code == 405
    assert r.headers.get("allow") == "POST"


def test_i08_forged_user_headers_are_ignored(h):
    forged = {
        "X-User-Email": BOB.graph_email,
        "X-User-Key": BOB.user_key,
        "X-Forwarded-User": BOB.graph_email,
    }
    is_error, payload = None, None
    message = rpc_result(post(h.client, rpc("tools/call", {"name": "whoami", "arguments": {}}), KEY_A, **forged))
    payload = json.loads(message["result"]["content"][0]["text"])
    is_error = message["result"].get("isError", False)
    assert is_error is False
    assert payload["user_key"] == ALICE.user_key
    assert payload["email"] == ALICE.graph_email


def test_initialize_is_stateless_and_issues_no_session_id(h):
    r = post(h.client, rpc("initialize", INIT_PARAMS), KEY_A)
    message = rpc_result(r)
    assert message["result"]["serverInfo"]["name"] == SERVER
    assert "mcp-session-id" not in {k.lower() for k in r.headers}


def test_tools_list_with_valid_key(h):
    message = rpc_result(post(h.client, rpc("tools/list"), KEY_B))
    assert [t["name"] for t in message["result"]["tools"]] == ["whoami"]


def test_notification_with_valid_key_is_accepted(h):
    r = post(h.client, rpc("notifications/initialized", msg_id=None), KEY_A)
    assert r.status_code == 202


# ----------------------------------------------------------------------
# 실제 SDK 경로 — 키별 principal·서비스 분리
# ----------------------------------------------------------------------
def test_sdk_path_each_key_gets_its_own_principal_and_service(h):
    seen = []
    for key, principal in ((KEY_A, ALICE), (KEY_B, BOB), (KEY_A, ALICE), (KEY_B, BOB)):
        is_error, payload = call_tool(h.client, key)
        assert is_error is False, payload
        assert payload["user_key"] == principal.user_key
        assert payload["service_user"] == principal.user_key
        assert payload["email"] == principal.graph_email
        assert len(payload["request_id"]) == 32
        seen.append(payload["request_id"])
        assert payload["bridged"] is True  # SDK request scope 에서 읽은 identity 다
    assert len(set(seen)) == 4  # 요청마다 서버가 새 request_id 를 만든다
    # 사용자별 서비스는 1번씩만 만들어지고 재사용된다
    assert sorted(h.factory_calls) == sorted([ALICE.user_key, BOB.user_key])
    # 런타임이 실행 전·후로 계정 상태를 재확인했다
    # tools/call 1건당 활성 검사 3회 — 진입 전, lease 획득 후(R01 재검사), 응답 전
    assert h.registry.active_calls.count(ALICE.user_key) == 6


def test_identity_comes_from_request_scope_not_contextvar_propagation(tmp_path, monkeypatch):
    """관문의 ContextVar 가 SDK task 로 전파되지 않아도 request scope 브리지로 동작한다."""

    @contextmanager
    def no_bind(identity):
        yield identity

    monkeypatch.setattr(http_identity, "bind_identity", no_bind)
    with running(tmp_path, monkeypatch) as h:
        is_error, payload = call_tool(h.client, KEY_B)
        assert is_error is False, payload
        assert payload["user_key"] == BOB.user_key and payload["bridged"] is True


def test_conflicting_contextvar_identity_is_rejected(tmp_path, monkeypatch):
    """scope 는 A 인데 전파된 ContextVar 가 B 면 어느 쪽도 믿지 않는다."""
    from mcp_common.testing import make_identity

    @contextmanager
    def bind_other(identity):
        with bind_identity(make_identity(BOB)):
            yield identity

    monkeypatch.setattr(http_identity, "bind_identity", bind_other)
    with running(tmp_path, monkeypatch) as h:
        is_error, payload = call_tool(h.client, KEY_A)
        assert is_error is True
        assert payload["error"] == ErrorCode.MISSING_PRINCIPAL
        assert h.handler_calls == [] and h.factory_calls == []


def test_email_match_is_normalized_and_returns_stored_form(h):
    is_error, payload = call_tool(h.client, KEY_A, {"user_email": "  ALICE@Contoso.com "})
    assert is_error is False
    assert payload["email"] == "alice@contoso.com"


# ----------------------------------------------------------------------
# I02 / I04 / I06 — 도구 오류(isError)
# ----------------------------------------------------------------------
def test_i02_other_users_email_is_identity_mismatch(h):
    is_error, payload = call_tool(h.client, KEY_A, {"user_email": BOB.graph_email})
    assert is_error is True
    assert payload["error"] == ErrorCode.IDENTITY_MISMATCH
    assert h.handler_calls == [] and h.factory_calls == []


@pytest.mark.parametrize("value", [None, "", "   ", 123, ["alice@contoso.com"]])
def test_i04_invalid_user_email_values(h, value):
    is_error, payload = call_tool(h.client, KEY_A, {"user_email": value})
    assert is_error is True
    assert payload["error"] == ErrorCode.INVALID_USER_EMAIL
    assert h.handler_calls == []


@pytest.mark.parametrize("extra", ["db_path", "user_key", "principal", "tenant_id", "token"])
def test_i06_injected_security_arguments_rejected(h, extra):
    is_error, payload = call_tool(h.client, KEY_A, {extra: "forged"})
    assert is_error is True
    assert payload["error"] == ErrorCode.UNEXPECTED_ARGUMENT
    assert payload["arguments"] == [extra]
    assert h.handler_calls == [] and h.factory_calls == []


def test_internal_error_is_masked_with_request_id(h):
    is_error, payload = call_tool(h.client, KEY_A, {"note": "boom"})
    assert is_error is True
    assert payload["error"] == ErrorCode.INTERNAL_ERROR
    assert len(payload["request_id"]) == 32
    text = json.dumps(payload)
    assert "secret" not in text and "abc123" not in text and "RuntimeError" not in text


def test_revocation_during_call_withholds_result(h):
    is_error, payload = call_tool(h.client, KEY_A, {"note": "revoke"})
    assert is_error is True
    assert payload["error"] == ErrorCode.ACCOUNT_INACTIVE
    assert "user_key" not in payload
    # 이후 호출도 런타임 재확인에서 막힌다 (registry 가 아직 401/403 을 주지 않는 창)
    is_error, payload = call_tool(h.client, KEY_A)
    assert is_error is True and payload["error"] == ErrorCode.ACCOUNT_INACTIVE
    # B 는 영향 없음
    assert call_tool(h.client, KEY_B)[0] is False


# ----------------------------------------------------------------------
# /health · 기동 검사 · mode 0 회귀
# ----------------------------------------------------------------------
def test_health_is_minimal_in_multi_user_mode(h):
    r = h.client.get("/health")
    assert r.status_code == 503  # 상태 판정(degraded)은 유지하되 사유는 싣지 않는다
    assert set(r.json()) == {"status", "server", "version"}
    assert r.json()["server"] == SERVER and r.json()["version"] == "9.9.9"
    assert "secret" not in r.text


def test_shutdown_closes_service_pool(tmp_path, monkeypatch):
    with running(tmp_path, monkeypatch) as h:
        assert call_tool(h.client, KEY_A)[0] is False
        assert h.services and not h.services[0].closed
    assert h.services[0].closed  # TestClient 종료 = lifespan shutdown


def _build(tmp_path, **kwargs):
    runtime = ToolRuntime(SERVER, TOOLS, {"whoami": lambda a: "ok"})
    return build_starlette_app(SERVER, _mcp_server(runtime), runtime, _Lifecycle(), **kwargs)


def test_startup_fails_on_conflicting_config(tmp_path, monkeypatch):
    for key in _ENV_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MS365_DEFAULT_USER_EMAIL", "operator@contoso.com")
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            _build(tmp_path, authenticator=FakeRegistry().authenticate,
                   active_checker=FakeRegistry().assert_active)


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_startup_fails_on_bad_request_limit(tmp_path, monkeypatch, value):
    for key in _ENV_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MS365_MAX_REQUEST_BYTES", value)
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            _build(tmp_path, authenticator=FakeRegistry().authenticate,
                   active_checker=FakeRegistry().assert_active)


def test_startup_fails_when_default_registry_unavailable(tmp_path, monkeypatch):
    for key in _ENV_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mcp_identity_bridge, "_REGISTRY_MODULE", "session._no_such_registry_wp1")
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            _build(tmp_path)  # 기본 authenticator·active_checker 를 쓰려 함


def test_mode0_app_is_unchanged(monkeypatch):
    """B01 — mode 0 은 인증 없이 SDK 로 가고(stateful), health 도 기존 형식이다."""
    for key in _ENV_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    with single_user_mode():
        runtime = ToolRuntime(SERVER, TOOLS, {"whoami": lambda a: "ok"})
        app = build_starlette_app(SERVER, _mcp_server(runtime), runtime, _Lifecycle(), version="1.2.3")
        with TestClient(app, base_url="http://127.0.0.1:5999") as client:
            r = client.post("/mcp", json=rpc("initialize", INIT_PARAMS), headers=HEADERS)
            assert r.status_code == 200
            assert r.headers.get("mcp-session-id")  # stateful 세션
            health = client.get("/health").json()
            assert health["tool_count"] == 1 and health["protocol"] == "streamable-http"
            assert "errors" in health
