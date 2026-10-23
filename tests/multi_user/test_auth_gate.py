"""시나리오 1 — 8개 실제 도메인 서버의 bearer 관문 (spec/spec_멀티유저.md ②-4.4, ②-10 I01·I07·I08).

| 요청 | 기대 |
|------|------|
| 키 없음·형식 오류·미지 키 — initialize / tools/list / tools/call / notification / GET / DELETE | 401 + `WWW-Authenticate: Bearer`, 서비스 풀·도메인 DB·Graph 0회 |
| 그 서버 scope 가 없는 유효 키 | 403 `forbidden_scope` |
| 유효 키 | initialize·tools/list 200, `Mcp-Session-Id` 미발급, 도구 목록 = param_spec |
| 유효 키 + `Mcp-Session-Id` | 400 (인증 뒤) |
"""

from pathlib import Path

import pytest

from mcp_common import service_pool
from mcp_common.principal import DOMAINS
from mcp_common.user_paths import paths_for
from session.tests.mu_support import ALICE
from tests.multi_user.harness import HANDLERS, INIT_PARAMS, issue_extra_key, rpc

UNKNOWN_KEY = "m365v1." + "0" * 32 + "." + "A" * 43


def _other_domain(domain: str) -> str:
    return "time" if domain != "time" else "outlook"


def _no_domain_storage(user_key: str) -> None:
    paths = paths_for(user_key)
    assert not [p for p in Path(paths.db_dir).glob("*") if p.is_file()], "도메인 DB 가 인증 전에 열렸다"
    assert service_pool.get_service_pool().stats()["entries"] == 0


@pytest.mark.parametrize("domain", DOMAINS)
def test_unauthenticated_requests_are_401_before_any_service(mu, domain):
    user = mu.register(ALICE)  # 저장소는 있지만 인증되지 않은 요청이 열면 안 된다
    tool = HANDLERS[domain].MCP_TOOLS[0]["name"]
    bodies = [
        rpc("initialize", INIT_PARAMS),
        rpc("tools/list"),
        rpc("tools/call", {"name": tool, "arguments": {}}),
        rpc("notifications/initialized", msg_id=None),
    ]
    with mu.client(domain) as c:
        for authorization in (None, "Bearer", "Basic abc", f"Bearer {UNKNOWN_KEY}", f"Bearer {user.key}x"):
            extra = {} if authorization is None else {"Authorization": authorization}
            for body in bodies:
                r = c.post(body, None, **extra)
                assert r.status_code == 401, (domain, authorization, body["method"], r.status_code)
                assert r.headers.get("www-authenticate") == "Bearer"
                assert r.json()["error"] == "unauthenticated"
                assert "mcp-session-id" not in r.headers
            for method in ("GET", "DELETE"):
                r = c.http.request(method, "/mcp", headers=extra)
                assert r.status_code == 401, (domain, method)
    assert mu.graph.calls == []
    _no_domain_storage(user.user_key)


@pytest.mark.parametrize("domain", DOMAINS)
def test_key_without_server_scope_is_403(mu, domain):
    user = mu.register(ALICE, domains=[_other_domain(domain)])
    tool = HANDLERS[domain].MCP_TOOLS[0]["name"]
    with mu.client(domain) as c:
        for body in (rpc("initialize", INIT_PARAMS), rpc("tools/list"), rpc("tools/call", {"name": tool, "arguments": {}})):
            r = c.post(body, user.key)
            assert r.status_code == 403, (domain, body["method"], r.status_code, r.text[:200])
            assert r.json()["error"] == "forbidden_scope"
            assert "mcp-session-id" not in r.headers
    assert mu.graph.calls == []
    _no_domain_storage(user.user_key)


@pytest.mark.parametrize("domain", DOMAINS)
def test_valid_key_lists_tools_statelessly(mu, domain):
    user = mu.register(ALICE, domains=[_other_domain(domain)])
    key = issue_extra_key(user, [domain])  # 이 서버 scope 만 가진 두 번째 키
    module = HANDLERS[domain]
    with mu.client(domain) as c:
        init = c.initialize(key)
        assert init.status_code == 200, init.text[:300]
        assert "mcp-session-id" not in init.headers
        listed = c.list_tools(key)
        assert listed.status_code == 200
        assert "mcp-session-id" not in listed.headers
        assert sorted(c.tool_names(key)) == sorted(t["name"] for t in module.MCP_TOOLS)
        # 세션 ID 를 보내면(다른 사용자 세션을 흉내) 인증 뒤 400
        r = c.post(rpc("tools/list"), key, **{"Mcp-Session-Id": "bob-session-0001"})
        assert r.status_code == 400
        # GET 스트림·DELETE 세션 종료는 인증 뒤 405
        for method in ("GET", "DELETE"):
            r = c.http.request(method, "/mcp", headers={"Authorization": f"Bearer {key}"})
            assert r.status_code == 405
    # tools/list 는 서비스를 만들지 않는다
    assert mu.graph.calls == []


@pytest.mark.parametrize("domain", DOMAINS)
def test_health_is_minimal_and_unauthenticated(mu, domain):
    with mu.client(domain) as c:
        r = c.http.get("/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status", "server", "version"}
    assert str(mu.root) not in r.text
