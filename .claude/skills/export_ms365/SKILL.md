---
name: export_ms365
description: KR_MS365_mcp의 MS365 MCP 서버(outlook/calendar/teams/onedrive/onenote/todo/file_handler) 중 1개 이상을 골라 독립 실행 가능한 번들로 잘라내 zip 압축 또는 GitHub 저장소 신규 생성·푸시로 배포한다. 인증(session/callback_server)·공용 런타임(mcp_common/core)·time 서버·설치 스킬(setup_ms365)·도구 계약(param_spec)·의존성 잠금(uv.lock)이 항상 함께 들어가고, 원본 .env 값이 섞였는지 비밀 스캔으로 막으며, Windows Sandbox 백지 환경에서 uv 설치→uv sync→서버 기동까지 실제 검증한다. TRIGGER when 사용자가 /export_ms365 호출, MCP 서버를 남에게 주려고 압축·패키징·번들·배포·저장소 생성 요청, 특정 서버만 떼어내 전달 요청. DO NOT TRIGGER when 서버 설치·기동·중지(→ setup_ms365), 원본 레포 커밋·푸시(→ git).
---

# MS365 MCP 번들 내보내기

`/export_ms365`로 호출. 선택한 서버를 **그 자체로 기동되는 프로젝트**로 잘라내 zip 또는
새 GitHub 저장소로 내보낸다.

## 무엇을 잘라내는가

사용자는 도메인 서버만 고르고, 나머지는 **항상 자동으로 따라간다**. 인증이나 공용
런타임이 빠지면 받은 쪽에서 아무것도 못 하기 때문이다.

| 구분 | 내용 | 선택 여부 |
|---|---|---|
| 도메인 서버 | `mcp_outlook` `mcp_calendar` `mcp_teams` `mcp_onedrive` `mcp_onenote` `mcp_todo` `mcp_file_handler` | **사용자 선택 (1개 이상)** |
| 인증 | `session/` (OAuth·토큰 갱신·auth.db), `callback_server.py` | 항상 |
| 공용 런타임 | `mcp_common/` (스키마 파생·검증·stdio/HTTP 트랜스포트·부트스트랩), `core/` | 항상 |
| 공용 time 서버 | `mcp_time/` + `spec/param_spec/time.yaml` | 항상 |
| 설치·운영 스킬 | `.claude/skills/setup_ms365/` | 항상 |
| 도구 계약 | `spec/param_spec/<선택서버>.yaml` — **런타임 필수** | 선택 서버분 |
| 의존성 잠금 | `uv.lock`, `.python-version`, `requirements.txt` | 항상 |
| 생성물 | `README.md`, `pyproject.toml`(범위 축소), `bundle_manifest.json`, `verify_bundle.py`, `MANIFEST.in`, `database/.gitkeep` | 항상 |

**`uv.lock` 이 재현성의 핵심이다.** 잠금 없이 보내면 받은 쪽이 그날의 최신본을 받아 깨진다 —
실제로 `mcp` 2.x 가 깔려 `Server.list_tools` 가 사라지는 바람에 6개 서버가 전부 기동에 실패한
적이 있다(2026-09-16). 빌드할 때 `uv lock --check` 로 잠금과 `pyproject.toml` 이 맞는지 확인하고,
어긋나면 **빌드를 실패**시킨다. `requirements.txt` 는 uv 를 못 쓰는 사람을 위한 안전망이며
`uv export` 산출물이다. 규약은 [spec/spec_패키지관리.md](../../../spec/spec_패키지관리.md).

번들은 원본과 **같은 상대 경로 구조**를 쓴다. 그래야 `bootstrap` 의 sys.path 삽입,
`param_spec` 의 `spec/param_spec` 해석, `session` 의 `database/auth.db` 경로가 손대지 않아도
성립한다. 레이아웃 근거는 [references/bundle_layout.md](references/bundle_layout.md).

## 절대 나가지 않는 것

`.env` · `database/*.db`(auth.db 포함) · `venv/` · `__pycache__/` · `*.log` · `.git/` ·
`output/` · `downloads/` · 인증서(`*.pem`/`*.pfx`).

빌드 마지막에 **비밀 스캔**이 돈다 — 로컬 `.env` 의 실제 값이 번들 안 어딘가에 문자열로
들어 있으면 번들을 **지우고 실패**시킨다. 자격증명처럼 생긴 리터럴(`AZURE_CLIENT_SECRET=`,
40자 이상 `refresh_token`)도 같이 잡되 `your_..._here` 류 자리표시자는 통과시킨다.

## 인자

- `/export_ms365` — 서버·배포 방식을 물어보고 진행 (기본)
- `/export_ms365 <서버>[,<서버>...]` — 서버 지정, 배포 방식만 질문
- `/export_ms365 all` — 6개 도메인 서버 전부 (`file_handler` 는 명시해야 들어간다)
- `/export_ms365 <서버...> zip` / `github` / `both` — 질문 없이 끝까지
- `/export_ms365 <서버...> --no-sandbox` — 샌드박스 검증 생략

## 스킬 구성

```
export_ms365/
├── SKILL.md
├── scripts/
│   ├── build_bundle.py    ← 스테이징 + 생성물 + 비밀 스캔
│   ├── publish_bundle.py  ← zip / gh repo create --push
│   └── sandbox_test.py    ← .wsb 생성·기동·결과 수집 (호스트 쪽)
├── assets/
│   ├── verify_bundle.py   ← 번들 자체 점검 (번들에 함께 실려 나간다)
│   └── sandbox_runner.ps1 ← 샌드박스 게스트에서 도는 러너
└── references/
    ├── bundle_layout.md   ← 무엇이 왜 들어가는가 / 의존 그래프
    └── sandbox_testing.md ← 샌드박스 검증 절차·함정·디버깅
```

---

## Instructions

경로 변수:

```bash
PROJ="$CLAUDE_PROJECT_DIR"                       # 예: E:\dev\KR_MS365_mcp
S="$PROJ\.claude\skills\export_ms365\scripts"
```

스크립트는 `uv run --frozen python "<스크립트>"` 로 돌린다. `uv` 가 없으면
`"$PROJ\.venv\Scripts\python.exe"`, 그것도 없으면 시스템 Python(`py -3.12`)으로 폴백한다 —
이 스킬의 스크립트는 표준 라이브러리만 쓰므로 어느 쪽이든 돈다.

다만 **`build_bundle.py` 는 `uv` 가 PATH 에 있을 때만 `uv lock --check` 로 잠금 일치를
확인한다.** uv 없이 빌드하면 그 검사가 조용히 빠지므로(매니페스트의
`lock.verified_by_uv` 가 `false`) 배포 전에 한 번은 uv 가 있는 환경에서 빌드할 것.

### 1단계: 내보낼 서버 결정

인자로 왔으면 그대로 쓴다. 없으면 **AskUserQuestion §1**. 미선택이면 종료.

### 2단계: 배포 방식 결정

인자로 왔으면 그대로. 없으면 **AskUserQuestion §2**.

`github` 또는 `both` 라면 이어서:

1. 저장소 이름을 묻는다 (기본 제안: `ms365-mcp-<서버들>`).
2. 공개 여부는 **AskUserQuestion §3**. 기본은 private.
3. `public` 을 골랐다면 — 번들에 인증 코드와 사내 도구 계약이 들어간다는 점을 한 줄로
   알리고 다시 확인받는다. 확인 전에는 `--confirm-public` 을 붙이지 않는다.

### 3단계: 번들 생성

```bash
"$VENV_PY" "$S\build_bundle.py" --servers <CSV|all> --json
```

출력 JSON 의 `bundle_path` 를 `BUNDLE` 로 기억한다. 실패 사유별 대응:

| 실패 | 대응 |
|---|---|
| `비밀이 섞여 번들을 폐기했다` | 위반 목록을 **파일:줄** 만 사용자에게 보여준다. 값은 절대 다시 출력하지 않는다. 원본 코드를 고쳐야 하는 문제이므로 여기서 멈춘다. |
| `pyproject.toml 에서 ... 배열을 찾지 못했다` | 원본 `pyproject.toml` 구조가 바뀐 것이다. `build_bundle.py` 의 `render_pyproject` 를 맞춘다. |
| `디렉터리 없음` / `파일 없음` | 원본에서 그 구성이 사라졌다. `SERVERS`/`COMMON_*` 상수를 현행화한다. |

### 4단계: Windows Sandbox 검증

`--no-sandbox` 인자가 없으면 **기본으로 실행한다**. 먼저 한 줄로 알린다: "백지 Windows 에서
uv 설치→`uv sync`→서버 기동까지 확인합니다. 1~2분 걸립니다."

```bash
"$VENV_PY" "$S\sandbox_test.py" --bundle "$BUNDLE" --timeout 900 --json
```

- 샌드박스는 **동시에 하나만** 뜬다. 이미 실행 중이면 스크립트가 먼저 멈춘다 — 사용자에게
  닫아달라고 요청하고 재시도.
- 게스트 안에서 도는 순서: 번들 복사 → **uv 설치** → **`uv sync --frozen`**(Python 조달 +
  의존성 한 번에) → `uv run --frozen verify_bundle.py --http` (도구 스키마 + 각 서버
  `/health` 200). Python 버전은 번들의 `.python-version` 이 정한다.
- 성공하면 검사 항목을 표로 요약. 실패하면 `artifacts` 의 `verify.log` / `uv-sync.log` /
  `uv-install.log` / `runner.log` 를 읽어 **어느 단계에서 깨졌는지** 짚는다. 진단표는
  [references/sandbox_testing.md](references/sandbox_testing.md).
- 실패 시 3단계로 돌아가 원인을 고친 뒤 다시 검증한다. **실패한 번들을 배포하지 않는다.**

### 5단계: 배포

```bash
# zip
"$VENV_PY" "$S\publish_bundle.py" --bundle "$BUNDLE" --mode zip --json

# GitHub (private)
"$VENV_PY" "$S\publish_bundle.py" --bundle "$BUNDLE" --mode github \
    --repo "<이름>" --visibility private --json

# public 은 사용자 확인을 받은 뒤에만
"$VENV_PY" "$S\publish_bundle.py" --bundle "$BUNDLE" --mode github \
    --repo "<이름>" --visibility public --confirm-public --json
```

`gh` 가 없거나 인증이 안 돼 있으면 스크립트가 그대로 알려준다 — `gh auth login` 을 안내하고
zip 으로 대체할지 묻는다. 같은 이름의 저장소가 이미 있으면 덮어쓰지 않고 멈춘다.

### 6단계: 보고

한 번만 요약한다:

- 번들 경로 / zip 경로 / 저장소 URL
- 포함 서버와 각 도구 개수 (샌드박스 `result.json` 의 `tools` 길이)
- 샌드박스 결과 (`N passed / M failed`, 설치된 Python 버전)
- 받는 쪽이 할 일 3줄: `venv` → `.env` 채우기 → `verify_bundle.py`

---

## AskUserQuestion 명세

### §1 서버 선택

한 질문당 옵션이 4개까지라 **두 질문을 한 번의 호출로** 던진다(7개 서버를 다 담기 위해).
"Other" 는 도구가 자동으로 붙이므로 직접 넣지 않는다.

```yaml
# 질문 1
question: "번들에 넣을 MS365 서버를 고르세요. (인증·공용 런타임·time·설치 스킬은 자동 포함)"
header: "주요 서버"
multiSelect: true
options:
  - label: "6개 전부 (all)"
    description: "outlook·calendar·teams·onedrive·onenote·todo. file_handler 는 빠진다."
  - label: "outlook (메일)"
  - label: "calendar (일정)"
  - label: "teams (채팅·채널)"

# 질문 2
question: "추가로 넣을 서버가 있나요? (없으면 넘어가세요)"
header: "그 외"
multiSelect: true
options:
  - label: "onedrive (파일)"
  - label: "onenote (노트)"
  - label: "todo (할 일)"
  - label: "file_handler (로컬 파일 변환)"
    description: "받는 쪽의 MCP_ALLOWED_PATHS 설정이 필요하다. all 에는 포함되지 않는다."
```

"6개 전부"가 선택되면 나머지 선택은 무시하고 `all` 로 간다(단, 질문 2 의 `file_handler`
가 함께 선택됐다면 `all,file_handler` 로 합친다). 양쪽 다 미선택이면 종료.

### §2 배포 방식

```yaml
question: "어떻게 내보낼까요?"
header: "배포"
multiSelect: false
options:
  - label: "zip 압축 파일"
    description: "output/bundles/<이름>.zip 로 만든다. 받는 쪽은 풀고 README 대로 하면 된다."
  - label: "GitHub 저장소 새로 생성"
    description: "gh repo create 로 새 저장소를 만들고 초기 커밋을 푸시한다."
  - label: "둘 다"
```

### §3 저장소 공개 여부

```yaml
question: "저장소를 어떻게 만들까요?"
header: "공개 범위"
multiSelect: false
options:
  - label: "private (권장)"
    description: "인증 코드와 사내 도구 계약이 들어 있다. 기본값."
  - label: "public"
    description: "누구나 볼 수 있다. 자격증명은 안 들어가지만 코드 전체가 공개된다."
```

---

## 더 보기

- **무엇이 왜 들어가는가 · 의존 그래프**: [references/bundle_layout.md](references/bundle_layout.md)
- **샌드박스 검증 절차 · 함정**: [references/sandbox_testing.md](references/sandbox_testing.md)
- **받은 쪽 설치·기동**: 번들 안의 `.claude/skills/setup_ms365/SKILL.md`
- **사양서**: [spec/spec_번들내보내기.md](../../../spec/spec_번들내보내기.md)
