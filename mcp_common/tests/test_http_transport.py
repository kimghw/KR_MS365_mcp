"""Streamable HTTP 트랜스포트의 Host/Origin 허용 목록 (DNS rebinding 방어) 검증."""

import pytest
from mcp.server.lowlevel import Server
from starlette.testclient import TestClient

from mcp_common.http_transport import build_starlette_app, transport_security


class _Lifecycle:
    async def startup(self):
        pass

    async def shutdown(self):
        pass


class _Runtime:
    tools = {}


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def client():
    app = build_starlette_app("t", Server("t"), _Runtime(), _Lifecycle())
    with TestClient(app) as c:
        yield c


def test_unknown_host_is_rejected(client):
    r = client.post("/mcp", json=INIT, headers={**HEADERS, "Host": "evil.example:5002"})
    assert r.status_code == 421


def test_unknown_origin_is_rejected(client):
    r = client.post("/mcp", json=INIT, headers={**HEADERS, "Host": "localhost:5002", "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_loopback_host_passes_header_check(client):
    # GET 은 세션이 없어 트랜스포트가 4xx 를 주지만, 헤더 검사(421/403)는 통과해야 한다
    r = client.get("/mcp", headers={"Host": "127.0.0.1:5002", "Accept": "text/event-stream"})
    assert r.status_code not in (421, 403)


def test_env_extends_allowlist(monkeypatch):
    monkeypatch.setenv("MCP_BIND_HOST", "192.168.0.5")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.internal:*")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://app.internal")
    s = transport_security()
    assert "192.168.0.5:*" in s.allowed_hosts
    assert "mcp.internal:*" in s.allowed_hosts
    assert "https://app.internal" in s.allowed_origins
