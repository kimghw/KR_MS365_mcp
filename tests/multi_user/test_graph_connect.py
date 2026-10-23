"""시나리오 3 — 등록됐지만 Graph 미연결 사용자 (②-6.4, ②-12.4, ②-10 O02).

1. 도구 호출 → `graph_not_connected` + `connect_url`(1회용, bearer 미포함), Graph 요청 0회
2. 그 링크를 브라우저로 열어 **등록된 계정**으로 로그인 → 다음 호출 성공(그 사용자 토큰)
3. 같은 흐름에서 **B 계정**으로 로그인 → 저장 전 거부, A 는 계속 미연결, B 저장소 불변
"""

from urllib.parse import parse_qs, urlsplit

import pytest

from session import identity_registry as ir
from session.tests.mu_support import ALICE, BOB
from tests.multi_user.harness import GATEWAY_BASE_URL, GRAPH_DOMAINS, READ_TOOLS, browser_connect, tokens_of


def _connect_details(result) -> str:
    assert result.is_error, result.text[:300]
    assert result.error_code == "graph_not_connected", result.text[:300]
    payload = result.payload
    url = payload.get("connect_url")
    assert isinstance(url, str) and url.startswith(f"{GATEWAY_BASE_URL}/auth/graph/connect?ticket=")
    assert payload.get("expires_in") == 300
    return url


@pytest.mark.parametrize("domain", GRAPH_DOMAINS)
def test_unlinked_user_gets_connect_url_then_succeeds_after_oauth(mu, domain):
    user = mu.register(ALICE)
    tool, args = READ_TOOLS[domain]
    with mu.client(domain) as c:
        first = c.call(user.key, tool, args)
        url = _connect_details(first)
        assert user.key not in url and user.key.split(".")[2] not in url  # bearer 가 URL 에 없다
        assert set(parse_qs(urlsplit(url).query)) == {"ticket"}
        assert mu.graph.calls == []

        outcome = browser_connect(mu.entra, url, ALICE)
        assert outcome.status_code == 200, outcome.page[:300]
        assert ir.get_user(user.user_key).status == "active"

        second = c.call(user.key, tool, args)
        assert not second.is_error, second.text[:300]
        assert mu.graph.calls
        alice_tokens = set(tokens_of(mu.entra, ALICE))
        assert {call.token for call in mu.graph.calls} <= alice_tokens


@pytest.mark.parametrize("domain", ["calendar", "outlook"])
def test_connect_with_other_account_is_rejected_and_nothing_stored(mu, bob, spy, domain):
    user = mu.register(ALICE)
    tool, args = READ_TOOLS[domain]
    bob_record_before = ir.get_user(bob.user_key)
    with mu.client(domain) as c:
        url = _connect_details(c.call(user.key, tool, args))

        spy.reset()
        outcome = browser_connect(mu.entra, url, BOB)  # A 의 연결 시도에 B 로 로그인
        assert outcome.status_code == 400
        assert "다른 Microsoft 계정" in outcome.page
        assert bob.email not in outcome.page

        record = ir.get_user(user.user_key)
        assert record.status == "pending_link" and record.graph_email is None
        # A 시도의 실패가 B 의 저장소·상태를 건드리지 않는다
        assert ir.get_user(bob.user_key) == bob_record_before
        assert bob.user_key not in spy.auth_store_users

        again = c.call(user.key, tool, args)
        _connect_details(again)
        assert mu.graph.calls == []


def test_connect_link_is_single_use(mu):
    user = mu.register(ALICE)
    with mu.client("calendar") as c:
        url = _connect_details(c.call(user.key, "list_events", {}))
    assert browser_connect(mu.entra, url, ALICE).status_code == 200
    from starlette.testclient import TestClient

    from session.auth_gateway import create_app

    with TestClient(create_app(entra=mu.entra, jwks_client=mu.entra.jwks), base_url=GATEWAY_BASE_URL) as browser:
        parts = urlsplit(url)
        replay = browser.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert replay.status_code == 400


def test_each_unlinked_call_issues_a_fresh_link_without_unbounded_attempts(mu):
    """연결 안내는 호출마다 새 링크를 만들지만 사용자별 진행 중 시도는 상한(3) 안에 머문다."""
    from session.graph_connect import MAX_PENDING_ATTEMPTS

    user = mu.register(ALICE)
    urls = []
    with mu.client("todo") as c:
        for _ in range(MAX_PENDING_ATTEMPTS + 3):
            urls.append(_connect_details(c.call(user.key, "todo_lists_view", {})))
    assert len(set(urls)) == len(urls)
    store = ir.get_user(user.user_key).store()
    assert len(store.active_attempts()) <= MAX_PENDING_ATTEMPTS
    # 가장 최근 링크는 여전히 유효하다
    assert browser_connect(mu.entra, urls[-1], ALICE).status_code == 200


def test_gateway_bearer_endpoints_are_scoped_to_the_caller(mu, bob):
    """B 의 bearer 로 A 의 연결 시도를 조회할 수 없고, B 의 연결 해제는 B 만 바꾼다."""
    from starlette.testclient import TestClient

    from session.auth_gateway import create_app

    user = mu.register(ALICE)
    with TestClient(create_app(entra=mu.entra, jwks_client=mu.entra.jwks), base_url=GATEWAY_BASE_URL) as gw:
        started = gw.post("/auth/graph/start", headers={"Authorization": f"Bearer {user.key}"}).json()
        attempt = started["attempt_id"]
        own = gw.get(f"/auth/attempts/{attempt}", headers={"Authorization": f"Bearer {user.key}"})
        other = gw.get(f"/auth/attempts/{attempt}", headers={"Authorization": f"Bearer {bob.key}"})
        assert own.status_code == 200 and own.json()["status"] == "created"
        assert other.status_code == 404
        r = gw.delete("/auth/graph/connection", headers={"Authorization": f"Bearer {bob.key}"})
        assert r.status_code == 200
    assert ir.get_user(bob.user_key).status == "pending_link"
    store = ir.get_user(user.user_key).store()
    assert [a["attempt_id"] for a in store.active_attempts()] == [attempt]  # A 의 시도는 그대로
