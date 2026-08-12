"""STDIO MCP Server for mcp_teams. Graph API 인증 필요.

도구 정의·핸들러·`Server` 구성은 `handlers.py` 한 벌을 쓰고, 구동은 공식 SDK 기반
`mcp_common.stdio_transport` 를 쓴다. 이 파일에는 **stdio 고유의 것만** 남는다
(spec/spec_MCP트랜스포트.md ②-3-1, ②-4).
"""

import os
import sys

# mcp_common 을 import 하려면 프로젝트 루트가 먼저 sys.path 에 있어야 한다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_common.bootstrap import bootstrap_stdio

# stdout 보호가 최우선이다 — 서비스 모듈 import 보다 먼저 호출해야 한다.
BOOT = bootstrap_stdio(__file__, package_name="mcp_teams")

from mcp_common.stdio_transport import run_stdio

from mcp_teams.mcp_server.handlers import build_mcp_server, lifecycle

if __name__ == "__main__":
    run_stdio(build_mcp_server(), lifecycle, BOOT)
