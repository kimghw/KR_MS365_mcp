"""
FileHandler MCP STDIO 서버 (JSON-RPC over stdin/stdout)

보안 주의:
    - 이 서버에는 **호출자 인증이 없다**(stdio 는 부모 프로세스를 그대로 신뢰한다).
      HTTP transport 의 기본 바인드는 loopback 전용이다.
    - 도구가 여는 모든 파일/디렉터리는 `mcp_common.paths` 허용 루트로 제한된다
      (기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장).

도구 호출은 `ToolRuntime` 을 경유한다. `FileManager` 메서드는 동기 함수이고
`ToolRuntime` 이 `maybe_await` 로 처리하므로, 예전처럼 동기 반환값을 `await` 해서
`object dict can't be used in 'await' expression` 이 나는 일은 없다.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

for _path in (grandparent_dir, parent_dir, current_dir):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# stdout 은 JSON-RPC 전용이므로 로그는 stderr 로만 내보낸다.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

from mcp_common.errors import ToolExecutionError

try:
    from .handlers import (
        MCP_TOOLS,
        SERVER_NAME,
        SERVER_VERSION,
        build_lifecycle,
        build_runtime,
    )
except ImportError:  # 스크립트 직접 실행
    from handlers import (  # type: ignore[no-redef]
        MCP_TOOLS,
        SERVER_NAME,
        SERVER_VERSION,
        build_lifecycle,
        build_runtime,
    )

PROTOCOL_VERSION = "2024-11-05"

runtime = build_runtime()
lifecycle = build_lifecycle()


class StdioMCPServer:
    """MCP STDIO 프로토콜 서버 (줄 단위 JSON-RPC)."""

    def __init__(self) -> None:
        self.running = False
        logger.info("FileHandler MCP STDIO Server initialized")

    async def read_message(self) -> Optional[Dict[str, Any]]:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                return None
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON received: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None

    def write_message(self, message: Dict[str, Any]) -> None:
        try:
            sys.stdout.write(json.dumps(message, ensure_ascii=False, default=str) + '\n')
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"Error writing message: {e}")

    def send_error(self, request_id: Any, code: int, message: str, data: Any = None) -> None:
        payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        if data is not None:
            payload["error"]["data"] = data
        self.write_message(payload)

    def send_result(self, request_id: Any, result: Any) -> None:
        self.write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        client_info = params.get("clientInfo", {})
        logger.info(f"Client connected: {client_info.get('name', 'unknown')}")
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    async def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"tools": MCP_TOOLS}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """도구 실행. 실패는 isError=True 로 표현한다(성공처럼 보이지 않게)."""
        tool_name = params.get("name")
        if not tool_name:
            raise ValueError("Tool name is required")

        try:
            blocks = await runtime.call(tool_name, params.get("arguments") or {})
        except ToolExecutionError as exc:
            logger.warning(f"Tool {tool_name} failed: {exc}")
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}

        return {"content": blocks}

    async def handle_request(self, request: Dict[str, Any]) -> None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {}) or {}

        if not method:
            self.send_error(request_id, -32600, "Invalid Request: missing method")
            return

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            elif method == "shutdown":
                logger.info("Shutdown requested")
                self.running = False
                result = {}
            elif method == "ping":
                result = {"pong": True}
            else:
                self.send_error(request_id, -32601, f"Method not found: {method}")
                return

            self.send_result(request_id, result)

        except ValueError as e:
            self.send_error(request_id, -32602, f"Invalid params: {e}")
        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)
            self.send_error(request_id, -32603, f"Internal error: {e}")

    async def handle_notification(self, notification: Dict[str, Any]) -> None:
        logger.info(f"Received notification: {notification.get('method')}")

    async def run(self) -> None:
        self.running = True

        await lifecycle.startup()
        if lifecycle.errors:
            logger.error("초기화 실패 (도구 호출이 실패할 수 있음): %s", lifecycle.errors)

        logger.info("FileHandler MCP STDIO Server started (tools=%d)", len(runtime.tools))

        try:
            while self.running:
                message = await self.read_message()
                if message is None:
                    logger.info("Input stream closed, shutting down")
                    break
                if "id" in message:
                    await self.handle_request(message)
                else:
                    await self.handle_notification(message)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)
        finally:
            await lifecycle.shutdown()
            logger.info("FileHandler MCP STDIO Server stopped")


async def handle_stdio() -> None:
    """Handle MCP protocol via stdin/stdout"""
    await StdioMCPServer().run()


if __name__ == "__main__":
    asyncio.run(handle_stdio())
