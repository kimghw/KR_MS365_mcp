"""WP1 멀티유저 런타임 — 호출 순서·컨텍스트 격리·사용자 해석·stdio 거부 (spec/spec_멀티유저.md ②-5, ②-10).

| ID | 검증 |
|----|------|
| C01 | A/B 호출을 await 경계에서 교차 실행 — principal·서비스·응답이 섞이지 않음 |
| C02 | 예외·취소 후 다음 요청에 이전 identity·서비스가 남지 않음 |
| I03 | 이메일 생략 → 현재 principal 만, 환경변수·legacy DB 조회 0회 |
| B01 | mode 0 런타임·resolver·검증 스위치 기존 동작 |
| B02 | mode 1 stdio 기동 거부 |
"""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

import mcp_common.auth as common_auth
from mcp_common import audit as audit_module
from mcp_common import service_pool
from mcp_common.errors import ToolExecutionError, ToolValidationError
from mcp_common.mcp_identity_bridge import (
    IDENTITY_STATE_KEY,
    identity_from_request_context,
    resolve_request_identity,
)
from mcp_common.principal import current_identity, require_principal
from mcp_common.runtime import ToolRuntime
from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError
from mcp_common.service_context import current_service
from mcp_common.service_pool import UserServicePool
from mcp_common.stdio_transport import run_stdio, serve_stdio
from mcp_common.testing import (
    FakeTokenProvider,
    bound,
    make_identity,
    make_principal,
    multi_user_mode,
    single_user_mode,
)
from mcp_common.user_resolver import UserResolver
from mcp_common.validation import validate_arguments, validation_enabled

DOMAIN = "wp1rt"
ALICE = make_principal("alice@contoso.com")
BOB = make_principal("bob@fabrikam.com")
NO_EMAIL = make_principal(None, object_id="00000000-0000-0000-0000-00000000c0de")

SCHEMA = {
    "type": "object",
    "properties": {
        "user_email": {"type": "string"},
        "count": {"type": "integer", "default": 5},
        "flag": {"type": "string", "enum": ["enabled", "disabled"]},
        "query": {"type": "string"},
    },
}
REQUIRED_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


def _payload(exc: ToolExecutionError) -> Dict[str, Any]:
    return json.loads(str(exc))


class Checker:
    """active_checker 가짜 — 호출 순서를 기록한다."""

    def __init__(self, events: List[str]) -> None:
        self.events = events
        self.inactive = set()

    async def __call__(self, principal) -> None:
        self.events.append("active")
        if principal.user_key in self.inactive:
            raise SecurityError(ErrorCode.ACCOUNT_INACTIVE)


@pytest.fixture
def mu(tmp_path, monkeypatch):
    """mode 1 + 빈 서비스 풀(이 테스트 도메인 factory 없음)."""
    monkeypatch.setattr(service_pool, "_pool", UserServicePool(token_provider_factory=FakeTokenProvider))
    with multi_user_mode(tmp_path):
        yield


def _runtime(handler, events=None, schema=SCHEMA, **kwargs) -> ToolRuntime:
    events = events if events is not None else []
    tools = [{"name": "t", "description": "d", "inputSchema": schema}]
    return ToolRuntime(DOMAIN, tools, {"t": handler}, active_checker=Checker(events), **kwargs)


# ----------------------------------------------------------------------
# identity 해석
# ----------------------------------------------------------------------
async def test_direct_call_without_identity_is_missing_principal(mu):
    calls = []
    runtime = _runtime(lambda a: calls.append(a) or "ok")
    with pytest.raises(SecurityError) as e:
        await runtime.call("t", {})
    assert e.value.code == ErrorCode.MISSING_PRINCIPAL
    assert calls == []


async def test_direct_call_uses_bound_identity(mu):
    runtime = _runtime(lambda a: require_principal().user_key)
    with bound(ALICE):
        blocks = await runtime.call("t", {})
    assert blocks == [{"type": "text", "text": ALICE.user_key}]


@contextmanager
def sdk_request(scope):
    """SDK `request_ctx` 에 HTTP request 가 연결된 상태를 흉내 낸다."""
    from mcp.server.lowlevel.server import request_ctx

    token = request_ctx.set(SimpleNamespace(request=SimpleNamespace(scope=scope)))
    try:
        yield
    finally:
        request_ctx.reset(token)


def test_bridge_reads_identity_from_request_scope():
    identity = make_identity(ALICE)
    with sdk_request({"state": {IDENTITY_STATE_KEY: identity}}):
        assert identity_from_request_context() is identity
        assert resolve_request_identity() is identity
    assert identity_from_request_context() is None


def test_bridge_conflict_with_bound_identity_is_rejected():
    with bound(BOB), sdk_request({"state": {IDENTITY_STATE_KEY: make_identity(ALICE)}}):
        with pytest.raises(SecurityError) as e:
            resolve_request_identity()
    assert e.value.code == ErrorCode.MISSING_PRINCIPAL


def test_bridge_same_identity_bound_and_in_scope_is_fine():
    """관문이 bind 한 ContextVar 가 SDK task 로 전파된 정상 경우."""
    from mcp_common.principal import bind_identity

    identity = make_identity(ALICE)
    with bind_identity(identity), sdk_request({"state": {IDENTITY_STATE_KEY: identity}}):
        assert resolve_request_identity() is identity


def test_bridge_same_user_but_different_request_is_rejected():
    """같은 사용자라도 다른 요청(request_id)의 컨텍스트가 섞이면 거부한다."""
    with bound(ALICE), sdk_request({"state": {IDENTITY_STATE_KEY: make_identity(ALICE)}}):
        with pytest.raises(SecurityError):
            resolve_request_identity()


@pytest.mark.parametrize(
    "scope",
    [{}, {"state": {}}, {"state": {IDENTITY_STATE_KEY: "forged"}}, {"state": None}, None],
)
def test_http_request_without_gateway_identity_is_rejected_even_if_bound(scope):
    """관문을 거치지 않은 HTTP 요청은 남아 있는 ContextVar 로 대체하지 않는다."""
    with bound(ALICE), sdk_request(scope):
        with pytest.raises(SecurityError) as e:
            resolve_request_identity()
    assert e.value.code == ErrorCode.MISSING_PRINCIPAL


def test_sdk_context_without_http_request_falls_back_to_bound():
    from mcp.server.lowlevel.server import request_ctx

    token = request_ctx.set(SimpleNamespace(request=None))
    try:
        with pytest.raises(SecurityError):
            resolve_request_identity()
        with bound(ALICE) as identity:
            assert resolve_request_identity() is identity
    finally:
        request_ctx.reset(token)


# ----------------------------------------------------------------------
# ②-5.4 호출 순서
# ----------------------------------------------------------------------
async def test_order_active_check_before_and_after_handler(mu):
    events: List[str] = []
    runtime = _runtime(lambda a: events.append("handler") or "ok", events)
    with bound(ALICE):
        await runtime.call("t", {})
    assert events == ["active", "handler", "active"]


async def test_inactive_account_blocks_before_handler(mu):
    events: List[str] = []
    runtime = _runtime(lambda a: events.append("handler") or "ok", events)
    runtime.active_checker.inactive.add(ALICE.user_key)
    with bound(ALICE):
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", {})
    assert e.value.code == ErrorCode.ACCOUNT_INACTIVE
    assert events == ["active"]


async def test_user_email_checked_before_unexpected_arguments(mu):
    runtime = _runtime(lambda a: "ok")
    with bound(ALICE):
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", {"user_email": None, "db_path": "C:/x.db"})
        assert e.value.code == ErrorCode.INVALID_USER_EMAIL
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", {"user_email": BOB.graph_email, "db_path": "C:/x.db"})
        assert e.value.code == ErrorCode.IDENTITY_MISMATCH


async def test_unexpected_argument_before_validation_and_defaults(mu):
    runtime = _runtime(lambda a: "ok", schema=REQUIRED_SCHEMA)
    with bound(ALICE):
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", {"user_key": ALICE.user_key})  # query 누락보다 먼저
    assert e.value.code == ErrorCode.UNEXPECTED_ARGUMENT
    assert _payload(e.value)["arguments"] == ["user_key"]


async def test_reported_unexpected_argument_names_are_bounded(mu):
    runtime = _runtime(lambda a: "ok")
    args = {f"x{i}" + "y" * 200: 1 for i in range(30)}
    with bound(ALICE):
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", args)
    names = _payload(e.value)["arguments"]
    assert len(names) == 10 and all(len(n) <= 64 for n in names)


async def test_boolean_coercion_defaults_and_validation_still_apply(mu, monkeypatch):
    monkeypatch.setenv("MCP_VALIDATE_INPUT", "0")  # mode 1 에서는 효과 없음
    seen = []
    runtime = _runtime(lambda a: seen.append(a) or "ok", validate=False)
    with bound(ALICE):
        await runtime.call("t", {"flag": True, "count": None})
        assert seen == [{"flag": "enabled", "count": 5}]
        with pytest.raises(ToolValidationError):
            await runtime.call("t", {"count": "many"})
    required = _runtime(lambda a: "ok", schema=REQUIRED_SCHEMA, validate=False)
    with bound(ALICE):
        with pytest.raises(ToolValidationError):
            await required.call("t", {})


async def test_unknown_tool_after_identity(mu):
    runtime = _runtime(lambda a: "ok")
    with pytest.raises(SecurityError):
        await runtime.call("nope", {})  # identity 가 먼저
    with bound(ALICE):
        with pytest.raises(ToolExecutionError) as e:
            await runtime.call("nope", {})
    assert _payload(e.value)["error"] == "unknown_tool"


async def test_handler_sees_stored_email_when_omitted(mu, monkeypatch):
    """I03 — 생략 시 principal 만. 환경변수·legacy DB 를 보지 않는다."""
    monkeypatch.setenv("MS365_DEFAULT_USER_EMAIL", "operator@contoso.com")

    class ExplodingDB:
        def list_users(self):
            raise AssertionError("legacy auth.db 를 조회했다")

    resolver = UserResolver(auth_database=ExplodingDB())
    runtime = _runtime(lambda a: resolver.resolve(a.get("user_email"), required=True))
    with bound(ALICE):
        assert (await runtime.call("t", {}))[0]["text"] == "alice@contoso.com"
        assert (await runtime.call("t", {"user_email": "ALICE@contoso.com"}))[0]["text"] == "alice@contoso.com"


# ----------------------------------------------------------------------
# 안전한 오류
# ----------------------------------------------------------------------
async def test_internal_exception_is_masked(mu):
    def handler(args):
        raise ValueError("refresh_token=SECRET at C:\\Users\\alice")

    runtime = _runtime(handler)
    with bound(ALICE, request_id="req-1234567890") as identity:
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", {})
    payload = _payload(e.value)
    assert payload["error"] == ErrorCode.INTERNAL_ERROR
    assert payload["request_id"] == identity.request_id
    assert "SECRET" not in str(e.value) and "ValueError" not in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


async def test_tool_execution_error_passes_through(mu):
    def handler(args):
        raise ToolExecutionError({"status": "error", "error": "graph_404"})

    runtime = _runtime(handler)
    with bound(ALICE):
        with pytest.raises(ToolExecutionError) as e:
            await runtime.call("t", {})
    assert _payload(e.value)["error"] == "graph_404"


async def test_failure_shaped_result_is_error(mu):
    runtime = _runtime(lambda a: {"success": False, "message": "no"})
    with bound(ALICE):
        with pytest.raises(ToolExecutionError):
            await runtime.call("t", {})


async def test_graph_not_connected_gets_connect_details(mu, monkeypatch):
    calls = []

    def details(principal):
        calls.append(principal.user_key)
        return {"connect_url": "https://gw.example/auth/start?t=1", "expires_in": 300, "error": "hijack"}

    monkeypatch.setattr(common_auth, "graph_connect_details", details, raising=False)
    runtime = _runtime(lambda a: "never")
    with bound(NO_EMAIL):
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", {"user_email": "x@contoso.com"})
    payload = _payload(e.value)
    assert payload["error"] == ErrorCode.GRAPH_NOT_CONNECTED  # 예약 키는 덮지 못한다
    assert payload["connect_url"].startswith("https://gw.example/")
    assert payload["expires_in"] == 300
    assert calls == [NO_EMAIL.user_key]


async def test_graph_reauth_from_handler_gets_async_connect_details(mu, monkeypatch):
    async def details(principal):
        return {"connect_url": "https://gw.example/auth/start?t=2", "expires_in": 300}

    monkeypatch.setattr(common_auth, "graph_connect_details", details, raising=False)

    def handler(args):
        raise SecurityError(ErrorCode.GRAPH_REAUTH_REQUIRED)

    runtime = _runtime(handler)
    with bound(ALICE):
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", {})
    assert _payload(e.value)["connect_url"].endswith("t=2")


async def test_connect_details_failure_keeps_original_error(mu, monkeypatch):
    def details(principal):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(common_auth, "graph_connect_details", details, raising=False)
    runtime = _runtime(lambda a: "never")
    with bound(NO_EMAIL):
        with pytest.raises(SecurityError) as e:
            await runtime.call("t", {"user_email": "x@contoso.com"})
    payload = _payload(e.value)
    assert payload["error"] == ErrorCode.GRAPH_NOT_CONNECTED and "connect_url" not in payload


async def test_tool_call_audit_has_no_email(mu, monkeypatch):
    records = []
    monkeypatch.setattr(audit_module, "audit", lambda event, **kw: records.append((event, kw)))
    runtime = _runtime(lambda a: "ok")
    with bound(ALICE, request_id="req-audit-0001"):
        await runtime.call("t", {})
        with pytest.raises(SecurityError):
            await runtime.call("t", {"user_email": BOB.graph_email})
    def leaky(args):
        raise ToolExecutionError({"status": "error", "error": "Graph said: token abc expired for alice@x"})

    runtime.handlers["t"] = leaky
    with bound(ALICE):
        with pytest.raises(ToolExecutionError):
            await runtime.call("t", {})
    assert records.pop()[1]["error_code"] == "tool_error"  # 예외 원문은 감사에 싣지 않는다
    events = [r[0] for r in records]
    assert events == ["tool.call", "tool.call", "auth.identity_mismatch"]
    assert records[0][1]["outcome"] == "success"
    assert records[1][1]["outcome"] == "denied"
    assert records[1][1]["error_code"] == ErrorCode.IDENTITY_MISMATCH
    assert records[1][1]["request_id"] == "req-audit-0001"
    for _, fields in records:
        # principal 객체는 audit() 가 user_key·credential_id·auth_epoch 만 꺼낸다
        assert fields["principal"] is ALICE
        assert not any("@" in str(v) for k, v in fields.items() if k != "principal")


# ----------------------------------------------------------------------
# C01 / C02 — 컨텍스트 격리
# ----------------------------------------------------------------------
class _Svc:
    def __init__(self, principal) -> None:
        self.principal = principal
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def pooled(tmp_path, monkeypatch):
    created: List[str] = []

    async def factory(principal, paths, tokens):
        await asyncio.sleep(0.01)  # 생성 중 경합 유도
        created.append(principal.user_key)
        assert tokens.user_key == principal.user_key
        return _Svc(principal)

    pool = UserServicePool(token_provider_factory=FakeTokenProvider)
    pool.register(DOMAIN, factory)
    monkeypatch.setattr(service_pool, "_pool", pool)
    with multi_user_mode(tmp_path):
        yield SimpleNamespace(pool=pool, created=created)


async def test_c01_interleaved_calls_keep_principals_apart(pooled):
    async def handler(args):
        before = require_principal().user_key
        await asyncio.sleep(0.001 * (args["count"] % 3))
        service = current_service(DOMAIN)
        await asyncio.sleep(0)
        return json.dumps({
            "before": before,
            "after": require_principal().user_key,
            "service": service.principal.user_key,
            "request_id": current_identity().request_id,
        })

    runtime = _runtime(handler)

    async def one(principal, i):
        with bound(principal, request_id=f"req-{principal.graph_email[:3]}-{i:04d}") as identity:
            blocks = await runtime.call("t", {"count": i})
        return principal, identity, json.loads(blocks[0]["text"])

    jobs = [one(ALICE if i % 2 else BOB, i) for i in range(40)]
    for principal, identity, out in await asyncio.gather(*jobs):
        assert out["before"] == out["after"] == out["service"] == principal.user_key
        assert out["request_id"] == identity.request_id
    assert sorted(pooled.created) == sorted([ALICE.user_key, BOB.user_key])  # 중복 생성 없음


async def test_c02_no_leftover_identity_or_service_after_exception(pooled):
    async def handler(args):
        assert current_service(DOMAIN).principal.user_key == require_principal().user_key
        if args.get("query") == "fail":
            raise RuntimeError("boom")
        return require_principal().user_key

    runtime = _runtime(handler)
    with bound(ALICE):
        with pytest.raises(SecurityError):
            await runtime.call("t", {"query": "fail"})
    assert current_identity() is None
    with pytest.raises(SecurityError) as e:
        current_service(DOMAIN)
    assert e.value.code == ErrorCode.MISSING_PRINCIPAL
    with pytest.raises(SecurityError) as e:
        await runtime.call("t", {})  # 이전 요청의 A 가 남아 있지 않다
    assert e.value.code == ErrorCode.MISSING_PRINCIPAL
    with bound(BOB):
        assert (await runtime.call("t", {}))[0]["text"] == BOB.user_key
    assert pooled.pool.stats()["leased"] == 0


async def test_c02_no_leftover_after_cancellation(pooled):
    started = asyncio.Event()

    async def handler(args):
        if args.get("query") == "hang":
            started.set()
            await asyncio.sleep(10)
        return require_principal().user_key

    runtime = _runtime(handler)

    async def hang():
        with bound(ALICE):
            await runtime.call("t", {"query": "hang"})

    task = asyncio.create_task(hang())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert current_identity() is None
    assert pooled.pool.stats()["leased"] == 0
    with bound(BOB):
        assert (await runtime.call("t", {}))[0]["text"] == BOB.user_key


# ----------------------------------------------------------------------
# user_resolver · validation 스위치
# ----------------------------------------------------------------------
def test_resolver_multi_user_uses_principal_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MS365_DEFAULT_USER_EMAIL", "operator@contoso.com")

    class ExplodingDB:
        def list_users(self):
            raise AssertionError("legacy auth.db 를 조회했다")

    resolver = UserResolver(auth_database=ExplodingDB())
    with multi_user_mode(tmp_path):
        with pytest.raises(SecurityError) as e:
            resolver.resolve(None)
        assert e.value.code == ErrorCode.MISSING_PRINCIPAL
        with bound(ALICE):
            assert resolver.resolve(None) == "alice@contoso.com"
            assert resolver.resolve(None, required=True) == "alice@contoso.com"
            assert resolver.default_email() == "alice@contoso.com"
            assert resolver.resolve(" Alice@Contoso.COM ") == "alice@contoso.com"
            for bad, code in (("", ErrorCode.INVALID_USER_EMAIL), ("  ", ErrorCode.INVALID_USER_EMAIL),
                              (BOB.graph_email, ErrorCode.IDENTITY_MISMATCH)):
                with pytest.raises(SecurityError) as e:
                    resolver.resolve(bad)
                assert e.value.code == code
            with pytest.raises(SecurityError):
                resolver._get_db()  # 공용 auth.db 경로 자체가 막혀 있다
        with bound(NO_EMAIL):
            with pytest.raises(SecurityError) as e:
                resolver.resolve(None)
            assert e.value.code == ErrorCode.GRAPH_NOT_CONNECTED


def test_resolver_mode0_unchanged(monkeypatch):
    class DB:
        def list_users(self):
            return [{"user_email": "zed@contoso.com"}, {"email": "amy@contoso.com"}]

    monkeypatch.delenv("MS365_DEFAULT_USER_EMAIL", raising=False)
    with single_user_mode():
        resolver = UserResolver(auth_database=DB())
        assert resolver.resolve(None) == "amy@contoso.com"
        assert resolver.resolve(" other@contoso.com ") == "other@contoso.com"
        assert resolver.resolve("") == "amy@contoso.com"
        monkeypatch.setenv("MS365_DEFAULT_USER_EMAIL", "op@contoso.com")
        assert resolver.default_email() == "op@contoso.com"


def test_validation_switch_only_in_mode0(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_VALIDATE_INPUT", "0")
    with single_user_mode():
        assert validation_enabled() is False
        validate_arguments(REQUIRED_SCHEMA, {})  # 꺼져 있음
    with multi_user_mode(tmp_path):
        assert validation_enabled() is True
        with pytest.raises(ToolValidationError):
            validate_arguments(REQUIRED_SCHEMA, {})


# ----------------------------------------------------------------------
# mode 0 런타임 회귀 (B01)
# ----------------------------------------------------------------------
async def test_mode0_runtime_unchanged(monkeypatch):
    monkeypatch.delenv("MCP_VALIDATE_INPUT", raising=False)

    def handler(args):
        if args.get("query") == "boom":
            raise ValueError("visible in mode 0")
        return {"args": args}

    tools = [{"name": "t", "inputSchema": SCHEMA}]
    runtime = ToolRuntime(DOMAIN, tools, {"t": handler})
    with single_user_mode():
        blocks = await runtime.call("t", {"flag": True, "extra": 1})  # 추가 인자 허용(하위 호환)
        assert json.loads(blocks[0]["text"])["args"] == {"flag": "enabled", "extra": 1, "count": 5}
        with pytest.raises(ToolExecutionError) as e:
            await runtime.call("t", {"query": "boom"})
        payload = _payload(e.value)
        assert payload["error"] == "ValueError" and payload["message"] == "visible in mode 0"


# ----------------------------------------------------------------------
# B02 — mode 1 stdio 기동 거부
# ----------------------------------------------------------------------
class _StdioLifecycle:
    server_name = DOMAIN
    errors: List[str] = []

    def __init__(self) -> None:
        self.started = False

    async def startup(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        pass


async def test_b02_serve_stdio_refused_in_multi_user(tmp_path):
    lifecycle = _StdioLifecycle()
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError) as e:
            await serve_stdio(object(), lifecycle, object())
    assert "stdio" in str(e.value)
    assert lifecycle.started is False


def test_b02_run_stdio_refused_in_multi_user(tmp_path):
    lifecycle = _StdioLifecycle()
    with multi_user_mode(tmp_path):
        with pytest.raises(StartupConfigError):
            run_stdio(object(), lifecycle, object())
    assert lifecycle.started is False
