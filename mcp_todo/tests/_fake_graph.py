"""테스트 전용 가짜 Graph HTTP (네트워크 없음).

`aiohttp.ClientSession` 자리에 끼워 넣어 요청마다 (메서드, URL, bearer, 요청 시점의
principal) 을 기록하고, 라우터가 돌려준 가짜 응답을 낸다. `gate` 를 걸면 응답 직전에
기다리므로 두 요청이 await 경계에서 겹치는지 강제할 수 있다.

장기 세션(`session.request(...)`)과 요청마다 여는 세션(`async with ClientSession() as s`)
두 사용 형태를 모두 흉내 낸다.
"""

import asyncio
import json as _json
from typing import Any, Callable, Dict, List, Optional

from mcp_common.principal import current_principal


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        payload: Any = None,
        *,
        text: Optional[str] = None,
        body: bytes = b"",
        headers: Optional[Dict[str, str]] = None,
    ):
        self.status = status
        self._payload = {} if payload is None else payload
        self._text = text
        self._body = body
        self.headers = headers or {}

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        return self._text if self._text is not None else _json.dumps(self._payload)

    async def read(self) -> bytes:
        return self._body


Router = Callable[[str, str, str, Any], FakeResponse]


class Rendezvous:
    """`n` 개 요청이 모두 도착할 때까지 응답을 미룬다 — 겹침을 강제한다."""

    def __init__(self, n: int, timeout: float = 2.0):
        self.n = n
        self.timeout = timeout
        self.arrived = 0
        self._event = asyncio.Event()

    async def __call__(self) -> None:
        self.arrived += 1
        if self.arrived >= self.n:
            self._event.set()
        await asyncio.wait_for(self._event.wait(), self.timeout)


class FakeGraph:
    def __init__(self, router: Router):
        self.router = router
        self.requests: List[Dict[str, Any]] = []
        self.gate: Optional[Callable[[], Any]] = None
        self.sessions_opened = 0
        self.sessions_closed = 0

    def session_factory(self, *args, **kwargs) -> "FakeSession":
        return FakeSession(self)


class _Pending:
    def __init__(
        self,
        graph: FakeGraph,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Any,
        allow_redirects: Any = None,
    ):
        self.graph = graph
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.allow_redirects = allow_redirects

    async def __aenter__(self) -> FakeResponse:
        principal = current_principal()
        auth = self.headers.get("Authorization", "")
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else auth
        self.graph.requests.append(
            {
                "method": self.method,
                "url": self.url,
                "token": token,
                "authorization": self.headers.get("Authorization"),
                "allow_redirects": self.allow_redirects,
                "body": self.body,
                "principal_key": principal.user_key if principal else None,
            }
        )
        await asyncio.sleep(0)
        if self.graph.gate is not None:
            await self.graph.gate()
        await asyncio.sleep(0)
        return self.graph.router(self.method, self.url, token, self.body)

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeSession:
    def __init__(self, graph: FakeGraph):
        self.graph = graph
        self.closed = False
        graph.sessions_opened += 1

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        await self.close()
        return False

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.graph.sessions_closed += 1

    def request(
        self, method, url, headers=None, json=None, data=None, timeout=None, allow_redirects=None, **kwargs
    ):
        return _Pending(
            self.graph, method, url, dict(headers or {}), json if json is not None else data, allow_redirects
        )

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def patch(self, url, **kw):
        return self.request("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)
