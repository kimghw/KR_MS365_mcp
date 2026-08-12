"""
공통 오류 계약.

기존에는 서버/transport 마다 실패 표현이 제각각이었다:
  - `{"status": "error", ...}` 를 TextContent 로 반환 (MCP 성공 경로처럼 보임)
  - `{"success": false, ...}`
  - JSON-RPC error

MCP 관점에서 도구 실행 실패는 CallToolResult(isError=True) 하나로 표현해야 한다.
MCP Python SDK lowlevel Server 는 call_tool 핸들러가 예외를 던지면
CallToolResult(isError=True) 로 감싸주므로, 실패는 ToolExecutionError 로 올린다.
"""

import json
from typing import Any, Dict, List, Optional


class ToolExecutionError(Exception):
    """도구 실행 실패. 메시지는 JSON 문자열로 직렬화되어 클라이언트에 전달된다."""

    def __init__(self, payload: Any, *, tool: Optional[str] = None):
        self.payload = payload
        self.tool = tool
        super().__init__(_to_text(payload))


class ToolValidationError(ToolExecutionError):
    """입력 스키마 검증 실패."""


def _to_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(payload)


def is_failure(result: Any) -> bool:
    """핸들러 반환값이 실패를 나타내는지 판정 (기존 3가지 표현 모두 인식)."""
    if not isinstance(result, dict):
        return False
    if result.get("status") in ("error", "failed", "auth_required"):
        return True
    if result.get("success") is False:
        return True
    if result.get("isError") is True:
        return True
    return False


def normalize_tool_result(result: Any, *, tool: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    핸들러 반환값을 MCP content block(dict) 목록으로 정규화한다.

    실패로 판정되면 ToolExecutionError 를 던져 SDK 가 isError=True 로 감싸게 한다.
    반환 형식은 `{"type": "text", "text": ...}` dict 목록이며, 호출측에서
    mcp.types.TextContent 로 변환한다 (mcp_common 이 SDK 에 하드 의존하지 않도록).
    """
    if is_failure(result):
        raise ToolExecutionError(result, tool=tool)

    if isinstance(result, str):
        return [{"type": "text", "text": result}]

    # 핸들러가 이미 MCP 형태의 content 를 담아 반환하는 경우
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        blocks: List[Dict[str, Any]] = []
        for item in result["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                blocks.append({"type": "text", "text": item.get("text", "")})
            else:
                blocks.append({"type": "text", "text": _to_text(item)})
        return blocks

    return [{"type": "text", "text": _to_text(result)}]
