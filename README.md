# KR_MS365_mcp

MS Graph API 기반 MS365 MCP 서버 모음. Outlook / Calendar / OneNote / OneDrive / Teams / Todo / Time 등 각 서비스를 독립 MCP 서버(HTTP Stream)로 제공한다.

## 모듈 구성

| 모듈 | 설명 |
|------|------|
| `mcp_outlook/` | 메일 조회·발송, 첨부파일 처리 (GraphMailClient Facade) |
| `mcp_calendar/` | 일정 조회·생성 (GraphCalendarClient Facade) |
| `mcp_onenote/` | OneNote 페이지 읽기/쓰기/삭제 + 로컬 DB 동기화 (`database/onenote.db`) |
| `mcp_onedrive/` | OneDrive 파일 관리 (GraphOneDriveClient Facade) |
| `mcp_teams/` | Teams 메시지·채널 (GraphTeamsClient Facade + 로컬 DB) |
| `mcp_todo/` | Microsoft To Do 작업 관리 (GraphTodoClient Facade) |
| `mcp_time/` | 현재 시간을 다양한 형식으로 반환 (Graph API 미사용) |
| `mcp_file_handler/` | 파일 변환·관리 (PDF/DOCX/HWP/Excel/이미지, OCR, OneDrive 연동) |
| `mcp_editor/` | MCP 툴 정의 편집용 웹 에디터 (Flask, 선택 설치) |
| `core/` | 모듈 간 공용 Protocol 정의 (`protocols.py`) |
| `session/` | Azure AD OAuth 인증 (AuthManager, 토큰 SQLite 저장) |
| `cloudflare/` | Cloudflare 터널 리셋 스크립트 |
| `main.py` | 인증 플로우 단독 실행 진입점 |
| `callback_server.py` | OAuth 콜백 처리 웹서버 (aiohttp) |

## 포트 할당

SSOT: `.claude/skills/port_manager/port_list.md`

| 포트 | 서비스 |
|------|--------|
| 5000 | OAuth Callback (`callback_server.py`) |
| 5001 | Outlook MCP |
| 5002 | Calendar MCP |
| 5003 | Teams MCP |
| 5004 | OneDrive MCP |
| 5005 | OneNote MCP |
| 5006 | Todo MCP |
| 5007 | Time MCP |
| 5008 | FileHandler MCP |

각 MCP 서버 실행: `venv/Scripts/python.exe <모듈>/mcp_server/server_stream.py`

## 아키텍처

- **계층 구조**: `*_service.py` (Facade, MCP 툴 진입점) → `graph_*_client.py` (Graph API 호출) → query/하위 모듈
- **토큰 주입 패턴**: `core/protocols.py`의 `TokenProviderProtocol`로 인증을 추상화.
  모든 Graph 클라이언트는 `token_provider` 파라미터로 주입받으며, 미지정 시 기본값으로 `session.AuthManager`를 사용한다. 테스트에서는 Mock 주입 가능.
- **인증(session/)**: Azure AD OAuth 2.0. `AuthManager`(다중 사용자 관리) + `AuthService`(OAuth 플로우) + `AuthDatabase`(SQLite 토큰 저장) + `callback_server.py`(브라우저 인증 콜백).

## 설치

요구사항: Python >= 3.12

```bash
pip install -r requirements.txt        # 핵심 의존성
pip install -e ".[editor]"             # 선택: mcp_editor 웹 UI
pip install -e ".[converters]"         # 선택: 첨부파일 변환기
pip install -e ".[dev]"                # 선택: pytest, ruff, black
```

`.env` 설정 (`.env.example` 참조):

```env
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
AZURE_TENANT_ID=...
AZURE_REDIRECT_URI=http://localhost:5000/callback
# 스코프는 공백 구분, offline_access 없으면 refresh_token 미발급
AZURE_SCOPES=https://graph.microsoft.com/.default offline_access openid
```

## 인증 플로우

1. 첫 MCP 툴 호출 시 자동으로 브라우저 인증이 트리거된다 (콜백은 5000 포트).
2. 발급된 토큰은 `database/auth.db`(SQLite)에 저장된다.
3. Refresh token 유효기간은 90일이며, 토큰 갱신·재인증 시 만료 시각이 +90일로 리셋된다.
4. `python main.py`로 인증 플로우만 단독 실행할 수도 있다.

## 개발

```bash
# 테스트
pytest mcp_teams/tests mcp_onedrive/tests mcp_file_handler/tests

# 린트/포맷 (설정: pyproject.toml)
ruff check .
black .
```
