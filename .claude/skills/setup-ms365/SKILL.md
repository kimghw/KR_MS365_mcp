---
name: setup-ms365
description: KR_MS365_mcp 통합 셋업·운영 스킬. 6개 MS365 MCP 서버(outlook/calendar/teams/onedrive/onenote/todo)의 venv·의존성·.env·MCP 등록(셋업)부터 HTTP 서버 백그라운드 실행·중지·상태점검까지 한 스킬에서 처리합니다. AskUserQuestion으로 모드/서버/등록타겟을 받고, Azure OAuth는 MCP 서버가 첫 툴 호출 시 자동 트리거합니다.
---

# MS365 MCP 통합 셋업·운영 스킬

이 스킬은 **`/setup-ms365`**로 호출. 셋업(venv/.env/등록)과 서버 운영(start/stop/status)을 한 곳에서 처리합니다.

## 인증은 MCP 서버가 자동 처리 — 이 스킬이 하지 않습니다

OAuth 브라우저 플로우, refresh_token 갱신, 콜백 서버, `auth.db` 저장은 [`session/auth_manager.py`](../../../session/auth_manager.py)와 MCP 서버가 자체 처리합니다. 이 스킬이 책임지는 건 단 하나 — Azure 자격증명(`CLIENT_ID/SECRET/TENANT_ID`)을 `.env`에 깔아두는 것 + 서버 프로세스 띄우기.

## 지원 서버 (6개)

| 서버 | HTTP 포트 | STDIO 진입점 (Desktop) | HTTP 진입점 (Code) |
|---|---|---|---|
| `outlook` | 5001 | `mcp_outlook/mcp_server/server_stdio.py` | `mcp_outlook/mcp_server/server_stream.py` |
| `calendar` | 5002 | `mcp_calendar/mcp_server/server_stdio.py` | `mcp_calendar/mcp_server/server_stream.py` |
| `teams` | 5003 | `mcp_teams/mcp_server/server_stdio.py` | `mcp_teams/mcp_server/server_stream.py` |
| `onedrive` | 5004 | `mcp_onedrive/mcp_server/server_stdio.py` | `mcp_onedrive/mcp_server/server_stream.py` |
| `onenote` | 5005 | `mcp_onenote/mcp_server/server_stdio.py` | `mcp_onenote/mcp_server/server_stream.py` |
| `todo` | 5006 | `mcp_todo/mcp_server/server_stdio.py` | `mcp_todo/mcp_server/server_stream.py` |

모든 서버는 `.env`와 `database/auth.db`를 **공유**합니다 — 1회 인증으로 6개 다 사용 가능.

## 모드

| 모드 | 하는 일 |
|---|---|
| **setup** | venv 생성 + `requirements.txt` 설치 + `.env` 부트스트랩 + 선택 서버를 선택 타겟(Code/Desktop)에 등록 |
| **env** | Azure 자격증명만 새로 받아 `.env` 덮어쓰기 (기존 백업) |
| **check** | 토큰 유효성 확인 + Code에 등록되고 포트 LISTEN 중인 HTTP 서버에 Streamable HTTP 8-probe 컴플라이언스 검사 |
| **status** | 현재 환경 + 6개 서버 상태 스냅샷만 출력 |
| **start** | 선택한 HTTP 서버를 백그라운드로 실행 |
| **stop** | 선택한 HTTP 서버 중지 (포트 점유 프로세스 kill) |
| **restart** | stop → start |

## 등록 타겟 (Claude Code vs Claude Desktop)

| 항목 | Claude Code | Claude Desktop |
|---|---|---|
| Config 파일 | `~/.claude.json` (= `C:\Users\USER\.claude.json`) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Transport | HTTP streamable (`server_stream.py`) | STDIO (`server_stdio.py`) |
| 등록 방법 | `claude mcp add --transport http -s user` | JSON 파일 직접 병합 |
| 서버 프로세스 | 별도 백그라운드 실행 필요 (이 스킬의 start 모드) | Claude Desktop이 자동 spawn |

**두 config는 공유되지 않습니다** — 양쪽 다 쓰려면 양쪽 다 등록.

## 스킬 구성

```
setup-ms365/
├── SKILL.md
├── references/
│   ├── setup_reference.md            ← 경로/의존성/OAuth 흐름
│   └── streamable_http_checklist.md  ← Streamable HTTP 8-probe 체크리스트
└── scripts/
    ├── verify_setup.py        ← venv/의존성/.env/토큰/등록/포트 통합 검증
    └── streamable_http_probe.py  ← 등록된 HTTP MCP 서버의 8-probe 실행
```

## 사전 확인 (Windows 절대 경로)

| 항목 | 경로 |
|---|---|
| 프로젝트 루트 | `c:\Users\USER\KR_MS365_mcp` |
| venv Python | `c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe` |
| `.env` (공통) | `c:\Users\USER\KR_MS365_mcp\.env` |
| 토큰 DB (공통) | `c:\Users\USER\KR_MS365_mcp\database\auth.db` |
| 인증 모듈 | `c:\Users\USER\KR_MS365_mcp\session\auth_manager.py` |
| Claude Desktop config | `%APPDATA%\Claude\claude_desktop_config.json` |
| OAuth 콜백 포트 | `.env`의 `AZURE_REDIRECT_URI` (현재 5000) |

상세는 [references/setup_reference.md](references/setup_reference.md).

## 인자

- `/setup-ms365` — 상태 표시 + AskUserQuestion으로 모드 선택
- `/setup-ms365 setup` — 셋업
- `/setup-ms365 env` — `.env` 갱신
- `/setup-ms365 check` — 토큰 + Streamable HTTP 점검
- `/setup-ms365 status` — 상태만
- `/setup-ms365 start` — AskUserQuestion으로 시작할 서버 선택
- `/setup-ms365 start all` — STOPPED인 모든 서버 시작
- `/setup-ms365 start outlook teams` — 명시 서버만 시작
- `/setup-ms365 stop <server>` — 해당 서버 중지
- `/setup-ms365 stop all` — 전체 중지
- `/setup-ms365 restart <server>` — 재시작

---

## Instructions

순서대로 실행. Bash 도구 사용, 경로는 Windows 형식.

### 1단계: 상태 스냅샷

```bash
VENV_PY="c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe"
SYS_PY=$(ls /c/Python3*/python.exe /mnt/c/Python3*/python.exe 2>/dev/null | head -1)

if [ -f "/c/Users/USER/KR_MS365_mcp/venv/Scripts/python.exe" ] \
   || [ -f "/mnt/c/Users/USER/KR_MS365_mcp/venv/Scripts/python.exe" ]; then
  PY="$VENV_PY"
else
  PY="$SYS_PY"
fi

"$PY" "c:\Users\USER\KR_MS365_mcp\.claude\skills\setup-ms365\scripts\verify_setup.py" --json
```

JSON을 한국어 표로 요약해서 한 번만 출력 (서버별로 Code/Desktop/Port 상태 + 공통 venv/.env/토큰). `status` 인자였다면 여기서 종료.

**경로 무결성 체크**: 서버별 `claude_desktop.path_valid == false` 또는 `matches_project == false`이면 경고.

### 2단계: 스마트 진단 (인자 없을 때 자동 실행)

1단계 JSON을 분석해 3개 카테고리로 분류:

- **`unhealthy_common`**: venv 없음 OR 의존성 누락 OR `.env` 부재/불완전 — 셋업 필수
- **`unregistered`**: 각 서버에 대해 Code 또는 Desktop에 누락된 항목  
  (예: `outlook`은 Code에는 있지만 Desktop에는 없음 → `outlook: [Desktop]`)
- **`stopped`**: Code에 등록되어 있고(또는 사용자가 시작 원함) 포트가 LISTEN 아닌 서버

이 3개에 따라 분기:

#### 2-A. `unhealthy_common`이 있으면

```
공통 환경이 불완전합니다: {빠진 항목들}
셋업이 필요합니다.
```

AskUserQuestion: `"지금 셋업할까요?"` — 예 → 3-A단계, 아니오 → 모드 선택 메뉴(2-D)로.

#### 2-B. `unregistered` 항목이 있으면

각 서버별로 어디에 누락됐는지 표로 보여준 뒤 (예: `teams [Code:O Desktop:X]`),
AskUserQuestion **multiSelect**:

- question: `"누락된 등록을 추가할까요? (체크한 항목만 추가)"`
- header: `"등록 추가"`
- multiSelect: `true`
- options: 누락된 (서버, 타겟) 쌍 각각을 1개 옵션으로
  - 예: `"outlook → Claude Desktop (STDIO)"`, `"teams → Claude Code (HTTP)"`, `"teams → Claude Desktop (STDIO)"`
- 미선택 항목은 건너뛰고, 선택한 (서버, 타겟) 조합으로 **3-A-5단계만 부분 실행** (venv/의존성/.env는 이미 OK이므로 skip).

`unregistered`가 비어있으면 이 단계 건너뛰고 2-C로.

#### 2-C. `stopped` 서버가 있으면

Code에 등록된 서버 중 포트가 LISTEN 아닌 것만 추림. (Desktop-only 서버는 Desktop이 자동 spawn하므로 제외.)

AskUserQuestion **multiSelect**:

- question: `"정지 중인 HTTP 서버를 백그라운드로 실행할까요?"`
- header: `"서버 시작"`
- multiSelect: `true`
- options: 정지된 서버마다 1개 (예: `"outlook (5001)"`, `"teams (5003)"`)
- 선택한 서버 → **3-D-1단계**로 (백그라운드 nohup 실행 + /health 확인)

`stopped`가 비어있으면 이 단계 건너뛰고 2-D로.

#### 2-D. 전부 OK이거나 위에서 다 처리된 경우

```
✅ 모든 서버 정상 등록 + 실행 중
```

추가 작업이 필요하면 AskUserQuestion으로 모드 메뉴 표시 (선택 안 하고 종료 가능):

- question: `"추가로 할 작업이 있나요? (없으면 그냥 종료)"`
- header: `"MS365 MCP"`
- multiSelect: `false`
- options:
  1. `".env 갱신 (Azure 자격증명 재입력)"` → 3-B
  2. `"인증 점검 (토큰 + Streamable HTTP probe)"` → 3-C
  3. `"서버 중지 / 재시작"` → 3-D-2/3-D-3
  4. `"종료"` → 끝

### 2-E단계: 명시 인자가 있을 때

`setup`/`env`/`check`/`status`/`start`/`stop`/`restart` 인자가 있으면 1단계 출력 후 2단계(스마트 진단) 건너뛰고 곧장 해당 단계로 분기:

| 인자 | 분기 |
|---|---|
| `setup` | 3-A |
| `env` | 3-B |
| `check` | 3-C |
| `status` | 1단계 출력 후 종료 |
| `start [서버...]` | 3-D-1 |
| `stop [서버...]` | 3-D-2 |
| `restart [서버...]` | 3-D-3 |

### 3-A단계: 셋업 모드

#### 3-A-0a. 처리할 서버 선택

`AskUserQuestion` multiSelect, 6개 옵션:
- `"outlook (메일, HTTP=5001)"`
- `"calendar (일정, HTTP=5002)"`
- `"teams (채팅/채널, HTTP=5003)"`
- `"onedrive (파일, HTTP=5004)"`
- `"onenote (노트, HTTP=5005)"`
- `"todo (할일, HTTP=5006)"`

선택 결과를 `{servers}` 집합으로 기억. 미선택 시 종료.

#### 3-A-0b. 등록 타겟 선택

`AskUserQuestion` multiSelect:
1. `"Claude Code (HTTP)"` — `~/.claude.json` -s user
2. `"Claude Desktop (STDIO)"` — `claude_desktop_config.json`

`{targets}` 집합으로 기억. 둘 다 미선택이면 종료.

> 이후 3-A-5와 4단계는 `{servers}`의 각 서버에 대해 반복. `{name}`, `{port}`, `{stdio_script}`, `{stream_script}`는 위 "지원 서버" 표 참조.

#### 3-A-1. Windows 시스템 Python 탐색

```bash
ls /c/Python3*/python.exe /mnt/c/Python3*/python.exe 2>/dev/null
```

여러 개면 사용자 선택. 없으면 직접 입력. `SYSTEM_PYTHON`으로 기억.

#### 3-A-2. venv 생성 (없으면)

```bash
if [ -f "/c/Users/USER/KR_MS365_mcp/venv/Scripts/python.exe" ] \
   || [ -f "/mnt/c/Users/USER/KR_MS365_mcp/venv/Scripts/python.exe" ]; then
  echo "venv 존재 — 의존성 업데이트만"
else
  "$SYSTEM_PYTHON" -m venv "c:\Users\USER\KR_MS365_mcp\venv"
fi
```

#### 3-A-3. 의존성 설치

```bash
"c:\Users\USER\KR_MS365_mcp\venv\Scripts\pip.exe" install -r "c:\Users\USER\KR_MS365_mcp\requirements.txt"
```

타임아웃 600초. 실패 시 마지막 에러 라인 보여주고 계속 여부 질문.

#### 3-A-4. `.env` 부트스트랩 (없을 때만)

`.env`가 없으면 → **3-B단계**의 자격증명 입력 로직 그대로 실행. 있으면 건너뜀.

#### 3-A-5. MCP 등록 (`{servers}` × `{targets}` 조합 반복)

각 서버에 대해:

**3-A-5-CC: Claude Code (HTTP)** — `{targets}`에 Code 포함 시

> **스코프는 항상 `-s user` (글로벌)** — 모든 Claude Code 세션에서 활성화.

```bash
# {name} = outlook/calendar/teams/onedrive/onenote/todo
# {port} = 5001/5002/5003/5004/5005/5006
claude mcp remove {name} -s user 2>/dev/null || true
claude mcp remove {name} -s local 2>/dev/null || true
claude mcp add -s user --transport http {name} http://localhost:{port}/mcp
claude mcp get {name} 2>&1 | head -10
```

CLI 폴백 (`claude` 없을 때) — `~/.claude.json` 직접 편집:

```bash
"c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe" - <<'PY'
import json
from pathlib import Path

p = Path.home() / ".claude.json"
data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
mcp = data.setdefault("mcpServers", {})

# 선택된 서버 목록 (스킬 컨텍스트에서 동적 결정)
servers_to_register = {
    "outlook":  5001,
    "calendar": 5002,
    "teams":    5003,
    "onedrive": 5004,
    "onenote":  5005,
    "todo":     5006,
}
for name, port in servers_to_register.items():
    mcp[name] = {"type": "http", "url": f"http://localhost:{port}/mcp"}

# 프로젝트-스코프에 잔존하는 동일 이름 entry 제거
for proj_path, proj_data in (data.get("projects") or {}).items():
    proj_mcp = proj_data.get("mcpServers") if isinstance(proj_data, dict) else None
    if isinstance(proj_mcp, dict):
        for name in list(proj_mcp.keys()):
            if name in servers_to_register:
                proj_mcp.pop(name)

p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"updated {p}: top-level mcpServers = {list(mcp.keys())}")
PY
```

> HTTP는 클라이언트가 외부 서버에 연결만 함 → `server_stream.py` 별도 실행 필요 (4단계).

**3-A-5-CD: Claude Desktop (STDIO)** — `{targets}`에 Desktop 포함 시

한 번의 read-modify-write로 처리 (다른 entry 보존):

```bash
"c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe" - <<'PY'
import json, os
from pathlib import Path

cfg = Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
cfg.parent.mkdir(parents=True, exist_ok=True)

data = {}
if cfg.exists():
    try:
        data = json.loads(cfg.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        print(f"ERROR: existing config invalid JSON: {e}")
        raise SystemExit(1)

PROJECT = r"c:\Users\USER\KR_MS365_mcp"
PYTHON = rf"{PROJECT}\venv\Scripts\python.exe"
mcp = data.setdefault("mcpServers", {})

# 선택된 서버 목록 (스킬 컨텍스트에서 동적 결정)
SERVERS_TO_REGISTER = ["outlook", "calendar", "teams", "onedrive", "onenote", "todo"]

for name in SERVERS_TO_REGISTER:
    mcp[name] = {
        "command": PYTHON,
        "args": [rf"{PROJECT}\mcp_{name}\mcp_server\server_stdio.py"],
        "env": {
            "PYTHONPATH": PROJECT,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        },
    }

cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"updated {cfg} — mcpServers: {list(mcp.keys())}")
PY
```

> Claude Desktop 재시작 필요. STDIO는 Desktop이 자동 spawn.

#### 3-A-6. 4단계로 (Code 포함 시) 또는 5단계로

### 3-B단계: `.env` 갱신 모드

#### 3-B-1. 기존 `.env` 백업

```bash
if [ -f "/c/Users/USER/KR_MS365_mcp/.env" ]; then
  cp "c:\Users\USER\KR_MS365_mcp\.env" "c:\Users\USER\KR_MS365_mcp\.env.bak.$(date +%Y%m%d_%H%M%S)"
fi
```

#### 3-B-2. Azure 자격증명 수집 (한 번에 텍스트로)

```
다음 3개 값을 알려주세요:
- AZURE_CLIENT_ID (Azure AD App의 Application/Client ID)
- AZURE_CLIENT_SECRET (Client Secret 값)
- AZURE_TENANT_ID (Tenant UUID 또는 'common')
```

**고정값 (묻지 말 것):**
- `AZURE_REDIRECT_URI=http://localhost:5000/callback`
- `AZURE_SCOPES=offline_access openid`
- `AZURE_AUTHORITY=https://login.microsoftonline.com`

#### 3-B-3. `.env` 작성 (`Write` 도구)

```
# Azure AD OAuth 설정
AZURE_CLIENT_ID={CLIENT_ID}
AZURE_CLIENT_SECRET={CLIENT_SECRET}
AZURE_TENANT_ID={TENANT_ID}
AZURE_REDIRECT_URI=http://localhost:5000/callback

# 선택 설정
AZURE_AUTHORITY=https://login.microsoftonline.com
AZURE_SCOPES=offline_access openid
```

**민감정보 출력 금지** — 라인 수만 확인.

### 3-C단계: 점검 모드 (토큰 + Streamable HTTP)

#### 3-C-1. 토큰 점검

```bash
cd /c/Users/USER/KR_MS365_mcp
"c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe" - <<'PY'
import asyncio, json
from session.auth_manager import AuthManager, get_default_user_email

async def main():
    am = AuthManager()
    try:
        email = get_default_user_email()
        if not email:
            print(json.dumps({"status": "no_user"}, ensure_ascii=False))
            return
        token = await am.validate_and_refresh_token(email, auto_reauth=False)
        if token:
            print(json.dumps({"status": "valid", "email": email}, ensure_ascii=False))
        else:
            print(json.dumps({"status": "invalid_or_expired", "email": email}, ensure_ascii=False))
    finally:
        await am.close()

asyncio.run(main())
PY
```

#### 3-C-2. Streamable HTTP 컴플라이언스 점검 (서버별)

`~/.claude.json`에 `type: http`로 등록되고 포트가 LISTEN 중인 각 서버에 대해 probe 실행:

```bash
for entry in "outlook 5001" "calendar 5002" "teams 5003" "onedrive 5004" "onenote 5005" "todo 5006"; do
  name=${entry%% *}; port=${entry##* }
  if powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue" 2>/dev/null | grep -q LocalPort; then
    echo "=== $name (port $port) ==="
    "c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe" \
      "c:\Users\USER\KR_MS365_mcp\.claude\skills\setup-ms365\scripts\streamable_http_probe.py" \
      --base "http://localhost:$port"
  else
    echo "$name (port $port): 미실행 — probe 건너뜀"
  fi
done
```

합격선:
- **8/8** → `compliant`
- **4–7개** → `partial`
- **0–3개** → `non-compliant`

비호환 진단은 [references/streamable_http_checklist.md](references/streamable_http_checklist.md).

### 3-D단계: 서버 운영 (start/stop/restart)

#### 3-D-1. start 모드

`/setup-ms365 start` (인자 없음) → 1단계 상태에서 STOPPED 서버 목록을 AskUserQuestion multiSelect로 표시.
`/setup-ms365 start all` → 모든 STOPPED 서버.
`/setup-ms365 start outlook teams` → 명시한 서버만.

각 선택된 `{name}`, `{port}`:

```bash
# 포트 점유 확인
if powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue" 2>/dev/null | grep -q LocalPort; then
  echo "{name}: 포트 {port} 이미 사용 중 — skip"
else
  cd /c/Users/USER/KR_MS365_mcp
  nohup ./venv/Scripts/python.exe mcp_{name}/mcp_server/server_stream.py > /tmp/mcp_{name}.log 2>&1 &
  disown
  echo "{name}: launched"
fi
```

전부 띄운 후 3초 대기, `/health` 응답 확인:

```bash
sleep 3
"c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe" - <<'PY'
import json, urllib.request
SERVERS = {"outlook":5001,"calendar":5002,"teams":5003,"onedrive":5004,"onenote":5005,"todo":5006}
for name, port in SERVERS.items():
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=1) as r:
            print(f"{name:9} {port}  healthy: {json.loads(r.read())}")
    except Exception as e:
        print(f"{name:9} {port}  -")
PY
```

실패한 서버는 로그 끝 20줄 출력: `tail -20 /tmp/mcp_{name}.log`

#### 3-D-2. stop 모드

`/setup-ms365 stop outlook` 또는 `/setup-ms365 stop all`:

```bash
"c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe" - <<'PY'
import subprocess
PORT = 5001   # 인자로 결정. all이면 6개 포트 모두 반복
ps = f"""
$conn = Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue
if ($conn) {{
    foreach ($c in $conn) {{ Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }}
    Write-Output "stopped PID(s) on port {PORT}"
}} else {{
    Write-Output "no listener on port {PORT}"
}}
"""
subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps])
PY
```

#### 3-D-3. restart 모드

`stop {name}` → 1초 대기 → `start {name}`.

### 4단계: (셋업 모드 + Code 등록 시) 서버 백그라운드 실행

Claude Desktop만 등록했으면 건너뜀 (자동 spawn).

`AskUserQuestion`: `"선택한 서버들을 지금 백그라운드로 실행할까요? ({servers})"` — 예/아니오.

"예" 시 3-D-1과 동일 로직으로 `{servers}` 각각 실행.

### 5단계: 최종 검증

```bash
"$VENV_PY" "c:\Users\USER\KR_MS365_mcp\.claude\skills\setup-ms365\scripts\verify_setup.py"
```

표 출력 + 모드별 요약:

**셋업 완료:**
```
✅ 셋업 완료
- venv / 의존성 / .env (CLIENT_ID/SECRET/TENANT_ID)
- 처리된 서버: {servers}
- [Code]    http://localhost:{port}/mcp  (RUNNING/STOPPED)
- [Desktop] STDIO 항목 추가 — Desktop 재시작 필요

인증: Claude에서 해당 서버 툴 처음 호출 시 auth URL 자동 표시.
(.env 자격증명 1세트로 6개 서버가 같은 auth.db 공유)
```

**.env 갱신:** `✅ .env 갱신 완료 (백업: .env.bak.{timestamp})`

**점검:** 토큰 + 서버별 probe 결과 표.

**start/stop/restart:** 1단계 상태 표 재출력.

---

## 보안 주의

- `.env` 내용을 채팅에 출력 금지 (Client Secret 평문)
- `.env`, `.env.bak.*`는 `.gitignore` 등재 확인
- 입력받은 자격증명을 memory 시스템에 저장 금지
- `auth.db`는 평문 SQLite — 공유 머신에 두지 말 것

## 주의사항

- **등록만 함, spawn 안 함** (HTTP) — Claude Code는 외부 서버에 붙기만 하므로 `start` 모드로 띄워야 함
- **포트 점유** — 이미 떠있는 서버는 재시작하지 않음. 강제 재시작 원하면 `restart` 사용
- **로그 위치** — `/tmp/mcp_{name}.log` (Git Bash MSYS 경로, 실제로는 `%TEMP%`)
- venv는 재생성하지 않고 `pip install`만 재실행 (멱등)
- Claude Desktop은 config 변경 후 **재시작** 필요
- 새 Claude Code 세션에서만 등록된 MCP가 보임
- 콜백 포트 5000은 Hyper-V 동적 예약과 충돌 가능 — `.env`의 `AZURE_REDIRECT_URI` + Azure Portal 동시 변경으로 회피

---

## Examples

**`/setup-ms365`** (첫 설치, 6개 다)

```
1. 상태: 다 X
2-A. unhealthy_common 감지 → "지금 셋업할까요?" 예
3-A-0a. 서버 → 6개 다
3-A-0b. 타겟 → Code + Desktop
3-A-1~3. Python 발견 → venv 생성 → pip install
3-A-4. .env 입력 → 작성
3-A-5-CC/CD. Code 6개 + Desktop 6개 등록
4. server_stream.py 6개 백그라운드 실행 → /health 확인
5. 검증 표 출력
```

**`/setup-ms365`** (기존 환경 — 일부 누락)

```
1. 상태: venv/deps/.env OK. teams는 Code만 등록, Desktop 누락. todo는 Code도 Desktop도 미등록
2-B. AskUserQuestion multiSelect:
     ☐ teams → Claude Desktop (STDIO)
     ☐ todo  → Claude Code (HTTP)
     ☐ todo  → Claude Desktop (STDIO)
   → 3개 다 체크 → 3-A-5만 부분 실행
2-C. 정지 서버 감지 (outlook 5001, todo 5006) → multiSelect로 시작 선택 → 3-D-1
5. 검증 표
```

**`/setup-ms365`** (전부 OK)

```
1. 상태: venv/deps/.env/토큰 OK, 6개 서버 다 Code+Desktop 등록 + 포트 LISTEN
2-D. ✅ 모든 서버 정상 — 추가 작업 메뉴 (없으면 종료)
```

**`/setup-ms365 start outlook teams`**

```
1. 상태 확인
3-D-1. outlook(5001)/teams(5003) 백그라운드 실행 → /health OK
```

**`/setup-ms365 stop all`**

```
3-D-2. 6개 포트 모두 Stop-Process
```

**`/setup-ms365 check`**

```
3-C-1. validate_and_refresh_token
3-C-2. LISTEN 중인 서버마다 8-probe → compliant/partial/non-compliant
```
