# 프로젝트 서버·포트·실행명령 할당

본 표는 `/port_manager` 가 읽는 단일 출처(SSOT)다. 한 행 = 한 서버 정의.

| 프로젝트 | 포트 | 서비스 | 시작명령 | 작업디렉토리 |
|---------|------|-------|---------|------------|
| TaskPilot | 3000 | Web UI | npm run dev | web |
| KR_MS365_mcp | 5000 | OAuth Callback | python callback_server.py | — |
| KR_MS365_mcp | 5001 | Outlook MCP | venv/Scripts/python.exe mcp_outlook/mcp_server/server_stream.py | — |
| KR_MS365_mcp | 5002 | Calendar MCP | venv/Scripts/python.exe mcp_calendar/mcp_server/server_stream.py | — |
| KR_MS365_mcp | 5003 | Teams MCP | venv/Scripts/python.exe mcp_teams/mcp_server/server_stream.py | — |
| KR_MS365_mcp | 5004 | OneDrive MCP | venv/Scripts/python.exe mcp_onedrive/mcp_server/server_stream.py | — |
| KR_MS365_mcp | 5005 | OneNote MCP | venv/Scripts/python.exe mcp_onenote/mcp_server/server_stream.py | — |
| KR_MS365_mcp | 5006 | Todo MCP | venv/Scripts/python.exe mcp_todo/mcp_server/server_stream.py | — |
| KR_MS365_mcp | 5007 | Time MCP | venv/Scripts/python.exe mcp_time/mcp_server/server_stream.py | — |
| KR_MS365_mcp | 5008 | FileHandler MCP | venv/Scripts/python.exe mcp_file_handler/mcp_server/server_stream.py | — |
