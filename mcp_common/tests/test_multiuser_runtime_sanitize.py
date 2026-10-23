"""mode 1 도메인 실패 페이로드 정화 — 외부 응답·예외 원문 비노출 이중 방어 (spec/spec_멀티유저.md ②-9, R01)."""

import json

import pytest

from mcp_common.errors import ToolExecutionError, ToolValidationError
from mcp_common.runtime import ToolRuntime
from mcp_common.testing import bound, make_principal, multi_user_mode, single_user_mode

ALICE = make_principal("alice@contoso.com")
SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}
CANARY = "CANARY-7f3a"

FAILURE = {
    "status": "error",
    "error": f"OSError: [Errno 13] Permission denied: 'D:\\ms365-data\\users\\abc\\files' {CANARY}",
    "message": "Graph 호출 실패 bob@fabrikam.com /home/svc/app/x.py",
    "details": {"error": {"code": "InternalServerError", "message": f"internal {CANARY}"}},
    "status_code": 500,
    "nested": {"response_body": f"{CANARY}", "graph_error_code": "InternalServerError"},
}


async def _active(_principal):
    return None


def _runtime(handler):
    tools = [{"name": "t", "inputSchema": SCHEMA}]
    return ToolRuntime("wp0san", tools, {"t": handler}, active_checker=_active)


async def test_mode1_failure_payload_is_scrubbed(tmp_path):
    async def handler(_args):
        return dict(FAILURE)

    with multi_user_mode(tmp_path), bound(ALICE):
        with pytest.raises(ToolExecutionError) as e:
            await _runtime(handler).call("t", {"q": "x"})
    text = str(e.value)
    payload = json.loads(text)
    assert CANARY not in text
    assert "ms365-data" not in text and "/home/svc" not in text
    assert "bob@fabrikam.com" not in text
    assert "details" not in payload and "response_body" not in payload["nested"]
    # 고정 코드·상태는 남는다
    assert payload["status"] == "error" and payload["status_code"] == 500
    assert payload["nested"]["graph_error_code"] == "InternalServerError"


async def test_mode1_validation_error_is_not_rewritten(tmp_path):
    async def handler(_args):
        return {"ok": True}

    with multi_user_mode(tmp_path), bound(ALICE):
        with pytest.raises(ToolValidationError):
            await _runtime(handler).call("t", {"q": 1})


async def test_mode0_failure_payload_unchanged():
    async def handler(_args):
        return dict(FAILURE)

    with single_user_mode():
        with pytest.raises(ToolExecutionError) as e:
            await _runtime(handler).call("t", {"q": "x"})
    assert CANARY in str(e.value)  # mode 0 은 기존 동작 유지
