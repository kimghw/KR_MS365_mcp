"""STDIO MCP Server for mcp_file_handler. 인증 불필요(로컬 파일 처리).

도구 정의·핸들러·`Server` 구성은 `handlers.py` 한 벌을 쓰고, 구동은 공식 SDK 기반
`mcp_common.stdio_transport` 를 쓴다. 이 파일에는 **stdio 고유의 것만** 남는다
(spec/spec_MCP트랜스포트.md ②-3-1, ②-4).

보안 주의:
    - 호출자 인증이 없다(stdio 는 부모 프로세스를 그대로 신뢰한다).
    - 도구가 여는 모든 파일/디렉터리는 `mcp_common.paths` 허용 루트로 제한된다
      (기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장).

이전 구현은 자체 JSON-RPC 루프(`StdioMCPServer`)를 갖고 있었고 **stdout 리다이렉트가
없어서** 임포트된 모듈의 `print()` 가 JSON-RPC 스트림을 오염시킬 수 있었다.
`bootstrap_stdio()` 가 `sys.stdout` 을 stderr 로 돌리고 원본 stdout 만 프로토콜 채널로
쓰므로 그 취약점이 구조적으로 사라진다.
"""

import os
import sys

# mcp_common 을 import 하려면 프로젝트 루트가 먼저 sys.path 에 있어야 한다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_common.bootstrap import bootstrap_stdio

# stdout 보호가 최우선이다 — 서비스 모듈 import 보다 먼저 호출해야 한다.
BOOT = bootstrap_stdio(__file__, package_name="mcp_file_handler")

from mcp_common.stdio_transport import run_stdio

from mcp_file_handler.mcp_server.handlers import build_mcp_server, lifecycle

if __name__ == "__main__":
    run_stdio(build_mcp_server(), lifecycle, BOOT)
