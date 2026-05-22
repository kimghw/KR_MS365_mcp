---
name: setup_ms365
description: Windows에서 MS365 MCP 서버(mcp_outlook, mcp_calendar)를 셋업하는 스킬. AskUserQuestion으로 처리할 서버(outlook/calendar/둘 다)와 등록 타겟(Claude Code / Claude Desktop / 둘 다)을 받아 venv 생성 + 의존성 설치 + .env 부트스트랩 + MCP 등록을 처리합니다. 실제 OAuth 인증은 MCP 서버가 첫 툴 호출 시 자동으로 트리거하므로 이 스킬은 .env(Azure 자격증명)만 깔아두면 됩니다.
---

# Windows MS365 MCP 셋업 스킬 (outlook + calendar)

이 스킬은 **`/setup_ms365`**로 호출합니다.

## 인증은 MCP 서버가 자동 처리 — 이 스킬이 하지 않습니다

OAuth 브라우저 플로우, refresh_token 갱신, 콜백 서버 기동, `auth.db` 저장은 모두 [`session/auth_manager.py`](../../../session/auth_manager.py)와 MCP 서버가 자체 처리합니다:

- 사용자가 Claude에서 outlook 툴 호출 → 토큰 조회 실패 → [`graph_mail_query.py:92`](../../../mcp_outlook/graph_mail_query.py#L92)이 [`get_auth_url_for_login()`](../../../session/auth_manager.py#L256) 호출 → `{"status": "auth_required", "auth_url": "..."}` 반환 → MCP 서버가 LLM에 텍스트로 전달 → Claude가 URL 노출 → 사용자 클릭 → 콜백이 자동 토큰 저장
- refresh_token 만료도 `validate_and_refresh_token(auto_reauth=True)`이 자동으로 브라우저 폴백

**이 스킬이 책임지는 것은 단 하나** — Azure 자격증명(`CLIENT_ID/SECRET/TENANT_ID`)을 `.env`에 깔아두는 것. 이게 없으면 서버가 auth URL 자체를 만들 수 없음.

## 지원 서버

| 서버 | HTTP 포트 (Code) | STDIO 진입점 (Desktop) |
|---|---|---|
| `outlook` | 8091 | `mcp_outlook/mcp_server/server_stdio.py` |
| `calendar` | 8002 | `mcp_calendar/mcp_server/server_stdio.py` |

`.env`, `auth.db`, OAuth 콜백은 두 서버가 **공유**합니다 — 1회 인증으로 양쪽 다 사용 가능.

## 모드

| 모드 | 하는 일 |
|---|---|
| **셋업** (full) | venv 생성 + `requirements.txt` 설치 + `.env` (없으면) + **선택 서버**들을 **선택 타겟**에 등록 |
| **.env 갱신** | Azure 자격증명만 새로 받아 `.env` 덮어쓰기 (기존 백업) |
| **상태** | 현재 환경 스냅샷만 출력 |
| **점검** | 현 토큰 유효성 확인 + Code에 등록되고 포트가 LISTEN 중인 HTTP 서버마다 Streamable HTTP 8-probe 컴플라이언스 검사 |

## 등록 타겟 (Claude Code vs Claude Desktop)

| 항목 | Claude Code | Claude Desktop |
|---|---|---|
| Config 파일 | `~/.claude.json` (= `C:\Users\USER\.claude.json`) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Transport | HTTP streamable (`server_stream.py`) | STDIO (`server_stdio.py`) |
| 등록 방법 | `claude mcp add --transport http` | JSON 파일 직접 병합 |
| 서버 프로세스 | 별도 실행 필요 (HTTP 백그라운드) | Claude Desktop이 자동 spawn |

**두 config 파일은 공유되지 않습니다.** 양쪽 다 쓰려면 양쪽 다 등록.

## 스킬 구성 파일

```
setup_ms365/
├── SKILL.md             ← 실행 지침 (이 파일)
├── references/
│   ├── setup_reference.md            ← Windows 경로, 의존성, OAuth 자동 처리 흐름
│   └── streamable_http_checklist.md  ← MCP Streamable HTTP transport 표준 8-probe 체크리스트
└── scripts/
    ├── verify_setup.py  ← venv/의존성/.env/토큰/등록/포트 통합 검증
    └── streamable_http_probe.py  ← 등록된 HTTP MCP 서버의 8-probe 자동 실행
```

## 사전 확인 (Windows 절대 경로)

| 항목 | 경로 |
|---|---|
| 프로젝트 루트 | `c:\Users\USER\KR_MS365_mcp` |
| venv Python | `c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe` |
| `.env` (공통) | `c:\Users\USER\KR_MS365_mcp\.env` |
| 토큰 DB (공통) | `c:\Users\USER\KR_MS365_mcp\database\auth.db` |
| outlook HTTP | `mcp_outlook\mcp_server\server_stream.py` (포트 8091) |
| outlook STDIO | `mcp_outlook\mcp_server\server_stdio.py` |
| calendar HTTP | `mcp_calendar\mcp_server\server_stream.py` (포트 8002) |
| calendar STDIO | `mcp_calendar\mcp_server\server_stdio.py` |
| 인증 모듈 (공통) | `c:\Users\USER\KR_MS365_mcp\session\auth_manager.py` |
| OAuth 콜백 포트 | `.env`의 `AZURE_REDIRECT_URI` 파싱 (현재 `5001`) |
| Claude Desktop config | `%APPDATA%\Claude\claude_desktop_config.json` |

상세는 [references/setup_reference.md](references/setup_reference.md) 참조.

## 인자

- `/setup_ms365` (인자 없음) → 상태 스냅샷 + AskUserQuestion으로 모드 선택
- `/setup_ms365 setup` → 셋업 강제
- `/setup_ms365 env` → `.env` 자격증명만 갱신
- `/setup_ms365 check` → 점검 (토큰 유효성 + Streamable HTTP 컴플라이언스)
- `/setup_ms365 status` → 상태 출력만

---

## Instructions

아래 단계를 **순서대로** 실행. Bash 도구를 사용하고, 경로는 Windows 형식 (`c:\...`).

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

"$PY" "c:\Users\USER\KR_MS365_mcp\.claude\skills\setup_ms365\scripts\verify_setup.py" --json
```

JSON을 한국어 표로 요약해서 한 번만 출력. `status` 인자였다면 여기서 종료.

**경로 무결성 체크**: `claude_desktop.path_valid == false` 또는 `claude_desktop.matches_project == false`이면 사용자에게 경고:

> ⚠️ Claude Desktop config의 outlook 경로가 무효하거나 현 프로젝트와 다릅니다.
> 등록된 command: `{cd.command}`
> 기대값: `c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe`
> 셋업 모드를 다시 실행해 덮어쓸 것을 권장합니다.

사용자가 동의하면 3-A-5-CD 단계만 즉시 실행해 덮어쓰기.

### 2단계: 모드 선택 (인자 없을 때만)

`AskUserQuestion`:

- question: `"무엇을 할까요? (현재: {요약 한 줄})"`
- header: `"Outlook MCP"`
- multiSelect: `false`
- options:
  1. label: `"셋업 (venv + 의존성 + .env + MCP 등록)"`
     description: `"전체 부트스트랩. .env가 없으면 자격증명도 함께 입력. 인증 자체는 첫 MCP 툴 호출 시 자동 진행."`
  2. label: `".env만 갱신 (Azure 자격증명 입력)"`
     description: `"CLIENT_ID/SECRET/TENANT_ID 새로 받아 덮어쓰기. 기존 .env는 자동 백업."`
  3. label: `"인증 점검 (현 토큰 유효성만 확인)"`
     description: `"브라우저 안 띄우고 validate_and_refresh_token으로 1회 체크. 만료면 refresh 시도."`
  4. label: `"상태만 보고 종료"`
     description: `"1단계 출력만"`

### 3-A단계: 셋업 모드

#### 3-A-0a. 처리할 서버 선택

`AskUserQuestion`:

- question: `"어떤 서버를 처리할까요?"`
- header: `"서버"`
- multiSelect: `true`
- options:
  1. label: `"outlook (메일)"`
     description: `"mcp_outlook 서버. HTTP=8091, STDIO=mcp_outlook/mcp_server/server_stdio.py"`
  2. label: `"calendar (일정)"`
     description: `"mcp_calendar 서버. HTTP=8002, STDIO=mcp_calendar/mcp_server/server_stdio.py"`

선택 결과를 `{servers}` 집합으로 기억 (예: `{outlook}`, `{calendar}`, `{outlook, calendar}`). 미선택 시 종료.

#### 3-A-0b. 등록 타겟 선택

`AskUserQuestion`:

- question: `"어디에 등록할까요?"`
- header: `"등록 타겟"`
- multiSelect: `true`
- options:
  1. label: `"Claude Code (HTTP)"`
     description: `"~/.claude.json에 HTTP MCP 등록. server_stream.py 별도 백그라운드 실행 필요."`
  2. label: `"Claude Desktop (STDIO)"`
     description: `"%APPDATA%\\Claude\\claude_desktop_config.json에 STDIO 항목 추가. Desktop이 server_stdio.py 자동 spawn."`

선택 결과를 `{targets}` 집합으로 기억. 둘 다 미선택이면 종료.

> 이후 단계 3-A-5와 4단계는 `{servers}`의 각 서버에 대해 반복 수행. `{name}`은 서버 이름(`outlook` 또는 `calendar`).
> 서버별 파라미터:
> - `{port}`: outlook=8091, calendar=8002
> - `{stdio_script}`: `c:\Users\USER\KR_MS365_mcp\mcp_{name}\mcp_server\server_stdio.py`
> - `{stream_script}`: `c:\Users\USER\KR_MS365_mcp\mcp_{name}\mcp_server\server_stream.py`

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

생성 후 `venv\Scripts\python.exe` 재확인.

#### 3-A-3. 의존성 설치

```bash
"c:\Users\USER\KR_MS365_mcp\venv\Scripts\pip.exe" install -r "c:\Users\USER\KR_MS365_mcp\requirements.txt"
```

타임아웃 600초. 실패 시 마지막 에러 라인 보여주고 계속 여부 질문.

#### 3-A-4. `.env` 부트스트랩 (없을 때만)

`.env`가 없으면 → **3-B단계** 자격증명 입력 로직 그대로 실행해 `.env` 작성.
이미 있으면 건너뜀.

#### 3-A-5. MCP 등록 (`{servers}` × `{targets}` 조합으로 반복)

각 서버 `{name}`에 대해 (`{port}` = 8091 또는 8002):

**3-A-5-CC: Claude Code (HTTP)** — `{targets}`에 `cc` 포함 시

> **스코프는 항상 `-s user` (글로벌)** — 모든 Claude Code 세션에서 활성화되도록. 프로젝트 스코프(`-s local`, 기본값)는 이 저장소를 열었을 때만 보이므로 사용 안 함.

```bash
# -s user를 명시해서 ~/.claude.json의 top-level mcpServers에 기록
claude mcp remove {name} -s user 2>/dev/null || true
claude mcp remove {name} -s local 2>/dev/null || true   # 잘못 등록된 project-scope entry 정리
claude mcp add -s user --transport http {name} http://localhost:{port}/mcp
claude mcp get {name} 2>&1 | head -10
```

CLI 폴백 (PATH에 `claude` 없을 때) — `~/.claude.json`의 **top-level** `mcpServers`에 기록 + 프로젝트 스코프에 잔존하는 entry는 함께 제거:

```bash
"c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe" - <<'PY'
import json
from pathlib import Path
p = Path.home() / ".claude.json"
data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
mcp = data.setdefault("mcpServers", {})

# 선택된 서버들 (스킬 컨텍스트에서 동적 결정)
servers_to_register = {
    "outlook": 8091,   # {servers}에 포함된 것만 남기기
    "calendar": 8002,
}
for name, port in servers_to_register.items():
    mcp[name] = {"type": "http", "url": f"http://localhost:{port}/mcp"}

# 프로젝트-스코프에 잔존하는 동일 이름 entry 제거 (글로벌과 중복 방지)
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

> HTTP는 클라이언트가 외부 서버에 연결만 하므로 각 `server_stream.py`는 별도 실행 필요. 4단계 참조.

**3-A-5-CD: Claude Desktop (STDIO)** — `{targets}`에 `cd` 포함 시

`{servers}`의 각 서버를 한 번의 read-modify-write로 처리 (다른 entry 보존):

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

# 선택된 서버들 (스킬 컨텍스트에서 동적 결정)
SERVERS_TO_REGISTER = ["outlook", "calendar"]   # {servers}에 포함된 것만 남기기

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

> Claude Desktop 재시작 필요. STDIO는 Desktop이 자동 spawn하므로 서버 백그라운드 실행 불필요.

#### 3-A-6. 검증 → 5단계로

### 3-B단계: `.env` 갱신 모드

#### 3-B-1. 기존 `.env` 백업

```bash
if [ -f "/c/Users/USER/KR_MS365_mcp/.env" ]; then
  cp "c:\Users\USER\KR_MS365_mcp\.env" "c:\Users\USER\KR_MS365_mcp\.env.bak.$(date +%Y%m%d_%H%M%S)"
fi
```

#### 3-B-2. Azure 자격증명 수집

사용자에게 텍스트로 한 번에 요청 (AskUserQuestion 쪼개지 말 것):

```
다음 3개 값을 알려주세요:
- AZURE_CLIENT_ID (Azure AD App의 Application/Client ID)
- AZURE_CLIENT_SECRET (Client Secret 값)
- AZURE_TENANT_ID (Tenant UUID 또는 'common')
```

검증:
- 셋 다 비어 있으면 안 됨
- `AZURE_TENANT_ID`는 UUID 또는 `common`/`organizations`/`consumers`

**고정값 (묻지 말 것):**
- `AZURE_REDIRECT_URI=http://localhost:5000/callback`
- `AZURE_SCOPES=offline_access openid`
- `AZURE_AUTHORITY=https://login.microsoftonline.com`

#### 3-B-3. `.env` 작성

`Write` 도구로:

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

#### 3-B-4. 마무리 안내

`.env`가 새로 생겼다면 사용자에게:

> `.env` 준비 완료. Claude에서 outlook MCP 툴을 한 번 호출하면 자동으로 인증 URL이 나옵니다. Claude Desktop 사용 시 재시작 필요할 수 있음.

### 3-C단계: 점검 모드 (토큰 + Streamable HTTP 컴플라이언스)

이 모드는 두 가지를 확인합니다:

1. **토큰 점검** — 브라우저 안 띄우고 `validate_and_refresh_token(auto_reauth=False)`만 1회 실행
2. **Streamable HTTP 컴플라이언스** — `~/.claude.json`에 `type: http`로 등록되고 해당 포트가 LISTEN 중인 각 MCP 서버에 대해 표준 transport spec 8개 probe 자동 실행 (initialize/Accept 협상/session-id/SSE/notification/세션 검증/DELETE/세션 종료 확인). 자체 구현이거나 legacy `/mcp/v1` 류라면 여기서 잡힘. 상세 spec과 anti-pattern은 [references/streamable_http_checklist.md](references/streamable_http_checklist.md) 참조.

#### 3-C-1. 토큰 점검

브라우저 안 띄우고 현 토큰 상태만 확인:

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
            print(json.dumps({"status": "no_user", "message": ".env로 자격증명 입력 후 Claude에서 첫 툴 호출하면 사용자 등록됨"}, ensure_ascii=False))
            return
        # auto_reauth=False — 브라우저 절대 안 띄움. refresh만 시도
        token = await am.validate_and_refresh_token(email, auto_reauth=False)
        if token:
            print(json.dumps({"status": "valid", "email": email, "token_preview": token[:20] + "..."}, ensure_ascii=False))
        else:
            print(json.dumps({"status": "invalid_or_expired", "email": email, "message": "Claude에서 outlook 툴 호출 → MCP 서버가 auth URL 자동 생성"}, ensure_ascii=False))
    finally:
        await am.close()

asyncio.run(main())
PY
```

결과에 따라 사용자에게 1줄 안내:
- `valid` → "토큰 유효 — 바로 사용 가능"
- `invalid_or_expired` → "refresh 실패. Claude에서 outlook 툴 호출하면 auth URL 나옴"
- `no_user` → "아직 1회 인증 안 됨. `.env` 확인 후 Claude에서 outlook 툴 호출"

#### 3-C-2. Streamable HTTP 컴플라이언스 점검 (서버별)

1단계 상태 스냅샷의 `claude_code.registered == true` 인 HTTP 서버 목록을 받아, 각 서버에 대해 포트가 LISTEN 중이면 `streamable_http_probe.py`를 실행:

```bash
for entry in "outlook 8091" "calendar 8002"; do
  name=${entry%% *}; port=${entry##* }
  if powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue" 2>/dev/null | grep -q LocalPort; then
    echo "=== $name (port $port) ==="
    "c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe" \
      "c:\Users\USER\KR_MS365_mcp\.claude\skills\setup_ms365\scripts\streamable_http_probe.py" \
      --base "http://localhost:$port"
  else
    echo "$name (port $port): 미실행 — probe 건너뜀"
  fi
done
```

표 출력에서 합격선:
- **8/8 통과** → `compliant` (Claude Code/Desktop MCP 클라이언트와 정상 동작 보장)
- **4–7개 통과** → `partial` (Probe 1·4·5·6 중 일부 미통과 시 호환성 의심 — 체크리스트의 "합격 기준" 참조)
- **0–3개 통과** → `non-compliant` (대표 사례: 자체 aiohttp 구현, legacy `/mcp/v1` 라우트, session-id 미사용)

비호환이면 [references/streamable_http_checklist.md](references/streamable_http_checklist.md)의 "코드-수준 안티패턴" + "마이그레이션 체크포인트" 섹션으로 진단/수정.

### 4단계: (셋업 모드, Claude Code 등록한 경우만) MCP 서버 백그라운드 실행

Claude Desktop만 등록했으면 건너뜀 (Desktop이 자동 spawn).

Claude Code 등록 포함 시 `AskUserQuestion`:

- question: `"선택한 서버들을 지금 백그라운드로 실행할까요? ({servers})"`
- header: `"서버 실행"`
- multiSelect: `false`
- options:
  1. label: `"예, 백그라운드 실행"`, description: `"각 서버를 nohup으로 띄우고 /tmp/mcp_{name}.log에 로그"`
  2. label: `"아니오, 나중에 직접"`, description: `"venv\\Scripts\\python.exe mcp_{name}\\mcp_server\\server_stream.py"`

"예" 시 `{servers}`의 각 `{name}`에 대해 반복 (`{port}` = 8091 또는 8002):

```bash
# {name} 포트 점유 확인
if powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue" 2>/dev/null | grep -q LocalPort; then
  echo "포트 {port} 이미 사용 중 — 기존 프로세스 유지"
else
  cd /c/Users/USER/KR_MS365_mcp
  nohup ./venv/Scripts/python.exe mcp_{name}/mcp_server/server_stream.py > /tmp/mcp_{name}.log 2>&1 &
  disown
  sleep 3
fi
```

### 5단계: 최종 검증

```bash
"$VENV_PY" "c:\Users\USER\KR_MS365_mcp\.claude\skills\setup_ms365\scripts\verify_setup.py"
```

표 출력 + 모드별 요약:

**셋업 완료:**
```
✅ 셋업 완료
- venv: c:\Users\USER\KR_MS365_mcp\venv (Python 3.x.x)
- 의존성: N개
- .env: O (CLIENT_ID/SECRET/TENANT_ID 채워짐)

처리된 서버: {servers} (예: outlook, calendar)

[Code 등록한 서버별]
- outlook  → http://localhost:8091/mcp  (server_stream RUNNING/STOPPED)
- calendar → http://localhost:8002/mcp  (server_stream RUNNING/STOPPED)

[Desktop 등록한 서버별]
- claude_desktop_config.json에 outlook, calendar STDIO 항목 추가
- Claude Desktop 재시작 필요

인증: Claude에서 outlook/calendar 툴을 처음 호출하면 자동으로 인증 URL이 나옵니다.
(.env의 자격증명 1세트로 두 서버가 같은 auth.db 공유)
```

**.env 갱신:**
```
✅ .env 갱신 완료 (백업: .env.bak.{timestamp})
다음: Claude에서 outlook 툴 호출 → 자동 인증
```

**점검:**
```
✅ 토큰 유효 (또는 갱신 필요/사용자 없음 — 상세 안내)
+ outlook  http://localhost:8091/mcp  → 8/8 probes — compliant
+ calendar http://localhost:8002/mcp  → 8/8 probes — compliant
```

(미실행 서버는 skip. 비호환 서버는 [references/streamable_http_checklist.md](references/streamable_http_checklist.md)로 진단)

---

## 보안 주의사항

- `.env` 파일 내용을 채팅에 그대로 출력하지 말 것 (Client Secret 평문)
- `.env`, `.env.bak.*`는 `.gitignore` 등재 확인
- 입력받은 자격증명을 memory 시스템에 저장 금지

---

## Examples

**입력:** `/setup_ms365` (첫 설치, 둘 다 설정)

```
1. 상태: venv X / 의존성 - / .env X / 토큰 - / outlook 미등록 / calendar 미등록
2. 모드 선택 → "셋업"
3-A-0a. 서버 → outlook + calendar 둘 다
3-A-0b. 타겟 → Code + Desktop 둘 다
3-A-1~3. Python 발견 → venv 생성 → pip install (56 packages)
3-A-4. .env 없음 → 자격증명 수집 → .env 작성
3-A-5-CC. claude mcp add outlook + calendar → OK (HTTP)
3-A-5-CD. claude_desktop_config.json에 outlook + calendar STDIO 병합 → OK
4. server_stream.py outlook(8091) + calendar(8002) 백그라운드 실행 → OK
5. 검증 표:
   공통: ✅ venv | 의존성 | .env | 토큰
   outlook:  ✅ Code | Desktop | 포트 8091
   calendar: ✅ Code | Desktop | 포트 8002

   다음: Claude/Desktop에서 outlook/calendar 툴 호출 → 자동 인증 URL 안내
```

**입력:** `/setup_ms365` (calendar만 추가)

```
1. 상태: 다 OK, 단 calendar Desktop 경로 무효 (옛 entry)
2. 모드 선택 → "셋업"
3-A-0a. 서버 → calendar만
3-A-0b. 타겟 → Desktop만
3-A-5-CD. claude_desktop_config.json의 calendar entry 덮어쓰기 (outlook은 그대로)
5. 검증 표: calendar Desktop OK
```

**입력:** `/setup_ms365 env` (자격증명만 갱신)

```
3-B. 기존 .env 백업 → 새 값 입력 → 작성
   → Claude에서 outlook 툴 호출하면 새 자격증명으로 자동 인증
```

**입력:** `/setup_ms365 check` (토큰 점검)

```
3-C. validate_and_refresh_token(auto_reauth=False) 실행
   → "valid" / "invalid_or_expired" / "no_user" 중 하나
```

---

## 주의사항

- venv는 재생성하지 않고 `pip install`만 재실행 (멱등)
- Claude Code 등록은 `claude mcp remove` + `claude mcp add` 패턴으로 멱등
- Claude Desktop은 config 변경 후 **재시작** 필요
- 새 Claude Code 세션에서만 등록된 MCP가 보임
- 콜백 포트 5000은 Hyper-V 동적 예약과 충돌 가능 — `.env`의 `AZURE_REDIRECT_URI`를 다른 포트로 변경하고 Azure Portal도 같이 갱신해서 회피
