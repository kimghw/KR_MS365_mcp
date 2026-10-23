"""
WP12 통합 격리 검증 하네스 (spec/spec_멀티유저.md ②-10).

실제 도메인 서버(8개)를 **실제 HTTP 스택**으로 띄운다.

    handlers.build_mcp_server() + http_transport.build_starlette_app()   (server_stream.py 와 같은 배선)
    → BearerAuthMiddleware → SDK StreamableHTTPSessionManager(stateless) → ToolRuntime
    → 서비스 풀(create_service) → 도메인 서비스 → BoundGraphTokenProvider → session.token_store

`server_stream.py` 는 import 하지 않는다 — `bootstrap_http` 가 개발자의 실제 `.env` 를 읽는다.

가짜는 경계 밖에만 둔다.

| 경계 | 가짜 |
|------|------|
| Entra (토큰 교환·갱신·`/me`·JWKS) | `session.tests.mu_support.FakeEntra` (WP2) |
| Graph HTTP (aiohttp) | `GraphFake` — `aiohttp.ClientSession._request` 를 가로채 요청마다 메서드·URL·Authorization·요청 시점 principal 기록 |
| `requests` (FileHandler OneDrive 경로) | 같은 `GraphFake` 가 기록 후 네트워크 차단 |

registry·사용자별 암호화 토큰 DB·KEK(memory)·OAuth gateway·서비스 풀·감사는 전부 **실제 구현**이다.
사용자 연결은 실제 OAuth gateway 흐름(`/auth/graph/start` → `/auth/graph/connect` → `/auth/callback`)
으로 만든다.

handlers 모듈은 이 파일 import 시점(= pytest 수집, mode 0)에 import 한다. 그래서 mode 0 전역
서비스(`mail_service` 등)가 존재하는 상태가 재현된다. 각 앱을 띄울 때 그 전역을 `LegacyPoison` 으로
바꿔 두고, mode 1 경로가 한 번이라도 건드리면 실패시킨다.
"""

import asyncio
import contextlib
import importlib
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlsplit

import aiohttp
from multidict import CIMultiDict
from starlette.testclient import TestClient

from mcp_common.principal import DOMAINS, current_principal
from mcp_common.security_policy import CONFLICTING_ENV
from session.tests.mu_support import BASE_ENV, CLEARED_ENV, Account, FakeEntra

# ----------------------------------------------------------------------
# 도메인 서버 (수집 시점 = mode 0 import)
# ----------------------------------------------------------------------
HANDLERS: dict[str, Any] = {d: importlib.import_module(f"mcp_{d}.mcp_server.handlers") for d in DOMAINS}

#: mode 0 에서만 존재해야 하는 전역 서비스 이름
LEGACY_GLOBALS = {
    "outlook": "mail_service",
    "calendar": "calendar_service",
    "teams": "teams_service",
    "onedrive": "onedrive_service",
    "onenote": "onenote_service",
    "todo": "todo_service",
    "file_handler": "file_manager_service",
}

GRAPH_DOMAINS = ("outlook", "calendar", "teams", "onedrive", "onenote", "todo")
GRAPH_HOST = "graph.microsoft.com"

#: 도메인별 대표 읽기 도구 (Graph 를 부른다)
READ_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "outlook": ("mail_list_keyword", {"search_keywords": "report"}),
    "calendar": ("list_events", {}),
    "teams": ("handler_teams_list_chats", {}),
    "onedrive": ("handler_onedrive_list_files", {}),
    "onenote": ("read_onenote", {"action": "list_sections"}),
    "todo": ("todo_lists_view", {}),
}

#: 개발 환경 값이 테스트에 섞이지 않게 지우는 환경변수
ENV_TO_CLEAR = tuple(
    dict.fromkeys(
        (
            *CLEARED_ENV,
            *CONFLICTING_ENV,
            "MCP_ATTACHMENT_METADATA_STORAGE",
            "MCP_VALIDATE_INPUT",
            "MS365_MAX_REQUEST_BYTES",
            "MCP_BIND_HOST",
            "MCP_ALLOWED_HOSTS",
            "MCP_ALLOWED_ORIGINS",
            "MS365_AUTH_GATEWAY_PORT",
            "MS365_MULTI_USER",
            "MS365_DATA_ROOT",
        )
    )
)

MCP_BASE_URL = "http://127.0.0.1:5999"
GATEWAY_BASE_URL = "http://localhost:5000"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT_PARAMS = {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {"name": "wp12", "version": "0"},
}


# ----------------------------------------------------------------------
# legacy 전역 감시
# ----------------------------------------------------------------------
class LegacyPoison:
    """mode 0 전역 서비스 자리에 넣는 감시 객체. 속성 접근 하나라도 있으면 기록하고 실패."""

    def __init__(self, domain: str):
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "touched", [])

    def __getattr__(self, name: str) -> Any:
        self.touched.append(name)
        raise AssertionError(f"mode 1 path used legacy {self.domain} global service (.{name})")


# ----------------------------------------------------------------------
# Graph HTTP 가짜
# ----------------------------------------------------------------------
@dataclass
class GraphCall:
    method: str
    url: str
    authorization: str | None
    kwargs: dict[str, Any] = field(default_factory=dict)
    principal_key: str | None = None
    library: str = "aiohttp"
    #: 도메인 코드가 넘긴 원래 URL 문자열 (url 은 yarl 정규화 뒤 실제 요청 URL)
    raw_url: str = ""

    @property
    def token(self) -> str | None:
        auth = self.authorization or ""
        return auth[7:] if auth.lower().startswith("bearer ") else (auth or None)

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def path(self) -> str:
        return urlsplit(self.url).path

    @property
    def json_body(self) -> Any:
        return self.kwargs.get("json")


class FakeHttpResponse:
    """aiohttp `ClientResponse` 대용 (도메인 코드가 쓰는 속성만)."""

    def __init__(
        self,
        status: int = 200,
        payload: Any = None,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        url: str = "",
    ):
        self.status = status
        self._payload = payload
        if body is None:
            body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self._body = body
        hdrs = {"Content-Type": "application/json"} if payload is not None else {}
        hdrs.update(headers or {})
        self.headers = CIMultiDict(hdrs)
        self.url = url
        self.reason = "OK" if status < 400 else "Error"
        self.content = _Content(self._body)

    @property
    def ok(self) -> bool:
        return self.status < 400

    @property
    def content_type(self) -> str:
        return (self.headers.get("Content-Type") or "application/octet-stream").split(";")[0]

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        if self._payload is not None:
            return self._payload
        return json.loads(self._body.decode("utf-8") or "null")

    async def text(self, *args: Any, **kwargs: Any) -> str:
        return self._body.decode("utf-8", errors="replace")

    async def read(self) -> bytes:
        return self._body

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None, history=(), status=self.status, message=self.reason  # type: ignore[arg-type]
            )

    def release(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_for_close(self) -> None:
        return None

    async def __aenter__(self) -> "FakeHttpResponse":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _Content:
    def __init__(self, body: bytes):
        self._body = body

    async def read(self, n: int = -1) -> bytes:
        body, self._body = self._body, b""
        return body

    async def iter_chunked(self, n: int):
        body, self._body = self._body, b""
        for i in range(0, len(body), max(1, n)):
            yield body[i : i + n]

    async def iter_any(self):
        body, self._body = self._body, b""
        if body:
            yield body


Responder = Union[FakeHttpResponse, dict[str, Any], list[Any], Callable[[GraphCall], Any]]


class GraphFake:
    """aiohttp·requests 를 가로채는 Graph 가짜. 라우트가 없으면 빈 성공 응답."""

    def __init__(self, entra: FakeEntra):
        self.entra = entra
        self.calls: list[GraphCall] = []
        self.routes: list[tuple[str | None, Pattern[str], Responder]] = []
        #: 응답 직전에 await 되는 훅 (동시성 테스트에서 겹침을 강제)
        self.gate: Callable[[GraphCall], Any] | None = None

    # --- 라우트 ---------------------------------------------------------
    def on(self, method: str | None, pattern: str, responder: Responder) -> None:
        """`pattern` 은 URL 경로(쿼리 제외)에 대한 정규식. 먼저 등록한 것이 이긴다."""
        self.routes.insert(0, (method.upper() if method else None, re.compile(pattern), responder))

    def _respond(self, call: GraphCall) -> FakeHttpResponse:
        for method, pattern, responder in self.routes:
            if method and method != call.method:
                continue
            if not pattern.search(call.path):
                continue
            value = responder(call) if callable(responder) else responder
            if isinstance(value, FakeHttpResponse):
                return value
            return FakeHttpResponse(200, value, url=call.url)
        if call.method == "GET":
            return FakeHttpResponse(200, {"value": []}, url=call.url)
        if call.method == "DELETE":
            return FakeHttpResponse(204, None, url=call.url)
        return FakeHttpResponse(201 if call.method == "POST" else 200, {"id": "fake-id"}, url=call.url)

    # --- 조회 -----------------------------------------------------------
    def owner(self, call: GraphCall) -> Account | None:
        return self.entra.access.get(call.token or "")

    def reset(self) -> None:
        self.calls.clear()

    def graph_calls(self) -> list[GraphCall]:
        return [c for c in self.calls if c.host == GRAPH_HOST]

    # --- 가로채기 -------------------------------------------------------
    async def _aiohttp_request(self, method: str, str_or_url: Any, kwargs: dict[str, Any]) -> FakeHttpResponse:
        from yarl import URL

        headers = dict(kwargs.get("headers") or {})
        authorization = next((v for k, v in headers.items() if k.lower() == "authorization"), None)
        # aiohttp 와 같은 변환(yarl.URL) — dot-segment 정규화 뒤 **실제로 나갈** URL 을 기록한다
        wire = str_or_url if isinstance(str_or_url, URL) else URL(str(str_or_url))
        params = kwargs.get("params")
        if params:
            wire = wire.extend_query(params)
        principal = current_principal()
        call = GraphCall(
            method.upper(),
            str(wire),
            authorization,
            {k: v for k, v in kwargs.items() if k in ("json", "data", "params", "allow_redirects")},
            principal.user_key if principal else None,
        )
        call.raw_url = str(str_or_url)
        self.calls.append(call)
        await asyncio.sleep(0)
        if self.gate is not None:
            result = self.gate(call)
            if asyncio.iscoroutine(result):
                await result
        return self._respond(call)

    def _requests_request(self, method: str, url: str, kwargs: dict[str, Any]) -> Any:
        import requests

        headers = dict(kwargs.get("headers") or {})
        authorization = next((v for k, v in headers.items() if k.lower() == "authorization"), None)
        principal = current_principal()
        call = GraphCall(method.upper(), str(url), authorization, {}, principal.user_key if principal else None,
                         library="requests")
        self.calls.append(call)
        fake = self._respond(call)
        response = requests.Response()
        response.status_code = fake.status
        response._content = fake._body
        response._content_consumed = True  # iter_content 가 _content 를 그대로 잘라 준다
        response.headers.update(dict(fake.headers))
        response.url = str(url)
        response.encoding = "utf-8"
        return response

    def install(self, monkeypatch: Any) -> None:
        fake = self

        async def _request(_session: Any, method: str, str_or_url: Any, **kwargs: Any) -> FakeHttpResponse:
            return await fake._aiohttp_request(method, str_or_url, kwargs)

        monkeypatch.setattr(aiohttp.ClientSession, "_request", _request)

        import requests

        def _req(_session: Any, method: str, url: str, **kwargs: Any) -> Any:
            return fake._requests_request(method, url, kwargs)

        monkeypatch.setattr(requests.Session, "request", _req)


# ----------------------------------------------------------------------
# MCP over HTTP
# ----------------------------------------------------------------------
@dataclass
class ToolResult:
    is_error: bool
    text: str
    payload: Any
    message: dict[str, Any]

    @property
    def error_code(self) -> str | None:
        if isinstance(self.payload, dict):
            return self.payload.get("error")
        return None


def rpc(method: str, params: dict[str, Any] | None = None, msg_id: int | None = 1) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        message["id"] = msg_id
    if params is not None:
        message["params"] = params
    return message


def jsonrpc_message(response: Any) -> dict[str, Any]:
    """stateless 응답(SSE `data:` 또는 JSON 본문)의 JSON-RPC 메시지."""
    assert response.status_code == 200, (response.status_code, response.text[:500])
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return response.json()


def parse_tool_result(message: dict[str, Any]) -> ToolResult:
    assert "result" in message, message
    result = message["result"]
    text = "".join(block.get("text", "") for block in result.get("content", []) if block.get("type") == "text")
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        payload = text
    return ToolResult(bool(result.get("isError")), text, payload, message)


class McpClient:
    """한 도메인 서버의 `/mcp` 를 부르는 얇은 클라이언트 (Starlette TestClient 위)."""

    def __init__(self, domain: str, client: TestClient, poison: LegacyPoison | None):
        self.domain = domain
        self.http = client
        self.poison = poison

    def post(self, body: Any, key: str | None = None, **headers: str) -> Any:
        merged = dict(MCP_HEADERS)
        if key is not None:
            merged["Authorization"] = f"Bearer {key}"
        merged.update(headers)
        return self.http.post("/mcp", json=body, headers=merged)

    def initialize(self, key: str | None) -> Any:
        return self.post(rpc("initialize", INIT_PARAMS), key)

    def list_tools(self, key: str | None) -> Any:
        return self.post(rpc("tools/list"), key)

    def tool_names(self, key: str) -> list[str]:
        return [t["name"] for t in jsonrpc_message(self.list_tools(key))["result"]["tools"]]

    def call_raw(self, key: str | None, tool: str, arguments: dict[str, Any] | None = None, **headers: str) -> Any:
        return self.post(rpc("tools/call", {"name": tool, "arguments": arguments or {}}), key, **headers)

    def call(self, key: str, tool: str, arguments: dict[str, Any] | None = None, **headers: str) -> ToolResult:
        return parse_tool_result(jsonrpc_message(self.call_raw(key, tool, arguments, **headers)))


def _lifecycle_for(domain: str, module: Any) -> Any:
    """mode 1 으로 import 됐을 때와 같은 lifecycle (전역 서비스는 time 의 무상태 서비스뿐)."""
    from mcp_common.runtime import ServiceLifecycle

    if domain == "time":
        return module.lifecycle
    return ServiceLifecycle(module.SERVER_NAME, [])


def build_domain_app(domain: str, monkeypatch: Any) -> tuple[Any, LegacyPoison | None]:
    """`server_stream.py` 와 같은 배선(기본 authenticator·active_checker = 실제 registry)."""
    from mcp_common.http_transport import build_starlette_app

    module = HANDLERS[domain]
    poison = None
    legacy = LEGACY_GLOBALS.get(domain)
    if legacy:
        poison = LegacyPoison(domain)
        monkeypatch.setattr(module, legacy, poison)
    # 다른 테스트가 runtime 에 가짜 checker 를 남겼더라도 실제 registry 를 쓰게 한다
    monkeypatch.setattr(module.runtime, "active_checker", None)
    app = build_starlette_app(
        module.SERVER_NAME,
        module.build_mcp_server(),
        module.runtime,
        _lifecycle_for(domain, module),
        version=module.SERVER_VERSION,
    )
    return app, poison


@contextlib.contextmanager
def domain_client(domain: str, monkeypatch: Any) -> Iterator[McpClient]:
    app, poison = build_domain_app(domain, monkeypatch)
    with TestClient(app, base_url=MCP_BASE_URL) as http:
        yield McpClient(domain, http, poison)
    if poison is not None:
        assert poison.touched == [], f"legacy {domain} service touched in mode 1: {poison.touched}"


# ----------------------------------------------------------------------
# 사용자 (실제 registry + 실제 OAuth gateway)
# ----------------------------------------------------------------------
@dataclass
class User:
    account: Account
    user_key: str
    key: str

    @property
    def email(self) -> str:
        return self.account.email

    @property
    def kid(self) -> str:
        return self.key.split(".")[1]


def register(account: Account, domains: list[str] | None = None) -> User:
    from session.tests.mu_support import register_with_key

    record, key = register_with_key(account, domains=domains)
    return User(account, record.user_key, key)


def issue_extra_key(user: User, domains: list[str]) -> str:
    from session import identity_registry as ir

    return ir.issue_key(user.user_key, domains).key


@dataclass
class OAuthOutcome:
    status_code: int
    page: str
    connect_url: str


def browser_connect(entra: FakeEntra, connect_url: str, login_as: Account) -> OAuthOutcome:
    """브라우저 한 개로 connect_url → Entra 로그인(login_as) → 콜백. 실제 gateway 앱."""
    from session.auth_gateway import create_app

    app = create_app(entra=entra, jwks_client=entra.jwks)
    with TestClient(app, base_url=GATEWAY_BASE_URL) as browser:
        parts = urlsplit(connect_url)
        redirect = browser.get(f"{parts.path}?{parts.query}", follow_redirects=False)
        assert redirect.status_code == 302, (redirect.status_code, redirect.text[:300])
        code, state = entra.login(redirect.headers["location"], login_as)
        result = browser.get("/auth/callback", params={"code": code, "state": state})
    return OAuthOutcome(result.status_code, result.text, connect_url)


def start_connect(entra: FakeEntra, key: str) -> str:
    """bearer 로 `POST /auth/graph/start` → connect_url."""
    from session.auth_gateway import create_app

    app = create_app(entra=entra, jwks_client=entra.jwks)
    with TestClient(app, base_url=GATEWAY_BASE_URL) as client:
        resp = client.post("/auth/graph/start", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 201, (resp.status_code, resp.text[:300])
    return resp.json()["connect_url"]


def connect_user(entra: FakeEntra, user: User, login_as: Account | None = None) -> OAuthOutcome:
    return browser_connect(entra, start_connect(entra, user.key), login_as or user.account)


def onboard(entra: FakeEntra, account: Account, domains: list[str] | None = None) -> User:
    """등록 + 키 발급 + 실제 OAuth 연결."""
    user = register(account, domains)
    outcome = connect_user(entra, user)
    assert outcome.status_code == 200, outcome.page[:300]
    return user


def tokens_of(entra: FakeEntra, account: Account) -> list[str]:
    return [token for token, owner in entra.access.items() if owner == account]


# ----------------------------------------------------------------------
# 저장소 접근 감시
# ----------------------------------------------------------------------
class AccessSpy:
    """사용자 auth.db(`UserAuthStore.connect`)·SQLite 파일 열기·토큰 획득을 기록한다."""

    def __init__(self) -> None:
        self.auth_store_users: list[str] = []
        self.sqlite_paths: list[str] = []
        self.token_principals: list[str] = []

    def install(self, monkeypatch: Any) -> "AccessSpy":
        import sqlite3

        from session import token_store
        from session.user_auth_store import UserAuthStore

        spy = self
        original_connect = UserAuthStore.connect

        def _connect(store: Any, *args: Any, **kwargs: Any) -> Any:
            spy.auth_store_users.append(store.user_key)
            return original_connect(store, *args, **kwargs)

        monkeypatch.setattr(UserAuthStore, "connect", _connect)

        original_sqlite = sqlite3.connect

        def _sqlite(database: Any, *args: Any, **kwargs: Any) -> Any:
            spy.sqlite_paths.append(str(database))
            return original_sqlite(database, *args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", _sqlite)

        original_token = token_store.get_graph_access_token

        async def _token(principal: Any, **kwargs: Any) -> Any:
            spy.token_principals.append(principal.user_key)
            return await original_token(principal, **kwargs)

        monkeypatch.setattr(token_store, "get_graph_access_token", _token)
        return self

    def reset(self) -> None:
        self.auth_store_users.clear()
        self.sqlite_paths.clear()
        self.token_principals.clear()

    def touched_user(self, user_key: str) -> bool:
        """그 사용자의 auth.db·도메인 DB·토큰 중 하나라도 건드렸는가."""
        root_marker = f"{user_key}"
        return (
            user_key in self.auth_store_users
            or user_key in self.token_principals
            or any(root_marker in p for p in self.sqlite_paths)
        )


# ----------------------------------------------------------------------
# 파일 스캔
# ----------------------------------------------------------------------
def files_under(root: Path) -> list[Path]:
    return [p for p in Path(root).rglob("*") if p.is_file()]


def contains_bytes(root: Path, needle: bytes) -> list[Path]:
    hits = []
    for path in files_under(root):
        try:
            if needle in path.read_bytes():
                hits.append(path)
        except OSError:
            pass
    return hits


def qs(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


__all__ = [
    "HANDLERS",
    "LEGACY_GLOBALS",
    "GRAPH_DOMAINS",
    "GRAPH_HOST",
    "READ_TOOLS",
    "ENV_TO_CLEAR",
    "BASE_ENV",
    "LegacyPoison",
    "GraphCall",
    "FakeHttpResponse",
    "GraphFake",
    "ToolResult",
    "rpc",
    "jsonrpc_message",
    "parse_tool_result",
    "McpClient",
    "build_domain_app",
    "domain_client",
    "User",
    "register",
    "issue_extra_key",
    "OAuthOutcome",
    "browser_connect",
    "start_connect",
    "connect_user",
    "onboard",
    "tokens_of",
    "AccessSpy",
    "files_under",
    "contains_bytes",
    "qs",
]
