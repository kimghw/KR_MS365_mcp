"""Streamable HTTP MCP Server for mcp_time (port 5007). 인증 불필요.

도구 정의·핸들러·`Server` 구성은 `handlers.py` 한 벌을 쓰고, ASGI 배선은
`mcp_common.http_transport` 를 쓴다. 이 파일에는 **HTTP 고유의 것만** 남는다
(spec/spec_MCP트랜스포트.md ②-3-1, ②-4).
"""

import os
import sys

# mcp_common 을 import 하려면 프로젝트 루트가 먼저 sys.path 에 있어야 한다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_common.bootstrap import bootstrap_http

BOOT = bootstrap_http(__file__, package_name="mcp_time")

# ↓ 서비스 모듈을 끌어오는 import 는 반드시 bootstrap 뒤에
from mcp_common.http_transport import build_starlette_app, run_http

from mcp_time.mcp_server.handlers import (
    DEFAULT_PORT,
    SERVER_NAME,
    SERVER_VERSION,
    build_mcp_server,
    lifecycle,
    runtime,
)

# 모듈 수준 ASGI 앱 (`uvicorn server_stream:app` 도 동작한다)
app = build_starlette_app(
    SERVER_NAME,
    build_mcp_server(),
    runtime,
    lifecycle,
    version=SERVER_VERSION,
)


def run(host=None, port: int = DEFAULT_PORT) -> None:
    run_http(app, SERVER_NAME, port, host)


if __name__ == "__main__":
    run(port=int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT)))
