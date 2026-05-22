---
name: setup-mcp
description: 프로젝트의 MCP 서버(streamable HTTP) 실행과 클라이언트 등록을 함께 관리. 등록 타겟(Claude Code / VSCode Copilot)을 명시적으로 받고, 발견된 모든 mcp_*/mcp_server/server_stream.py 서버 목록과 각각의 실행/등록 상태를 보여준 뒤 AskUserQuestion으로 사용자가 처리할 서버를 고르게 한다. 선택된 서버는 백그라운드 실행 + 해당 클라이언트 설정에 등록한다.
---

# MCP 서버 실행/등록 관리 스킬

이 스킬은 **`/setup-mcp`**로 호출하며, 다음 흐름을 자동화한다:

1. **타겟 결정** — 어느 클라이언트에 등록할지(Claude Code / VSCode Copilot)
2. 프로젝트의 모든 MCP HTTP 서버 발견 + 실행 상태 + 타겟별 등록 상태 표시
3. `AskUserQuestion`으로 처리할 서버 목록을 사용자가 선택
4. 선택된 서버를 백그라운드 실행 → health check → **선택한 타겟**에 등록

## 사전 확인

- 프로젝트 루트: `/home/kimghw/KR_MS365_mcp`
- venv Python: `/home/kimghw/KR_MS365_mcp/.venv/bin/python`
- 로그 디렉토리: `/tmp/mcp_*.log` (서버별)
- `claude` CLI: PATH 상에 있어야 함

## 스킬 구성 파일

```
setup-mcp/
├── SKILL.md       ← 실행 지침 (이 파일)
└── mcp_status.py  ← 디스커버리/상태 조회 헬퍼 (테이블/JSON 출력)
```

`mcp_status.py`는 다음 정보를 한 번에 산출하므로, SKILL의 디스커버리·실행상태·등록상태 확인은 **모두 이 스크립트 1회 호출로 처리**한다:

- 발견된 서버 목록 (`mcp_*/mcp_server/server_stream.py`)
- 각 서버의 기본 포트
- 프로세스 상태 (STOPPED / RUNNING(pid) / PORT_BUSY(pid))
- Claude Code 등록 상태 (`claude mcp list` 파싱)
- VSCode 등록 상태 (`.vscode/mcp.json` 파싱)

사용:

```bash
# 사람용 표 (양쪽 타겟)
.venv/bin/python .claude/skills/setup-mcp/mcp_status.py

# 사람용 표 (특정 타겟만)
.venv/bin/python .claude/skills/setup-mcp/mcp_status.py --target claude
.venv/bin/python .claude/skills/setup-mcp/mcp_status.py --target vscode

# 기계 처리용 JSON
.venv/bin/python .claude/skills/setup-mcp/mcp_status.py --target claude --json
```

## 인자

### 타겟 플래그 (필수, 1개만)

- `--claude` — Claude Code (CLI + VSCode 확장 공통, `~/.claude.json` 또는 프로젝트 `.mcp.json`)
- `--vscode` — VSCode Copilot Chat (워크스페이스 `.vscode/mcp.json`)
- 둘 다 안 주면 → `AskUserQuestion`으로 타겟부터 물어봄

### 동작 모드 (선택, 1개만)

- (기본) → 서버 목록 표시 + `AskUserQuestion`으로 선택 + 실행/등록
- `--all` → 발견된 모든 서버를 자동으로 실행 + 등록 (질문 생략)
- `--status` → 상태만 보고하고 종료
- `--stop <name>` → 지정 서버 종료 (타겟 플래그 무시)

### 예시

- `/setup-mcp --claude` — Claude Code에 등록할 서버를 골라서 띄움 (인터랙티브)
- `/setup-mcp --vscode` — VSCode `.vscode/mcp.json`에 추가할 서버 선택
- `/setup-mcp --claude --all` — 발견된 모든 서버를 Claude Code에 일괄 등록
- `/setup-mcp --status` — 타겟별 등록 상태와 실행 상태 출력
- `/setup-mcp --stop outlook` — outlook 서버 프로세스 종료

---

## Instructions

아래 단계를 순서대로 자동 실행하세요.

### 1단계: 타겟 결정

인자에서 `--claude` 또는 `--vscode`를 확인.

- 한 쪽이 명시되면 → 그대로 사용 (`target=claude` 또는 `target=vscode`)
- 둘 다 미지정 → 일단 `target=None`으로 두고 2단계 헬퍼를 `--target` 없이 호출해 **양쪽 컬럼 모두 표시**. 그 후 3단계 진입 전에 `AskUserQuestion`으로 묻기:
  - question: `"어디에 MCP 서버를 등록할까요?"`
  - header: `"등록 타겟"`
  - multiSelect: `false`
  - options:
    1. `label: "Claude Code (~/.claude.json)"`, `description: "claude mcp add 명령으로 전역 등록. VSCode 안의 Claude Code 확장도 동일 설정 공유."`
    2. `label: "VSCode Copilot (.vscode/mcp.json)"`, `description: "이 워크스페이스의 GitHub Copilot Chat에만 적용."`
- `--stop <name>`은 등록 작업이 없으므로 타겟 결정 단계를 건너뛰고 곧장 종료 절차로 진행 (다만 등록 제거 여부를 사용자에게 묻는 단계에서 `AskUserQuestion`으로 타겟까지 함께 선택)

### 2단계: 상태 조회 (헬퍼 1회 호출)

디스커버리, 실행 상태, 타겟별 등록 상태는 모두 한 번에 헬퍼 스크립트로 조회한다:

```bash
# 1) 사람용 표 출력 (사용자에게 보여줄 용도)
.venv/bin/python .claude/skills/setup-mcp/mcp_status.py --target ${target}

# 2) 의사결정용 JSON 캡처 (다음 단계에서 파싱)
STATUS_JSON=$(.venv/bin/python .claude/skills/setup-mcp/mcp_status.py --target ${target} --json)
```

JSON 항목 스키마:

```json
{
  "name": "outlook",
  "port": 8091,
  "path": "/home/kimghw/KR_MS365_mcp/mcp_outlook/mcp_server/server_stream.py",
  "process": {"state": "RUNNING|STOPPED|PORT_BUSY", "pid": 123, "cmdline": "..."},
  "claude": "REGISTERED_OK|REGISTERED_FAILED|REGISTERED_UNKNOWN|NOT_REGISTERED",
  "vscode": "REGISTERED_OK|NOT_REGISTERED"
}
```

`claude` 키는 `target=claude` 또는 미지정 시 포함, `vscode`는 `target=vscode` 또는 미지정 시 포함.

발견된 서버가 0개면 → `(no MCP servers discovered)` 메시지가 표에 출력. 이때 **중단**.

`--status` 인자였다면 표 출력 후 여기서 종료.

### 3단계: 사용자에게 서버 선택 질문

**전체 서버 목록**을 옵션으로 제시하고 처리할 항목을 사용자가 직접 고르게 한다 (`--all`이면 전부 선택된 것으로 간주, 6단계 건너뛰고 7단계).

각 서버의 옵션 라벨에 현재 상태를 요약해 보여주어, 사용자가 어느 게 시작/등록이 필요한지 한눈에 보고 선택할 수 있도록 한다.

`AskUserQuestion` 호출:

- question: `"이 중 처리할 MCP 서버를 선택하세요 (타겟: {target})"`
- header: `"MCP 서버"`
- multiSelect: `true`
- options (예시 — 실제 상태에 따라 라벨 동적 구성):
  - label: `"outlook — RUNNING / REGISTERED ✓"`, `description: "추가 액션 불필요 (선택해도 idempotent하게 다시 등록만 수행)"`
  - label: `"calendar — STOPPED / NOT_REGISTERED"`, `description: "8002 포트로 띄우고 {target}에 등록"`
  - label: `"file_handler — STOPPED / NOT_REGISTERED"`, `description: "8001 포트로 띄우고 {target}에 등록"`
  - (PORT_BUSY 상태는 옵션에서 제외 — 자동 처리 위험)

선택된 항목들에 대해 4단계로 진행. 선택 안 한 항목은 건너뜀. 모두 선택 해제 → "선택된 서버 없음 ✓" 출력 후 종료.

### 4단계: 서버 시작 + 타겟별 등록

각 선택된 서버에 대해:

#### 4-A. 서버 시작 (STOPPED인 경우만)

```bash
cd /home/kimghw/KR_MS365_mcp
nohup .venv/bin/python {server_path} > /tmp/mcp_{name}.log 2>&1 &
echo "started pid=$!"
disown
```

3초 대기 후 health check:

```bash
sleep 3
curl -sf http://localhost:{port}/health -w "\n[status=%{http_code}]\n" || echo "HEALTH FAIL"
```

- HTTP 200 + `"status":"healthy"` → 성공
- 실패 → `/tmp/mcp_{name}.log` 마지막 20줄 출력 후 다음 서버로 (등록 단계 건너뜀)

#### 4-B. 타겟에 등록

**타겟이 `claude`인 경우:**

```bash
# REGISTERED_FAILED 상태였다면 제거 후 재등록
claude mcp remove {name} 2>/dev/null || true
claude mcp add --transport http {name} http://localhost:{port}/mcp
claude mcp get {name} 2>&1 | head -5
```

- 저장 위치: `~/.claude.json` (로컬 스코프, 이 프로젝트 entry)
- VSCode 안의 Claude Code 확장도 동일 설정 자동 적용

**타겟이 `vscode`인 경우:**

`.vscode/mcp.json`을 read-modify-write로 갱신 (다른 entry를 보존):

```bash
VSCODE_MCP=/home/kimghw/KR_MS365_mcp/.vscode/mcp.json
mkdir -p "$(dirname $VSCODE_MCP)"
/home/kimghw/KR_MS365_mcp/.venv/bin/python <<PY
import json, os
path = "$VSCODE_MCP"
data = {"servers": {}}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
    if "servers" not in data: data["servers"] = {}
data["servers"]["{name}"] = {
    "type": "http",
    "url": "http://localhost:{port}/mcp"
}
with open(path, "w") as f:
    json.dump(data, f, indent=2)
print(f"updated {path} — servers: {list(data['servers'].keys())}")
PY
```

- 적용 후 VSCode를 reload하거나 Command Palette → `MCP: List Servers`에서 Start 필요할 수 있음

### 5단계: 최종 상태 재확인

2단계 헬퍼를 다시 1회 호출해 표 갱신 후 출력:

```bash
.venv/bin/python .claude/skills/setup-mcp/mcp_status.py --target ${target}
```

```
✅ 등록 완료 (타겟: {target})

| Server        | Port  | Process            | {target}       |
|---------------|-------|--------------------|----------------|
| outlook       | 8091  | RUNNING(pid=12345) | REGISTERED ✓   |
| calendar      | 8002  | RUNNING(pid=12399) | REGISTERED ✓   |
| file_handler  | 8001  | STOPPED            | NOT_REGISTERED |

다음 단계:
- claude 타겟: 새 Claude Code 세션 열기 → /mcp 명령으로 연결 확인
- vscode 타겟: VSCode reload → Command Palette → MCP: List Servers
- 로그: tail -f /tmp/mcp_outlook.log
- 종료: /setup-mcp --stop outlook
```

---

## `--stop` 모드 처리

`--stop <name>`이 주어지면:

1. 1~2단계로 해당 서버의 PID 찾기
2. `kill <pid>` (SIGTERM), 5초 대기
3. 여전히 떠 있으면 `kill -9 <pid>` (SIGKILL)
4. 포트가 해제됐는지 `ss -tlnp | grep :{port}` 로 재확인
5. (선택) `claude mcp remove <name>` 도 함께 묻기 → `AskUserQuestion`

---

## 보안/안정성

- **포트 충돌 시 자동으로 다른 프로세스 죽이지 말 것** — 외부 서비스를 잘못 죽일 수 있음
- **`claude mcp add` 실행 전 `.env` 토큰이 없는 환경변수에는 의존하지 말 것** — 서버 자체가 .env를 로드함
- **nohup + disown 패턴** 사용 — 부모 셸 종료 후에도 서버 유지
- **`/tmp/mcp_*.log` 로그 로테이션 없음** — 장기 실행 시 디스크 증가, 정기 정리 필요 시 사용자에게 안내

---

## Examples

**입력**: `/setup-mcp --claude`

```
1. 타겟: claude (인자에서 결정)

2. 디스커버리: outlook(8091), calendar(8002), file_handler(8001)

3. 상태 표:
   | Server       | Port | Process       | claude         |
   | outlook      | 8091 | RUNNING       | NOT_REGISTERED |
   | calendar     | 8002 | STOPPED       | NOT_REGISTERED |
   | file_handler | 8001 | STOPPED       | NOT_REGISTERED |

4. AskUserQuestion (전체 서버 목록 표시):
   ☑ outlook — RUNNING / NOT_REGISTERED
   ☑ calendar — STOPPED / NOT_REGISTERED
   ☐ file_handler — STOPPED / NOT_REGISTERED

5. 선택된 outlook + calendar 처리:
   - outlook: claude mcp add --transport http outlook http://localhost:8091/mcp ✓
   - calendar: nohup 실행 → health 200 → claude mcp add ... ✓

6. 최종 상태:
   | outlook      | 8091 | RUNNING(...) | REGISTERED ✓ |
   | calendar     | 8002 | RUNNING(...) | REGISTERED ✓ |
```

**입력**: `/setup-mcp --vscode`

```
1. 타겟: vscode

2~3. (위와 동일하지만 등록 상태는 .vscode/mcp.json 기반)

4. AskUserQuestion → outlook 선택

5. .vscode/mcp.json에 outlook entry 추가:
   {
     "servers": {
       "outlook": {"type": "http", "url": "http://localhost:8091/mcp"}
     }
   }

6. VSCode reload → Command Palette → "MCP: List Servers" → outlook 클릭해서 Start
```

**입력**: `/setup-mcp` (타겟 미지정)

```
1. 디스커버리 + 상태 표 출력
2. AskUserQuestion으로 타겟부터 물어봄: Claude Code vs VSCode
3. 사용자가 Claude Code 선택 → --claude 케이스와 동일하게 진행
```

**입력**: `/setup-mcp --claude --all`

```
질문 없이 발견된 모든 서버를 Claude Code에 일괄 등록 + 미실행 서버는 시작까지.
```

**입력**: `/setup-mcp --status`

```
타겟이 없으면 양쪽 다 상태 표시:

타겟: claude
| Server | Port | Process | claude |
...

타겟: vscode
| Server | Port | Process | vscode |
...

(액션 없이 종료)
```

**입력**: `/setup-mcp --stop calendar`

```
calendar 서버 종료 → 포트 8002 해제 확인
→ AskUserQuestion: 등록도 제거할까요? (양쪽 타겟별로 물음)
```

---

## 주의사항

- 새 세션에서만 등록된 MCP 서버가 보임 — 현재 Claude Code 세션에는 즉시 반영 안 됨
- WSL 환경에서 `0.0.0.0:8091`은 Windows host에서도 접근 가능. localhost 외부 노출 원치 않으면 서버 코드에서 `host='127.0.0.1'`로 변경 필요
- `claude mcp list`가 보여주는 `claude.ai *` 항목들은 web 서비스의 원격 MCP이므로 이 스킬과 무관 (건드리지 않음)
