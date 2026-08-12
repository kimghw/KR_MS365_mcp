"""MCP server module.

트랜스포트는 stdio(`server_stdio.py`)와 Streamable HTTP(`server_stream.py`) 2종이다
(spec/spec_MCP트랜스포트.md ②-1). 서버 모듈은 임포트 시점에 프로세스 부트스트랩을
수행하므로 패키지 임포트만으로 끌어오지 않는다.
"""

from .tool_definitions import MCP_TOOLS

__all__ = ['MCP_TOOLS']