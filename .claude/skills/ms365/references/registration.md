# MCP 등록 상세 — Claude Code (HTTP) / Claude Desktop (STDIO)

SKILL.md 의 3-A-5 단계가 호출하는 두 등록 경로의 배경 / 폴백 / 디버깅 가이드.

## 두 클라이언트의 차이

| 항목 | Claude Code | Claude Desktop |
|---|---|---|
| Config 파일 | `~/.claude.json` (= `C:\Users\<u>\.claude.json`) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Transport | HTTP streamable (`server_stream.py`) | STDIO (`server_stdio.py`) |
| 서버 spawn | 외부에서 띄워야 함 (HTTP는 클라이언트가 연결만) | Desktop 이 자동 spawn |
| 등록 도구 | `claude mcp add` CLI 또는 직접 JSON 편집 | JSON 직접 편집만 |
| 활성 범위 (스코프) | `-s user` 전역 / `-s local` 프로젝트 / `-s project` `.mcp.json` | 전역 한 파일 |

**두 config 는 공유되지 않음** — 양쪽 다 쓰려면 양쪽 다 등록.

## Claude Code (HTTP) 등록

### 권장 — `claude` CLI 사용

스코프는 항상 `-s user` (글로벌). 모든 Claude Code 세션에서 활성화.

```bash
# {name} ∈ outlook/calendar/teams/onedrive/onenote/todo
# {port} ∈ 5001~5006
claude mcp remove {name} -s user 2>/dev/null || true
claude mcp remove {name} -s local 2>/dev/null || true
claude mcp add -s user --transport http {name} http://localhost:{port}/mcp
claude mcp get {name} 2>&1 | head -10
```

### CLI 폴백 — 스크립트 사용

`claude` 가 PATH 에 없으면 `scripts/register_claude_code.py` 를 직접 호출:

```bash
"$VENV_PY" "$SCRIPTS/register_claude_code.py" --servers outlook,teams
# 또는 6개 전부
"$VENV_PY" "$SCRIPTS/register_claude_code.py" --servers all
```

스크립트는 read-modify-write 로 `~/.claude.json` 의 다른 엔트리를 모두 보존하며, 프로젝트 스코프에 남은 동일 이름 entry 는 제거하여 충돌을 막는다.

### 엔트리 스키마

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

### 디버깅

```bash
claude mcp list                       # 등록된 서버 목록
claude mcp get outlook                # outlook 상세
claude mcp remove outlook -s user     # 제거
```

VSCode 안의 Claude Code 확장도 같은 `~/.claude.json` 을 공유.

## Claude Desktop (STDIO) 등록

### 스크립트 호출

```bash
"$VENV_PY" "$SCRIPTS/register_claude_desktop.py" --servers outlook,teams
# 또는 전체
"$VENV_PY" "$SCRIPTS/register_claude_desktop.py" --servers all
```

스크립트는 utf-8-sig BOM 을 허용하고 read-modify-write 로 다른 엔트리(`gmail`, `google_calendar` 등)를 보존한다.

### 엔트리 스키마 (한 서버 예)

```json
{
  "mcpServers": {
    "outlook": {
      "command": "c:\\Users\\USER\\KR_MS365_mcp\\venv\\Scripts\\python.exe",
      "args":    ["c:\\Users\\USER\\KR_MS365_mcp\\mcp_outlook\\mcp_server\\server_stdio.py"],
      "env": {
        "PYTHONPATH":        "c:\\Users\\USER\\KR_MS365_mcp",
        "PYTHONUTF8":        "1",
        "PYTHONIOENCODING":  "utf-8"
      }
    }
  }
}
```

다른 5개 서버(`calendar/teams/onedrive/onenote/todo`)는 `mcp_{name}\mcp_server\server_stdio.py` 만 다르고 구조 동일.

### 주의

- Claude Desktop 은 HTTP/SSE 를 직접 지원하지 않음 — mcp-proxy 브리지가 없으면 STDIO 만.
- Config 수정 후 **Claude Desktop 재시작 필수**.
- `env.PYTHONIOENCODING=utf-8` 은 Korean Windows 에서 한글 출력 깨짐 방지.
- 기존 다른 `mcpServers` 엔트리와 `preferences` 등 최상위 키는 read-modify-write 로 자동 보존됨 — 절대 통째 덮어쓰기 금지.

## 흔한 함정

| 증상 | 원인 | 해결 |
|---|---|---|
| Claude Code 에서 서버가 안 보임 | 새 세션이 아님 — 등록은 새 세션에서만 활성화 | Claude Code 재시작 |
| Claude Desktop 에서 서버가 안 보임 | Desktop 재시작 안 함 | Desktop 종료 후 재실행 |
| `claude mcp list` 에 두 번 나옴 | user + local 양쪽 등록됨 | `claude mcp remove {name} -s local` |
| Desktop STDIO 서버 즉시 종료 | `PYTHONPATH` 누락으로 `session` import 실패 | env 의 `PYTHONPATH` 가 프로젝트 루트인지 확인 |
| HTTP 서버 등록은 됐는데 연결 실패 | `server_stream.py` 가 안 떠 있음 | `/ms365 start` 또는 `/port_manager` 로 기동 |
