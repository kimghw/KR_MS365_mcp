"""시나리오 6 — A·B 요청이 await 경계에서 겹쳐도 토큰·응답·저장이 섞이지 않는다 (②-5.2, ②-10 C01·C02).

- asyncio: `httpx.AsyncClient(ASGITransport)` 로 같은 이벤트 루프에서 A/B 호출을 동시에 띄우고,
  Graph 가짜의 gate 로 A·B 요청이 **동시에 Graph 대기 중**인 순간을 강제한다.
- threads: Starlette `TestClient` 를 여러 스레드에서 동시에 불러 사용자별 DB 쓰기가 섞이지 않는지 본다.
"""

import asyncio
import json
import random
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tests.multi_user.harness import (
    MCP_BASE_URL,
    MCP_HEADERS,
    FakeHttpResponse,
    build_domain_app,
    jsonrpc_message,
    parse_tool_result,
    rpc,
)

PAIRS = 6


class BothInFlight:
    """A 와 B 의 Graph 요청이 모두 도착할 때까지 응답을 미룬다(그 뒤로는 무작위 지연만)."""

    def __init__(self, mu, accounts, timeout: float = 5.0):
        self.mu = mu
        self.needed = set(accounts)
        self.seen = set()
        self.event = asyncio.Event()
        self.timeout = timeout
        self.max_concurrent = 0
        self.inflight = 0

    async def __call__(self, call):
        owner = self.mu.graph.owner(call)
        self.seen.add(owner)
        self.inflight += 1
        self.max_concurrent = max(self.max_concurrent, self.inflight)
        try:
            if self.needed <= self.seen:
                self.event.set()
            await asyncio.wait_for(self.event.wait(), self.timeout)
            await asyncio.sleep(random.random() * 0.01)
        finally:
            self.inflight -= 1


async def _call(client: httpx.AsyncClient, key: str, tool: str, args: dict):
    body = rpc("tools/call", {"name": tool, "arguments": args})
    response = await client.post("/mcp", json=body, headers={**MCP_HEADERS, "Authorization": f"Bearer {key}"})
    return parse_tool_result(jsonrpc_message(response))


@pytest.mark.parametrize("domain,tool,args,pattern", [
    ("calendar", "list_events", {}, r"/me/events$"),
    ("todo", "todo_lists_view", {}, r"/me/todo/lists$"),
    ("teams", "handler_teams_list_chats", {}, r"/me/chats$"),
])
async def test_interleaved_async_calls_never_cross_tokens(mu, alice, bob, domain, tool, args, pattern):
    def _respond(call):
        owner = mu.graph.owner(call)
        marker = f"owned-by-{owner.email}" if owner else "anonymous"
        return {"value": [{"id": marker, "subject": marker, "displayName": marker, "topic": marker}]}

    mu.graph.on("GET", pattern, _respond)
    gate = BothInFlight(mu, [alice.account, bob.account])
    mu.graph.gate = gate
    app, poison = build_domain_app(domain, mu.monkeypatch)
    order = [alice, bob] * PAIRS
    random.Random(7).shuffle(order)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=MCP_BASE_URL) as client:
            results = await asyncio.gather(*[_call(client, u.key, tool, args) for u in order])

    assert gate.max_concurrent >= 2, "A·B 요청이 실제로 겹치지 않았다"
    for user, result in zip(order, results, strict=True):
        assert not result.is_error, result.text[:300]
        other = bob if user is alice else alice
        assert f"owned-by-{user.email}" in result.text
        assert f"owned-by-{other.email}" not in result.text
    for call in mu.graph.calls:
        owner = mu.graph.owner(call)
        assert owner is not None
        owner_user = alice if owner == alice.account else bob
        assert call.principal_key == owner_user.user_key, "Graph 요청 시점의 principal 과 토큰 주인이 다르다"
    assert len(mu.graph.calls) == len(order)
    assert poison is None or poison.touched == []


async def test_failure_and_cancellation_do_not_leak_context_to_next_request(mu, alice, bob):
    """C02 — A 의 Graph 호출이 예외로 끝나거나 클라이언트가 끊어도 다음 B 요청은 B 로만 처리된다."""
    phase = {"mode": "boom"}
    release = asyncio.Event()

    def _route(call):
        if mu.graph.owner(call) == alice.account and phase["mode"] == "boom":
            raise RuntimeError("graph exploded")
        return {"value": []}

    async def _hold(call):
        if mu.graph.owner(call) == alice.account and phase["mode"] == "hold":
            await release.wait()

    mu.graph.on("GET", r"/me/events$", _route)
    mu.graph.gate = _hold
    app, _ = build_domain_app("calendar", mu.monkeypatch)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=MCP_BASE_URL) as client:
            failed = await _call(client, alice.key, "list_events", {})
            assert failed.is_error  # 오류 문구의 원문 노출은 test_canary_logs 에서 따로 본다

            # 진행 중 취소: A 의 Graph 응답을 붙잡아 둔 채 클라이언트가 끊는다
            phase["mode"] = "hold"
            task = asyncio.create_task(_call(client, alice.key, "list_events", {}))
            for _ in range(200):
                if any(mu.graph.owner(c) == alice.account for c in mu.graph.calls[1:]):
                    break
                await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            phase["mode"] = "ok"

            mu.graph.reset()
            ok = await _call(client, bob.key, "list_events", {})
    assert not ok.is_error, ok.text[:300]
    assert [c.principal_key for c in mu.graph.calls] == [bob.user_key]
    assert {mu.graph.owner(c) for c in mu.graph.calls} == {bob.account}


def test_threaded_concurrent_writes_stay_in_each_users_store(mu, alice, bob):
    """여러 스레드가 같은 서버에 A/B 메타데이터를 동시에 저장해도 각자의 DB 에만 남는다."""
    url = "https://contoso.sharepoint.com/shared/doc-{n}.docx"
    with mu.client("file_handler") as c:
        jobs = [(user, n) for n in range(10) for user in (alice, bob)]

        def _save(job):
            user, n = job
            return c.call(user.key, "save_file_metadata",
                          {"file_url": url.format(n=n), "keywords": [f"kw-{user.account.object_id[:8]}-{n}"]})

        with ThreadPoolExecutor(max_workers=8) as pool:
            saved = list(pool.map(_save, jobs))
        assert all(not r.is_error for r in saved), [r.text[:200] for r in saved if r.is_error]

        for user, other in ((alice, bob), (bob, alice)):
            found = c.call(user.key, "search_metadata", {}).payload
            keywords = sorted(kw for r in found["results"] for kw in r["keywords"])
            assert keywords == sorted(f"kw-{user.account.object_id[:8]}-{n}" for n in range(10))
            assert other.account.object_id[:8] not in json.dumps(found)
