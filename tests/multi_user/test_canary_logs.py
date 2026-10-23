"""시나리오 8 — 로그·감사·응답에 민감 canary 가 남지 않는다 (②-9, ②-10 R01·A02).

입력에 canary 를 심는다: 미지 bearer key, JWT(Authorization·Cookie·도구 인자), 다른 사람 이메일
(`user_email`·`X-User-Email`), 위조 인자 값. 실제 OAuth 연결·도구 호출·실패 경로를 8개 서버로
돌린 뒤 **필터를 거치지 않은 원본 로그 레코드**(caplog, DEBUG)·감사 jsonl·HTTP 응답을 검사한다.

- 비밀(키 secret·Graph access/refresh token·JWT·canary key): 모든 레코드에 없어야 한다.
- 이메일·데이터 루트 절대경로: 모든 레코드에 없어야 한다. 단 `sse_starlette` DEBUG 의 응답 청크
  (호출자 본인에게 가는 응답 본문 그 자체, 운영 기본 INFO 에서는 나오지 않음)는 제외한다.
- 감사: 비밀·이메일·경로 없음 + principal(user_key)·request_id 로 추적 가능.
"""

import json
import logging

import pytest

from mcp_common.principal import DOMAINS
from session.tests.mu_support import ALICE, BOB
from tests.multi_user.harness import GRAPH_DOMAINS, READ_TOOLS, FakeHttpResponse, rpc

CANARY_EMAIL = "canary.zq7@evil.example"
CANARY_KEY_SECRET = "CANARYsecret" + "A" * 31
CANARY_KEY = "m365v1." + "c" * 32 + "." + CANARY_KEY_SECRET
CANARY_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJDQU5BUllKV1QifQ.Q0FOQVJZU0lHTkFUVVJF"
CANARY_ARG = "CANARY-ARG-VALUE-9f3"


def _record_text(record: logging.LogRecord) -> str:
    try:
        message = record.getMessage()
    except Exception:  # pragma: no cover - 형식 오류 레코드
        message = str(record.msg)
    return message + (record.exc_text or "") + (record.stack_info or "")


def test_canaries_never_reach_logs_audit_or_responses(mu, caplog):
    caplog.set_level(logging.DEBUG)
    alice = mu.onboard(ALICE)
    bob = mu.onboard(BOB)
    responses = []

    for domain in DOMAINS:
        with mu.client(domain) as c:
            responses.append(c.post(rpc("tools/list"), CANARY_KEY))
            responses.append(c.post(rpc("tools/list"), None, Authorization=f"Bearer {CANARY_JWT}",
                                    Cookie=f"m365_oauth_x={CANARY_JWT}"))
            if domain in READ_TOOLS:
                tool, args = READ_TOOLS[domain]
                ok = c.call(alice.key, tool, args, **{"X-User-Email": CANARY_EMAIL})
                assert not ok.is_error, ok.text[:300]
                for extra in ({"user_email": CANARY_EMAIL}, {"canary_arg": CANARY_ARG}, {"user_email": bob.email}):
                    result = c.call(alice.key, tool, {**args, **extra})
                    assert result.is_error
                    responses.append(result)

    # 401 응답·도구 오류 응답이 입력 canary 를 되돌려 주지 않는다
    for item in responses:
        text = item.text
        for canary in (CANARY_KEY_SECRET, CANARY_JWT, CANARY_EMAIL, CANARY_ARG, bob.email):
            assert canary not in text, (canary, text[:200])

    secrets = {
        "alice_key_secret": alice.key.split(".")[2],
        "bob_key_secret": bob.key.split(".")[2],
        "canary_key": CANARY_KEY_SECRET,
        "canary_jwt": CANARY_JWT[:24],
        "canary_arg": CANARY_ARG,
    }
    secrets.update({f"graph_access_{i}": t for i, t in enumerate(mu.entra.access)})
    secrets.update({f"graph_refresh_{i}": t for i, t in enumerate(mu.entra.refresh_tokens)})
    personal = {
        "canary_email": CANARY_EMAIL,
        "alice_email": ALICE.email,
        "bob_email": BOB.email,
        "data_root": str(mu.root),
        "data_root_posix": str(mu.root).replace("\\", "/"),
    }

    records = caplog.records
    assert records, "로그가 하나도 잡히지 않았다 — caplog 설정 확인"
    leaks = []
    for record in records:
        text = _record_text(record)
        for name, value in secrets.items():
            if value in text:
                leaks.append((name, record.name, record.levelname))
        if record.name.startswith("sse_starlette") and record.levelno <= logging.DEBUG:
            continue
        for name, value in personal.items():
            if value in text:
                leaks.append((name, record.name, record.levelname))
    assert leaks == []

    audit = mu.audit_text()
    assert audit, "감사 파일이 비어 있다"
    for name, value in {**secrets, **personal}.items():
        assert value not in audit, name

    lines = [json.loads(line) for line in audit.splitlines() if line.strip()]
    events = {(r["event"], r.get("outcome"), r.get("error_code")) for r in lines}
    assert ("auth.bearer", "failure", "unauthenticated") in events
    assert ("auth.identity_mismatch", "denied", "identity_mismatch") in events
    assert ("tool.call", "denied", "unexpected_argument") in events
    # A 의 도구 호출은 user_key·request_id 로 추적된다
    alice_calls = [r for r in lines if r["event"] == "tool.call" and r.get("user_key") == alice.user_key]
    assert alice_calls and all(r.get("request_id") and r.get("domain") for r in alice_calls)
    assert {r["domain"] for r in alice_calls} == set(READ_TOOLS)


def test_secrets_not_left_in_data_root_files(mu):
    """A02 — DB·WAL·JSON 어디에도 평문 bearer secret·Graph 토큰이 없다(실제 OAuth·도구 호출 뒤)."""
    from tests.multi_user.harness import contains_bytes

    alice = mu.onboard(ALICE)
    with mu.client("calendar") as c:
        assert not c.call(alice.key, "list_events", {}).is_error
    needles = [alice.key.split(".")[2], *mu.entra.access, *mu.entra.refresh_tokens]
    for needle in needles:
        assert contains_bytes(mu.root, needle.encode("utf-8")) == [], needle[:8]


# ----------------------------------------------------------------------
# 외부 오류 원문 (②-9 "외부 오류는 정해진 코드와 request_id 로 변환한다")
# ----------------------------------------------------------------------
EXC_CANARY = "CANARY-EXC-7c1"
BODY_CANARY = "CANARY-BODY-5e2"

@pytest.mark.parametrize("domain", GRAPH_DOMAINS)
def test_transport_exception_text_not_reflected(mu, alice, domain):
    def _boom(call):
        raise OSError(f"[Errno 13] Permission denied: 'D:\\\\ms365-data\\\\users\\\\x\\\\files' {EXC_CANARY}")

    mu.graph.on(None, r".", _boom)
    tool, args = READ_TOOLS[domain]
    with mu.client(domain) as c:
        result = c.call(alice.key, tool, args)
    assert result.is_error
    assert EXC_CANARY not in result.text and "ms365-data" not in result.text


@pytest.mark.parametrize("domain", GRAPH_DOMAINS)
def test_graph_error_body_not_reflected(mu, alice, domain):
    mu.graph.on(None, r".", FakeHttpResponse(500, {"error": {"code": "InternalServerError",
                                                             "message": f"internal detail {BODY_CANARY}"}}))
    tool, args = READ_TOOLS[domain]
    with mu.client(domain) as c:
        result = c.call(alice.key, tool, args)
    assert result.is_error
    assert BODY_CANARY not in result.text
