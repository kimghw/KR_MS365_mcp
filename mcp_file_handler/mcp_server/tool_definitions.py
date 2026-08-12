"""도구 정의 관문 — 계약의 원본은 `spec/param_spec/file_handler.yaml` 이다.

2026-08-12 코드 생성 폐지 이전에는 이 모듈이 에디터 쪽 AST 추출 산출물
(`tool_definition_templates.yaml`)을 읽었다. 이제는 `mcp_common.param_spec` 이
param_spec 에서 `inputSchema` 를 파생시키고, 이 모듈은 그 결과를 재수출만 한다.
에디터 패키지에 대한 의존은 없다.

`handlers.py` 가 아니라 여기서 spec 을 로드하는 이유: `mcp_server/__init__.py` 가
`MCP_TOOLS` 를 재수출하는데, `handlers` 를 거치면 패키지 import 만으로 `FileManager`
(메타데이터 DB 생성 등 부수효과)가 만들어진다. 이 관문은 param_spec 만 읽어 가볍다.
"""

from typing import Any, Dict, List

from mcp_common.param_spec import load_param_spec

#: 도구 계약의 단일 원본. `handlers.py` 가 호출 인자 생성에도 이 객체를 쓴다.
SPEC = load_param_spec("file_handler")

MCP_TOOLS: List[Dict[str, Any]] = SPEC.mcp_tools()

__all__ = ["SPEC", "MCP_TOOLS"]
