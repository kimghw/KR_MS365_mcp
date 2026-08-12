"""
MCP Server for Outlook Graph Mail API
Provides Model Context Protocol interface for email operations

트랜스포트는 stdio(`server_stdio.py`)와 Streamable HTTP(`server_stream.py`) 2종이다
(spec/spec_MCP트랜스포트.md ②-1). 두 서버 모듈은 임포트 시점에 .env 로드·경로 조작 등
프로세스 부트스트랩을 수행하므로 패키지 임포트만으로 끌어오지 않는다 — 실행할 트랜스포트를
직접 임포트하라.
"""

__all__: list[str] = []
