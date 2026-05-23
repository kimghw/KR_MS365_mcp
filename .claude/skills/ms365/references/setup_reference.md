# setup-ms365 참고 문서 (Windows + Claude Code HTTP + Claude Desktop STDIO)

이 문서는 `SKILL.md`가 실행 중 참조하는 환경 요구사항, 경로 매핑, OAuth Flow 요약입니다.

## 지원 서버 (6개)

| 서버 | HTTP 포트 (env 변수) | STDIO 스크립트 | Stream 스크립트 |
|---|---|---|---|
| `outlook`  | 5001 (`MCP_OUTLOOK_PORT`)  | `mcp_outlook/mcp_server/server_stdio.py`  | `mcp_outlook/mcp_server/server_stream.py`  |
| `calendar` | 5002 (`MCP_CALENDAR_PORT`) | `mcp_calendar/mcp_server/server_stdio.py` | `mcp_calendar/mcp_server/server_stream.py` |
| `teams`    | 5003 (`MCP_TEAMS_PORT`)    | `mcp_teams/mcp_server/server_stdio.py`    | `mcp_teams/mcp_server/server_stream.py`    |
| `onedrive` | 5004 (`MCP_ONEDRIVE_PORT`) | `mcp_onedrive/mcp_server/server_stdio.py` | `mcp_onedrive/mcp_server/server_stream.py` |
| `onenote`  | 5005 (`MCP_ONENOTE_PORT`)  | `mcp_onenote/mcp_server/server_stdio.py`  | `mcp_onenote/mcp_server/server_stream.py`  |
| `todo`     | 5006 (`MCP_TODO_PORT`)     | `mcp_todo/mcp_server/server_stdio.py`     | `mcp_todo/mcp_server/server_stream.py`     |

**공유 자원:**
- `.env` — 6개 서버가 같은 Azure 자격증명 사용
- `session/auth_manager.py` + `database/auth.db` — 1회 인증 → 6개 서버 공통
- 콜백 포트 (`AZURE_REDIRECT_URI`에서 파싱) — 한 번에 한 인증만 진행됨

## 환경 요구사항

| 항목 | 요구 |
|---|---|
| OS | Windows 10/11 (WSL Bash 도구로 Windows 바이너리 호출) |
| Python | Windows 시스템 Python 3.10+ (`C:\Python3*\python.exe`) |
| venv 위치 | `c:\Users\USER\KR_MS365_mcp\venv\` |
| Claude Code CLI | `claude` (PATH에 있어야 함) |
| 한컴오피스 (선택) | `pyhwpx`로 HWP 변환 시에만 필요 — 기본 스킬에서는 비활성 |

## 절대 경로 매핑

| 항목 | Git Bash / WSL 경로 | Windows 경로 |
|---|---|---|
| 프로젝트 루트 | `/c/...` 또는 `/mnt/c/Users/USER/KR_MS365_mcp` | `c:\Users\USER\KR_MS365_mcp` |
| venv Python | `<root>/venv/Scripts/python.exe` | `c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe` |
| venv pip | `<root>/venv/Scripts/pip.exe` | `c:\Users\USER\KR_MS365_mcp\venv\Scripts\pip.exe` |
| `.env` | `<root>/.env` | `c:\Users\USER\KR_MS365_mcp\.env` |
| 토큰 DB | `<root>/database/auth.db` | `c:\Users\USER\KR_MS365_mcp\database\auth.db` |
| 인증 모듈 | `<root>/session/auth_manager.py` | `c:\Users\USER\KR_MS365_mcp\session\auth_manager.py` |

서버별 진입점: 위 "지원 서버" 표 참조.

## 핵심 의존성 (requirements.txt)

| 패키지 | 용도 |
|---|---|
| aiohttp | Graph API HTTP 호출 |
| python-dotenv | `.env` 로드 (utf-8-sig BOM 처리) |
| cryptography | 토큰 암호화 |
| psutil | 프로세스/포트 점검 |
| pydantic | 데이터 모델 |
| PyYAML | 도구 정의 로드 |
| fastapi, uvicorn | REST/Stream 웹서버 |
| mcp-proxy | (옵션) Claude Desktop 원격 연결 |
| pdfplumber, python-docx, olefile, openpyxl, python-pptx | 메일 첨부 변환 |

**비활성 (주석 처리):**
- `pyhwpx` — Windows 전용, 한컴오피스 ActiveX 의존. 필요 시 별도 `pip install pyhwpx`

## Azure AD 환경변수

`.env`에 들어가는 값:

| 변수 | 값 | 설명 |
|---|---|---|
| `AZURE_CLIENT_ID` | (사용자 입력) | Azure AD App Application ID |
| `AZURE_CLIENT_SECRET` | (사용자 입력) | Client Secret 값 (Secret ID 아님) |
| `AZURE_TENANT_ID` | (사용자 입력) | Tenant UUID 또는 `common`/`organizations`/`consumers` |
| `AZURE_REDIRECT_URI` | `http://localhost:5000/callback` | **고정** — Azure Portal Redirect URI와 일치 필수 |
| `AZURE_AUTHORITY` | `https://login.microsoftonline.com` | **고정** |
| `AZURE_SCOPES` | `offline_access openid` | **고정** — 추가 권한(Mail.Read 등)이 필요하면 수동 편집 |

## OAuth Flow 요약

스킬은 **Authorization Code Flow** 사용:

1. 사용자를 브라우저로 `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize`로 리다이렉트
2. MS 계정 로그인 + 권한 동의
3. Azure가 `http://localhost:5000/callback`으로 authorization code 전달
4. 프로젝트의 `callback_server.py`가 코드를 받아 `/oauth2/v2.0/token`에서 access_token + refresh_token으로 교환
5. 토큰이 `database/auth.db`(`azure_user_info`, `azure_token_info` 테이블)에 저장

**재인증 (refresh):** `AuthManager.refresh_token()`이 저장된 refresh_token으로 access_token만 갱신. refresh_token 만료(통상 90일) 시 실패 → 브라우저 OAuth 재진행 필요.

## 등록 타겟별 Config 위치 / 스키마

### Claude Code (HTTP)

`claude mcp add` 저장 위치는 **스코프**(`-s`)에 따라 다름:

| 스코프 | `claude mcp add` 옵션 | 저장 위치 | 활성 범위 |
|---|---|---|---|
| **user (글로벌)** | `-s user` | `~/.claude.json` 최상위 `mcpServers` | 모든 디렉토리에서 활성 |
| local (프로젝트, 기본) | (생략) | `~/.claude.json` 안의 `projects[<현재경로>].mcpServers` | 그 프로젝트를 열었을 때만 |
| project | `-s project` | 프로젝트 루트의 `.mcp.json` | 해당 저장소에 체크인됨 |

**setup-ms365 스킬은 항상 `-s user` 사용** — 6개 서버는 디렉토리 무관하게 항상 보여야 하므로.

엔트리 스키마 (6개 모두 같은 구조, port만 다름):

```json
{
  "mcpServers": {
    "outlook":  { "type": "http", "url": "http://localhost:5001/mcp" },
    "calendar": { "type": "http", "url": "http://localhost:5002/mcp" },
    "teams":    { "type": "http", "url": "http://localhost:5003/mcp" },
    "onedrive": { "type": "http", "url": "http://localhost:5004/mcp" },
    "onenote":  { "type": "http", "url": "http://localhost:5005/mcp" },
    "todo":     { "type": "http", "url": "http://localhost:5006/mcp" }
  }
}
```

확인 명령 (CLI 있으면):

```bash
claude mcp list             # 등록된 서버 목록
claude mcp get outlook      # outlook 서버 상세
claude mcp remove outlook   # 제거
```

VSCode 안의 Claude Code 확장도 같은 `~/.claude.json`을 공유합니다.

### Claude Desktop (STDIO)

Config 위치: `%APPDATA%\Claude\claude_desktop_config.json`
(= `C:\Users\<user>\AppData\Roaming\Claude\claude_desktop_config.json`)

엔트리 스키마 (6개 동시 등록 예 — 다른 5개는 outlook과 동일한 구조, `mcp_{name}` 부분만 다름):

```json
{
  "mcpServers": {
    "outlook": {
      "command": "c:\\Users\\USER\\KR_MS365_mcp\\venv\\Scripts\\python.exe",
      "args": ["c:\\Users\\USER\\KR_MS365_mcp\\mcp_outlook\\mcp_server\\server_stdio.py"],
      "env": {
        "PYTHONPATH": "c:\\Users\\USER\\KR_MS365_mcp",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    },
    "calendar": { "command": "...python.exe", "args": ["...mcp_calendar\\mcp_server\\server_stdio.py"], "env": {...} },
    "teams":    { "command": "...python.exe", "args": ["...mcp_teams\\mcp_server\\server_stdio.py"],    "env": {...} },
    "onedrive": { "command": "...python.exe", "args": ["...mcp_onedrive\\mcp_server\\server_stdio.py"], "env": {...} },
    "onenote":  { "command": "...python.exe", "args": ["...mcp_onenote\\mcp_server\\server_stdio.py"],  "env": {...} },
    "todo":     { "command": "...python.exe", "args": ["...mcp_todo\\mcp_server\\server_stdio.py"],     "env": {...} }
  }
}
```

**중요:**
- Claude Desktop은 HTTP/SSE transport를 직접 지원하지 않음 (mcp-proxy 브리지 필요)
- Config 수정 후 **Claude Desktop 재시작** 필요
- `env`의 `PYTHONIOENCODING=utf-8`은 Korean Windows에서 한글 출력 깨짐 방지
- 기존 `mcpServers`의 다른 항목과 `preferences` 등 최상위 키는 절대 삭제하지 말 것 (read-modify-write)

### 두 config의 관계

| 항목 | Claude Code | Claude Desktop |
|---|---|---|
| 파일 | `~/.claude.json` | `%APPDATA%\Claude\claude_desktop_config.json` |
| **파일 공유 여부** | ❌ 별개 파일 | ❌ 별개 파일 |
| Transport | HTTP / SSE / STDIO 다 됨 | STDIO만 (HTTP는 mcp-proxy 필요) |
| 서버 spawn | 외부에서 띄움 (HTTP) | Desktop이 자동 spawn (STDIO) |
| CLI 도구 | `claude mcp` | 없음 (JSON 직접 편집) |

## 포트 사용

| 포트 | 용도 | 변경 방법 |
|---|---|---|
| 5000 | OAuth 콜백 (Azure Portal redirect URI 기준) | Azure Portal Redirect URI + `.env`의 `AZURE_REDIRECT_URI` 함께 변경 |
| 5001 | outlook MCP HTTP | 환경변수 `MCP_OUTLOOK_PORT` |
| 5002 | calendar MCP HTTP | 환경변수 `MCP_CALENDAR_PORT` |
| 5003 | teams MCP HTTP | 환경변수 `MCP_TEAMS_PORT` |
| 5004 | onedrive MCP HTTP | 환경변수 `MCP_ONEDRIVE_PORT` |
| 5005 | onenote MCP HTTP | 환경변수 `MCP_ONENOTE_PORT` |
| 5006 | todo MCP HTTP | 환경변수 `MCP_TODO_PORT` |

**Windows 포트 5000 Hyper-V 충돌:**
Windows 10/11의 winnat/Hyper-V 동적 예약 범위에 5000이 포함되는 경우가 있어 콜백 서버 바인딩이 실패할 수 있습니다. 회피 방법:
1. `netsh int ipv4 show excludedportrange protocol=tcp`로 예약 범위 확인
2. Azure Portal에서 앱 Redirect URI를 다른 포트(예: 53682)로 변경
3. `.env`의 `AZURE_REDIRECT_URI`도 동일하게 변경

## 보안 주의

- `.env`와 `.env.bak.*`는 `.gitignore` 등재 확인
- `.env` 내용을 채팅에 출력 금지 (Client Secret 평문 노출)
- 입력받은 자격증명을 memory 시스템에 저장 금지
- `auth.db`는 평문 SQLite — 디스크 권한으로만 보호되므로 공유 머신에 두지 말 것
