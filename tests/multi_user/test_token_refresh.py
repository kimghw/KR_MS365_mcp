"""토큰 갱신이 실제 HTTP 스택 안에서 사용자별로 동작한다 (②-6.3, ②-10 A03·A04, ②-12.4).

- A 의 저장 토큰이 곧 만료 → 같은 프로세스의 두 도메인 서버에서 동시에 6건 호출해도 token
  endpoint 갱신은 1회, 이후 Graph 요청은 전부 A 의 **새** 토큰.
- A 의 갱신이 token endpoint 에서 멈춰 있는 동안 B 의 호출은 기다리지 않는다(전역 직렬화 없음).
- `invalid_grant` → `graph_reauth_required` + `connect_url`, 재연결 뒤 정상.
"""

import asyncio

import httpx
import pytest

from session.tests.mu_support import ALICE, BOB
from tests.multi_user.harness import (
    MCP_BASE_URL,
    MCP_HEADERS,
    browser_connect,
    build_domain_app,
    jsonrpc_message,
    parse_tool_result,
    rpc,
    tokens_of,
)


def _short_lived_exchange(mu, accounts):
    """다음 OAuth 연결(code 교환)에서 발급되는 토큰을 60초짜리로 만든다 (refresh 를 강제)."""
    original = mu.entra.exchange_code

    async def _exchange(**kwargs):
        data = await original(**kwargs)
        if mu.entra.access[data["access_token"]] in accounts:
            data["expires_in"] = 60
        return data

    mu.monkeypatch.setattr(mu.entra, "exchange_code", _exchange)


async def _call(client, key, tool, args=None):
    body = rpc("tools/call", {"name": tool, "arguments": args or {}})
    response = await client.post("/mcp", json=body, headers={**MCP_HEADERS, "Authorization": f"Bearer {key}"})
    return parse_tool_result(jsonrpc_message(response))


class _Apps:
    def __init__(self, mu, domains):
        self.mu = mu
        self.domains = domains
        self.stack = None
        self.clients = {}

    async def __aenter__(self):
        from contextlib import AsyncExitStack

        self.stack = AsyncExitStack()
        for domain in self.domains:
            app, _ = build_domain_app(domain, self.mu.monkeypatch)
            await self.stack.enter_async_context(app.router.lifespan_context(app))
            client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=MCP_BASE_URL)
            self.clients[domain] = await self.stack.enter_async_context(client)
        return self.clients

    async def __aexit__(self, *exc):
        await self.stack.aclose()


async def test_concurrent_calls_refresh_once_and_use_new_token(mu):
    _short_lived_exchange(mu, {ALICE})
    alice = mu.onboard(ALICE)
    old_tokens = set(tokens_of(mu.entra, ALICE))
    assert mu.entra.refresh_calls == 0

    async with _Apps(mu, ["calendar", "todo"]) as clients:
        jobs = [_call(clients["calendar"], alice.key, "list_events") for _ in range(3)]
        jobs += [_call(clients["todo"], alice.key, "todo_lists_view") for _ in range(3)]
        results = await asyncio.gather(*jobs)

    assert all(not r.is_error for r in results), [r.text[:200] for r in results if r.is_error]
    assert mu.entra.refresh_calls == 1
    used = {call.token for call in mu.graph.calls}
    assert used and not (used & old_tokens), "만료 직전 토큰이 Graph 로 나갔다"
    assert {mu.entra.access[t] for t in used} == {ALICE}


async def test_one_users_refresh_does_not_block_another_user(mu):
    _short_lived_exchange(mu, {ALICE})
    alice = mu.onboard(ALICE)
    bob = mu.onboard(BOB)
    release = asyncio.Event()
    entered = asyncio.Event()

    async def _slow_refresh(_refresh_token):
        entered.set()
        await asyncio.wait_for(release.wait(), 10)

    mu.entra.on_refresh = _slow_refresh
    async with _Apps(mu, ["calendar"]) as clients:
        client = clients["calendar"]
        a_task = asyncio.create_task(_call(client, alice.key, "list_events"))
        await asyncio.wait_for(entered.wait(), 5)
        # A 의 갱신이 token endpoint 에서 멈춰 있는 동안 B 는 끝까지 처리된다
        b_results = await asyncio.wait_for(asyncio.gather(*[_call(client, bob.key, "list_events") for _ in range(3)]), 5)
        assert all(not r.is_error for r in b_results)
        assert not a_task.done()
        release.set()
        a_result = await asyncio.wait_for(a_task, 10)
    assert not a_result.is_error, a_result.text[:300]
    assert mu.entra.refresh_calls == 1


def test_invalid_grant_requires_reconnect_then_recovers(mu):
    _short_lived_exchange(mu, {ALICE})
    alice = mu.onboard(ALICE)
    mu.entra.refresh_error = "invalid_grant"
    with mu.client("calendar") as c:
        result = c.call(alice.key, "list_events", {})
        assert result.is_error and result.error_code == "graph_reauth_required", result.text[:300]
        url = result.payload.get("connect_url")
        assert url
        assert mu.graph.calls == []
        # 같은 상태에서 다시 불러도 token endpoint 를 또 두드리지 않는다
        calls = mu.entra.refresh_calls
        again = c.call(alice.key, "list_events", {})
        assert again.error_code == "graph_reauth_required"
        assert mu.entra.refresh_calls == calls

        mu.entra.refresh_error = None
        assert browser_connect(mu.entra, url, ALICE).status_code == 200
        ok = c.call(alice.key, "list_events", {})
    assert not ok.is_error, ok.text[:300]
