"""시나리오 2 — Graph 도메인 6개: 토큰·대상 계정이 호출자에 고정된다 (②-5.3, ②-10 I02·I03·I06·I08).

A 의 bearer 로 들어온 요청은 Graph 에 **A 의 access token** 만 실어 보내고, 경로는 `/me/...` 또는
A 자신의 식별자만 가리킨다. `user_email=B` 는 `identity_mismatch` 로 끝나며 Graph 요청 0회, B 의
토큰 저장소·도메인 DB 접근 0회다.
"""

import json
from urllib.parse import unquote, urlsplit

import pytest

from tests.multi_user.harness import GRAPH_DOMAINS, GRAPH_HOST, READ_TOOLS, User


def assert_graph_calls_belong_to(mu, user: User, other: User) -> None:
    calls = mu.graph.calls
    assert calls, "대표 읽기 도구가 Graph 를 부르지 않았다"
    for call in calls:
        assert call.host == GRAPH_HOST, call.url
        assert mu.graph.owner(call) == user.account, f"다른 사용자의 토큰: {call.url}"
        assert call.principal_key == user.user_key
        text = unquote(call.url).lower() + json.dumps(call.kwargs.get("json") or {}).lower()
        for marker in (other.email, other.account.object_id, other.user_key):
            assert marker.lower() not in text, call.url
        path = unquote(urlsplit(call.url).path).lower()
        assert (
            path.startswith("/v1.0/me/")
            or path == "/v1.0/me"
            or f"/users/{user.email}" in path
            or f"/users/{user.account.object_id}" in path
            or path == "/v1.0/$batch"
        ), call.url


@pytest.mark.parametrize("domain", GRAPH_DOMAINS)
def test_read_tool_uses_only_callers_token_and_identity(mu, alice, bob, spy, domain):
    tool, args = READ_TOOLS[domain]
    with mu.client(domain) as c:
        result = c.call(alice.key, tool, args)
        assert not result.is_error, result.text[:500]
        assert_graph_calls_belong_to(mu, alice, bob)
        assert not spy.touched_user(bob.user_key)

        # 같은 계정을 대소문자만 바꿔 적어도 본인으로 처리된다
        mu.graph.reset()
        result = c.call(alice.key, tool, {**args, "user_email": "ALICE@Contoso.com"})
        assert not result.is_error, result.text[:500]
        assert_graph_calls_belong_to(mu, alice, bob)


@pytest.mark.parametrize("domain", GRAPH_DOMAINS)
def test_other_users_email_is_identity_mismatch_without_touching_b(mu, alice, bob, spy, domain):
    tool, args = READ_TOOLS[domain]
    with mu.client(domain) as c:
        # B 의 서비스가 풀에 살아 있어도(이미 한 번 호출) A 의 요청이 그것을 쓰지 않는다
        assert not c.call(bob.key, tool, args).is_error
        mu.graph.reset()
        spy.reset()

        result = c.call(alice.key, tool, {**args, "user_email": bob.email})

    assert result.is_error
    assert result.error_code == "identity_mismatch", result.text[:300]
    assert mu.graph.calls == []
    assert not spy.touched_user(bob.user_key), (spy.auth_store_users, spy.sqlite_paths, spy.token_principals)
    # 응답이 B 계정의 존재 여부를 알려 주지 않는다
    assert bob.email not in result.text


@pytest.mark.parametrize("domain", GRAPH_DOMAINS)
@pytest.mark.parametrize("value", [None, "", "   ", 123])
def test_invalid_user_email_values_are_input_errors(mu, alice, value, domain):
    tool, args = READ_TOOLS[domain]
    with mu.client(domain) as c:
        result = c.call(alice.key, tool, {**args, "user_email": value})
    assert result.is_error
    assert result.error_code == "invalid_user_email", result.text[:300]
    assert mu.graph.calls == []


@pytest.mark.parametrize("domain", GRAPH_DOMAINS)
@pytest.mark.parametrize("field", ["user_key", "db_path", "principal", "tenant_id", "token"])
def test_injected_security_arguments_rejected(mu, alice, bob, spy, domain, field):
    tool, args = READ_TOOLS[domain]
    forged = {"user_key": bob.user_key, "db_path": "C:/x/onenote.db", "principal": {"user_key": bob.user_key},
              "tenant_id": bob.account.tenant_id, "token": "at-forged"}[field]
    with mu.client(domain) as c:
        result = c.call(alice.key, tool, {**args, field: forged})
    assert result.is_error
    assert result.error_code == "unexpected_argument", result.text[:300]
    assert mu.graph.calls == []
    assert not spy.touched_user(bob.user_key)


@pytest.mark.parametrize("domain", GRAPH_DOMAINS)
def test_forged_identity_headers_and_default_email_env_do_not_change_caller(mu, alice, bob, domain):
    """I03·I08 — 위조 `X-User-*` 헤더, 기동 뒤 생긴 `MS365_DEFAULT_USER_EMAIL` 은 무시된다."""
    tool, args = READ_TOOLS[domain]
    with mu.client(domain) as c:
        mu.monkeypatch.setenv("MS365_DEFAULT_USER_EMAIL", bob.email)
        result = c.call(
            alice.key, tool, args,
            **{"X-User-Email": bob.email, "X-User-Key": bob.user_key, "X-Forwarded-User": bob.email},
        )
        mu.monkeypatch.delenv("MS365_DEFAULT_USER_EMAIL")
    assert not result.is_error, result.text[:300]
    assert_graph_calls_belong_to(mu, alice, bob)
