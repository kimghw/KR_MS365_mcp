---
name: mcp_ms365
description: setup_ms365로 등록된 Claude Code HTTP MCP 서버(outlook, calendar 등)를 백그라운드 실행하는 스킬. ~/.claude.json에서 type=http 서버를 자동 디스커버리하고, .claude 설정/포트/스크립트 sanity 체크 후 AskUserQuestion으로 시작할 서버를 고르게 합니다. 시작 후 /health probe로 실제 응답 확인. Claude Desktop STDIO는 Desktop이 자동 spawn하므로 이 스킬 대상 아님.
---

# mcp_ms365 — HTTP MCP 서버 실행 스킬

이 스킬은 **`/mcp_ms365`**로 호출합니다.

`setup_ms365`가 등록(레지스트레이션)만 하고 HTTP transport 서버 프로세스는 띄우지 않으므로, 이 스킬이 백그라운드 실행을 담당합니다.

## 책임 범위 (start 전용)

| 항목 | 이 스킬 | setup_ms365 |
|---|---|---|
| venv / 의존성 / .env | X | O |
| Claude Code / Desktop 등록 | X (등록 점검만) | O |
| HTTP 서버 프로세스 시작 | **O** | X (등록까지만) |
| 서버 종료 / 재시작 | X — OS 도구 사용 (`taskkill /PID ...`) | X |

문제 발생 시 (venv 없음, 스크립트 없음, 등록 깨짐 등) → **`/setup_ms365`**로 재셋업 권장.

## 대상 서버

- **자동 디스커버리** — `~/.claude.json`의 top-level + projects.*.mcpServers에서 `type=http` (또는 url이 `http*://...`)인 모든 entry
- **STDIO 서버는 제외** — Claude Desktop이 자동 spawn하므로 이 스킬이 띄울 필요 없음

## 스킬 구성 파일

```
mcp_ms365/
├── SKILL.md
└── scripts/
    └── discover_servers.py   ← .claude.json 파싱 + sanity check + JSON/표 출력
```

## 사전 확인

| 항목 | 경로 |
|---|---|
| 프로젝트 루트 | `c:\Users\USER\KR_MS365_mcp` |
| venv Python | `c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe` |
| ~/.claude.json | `C:\Users\USER\.claude.json` |
| 서버 스크립트 패턴 | `c:\Users\USER\KR_MS365_mcp\mcp_{name}\mcp_server\server_stream.py` |
| 백그라운드 로그 | `/tmp/mcp_{name}.log` (Git Bash) |
| Health endpoint | `<url>` 의 `/mcp`를 `/health`로 치환해 GET |

## 인자

- `/mcp_ms365` (인자 없음) → 디스커버리 + AskUserQuestion으로 시작할 서버 선택
- `/mcp_ms365 --all` → 디스커버리 결과 중 `startable=true`인 모든 서버를 질문 없이 시작
- `/mcp_ms365 --status` → 디스커버리 표만 출력하고 종료

---

## Instructions

### 1단계: 디스커버리 + sanity check

```bash
VENV_PY="c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe"
DISCOVER="c:\Users\USER\KR_MS365_mcp\.claude\skills\mcp_ms365\scripts\discover_servers.py"

# 사용자에게 보여줄 표
"$VENV_PY" "$DISCOVER"

# 의사결정용 JSON 캡처
STATUS_JSON=$("$VENV_PY" "$DISCOVER" --json)
```

JSON 스키마:

```json
{
  "venv_ok": true,
  "claude_json_exists": true,
  "http_server_count": 2,
  "servers": [
    {
      "name": "outlook",
      "scope": "user",
      "url": "http://localhost:8091/mcp",
      "host": "localhost",
      "port": 8091,
      "stream_script": "c:\\...\\server_stream.py",
      "stream_script_exists": true,
      "port_in_use": false,
      "port_pid": null,
      "health": {"ok": false, "status": null, "url": "...", "body": null},
      "startable": true,
      "running": false,
      "issues": []
    }
  ]
}
```

`--status` 인자였다면 표 출력 후 여기서 종료.

**sanity 분기:**

- `venv_ok=false` 또는 `claude_json_exists=false` → "선행 셋업 필요" 안내 + **`/setup_ms365`** 실행 권장 후 중단
- `http_server_count=0` → "등록된 HTTP MCP 서버 없음" + **`/setup_ms365`** 안내 후 중단
- 개별 서버의 `issues`가 비어있지 않으면 → 해당 서버는 선택지에서 제외하고 표에 경고 표시. 모든 서버에 issue가 있으면 중단.

### 2단계: 시작 대상 선택

`--all`이면 `startable=true`인 모든 서버 자동 선택, 4단계로.

그 외에는 `AskUserQuestion`:

- question: `"어떤 서버를 시작할까요? (이미 RUNNING인 서버는 제외)"`
- header: `"MCP 시작"`
- multiSelect: `true`
- options (servers에서 동적으로 구성, **`running=true`인 서버는 제외**):
  - label: `"{name} — STOPPED (port {port})"`, description: `"server_stream.py를 nohup으로 백그라운드 실행 → /health probe"`
  - (`startable=false`이고 `running=false`인 서버는 옵션에 두되 disabled 표시는 못 하니 issues 텍스트를 description에 포함)

모든 서버가 이미 RUNNING이면 옵션이 0개 → "시작할 서버 없음 (모두 실행 중)" 출력 후 종료.

### 3단계: 백그라운드 시작 + health check

선택된 각 서버 `{name}` (port `{port}`, script `{stream_script}`)에 대해 순차 실행:

```bash
# 한 번 더 점유 확인 (race 방지)
if powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue" 2>/dev/null | grep -q LocalPort; then
  echo "[{name}] 포트 {port} 이미 점유 — 시작 건너뜀"
else
  cd /c/Users/USER/KR_MS365_mcp
  nohup ./venv/Scripts/python.exe "mcp_{name}/mcp_server/server_stream.py" > /tmp/mcp_{name}.log 2>&1 &
  echo "[{name}] started, pid=$!"
  disown
fi

# 부팅 시간 대기
sleep 3

# health probe — /mcp 경로를 /health로 치환
HEALTH_URL=$(echo "{url}" | sed 's|/mcp/*$|/health|')
HTTP_CODE=$(curl -sS -o /tmp/mcp_{name}_health.json -w "%{http_code}" "$HEALTH_URL")
if [ "$HTTP_CODE" = "200" ]; then
  echo "[{name}] HEALTHY ✓ ($HEALTH_URL)"
  cat /tmp/mcp_{name}_health.json
else
  echo "[{name}] HEALTH FAIL (http=$HTTP_CODE) — 로그 확인:"
  tail -20 /tmp/mcp_{name}.log
fi
```

> **참고:** Git Bash에서 `/tmp`는 보통 `C:\Users\<user>\AppData\Local\Temp` 또는 `/c/Users/<user>/AppData/Local/Temp`로 매핑됩니다. WSL이면 별도 `/tmp`.

### 4단계: 최종 디스커버리 재호출

```bash
"$VENV_PY" "$DISCOVER"
```

표가 모든 시작된 서버를 RUNNING ✓로 보여주면 성공.

---

## 사용자에게 전달할 최종 메시지 (start 후)

```
✅ 시작 완료
- 시작한 서버: {names}
- 로그 위치: /tmp/mcp_{name}.log (각 서버별)
- 종료 방법: taskkill /F /PID <pid> 또는 OS 작업 관리자
- 등록/설정 변경: /setup_ms365 재실행
```

---

## 주의사항

- **start 전용 스킬** — stop/restart는 OS 도구로. 이유: 잘못된 종료가 다른 사용자의 프로세스 죽일 위험. 디스커버리로 알게 된 pid를 그대로 죽이는 게 안전하지 않을 수 있음.
- **종료/재시작이 필요한 시나리오** → `taskkill /F /PID {pid}` 후 이 스킬 재실행
- **포트 충돌 (`PORT_BUSY (health X)`)** → 다른 프로세스가 같은 포트를 잡고 있음. 무엇인지 확인:
  ```bash
  powershell.exe -NoProfile -Command "Get-Process -Id <pid> | Select-Object Name,Path"
  ```
  → 외부 프로세스면 죽이지 말고 MCP 서버 포트를 `MCP_OUTLOOK_PORT`/`MCP_CALENDAR_PORT` env로 변경 후 `/setup_ms365`로 재등록
- **반복 실행 안전** — 이미 RUNNING인 서버는 자동으로 시작 건너뜀 (idempotent)
- **Claude Desktop STDIO는 이 스킬과 무관** — Desktop이 spawn 관리. 문제 있으면 Desktop 재시작

---

## Examples

**입력:** `/mcp_ms365` (둘 다 STOPPED 상태)

```
1. 디스커버리 표:
   outlook  — STOPPED — start 가능 (port 8091)
   calendar — STOPPED — start 가능 (port 8002)

2. AskUserQuestion → outlook + calendar 둘 다 선택

3. outlook 시작 → pid=12345 → health 200 ✓
   calendar 시작 → pid=12399 → health 200 ✓

4. 최종 표: 둘 다 RUNNING ✓
```

**입력:** `/mcp_ms365 --status`

```
디스커버리 표만 출력하고 종료 (시작 액션 없음)
```

**입력:** `/mcp_ms365 --all` (calendar는 이미 RUNNING)

```
1. 디스커버리: outlook STOPPED, calendar RUNNING
2. startable=true인 outlook만 자동 시작
3. calendar는 건너뜀 (이미 RUNNING)
4. 최종: 둘 다 RUNNING ✓
```

**입력:** `/mcp_ms365` (등록은 됐지만 venv가 없음)

```
1. 디스커버리: venv_ok=false → 모든 서버 issues에 "venv missing" 포함
2. 중단 안내: "venv가 없어 시작 불가. /setup_ms365 실행 후 재시도"
```
