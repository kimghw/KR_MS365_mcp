"""시나리오 2 보강 — 리소스 ID·URL 인자로 Graph 대상 사용자를 바꿀 수 없다 (②-1.1-2, ②-7.5, ②-10 G01).

ID 자리에 `../../users/<B>`·인코딩된 변형·절대 URL 을 넣는다. 기록하는 URL 은 aiohttp 가 실제로
보내는 것 — 문자열 URL 은 `yarl.URL` 이 되며 **dot-segment(`..`) 가 정규화**된다. 그래서
`/me/events/../../users/B` 는 실제로 `/v1.0/users/B` 로 나간다.

판정: 모든 요청이 (1) Graph 호스트로만, (2) 호출자 토큰으로, (3) `/v1.0/me...`·A 자신의
`/users/{A}`·`/$batch` 아래로만 가고, (4) 도메인 코드가 aiohttp 에 넘긴 경로에 `..` 세그먼트가
없어야(= ID 가 경로 구조를 바꾸지 못해야) 한다.
"""

import json
from urllib.parse import urlsplit

import pytest

from tests.multi_user.harness import GRAPH_HOST

BOB = "bob@contoso.com"
BOB_OID = "bbbbbbbb-0000-4000-8000-00000000000b"

#: (이름, 값) — 앞쪽 다섯 개는 슬래시 dot-segment 로 경로를 탈출한다
TRAVERSALS = [
    ("dotdot2_email", f"../../users/{BOB}"),
    ("dotdot3_email", f"../../../users/{BOB}/events"),
    ("dotdot4_email", f"../../../../users/{BOB}"),
    ("dotdot_oid", f"../../../users/{BOB_OID}"),
    ("dotdot_batch", "../../../../$batch"),
    ("encoded_slash", f"..%2F..%2Fusers%2F{BOB}"),
    ("backslash", f"..\\..\\users\\{BOB}"),
    ("absolute_url", f"https://graph.microsoft.com/v1.0/users/{BOB}/messages"),
]
ESCAPING = {"dotdot2_email", "dotdot3_email", "dotdot4_email", "dotdot_oid", "dotdot_batch"}

CASES = {
    "calendar": ("get_event", lambda v: {"event_id": v}),
    "todo": ("todo_task_get", lambda v: {"list_id_or_name": v, "task_id": v}),
    "teams": ("handler_teams_get_chat", lambda v: {"chat_id": v}),
    "onedrive": ("handler_onedrive_read_file", lambda v: {"file_path": v}),
    "onenote": ("read_onenote", lambda v: {"action": "get_content", "page_id": v}),
    "outlook": ("mail_query_if_emaidID", lambda v: {"message_ids": [v]}),
}

def _allowed_path(path: str, alice) -> bool:
    lowered = path.lower()
    return (
        lowered == "/v1.0/me"
        or lowered.startswith("/v1.0/me/")
        or lowered.startswith(f"/v1.0/users/{alice.email}")
        or lowered.startswith(f"/v1.0/users/{alice.account.object_id}")
        or lowered == "/v1.0/$batch"
    )


def _assert_no_cross_user_target(mu, alice):
    for call in mu.graph.calls:
        assert call.host == GRAPH_HOST, f"Graph 밖으로 토큰 전송: {call.url}"
        assert mu.graph.owner(call) == alice.account
        assert _allowed_path(call.path, alice), f"호출자 범위를 벗어난 Graph 경로: {call.method} {call.path}"
        raw_segments = urlsplit(call.raw_url).path.split("/")
        assert ".." not in raw_segments, f"ID 가 경로 구조를 바꿨다(dot-segment): {call.raw_url}"
        inner = call.kwargs.get("json") or {}
        for request in inner.get("requests", []) if isinstance(inner, dict) else []:
            url = str(request.get("url", ""))
            segments = [s.lower() for s in urlsplit(url).path.split("/")]
            assert ".." not in segments, url
            # 인코딩된(%2F) 값은 한 세그먼트 안의 문자일 뿐이다 — 구조상 /users/{B} 로 시작하면 안 된다
            assert not (len(segments) > 2 and segments[1] == "users" and segments[2] in (BOB, BOB_OID)), url


def _cases():
    # 모든 도메인이 호출자 ID 를 `mcp_common.graph_paths.graph_segment()` 로 단일 세그먼트 인코딩한다
    # (2026-10-23 G01 수정). 어느 도메인이든 dot-segment 로 경로를 탈출하면 안 된다.
    return [
        pytest.param(domain, value, id=f"{domain}-{name}")
        for domain in CASES
        for name, value in TRAVERSALS
    ]


@pytest.mark.parametrize("domain,value", _cases())
def test_resource_id_cannot_retarget_graph_path(mu, alice, domain, value):
    tool, build = CASES[domain]
    with mu.client(domain) as c:
        c.call(alice.key, tool, build(value))  # 성공·실패와 무관하게 나간 요청만 본다
    _assert_no_cross_user_target(mu, alice)


def test_delete_with_traversal_id_cannot_delete_other_users_event(mu, alice):
    """같은 결함의 파괴적 형태 — delete_event 가 다른 사용자 경로로 DELETE 를 보낸다."""
    with mu.client("calendar") as c:
        c.call(alice.key, "delete_event", {"event_id": f"../../../users/{BOB}/events/AAMk-bob-event"})
    deletes = [call for call in mu.graph.calls if call.method == "DELETE"]
    assert all(_allowed_path(call.path, alice) for call in deletes), [c.path for c in deletes]


@pytest.mark.parametrize("url", [
    f"https://graph.microsoft.com/v1.0/users/{BOB}/messages",
    f"https://graph.microsoft.com/v1.0/users/{BOB_OID}/messages",
    "https://graph.microsoft.com/v1.0/me/../users/bob@contoso.com/messages",
    "https://evil.example/v1.0/me/messages",
    "http://graph.microsoft.com/v1.0/me/messages",
    "https://graph.microsoft.com.evil.example/v1.0/me/messages",
    "https://127.0.0.1:5001/mcp",
])
def test_mail_query_url_cannot_reach_other_user_or_host(mu, alice, url):
    with mu.client("outlook") as c:
        result = c.call(alice.key, "mail_query_url", {"url": url})
    assert result.is_error, result.text[:300]
    _assert_no_cross_user_target(mu, alice)


def test_mail_query_url_next_link_to_other_user_is_not_followed(mu, alice):
    """다음 페이지 URL 도 같은 정책 — Graph 가 준 nextLink 가 B 를 가리키면 따라가지 않는다."""
    page = {"value": [{"id": "m1", "subject": "s"}],
            "@odata.nextLink": f"https://graph.microsoft.com/v1.0/users/{BOB}/messages?$skip=10"}
    mu.graph.on("GET", r"/me/messages$", page)
    mu.graph.on("GET", rf"/users/{alice.email}/messages$", page)
    with mu.client("outlook") as c:
        c.call(alice.key, "mail_query_url", {"url": "https://graph.microsoft.com/v1.0/me/messages"})
    assert mu.graph.calls, "첫 페이지 요청이 없다"
    _assert_no_cross_user_target(mu, alice)
