---
name: ms365
description: KR_MS365_mcp 통합 셋업·운영 스킬. 6개 MS365 MCP 서버(outlook/calendar/teams/onedrive/onenote/todo)의 venv·의존성·.env·MCP 등록(셋업)부터 HTTP 서버 백그라운드 실행·중지·상태점검까지 한 스킬에서 처리합니다. AskUserQuestion으로 모드/서버/등록타겟을 받고, Azure OAuth는 MCP 서버가 첫 툴 호출 시 자동 트리거합니다.
---

# MS365 MCP 통합 셋업·운영 스킬

`/ms365`로 호출. 셋업(venv/.env/등록)과 서버 운영(start/stop/status)을 한 곳에서 처리합니다.

## 인증은 MCP 서버가 자동 처리

OAuth 브라우저 플로우, refresh_token 갱신, 콜백 서버, `auth.db` 저장은 [`session/auth_manager.py`](../../../session/auth_manager.py)와 MCP 서버가 자체 처리합니다. 이 스킬의 책임은 단 둘 — Azure 자격증명(`CLIENT_ID/SECRET/TENANT_ID`)을 `.env`에 깔아두는 것 + 서버 프로세스 띄우기.

## 지원 서버 (6개)

| 서버 | HTTP 포트 | STDIO (Desktop) | HTTP (Code) |
|---|---|---|---|
| `outlook` | 5001 | `mcp_outlook/mcp_server/server_stdio.py` | `mcp_outlook/mcp_server/server_stream.py` |
| `calendar` | 5002 | `mcp_calendar/mcp_server/server_stdio.py` | `mcp_calendar/mcp_server/server_stream.py` |
| `teams` | 5003 | `mcp_teams/mcp_server/server_stdio.py` | `mcp_teams/mcp_server/server_stream.py` |
| `onedrive` | 5004 | `mcp_onedrive/mcp_server/server_stdio.py` | `mcp_onedrive/mcp_server/server_stream.py` |
| `onenote` | 5005 | `mcp_onenote/mcp_server/server_stdio.py` | `mcp_onenote/mcp_server/server_stream.py` |
| `todo` | 5006 | `mcp_todo/mcp_server/server_stdio.py` | `mcp_todo/mcp_server/server_stream.py` |

콜백은 5000 고정. 모든 서버는 `.env`와 `database/auth.db`를 공유 — 1회 인증으로 6개 다 사용.

## 등록 타겟

| 항목 | Claude Code | Claude Desktop |
|---|---|---|
| Config | `~/.claude.json` | `%APPDATA%\Claude\claude_desktop_config.json` |
| Transport | HTTP (`server_stream.py`) | STDIO (`server_stdio.py`) |
| 서버 프로세스 | 별도 백그라운드 실행 (이 스킬 start 모드) | Desktop이 자동 spawn |

**두 config는 공유되지 않음** — 양쪽 다 쓰려면 양쪽 다 등록. 상세는 [references/registration.md](references/registration.md).

## 모드

| 모드 | 동작 |
|---|---|
| **setup** | venv + requirements 설치 + `.env` 부트스트랩 + MCP 등록 |
| **env** | Azure 자격증명만 새로 받아 `.env` 덮어쓰기 (백업 포함) |
| **check** | 토큰 유효성 + Code 등록 + LISTEN 중인 HTTP 서버 Streamable HTTP 8-probe |
| **status** | 환경 + 6개 서버 상태 스냅샷만 출력 |
| **start** | 선택한 HTTP 서버 백그라운드 실행 |
| **stop** | 선택한 HTTP 서버 중지 (포트 점유 프로세스 kill) |
| **restart** | stop → start |

## 인자

- `/ms365` — 상태 표시 + 스마트 진단으로 다음 동작 자동 결정
- `/ms365 setup` / `env` / `check` / `status` — 명시 모드
- `/ms365 start [<server>...]` — 시작 (인자 없으면 AskUserQuestion, `all` 또는 이름 나열)
- `/ms365 stop [<server>...]` / `restart [<server>...]` — 중지/재시작

## 사전 확인 (Windows 절대 경로)

| 항목 | 경로 |
|---|---|
| 프로젝트 루트 | `c:\Users\USER\KR_MS365_mcp` |
| venv Python | `c:\Users\USER\KR_MS365_mcp\venv\Scripts\python.exe` |
| `.env` (공통) | `c:\Users\USER\KR_MS365_mcp\.env` |
| 토큰 DB (공통) | `c:\Users\USER\KR_MS365_mcp\database\auth.db` |
| Claude Desktop config | `%APPDATA%\Claude\claude_desktop_config.json` |
| OAuth 콜백 포트 | `.env`의 `AZURE_REDIRECT_URI` (5000 고정) |

상세 경로/의존성/OAuth flow는 [references/setup_reference.md](references/setup_reference.md).

## 스킬 구성

```
ms365/
├── SKILL.md
├── references/
│   ├── setup_reference.md            ← 경로·의존성·OAuth flow
│   ├── streamable_http_checklist.md  ← Streamable HTTP 8-probe 체크리스트
│   ├── registration.md               ← Code/Desktop 등록 상세
│   ├── examples.md                   ← 시나리오 예시 5개
│   └── caveats.md                    ← 운영 함정·보안 주의
└── scripts/
    ├── verify_setup.py            ← 통합 검증 (venv/.env/토큰/등록/포트)
    ├── streamable_http_probe.py   ← 등록된 HTTP MCP 서버 8-probe
    ├── register_claude_code.py    ← Claude Code (~/.claude.json) HTTP 등록
    ├── register_claude_desktop.py ← Claude Desktop STDIO 등록
    ├── check_token.py             ← AuthManager 토큰 유효성 확인
    ├── health_check.py            ← /health 일괄 probe
    └── stop_server.py             ← 포트 점유 프로세스 종료
```

---

## Instructions

순서대로 실행. Bash 도구 사용, 경로는 Windows 형식. 본 절차에서 자주 등장하는 변수:

```bash
PROJ="c:\Users\USER\KR_MS365_mcp"
VENV_PY="$PROJ\venv\Scripts\python.exe"
SCRIPTS="$PROJ\.claude\skills\ms365\scripts"
```

### 1단계: 상태 스냅샷

```bash
"$VENV_PY" "$SCRIPTS\verify_setup.py" --json
```

venv 부재 시 시스템 Python(`ls /c/Python3*/python.exe`) 으로 폴백. JSON 결과를 한국어 표로 한 번만 요약 (서버별 Code/Desktop/Port + 공통 venv/.env/토큰). **`status` 인자였다면 여기서 종료**.

**경로 무결성 체크**: 서버별 `claude_desktop.path_valid == false` 또는 `matches_project == false`이면 경고.

### 2단계: 스마트 진단 (인자 없을 때 자동 실행)

1단계 JSON을 분석해 3개 카테고리로 분류:

- **`unhealthy_common`**: venv 없음 OR 의존성 누락 OR `.env` 부재/불완전 — 셋업 필수
- **`unregistered`**: 각 서버에 대해 Code 또는 Desktop에 누락된 항목 (예: `outlook: [Desktop]`)
- **`stopped`**: Code에 등록되어 있고 포트가 LISTEN 아닌 서버

#### 2-A. `unhealthy_common`이 있으면

AskUserQuestion: `"지금 셋업할까요?"` — 예 → 3-A, 아니오 → 2-D.

#### 2-B. `unregistered`가 있으면

각 서버별로 누락된 타겟 표 표시 후 `AskUserQuestion` (multiSelect: true) — §AskUserQuestion 규약. 선택 결과는 (서버, 타겟) 쌍 리스트로 보관 후 **3-A-1~3-A-4 모두 skip, 3-A-5만 실행** (venv/의존성/.env는 이미 OK).

선택 → 스크립트 호출 매핑:

```bash
# 선택된 쌍에서 타겟별 서버 CSV 추출
SERVERS_FOR_CODE=$(echo "$PAIRS"    | awk -F: '$2=="code"'    | cut -d: -f1 | paste -sd,)
SERVERS_FOR_DESKTOP=$(echo "$PAIRS" | awk -F: '$2=="desktop"' | cut -d: -f1 | paste -sd,)

[ -n "$SERVERS_FOR_CODE" ]    && "$VENV_PY" "$SCRIPTS\register_claude_code.py"    --servers "$SERVERS_FOR_CODE"
[ -n "$SERVERS_FOR_DESKTOP" ] && "$VENV_PY" "$SCRIPTS\register_claude_desktop.py" --servers "$SERVERS_FOR_DESKTOP"
```

2-B 경로는 Code 등록만 보충된 경우 4단계(백그라운드 실행) 진입 필요. Desktop만 보충됐으면 4단계 skip → 5단계로.

#### 2-C. `stopped` 서버가 있으면

Code 등록 + 포트 LISTEN 아닌 것만 추림. `AskUserQuestion` (multiSelect: true) 로 선택받아 **3-D-1단계**.

#### 2-D. 전부 OK이거나 위에서 다 처리

`✅ 모든 서버 정상 등록 + 실행 중` 출력 후 추가 작업 메뉴 (AskUserQuestion, 선택 안 하면 종료): .env 갱신 / 점검 / 중지·재시작 / 종료.

### 2-E. 명시 인자가 있을 때

1단계 출력 후 2단계는 건너뜀:

| 인자 | 분기 |
|---|---|
| `setup` | 3-A |
| `env` | 3-B |
| `check` | 3-C |
| `status` | 1단계 출력 후 종료 |
| `start [서버...]` | 3-D-1 |
| `stop [서버...]` | 3-D-2 |
| `restart [서버...]` | 3-D-3 |

### 3-A. 셋업 모드

**3-A-0a**. `AskUserQuestion` multiSelect 로 처리할 서버 6개 중 선택 → `{servers}`. 미선택 시 종료.

**3-A-0b**. `AskUserQuestion` multiSelect 로 등록 타겟 선택 (`Claude Code (HTTP)` / `Claude Desktop (STDIO)`) → `{targets}`. 둘 다 미선택 시 종료.

**3-A-1. Windows 시스템 Python 탐색**

```bash
ls /c/Python3*/python.exe /mnt/c/Python3*/python.exe 2>/dev/null
```

여러 개면 사용자 선택, 없으면 직접 입력. `SYSTEM_PYTHON`으로 기억.

**3-A-2. venv 생성 (없으면)**

```bash
if [ ! -f "$PROJ/venv/Scripts/python.exe" ]; then
  "$SYSTEM_PYTHON" -m venv "$PROJ\venv"
fi
```

**3-A-3. 의존성 설치 (타임아웃 600초)**

```bash
"$PROJ\venv\Scripts\pip.exe" install -r "$PROJ\requirements.txt"
```

실패 시 마지막 에러 라인 표시 + 계속 여부 질문.

**3-A-4. `.env` 부트스트랩** — `.env`가 없으면 3-B 자격증명 입력 로직 그대로 실행. 있으면 skip.

**3-A-5. MCP 등록** — `{servers}` 를 CSV 로 결합한 뒤 `{targets}` 에 따라 **두 스크립트를 조건부로** 호출 (Code 또는 Desktop 또는 둘 다):

```bash
SERVERS_CSV=$(IFS=,; echo "${SERVERS[*]}")   # 예: outlook,teams

# Code 포함 시 — 항상 -s user (글로벌 스코프). 모든 Claude Code 세션에서 활성화.
if printf '%s\n' "${TARGETS[@]}" | grep -q "Claude Code"; then
  "$VENV_PY" "$SCRIPTS\register_claude_code.py" --servers "$SERVERS_CSV"
fi

# Desktop 포함 시 — claude_desktop_config.json 갱신 후 Desktop 재시작 필요.
if printf '%s\n' "${TARGETS[@]}" | grep -q "Claude Desktop"; then
  "$VENV_PY" "$SCRIPTS\register_claude_desktop.py" --servers "$SERVERS_CSV"
fi
```

두 스크립트 모두 read-modify-write 로 다른 엔트리(`gmail`, `google_calendar` 등)를 보존. `claude` CLI 가 PATH 에 있으면 `claude mcp add -s user --transport http <name> http://localhost:<port>/mcp` 도 동등. CLI vs 스크립트 비교·디버깅은 [references/registration.md](references/registration.md).

**3-A-6. 다음 단계 결정**
- `{targets}` 에 **Claude Code 포함** → **4단계 (서버 백그라운드 실행)** 필요. HTTP 는 클라이언트가 외부 서버에 연결만 하므로 `server_stream.py` 별도 실행.
- **Desktop 만** 선택 → **5단계 (검증)** 로. Desktop 이 STDIO 를 자동 spawn 하므로 백그라운드 실행 불필요.

### 3-B. `.env` 갱신 모드

**3-B-1. 기존 백업**

```bash
[ -f "$PROJ/.env" ] && cp "$PROJ\.env" "$PROJ\.env.bak.$(date +%Y%m%d_%H%M%S)"
```

**3-B-2. Azure 자격증명 수집** (한 번에 텍스트로):

```
다음 3개 값을 알려주세요:
- AZURE_CLIENT_ID
- AZURE_CLIENT_SECRET
- AZURE_TENANT_ID (UUID 또는 'common')
```

**고정값 (묻지 말 것):** `AZURE_REDIRECT_URI=http://localhost:5000/callback`, `AZURE_SCOPES=offline_access openid`, `AZURE_AUTHORITY=https://login.microsoftonline.com`.

**3-B-3. `.env` 작성** (`Write` 도구). **민감정보 채팅 출력 금지** — 라인 수만 확인.

### 3-C. 점검 모드

**3-C-1. 토큰 점검**

```bash
"$VENV_PY" "$SCRIPTS\check_token.py"
# {"status":"valid","email":"..."} | invalid_or_expired | no_user | error
```

**3-C-2. Streamable HTTP 컴플라이언스** — LISTEN 중인 각 서버에 대해 probe 실행:

```bash
for entry in "outlook 5001" "calendar 5002" "teams 5003" "onedrive 5004" "onenote 5005" "todo 5006"; do
  name=${entry%% *}; port=${entry##* }
  if powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue" 2>/dev/null | grep -q LocalPort; then
    echo "=== $name (port $port) ==="
    "$VENV_PY" "$SCRIPTS\streamable_http_probe.py" --base "http://localhost:$port"
  else
    echo "$name (port $port): 미실행 — probe 건너뜀"
  fi
done
```

합격선: 8/8 → `compliant`, 4~7 → `partial`, 0~3 → `non-compliant`. 비호환 진단은 [references/streamable_http_checklist.md](references/streamable_http_checklist.md).

### 3-D. 서버 운영

**3-D-1. start** — `/ms365 start` (인자 없음) → 1단계의 STOPPED 서버를 `AskUserQuestion` multiSelect 로. `all` 또는 명시 이름은 직접 매핑.

각 선택된 `{name}`, `{port}`:

```bash
if powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue" 2>/dev/null | grep -q LocalPort; then
  echo "{name}: 포트 {port} 이미 사용 중 — skip"
else
  cd "$PROJ"
  nohup ./venv/Scripts/python.exe mcp_{name}/mcp_server/server_stream.py > /tmp/mcp_{name}.log 2>&1 &
  disown
  echo "{name}: launched"
fi
```

전부 띄운 뒤 3초 대기 후 health 확인:

```bash
sleep 3
"$VENV_PY" "$SCRIPTS\health_check.py" --servers <CSV>   # 또는 --servers all
```

health_check.py 출력 형식:
- `outlook   5001  healthy: {"tool_count":N,...}` — 서버 정상
- `teams     5003  unreachable` — 포트 LISTEN 안 됨 (실패)

실패한 서버는 로그 확인: `tail -20 /tmp/mcp_{name}.log`. 운영 함정은 [references/caveats.md](references/caveats.md).

**3-D-2. stop** — `/ms365 stop <server>` 또는 `stop all`:

```bash
"$VENV_PY" "$SCRIPTS\stop_server.py" --servers outlook        # 단일
"$VENV_PY" "$SCRIPTS\stop_server.py" --servers all            # 전체 6개
"$VENV_PY" "$SCRIPTS\stop_server.py" --ports 5001 5002        # 포트 직접 지정도 가능
```

**3-D-3. restart** — `stop {name}` → 1초 대기 → `start {name}`.

### 4단계: 서버 백그라운드 실행 (Code 등록 경로만)

**진입 조건**: 3-A 또는 2-B 경로에서 **Claude Code 등록을 수행한 경우만**. Desktop 전용 경로는 이 단계를 건너뛰고 5단계로 — Desktop이 STDIO 를 자동 spawn 하므로.

`AskUserQuestion`: `"선택한 서버들을 지금 백그라운드로 실행할까요? ({servers})"` — 예/아니오. 예 시 3-D-1과 동일 로직.

### 5단계: 최종 검증

```bash
"$VENV_PY" "$SCRIPTS\verify_setup.py"
```

표 출력 후 모드별 요약 ("✅ 셋업 완료" / ".env 갱신 완료 (백업: ...)" / 토큰+probe 결과 표 / 1단계 상태 표 재출력).

---

## AskUserQuestion 명세

의사결정 지점이므로 본문에 유지. 모드별 question/header/options/multiSelect.

### 2-A: 셋업 여부 (`unhealthy_common`)

```yaml
question: "공통 환경이 불완전합니다: {빠진 항목들}. 지금 셋업할까요?"
header: "셋업 여부"
multiSelect: false
options:
  - label: "예 (3-A로 진행)"
  - label: "아니오 (모드 메뉴로)"
```

### 2-B: 누락된 등록 보충

```yaml
question: "누락된 등록을 추가할까요? (체크한 항목만 추가)"
header: "등록 추가"
multiSelect: true
options:
  - label: "outlook → Claude Desktop (STDIO)"
  - label: "teams → Claude Code (HTTP)"
  - label: "teams → Claude Desktop (STDIO)"
  # … (누락된 (서버, 타겟) 쌍마다 1개)
```

### 2-C: 정지된 HTTP 서버 시작

```yaml
question: "정지 중인 HTTP 서버를 백그라운드로 실행할까요?"
header: "서버 시작"
multiSelect: true
options:
  - label: "outlook (5001)"
  - label: "teams (5003)"
  # …
```

### 2-D: 추가 작업 선택

```yaml
question: "추가로 할 작업이 있나요? (없으면 그냥 종료)"
header: "MS365 MCP"
multiSelect: false
options:
  - label: ".env 갱신 (Azure 자격증명 재입력)"
  - label: "인증 점검 (토큰 + Streamable HTTP probe)"
  - label: "서버 중지 / 재시작"
  - label: "종료"
```

### 3-A-0a: 셋업할 서버 선택

```yaml
question: "셋업할 서버를 모두 고르세요."
header: "서버"
multiSelect: true
options:
  - label: "outlook (메일, HTTP=5001)"
  - label: "calendar (일정, HTTP=5002)"
  - label: "teams (채팅/채널, HTTP=5003)"
  # 4개 초과 시 처음 3개 + "그 외 직접 입력"
```

### 3-A-0b: 등록 타겟 선택

```yaml
question: "등록 타겟을 모두 고르세요."
header: "등록 타겟"
multiSelect: true
options:
  - label: "Claude Code (HTTP)"
  - label: "Claude Desktop (STDIO)"
```

---

## 더 보기

- **시나리오 예시 5개**: [references/examples.md](references/examples.md) — 첫 설치 / 일부 누락 / 모두 OK / start / stop / check
- **등록 상세 (CLI vs JSON, 디버깅)**: [references/registration.md](references/registration.md)
- **운영 함정 · 보안 주의**: [references/caveats.md](references/caveats.md)
- **Streamable HTTP 8-probe 체크리스트**: [references/streamable_http_checklist.md](references/streamable_http_checklist.md)
- **경로·의존성·OAuth flow 상세**: [references/setup_reference.md](references/setup_reference.md)
