"""
Outlook MCP 서버 패키지.

`__init__.py` 가 없던 시절에는 PEP 420 namespace 패키지로 처리돼서,
`mcp_outlook/tests/` (이쪽은 `__init__.py` 보유)가 최상위 `tests` 패키지로 import 됐다.
루트에 `tests/` 를 만들면 곧바로 모듈명이 충돌한다. 정규 패키지로 만들어 그 충돌을 막는다.
"""
