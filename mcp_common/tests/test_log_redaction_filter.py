"""WP10 로그 마스킹 — `mcp_common.log_redaction` (spec/spec_멀티유저.md ②-9, 테스트 R01).

canary 비밀이 로그 출력에 남지 않고, principal(user_key)·request_id 는 추적 가능하게 남는지 본다.
"""

import io
import logging

import pytest

from mcp_common import bootstrap
from mcp_common.log_redaction import (
    DEFAULT_LOGGERS,
    REDACTED,
    RedactionFilter,
    install_redaction,
    redact_text,
)
from mcp_common.security_policy import reset_policy_cache
from mcp_common.testing import make_principal, multi_user_mode, single_user_mode

KID = "0123456789abcdef0123456789abcdef"
SECRET = "S3cr3tS3cr3tS3cr3tS3cr3tS3cr3tS3cr3tS3cr3tX"
BEARER_KEY = f"m365v1.{KID}.{SECRET}"
JWT = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJvaWQiOiJjYW5hcnkiLCJ0aWQiOiJ4In0.c2lnbmF0dXJlLWNhbmFyeQ"
EMAIL = "canary.person@contoso.com"
OPAQUE_REFRESH = "0.AXoA" + "R" * 300


@pytest.fixture
def capture():
    """필터를 단 전용 핸들러로 포맷된 최종 출력을 받는다."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s|%(message)s"))
    handler.addFilter(RedactionFilter())
    log = logging.getLogger("test.redaction")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False
    try:
        yield log, stream
    finally:
        log.removeHandler(handler)
        log.propagate = True


@pytest.fixture
def restore_filters():
    """install_redaction() 이 전역 로거에 남기는 필터를 테스트 뒤에 되돌린다."""
    root = logging.getLogger()
    targets = [root, *root.handlers, *(logging.getLogger(n) for n in DEFAULT_LOGGERS)]
    for name in DEFAULT_LOGGERS:
        targets.extend(logging.getLogger(name).handlers)
    saved = {id(t): (t, list(t.filters)) for t in targets}
    yield
    for target, filters in saved.values():
        target.filters[:] = filters


# ----------------------------------------------------------------------
# redact_text
# ----------------------------------------------------------------------
def test_bearer_key_secret_masked_kid_kept():
    out = redact_text(f"auth with {BEARER_KEY} ok")
    assert SECRET not in out and f"m365v1.{KID}.{REDACTED}" in out
    assert SECRET[:8] not in redact_text(f"m365v1.short.{SECRET}")


def test_jwt_and_its_prefix_masked():
    assert JWT not in redact_text(f"token={JWT}")
    assert "eyJ0eXAiOiJKV1Qi" not in redact_text(f"token prefix: {JWT[:24]}...")
    assert "eyJvaWQi" not in redact_text(JWT)


@pytest.mark.parametrize(
    "line,leak",
    [
        ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
        ("{'Authorization': 'Bearer zzzzzzzzzzzz', 'Accept': 'json'}", "zzzzzzzzzzzz"),
        ('{"authorization": "Basic dXNlcjpwYXNzd29yZA=="}', "dXNlcjpwYXNzd29yZA"),
        ("Proxy-Authorization=Negotiate YYYYYYYYYY", "YYYYYYYYYY"),
        ("Cookie: ms365_session=AAAA; other=BBBB", "AAAA"),
        ("Cookie: ms365_session=AAAA; other=BBBB", "BBBB"),
        ("set-cookie: ticket=TTTTTTTT; HttpOnly", "TTTTTTTT"),
        ("sending Bearer qqqqqqqqqqqqqqqq to graph", "qqqqqqqqqqqqqqqq"),
    ],
)
def test_headers_and_bearer_values_masked(line, leak):
    assert leak not in redact_text(line)


def test_authorization_mask_keeps_rest_of_line():
    out = redact_text("Authorization: Bearer abcdefghijklmnop request_id=req-1")
    assert "request_id=req-1" in out


@pytest.mark.parametrize(
    "key", ["code", "state", "code_verifier", "refresh_token", "access_token", "id_token",
            "client_secret", "session_state", "nonce", "ticket", "password"]
)
def test_oauth_query_and_form_values_masked(key):
    for line in (
        f"GET /auth/callback?{key}=CANARYVALUE123&x=1",
        f"POST body grant_type=authorization_code&{key}=CANARYVALUE123",
        f"{key}=CANARYVALUE123",
    ):
        out = redact_text(line)
        assert "CANARYVALUE123" not in out and f"{key}={REDACTED}" in out


def test_non_secret_keys_are_kept():
    out = redact_text("error_code=invalid_grant status_code=400 request_id=req-1 user_key=abc")
    assert out == "error_code=invalid_grant status_code=400 request_id=req-1 user_key=abc"


def test_json_token_fields_masked_but_graph_error_code_kept():
    body = '{"access_token": "AT-CANARY", "refresh_token": "RT-CANARY", "error": {"code": "InvalidAuthenticationToken"}}'
    out = redact_text(body)
    assert "AT-CANARY" not in out and "RT-CANARY" not in out
    assert "InvalidAuthenticationToken" in out


def test_long_opaque_token_masked():
    assert OPAQUE_REFRESH not in redact_text(f"refresh failed for {OPAQUE_REFRESH}")


def test_email_masked_only_when_requested():
    line = f"user {EMAIL} and /users/{EMAIL.replace('@', '%40')}/messages"
    assert EMAIL in redact_text(line)
    out = redact_text(line, mask_emails=True)
    assert "canary.person" not in out and "***@contoso.com" in out and "***%40contoso.com" in out


def test_query_strip():
    out = redact_text('"GET /auth/callback?code=x&state=y HTTP/1.1" 200', strip_query=True)
    assert out == '"GET /auth/callback HTTP/1.1" 200'


# ----------------------------------------------------------------------
# RedactionFilter on records (R01)
# ----------------------------------------------------------------------
def test_record_args_and_traceback_are_masked(capture):
    log, stream = capture
    principal = make_principal(EMAIL)
    with single_user_mode():
        log.info("calling graph key=%s jwt=%s", BEARER_KEY, JWT)
        log.warning("oauth body: %r", {"refresh_token": "RT-CANARY-1", "code": "C"})
        try:
            raise RuntimeError(f"token endpoint said access_token=AT-CANARY-2 for {JWT}")
        except RuntimeError:
            log.exception("refresh failed user_key=%s request_id=%s", principal.user_key, "req-trace-01")
    out = stream.getvalue()
    for leak in (SECRET, JWT, "RT-CANARY-1", "AT-CANARY-2"):
        assert leak not in out
    # 추적성: user_key·request_id 는 남는다
    assert principal.user_key in out and "req-trace-01" in out
    assert "RuntimeError" in out  # traceback 자체는 남는다


def test_email_masked_in_mode1_records_only(capture, tmp_path):
    log, stream = capture
    with single_user_mode():
        log.info("mode0 user %s", EMAIL)
    assert EMAIL in stream.getvalue()
    with multi_user_mode(tmp_path):
        log.info("mode1 user %s", EMAIL)
    assert stream.getvalue().count(EMAIL) == 1


def test_unformattable_record_does_not_leak(capture):
    log, stream = capture
    with single_user_mode():
        log.info("only one %s", BEARER_KEY, "extra-arg")  # 인자 개수 불일치
    out = stream.getvalue()
    assert SECRET not in out and "extra-arg" not in out


def test_redaction_failure_fails_closed(capture, monkeypatch):
    log, stream = capture
    from mcp_common import log_redaction

    monkeypatch.setattr(log_redaction, "redact_text", lambda *a, **k: 1 / 0)
    log.info("secret %s", BEARER_KEY)
    out = stream.getvalue()
    assert SECRET not in out and "redaction failed" in out


def test_uvicorn_access_args_keep_structure_and_lose_query():
    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", f"/auth/callback?code=CANARYCODE&state=CANARYSTATE&u={EMAIL}", "1.1", 200),
        None,
    )
    RedactionFilter().filter(record)
    assert record.args[2] == "/auth/callback"
    text = AccessFormatter(fmt='%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert "CANARY" not in text and "/auth/callback" in text and "200" in text


def test_aiohttp_access_message_and_extra_lose_query():
    line = '127.0.0.1 [x] "GET /auth/callback?code=CANARYCODE&state=CANARYSTATE HTTP/1.1" 302 0 "https://login.microsoftonline.com/?x=CANARYREF" "UA"'
    record = logging.LogRecord("aiohttp.access", logging.INFO, __file__, 1, line, None, None)
    record.first_request_line = "GET /auth/callback?code=CANARYCODE HTTP/1.1"
    record.request_header = {"Referer": "https://login.microsoftonline.com/?x=CANARYREF"}
    RedactionFilter().filter(record)
    assert "CANARY" not in record.getMessage()
    assert "CANARY" not in record.first_request_line
    assert "CANARY" not in record.request_header["Referer"]
    assert "/auth/callback" in record.getMessage()


def test_outbound_url_query_stripped_in_mode1_only(tmp_path):
    url = "https://graph.microsoft.com/v1.0/me/messages?$search=%22salary%22&$top=5"

    def run():
        record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "HTTP Request: GET %s", (url,), None)
        RedactionFilter().filter(record)
        return record.getMessage()

    with single_user_mode():
        assert "salary" in run()
    with multi_user_mode(tmp_path):
        assert "salary" not in run() and "/v1.0/me/messages" in run()


def test_filter_is_applied_once_per_record():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "k=%s", (BEARER_KEY,), None)
    first = RedactionFilter()
    assert first.filter(record) and RedactionFilter().filter(record)
    assert record.getMessage() == f"k=m365v1.{KID}.{REDACTED}"


# ----------------------------------------------------------------------
# install / bootstrap
# ----------------------------------------------------------------------
def test_install_redaction_is_idempotent(restore_filters):
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    try:
        install_redaction()
        install_redaction(extra_loggers=["custom.lib"])
        install_redaction()
        assert sum(isinstance(f, RedactionFilter) for f in handler.filters) == 1
        for name in ("uvicorn.access", "uvicorn.error", "aiohttp.access", "httpx", "custom.lib"):
            assert sum(isinstance(f, RedactionFilter) for f in logging.getLogger(name).filters) == 1
    finally:
        root.removeHandler(handler)
        logging.getLogger("custom.lib").filters.clear()


def test_logger_level_filter_survives_uvicorn_dictconfig(restore_filters):
    """uvicorn 은 기동 때 dictConfig 로 핸들러를 갈아 끼운다 — 로거 수준 필터는 남아야 한다."""
    import logging.config

    from uvicorn.config import LOGGING_CONFIG

    install_redaction()
    access = logging.getLogger("uvicorn.access")
    saved = (list(access.handlers), access.propagate, access.level)
    try:
        logging.config.dictConfig(LOGGING_CONFIG)
        assert any(isinstance(f, RedactionFilter) for f in access.filters)
    finally:
        access.handlers[:] = saved[0]
        access.propagate, access.level = saved[1], saved[2]
        for name in ("uvicorn", "uvicorn.error"):
            logging.getLogger(name).handlers.clear()


def test_bootstrap_installs_redaction_and_logs_mode(restore_filters, caplog):
    handler = logging.StreamHandler(io.StringIO())
    logging.getLogger().addHandler(handler)
    try:
        with single_user_mode(), caplog.at_level(logging.INFO, logger="mcp_common.bootstrap"):
            bootstrap._install_log_redaction()
            bootstrap._log_mode()
        assert any(isinstance(f, RedactionFilter) for f in handler.filters)
        assert "multi_user=False" in caplog.text
    finally:
        logging.getLogger().removeHandler(handler)


def test_bootstrap_mode_log_tolerates_bad_config(monkeypatch, caplog):
    monkeypatch.setenv("MS365_MULTI_USER", "maybe")
    reset_policy_cache()
    try:
        with caplog.at_level(logging.INFO, logger="mcp_common.bootstrap"):
            bootstrap._log_mode()  # 기동 검사(validate_startup)가 막는다 — 여기서는 기록만
        assert "multi_user=invalid" in caplog.text
    finally:
        monkeypatch.delenv("MS365_MULTI_USER")
        reset_policy_cache()


def test_bootstrap_keeps_ordering_contract():
    import inspect

    doc = bootstrap.__doc__
    steps = ["1. 원본 stdout", "2. `.env` 로드", "5. 로깅 설정", "6. 로그 마스킹 필터 설치", "7. 모드 기록", "8. 그 다음에야"]
    positions = [doc.index(step) for step in steps]
    assert positions == sorted(positions)
    source = inspect.getsource(bootstrap._common)
    calls = ["_load_env(", "_strip_env_bom(", "_insert_paths(", "_configure_logging(", "_install_log_redaction(", "_log_mode("]
    order = [source.index(call) for call in calls]
    assert order == sorted(order)
    stdio = inspect.getsource(bootstrap.bootstrap_stdio)
    assert stdio.index("sys.stdout = sys.stderr") < stdio.index("_common(")
