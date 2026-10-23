"""query_url 의 호스트 검사(토큰 유출 방지)와 $skip 병렬 조회의 중복 제거 검증."""

import pytest

from mcp_outlook.graph_mail_query import GraphMailQuery

GRAPH = "https://graph.microsoft.com/v1.0/me/messages"


class _Provider:
    """요청마다 토큰을 새로 얻는 계약(N01) — 호출 수를 센다."""

    def __init__(self):
        self.calls = 0

    async def validate_and_refresh_token(self, email=None, auto_reauth=False):
        self.calls += 1
        return "tok"


@pytest.mark.parametrize(
    "url",
    [
        "http://graph.microsoft.com/v1.0/me/messages",  # https 아님
        "https://evil.example/collect",
        "https://graph.microsoft.com.evil.example/x",  # 접두 호스트 위장
    ],
)
async def test_token_is_not_sent_to_non_graph_url(url):
    provider = _Provider()
    q = GraphMailQuery(token_provider=provider)
    result = await q._fetch_parallel_with_url("u@x", url, 10)
    assert result["status"] == "error"
    assert result["value"] == []
    assert provider.calls == 0  # 거부된 URL 에는 토큰을 얻지도 않는다


class _Resp:
    def __init__(self, data):
        self.status = 200
        self._data = data

    async def json(self):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _Session:
    def __init__(self, pages):
        self._pages = pages

    def get(self, url, headers=None, **kwargs):
        # Authorization 을 단 요청은 redirect 를 따라가지 않는다 (spec/spec_멀티유저.md ②-7.5)
        assert kwargs.get("allow_redirects") is False
        skip = int(url.split("$skip=")[1])
        return _Resp({"value": self._pages.get(skip, [])})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


async def test_duplicate_ids_across_pages_are_dropped(monkeypatch):
    # 페이지 경계가 한 칸 밀려 m149 가 두 페이지에 걸친 상황 (300행, 고유 299)
    pages = {
        0: [{"id": f"m{i}"} for i in range(150)],
        150: [{"id": "m149"}] + [{"id": f"m{i}"} for i in range(150, 299)],
    }
    monkeypatch.setattr("mcp_outlook.graph_mail_query.aiohttp.ClientSession", lambda: _Session(pages))
    provider = _Provider()
    q = GraphMailQuery(token_provider=provider)
    result = await q._fetch_parallel_with_url("u@x", GRAPH, 300)
    ids = [e["id"] for e in result["value"]]
    assert len(ids) == len(set(ids)) == 299
    assert provider.calls == 2  # 페이지마다 토큰을 새로 얻는다 (N01)
