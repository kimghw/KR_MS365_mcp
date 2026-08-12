"""
FileHandler MCP REST 서버 (FastAPI, JSON over HTTP)

보안 주의:
    - 이 서버에는 **호출자 인증이 없다**. 기본 바인드는 loopback(127.0.0.1) 전용이며,
      외부 노출은 `MCP_BIND_HOST` + `MCP_ALLOW_PUBLIC_BIND=1` 옵트인이 필요하다.
    - 도구가 여는 모든 파일/디렉터리는 `mcp_common.paths` 허용 루트로 제한된다
      (기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장).

표준 MCP Streamable HTTP 클라이언트는 `server_stream.py` 의 `/mcp` 를 쓴다.
이 모듈은 그와 별개인 **단순 REST 래퍼**(`/mcp/v1/*`)이며, 도구 실행은 동일한
`ToolRuntime` 을 경유한다(동기 핸들러를 `await` 하던 버그가 재발하지 않는다).
실패는 성공 200 이 아니라 적절한 HTTP 상태코드로 나간다.
"""

import logging
import os
import sys
from typing import Any, Dict, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

for _path in (grandparent_dir, parent_dir, current_dir):
    if _path not in sys.path:
        sys.path.insert(0, _path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from mcp_common.errors import ToolExecutionError, ToolValidationError
from mcp_common.net import resolve_bind_host
from mcp_common.runtime import build_health_payload, health_status_code

try:
    from .handlers import (
        MCP_TOOLS,
        SERVER_NAME,
        SERVER_VERSION,
        build_lifecycle,
        build_runtime,
        security_payload,
    )
except ImportError:  # 스크립트 직접 실행
    from handlers import (  # type: ignore[no-redef]
        MCP_TOOLS,
        SERVER_NAME,
        SERVER_VERSION,
        build_lifecycle,
        build_runtime,
        security_payload,
    )

DEFAULT_REST_PORT = 8000

runtime = build_runtime()
lifecycle = build_lifecycle()

app = FastAPI(title="File Handler MCP Server (REST)", version=SERVER_VERSION)


@app.on_event("startup")
async def startup_event() -> None:
    await lifecycle.startup()
    if lifecycle.errors:
        logger.error("초기화 실패로 degraded 상태입니다: %s", lifecycle.errors)
    logger.info("File Handler MCP REST server started (tools=%d)", len(runtime.tools))


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await lifecycle.shutdown()
    logger.info("File Handler MCP REST server stopped")


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "name": "File Handler MCP Server (REST)",
        "version": SERVER_VERSION,
        "standard_endpoint": "server_stream.py 의 /mcp (Streamable HTTP)",
        "security": security_payload(),
    }


@app.get("/health")
async def health_check() -> JSONResponse:
    payload = build_health_payload(
        SERVER_NAME, runtime, lifecycle, version=SERVER_VERSION, protocol="rest"
    )
    payload["security"] = security_payload()
    return JSONResponse(content=payload, status_code=health_status_code(payload))


@app.post("/mcp/v1/initialize")
async def initialize(request: Request) -> Dict[str, Any]:
    return {
        "serverInfo": {"name": f"{SERVER_NAME}-mcp-server", "version": SERVER_VERSION},
        "capabilities": {"tools": {}},
        "note": "표준 MCP 클라이언트는 server_stream.py 의 /mcp 를 사용하십시오.",
    }


@app.post("/mcp/v1/tools/list")
async def list_tools(request: Request) -> JSONResponse:
    tools_list = [
        {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": runtime.input_schema(tool["name"]),
        }
        for tool in MCP_TOOLS
        if tool.get("name")
    ]
    return JSONResponse(content={"result": {"tools": tools_list}})


def _status_for(error: ToolExecutionError) -> Tuple[int, Dict[str, Any]]:
    """도구 실행 실패를 적절한 HTTP 상태코드로 매핑한다."""
    payload = error.payload if isinstance(error.payload, dict) else {"message": str(error)}
    code = str(payload.get("error") or "")

    if isinstance(error, ToolValidationError) or code == "invalid_arguments":
        return 400, payload
    if code == "unknown_tool":
        return 404, payload
    if code in ("not_found",):
        return 404, payload
    if code in ("PathNotAllowedError", "NotADirectoryError", "ValueError", "KeyError"):
        return 400, payload
    if code in ("FileNotFoundError",):
        return 404, payload

    # FileManager.process() 는 경로 거부/미존재 예외를 잡아서 {"success": false,
    # "errors": [...]} 로 반환한다. 이 payload 에는 error/message 키가 없으므로,
    # errors 목록 문자열을 함께 살펴 400/404 로 매핑한다(그렇지 않으면 전부 500).
    error_text = " ".join(str(e) for e in payload.get("errors") or []).lower()
    if "no converter available" in error_text or "unsupported" in error_text:
        return 400, payload
    if "outside allowed roots" in error_text or "path outside" in error_text or "not allowed" in error_text:
        return 400, payload
    if "does not exist" in error_text or "no such file" in error_text or "not found" in error_text:
        return 404, payload

    message = str(payload.get("message") or "").lower()
    if "401" in message or "unauthorized" in message or "token expired" in message:
        return 401, payload
    if "403" in message or "forbidden" in message or "permission" in message:
        return 403, payload
    return 500, payload


@app.post("/mcp/v1/tools/call")
async def call_tool(request: Request) -> JSONResponse:
    tool_name = None
    try:
        data = await request.json()
        tool_name = data.get("name")
        arguments = data.get("arguments", {}) or {}

        if not tool_name:
            return JSONResponse(
                status_code=400, content={"error": {"message": "Tool name is required"}}
            )

        logger.info("Tool call: %s", tool_name)

        # ToolRuntime 이 기본값 주입/검증/동기·비동기 호출/오류 정규화를 모두 처리한다.
        blocks = await runtime.call(tool_name, arguments)
        return JSONResponse(content={"result": {"content": blocks}})

    except ToolExecutionError as exc:
        status, payload = _status_for(exc)
        logger.warning("Tool %s failed (%s): %s", tool_name, status, exc)
        return JSONResponse(status_code=status, content={"error": payload})
    except Exception as exc:  # noqa: BLE001 - 마지막 방어선
        logger.error("Unexpected error executing tool %s: %s", tool_name, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
        )


def run(host: str = None, port: int = DEFAULT_REST_PORT) -> None:
    import uvicorn

    bind_host = resolve_bind_host(host, server_name=SERVER_NAME)
    logger.info("Starting File Handler MCP REST server on %s:%s", bind_host, port)
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


if __name__ == "__main__":
    # controller(MCPServerManager)는 프로필 포트를 MCP_SERVER_PORT 로 전달한다.
    # 예전 MCP_REST_PORT 도 하위 호환으로 계속 받되, MCP_SERVER_PORT 를 우선한다.
    _port = os.environ.get("MCP_SERVER_PORT") or os.environ.get("MCP_REST_PORT") or DEFAULT_REST_PORT
    run(port=int(_port))
