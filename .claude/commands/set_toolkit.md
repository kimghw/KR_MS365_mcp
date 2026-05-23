---
description: "스킬의 사전 작업·전제 조건 안내(CLAUDE.md)와 toolkit 동기화 제외 패턴(.toolignore)을 모아 프로젝트 루트의 같은 이름 파일 marker 구간에 합쳐 쓴다. + OS 감지해서 호출 프로젝트의 .claude/commands/ 에서 부적합 변종(toolkit_link/git ↔ toolkit_sync) 정리. source = .claude/skills/<name>/{CLAUDE.md,.toolignore} + .claude/references/{CLAUDE.md,.toolignore}, target = $CLAUDE_PROJECT_DIR/{CLAUDE.md,.toolignore}."
allowed-tools: Bash, Read, Write, Glob, AskUserQuestion
---

# /set_toolkit 명령

인자: $ARGUMENTS

## 목적

각 스킬은 두 가지 프로젝트 레벨 설정 조각을 가질 수 있다:

1. **`CLAUDE.md`** — 스킬 사용 전 필요한 **사전 작업·전제 조건·주의사항** (예: 외부 CLI 설치, 회사 reference 매핑 선행, 환경 변수 설정, 출력 폴더 관습, 사용자 확인 필요 단계 안내). Claude Code 의 `claudeMd` context 가 자동 로드하므로 컨버세이션 시작 시 인지된다.
2. **`.toolignore`** — 이 스킬을 toolkit 동기화에서 제외하기 위한 ignore 패턴. `/toolkit_sync`, `/toolkit_link`, `/toolkit_git` 이 참조하는 프로젝트 루트 `.toolignore` 의 일부.

추가로, **OS 별 부적합 toolkit command 정리**를 수행한다 — 호출한 프로젝트의 `.claude/commands/` 에서 현재 OS 에 맞지 않는 toolkit 변종을 제거한다 (자세한 절차는 아래 "OS 별 command 정리" 절 참조). **toolkit 원본 레포는 절대 건드리지 않는다.**

`/set_toolkit` 은 두 종류 조각을 source 들(`.claude/skills/<name>/{CLAUDE.md,.toolignore}` + `.claude/references/{CLAUDE.md,.toolignore}`)에서 모아 프로젝트 루트의 같은 이름 파일 marker 구간에 합쳐 쓴다. Source 가 갱신되면 `/set_toolkit` 재호출로 target 도 갱신.

전형적인 source 조각 내용:

**`CLAUDE.md` 조각**
- "이 스킬을 사용하려면 X 가 사전 설치/매핑돼 있어야 한다"
- "변환 결과는 `<cwd>/<template>/<md>/` 폴더로 떨어진다"
- "사용자 확인 없이 진행 금지인 단계 (예: strip 패턴 promote/유지 선택)"
- "옛 규약 호환성 메모, 마이그레이션 안내"

**`.toolignore` 조각**
- 그 스킬 자신을 등록 (예: `skills/md2docx/`)
- 스킬 전용 reference 자산 (예: `references/reference_reg.docx`)

## 경로

본 명령은 두 종류 파일을 다룬다. **각각 별도 source 후보 → 별도 target.**

### `CLAUDE.md` 그룹
- **Target**: `$CLAUDE_PROJECT_DIR/CLAUDE.md`. Claude Code 가 `claudeMd` context 로 자동 로드하는 표준 위치.
- **Source** (있는 것만 모음):
  - `$CLAUDE_PROJECT_DIR/.claude/skills/*/CLAUDE.md` — 스킬 폴더마다 가질 수 있는 스킬 특화 가이드.
  - `$CLAUDE_PROJECT_DIR/.claude/references/CLAUDE.md` — 공통 references (스킬과 무관한 프로젝트 전반 가이드).

### `.toolignore` 그룹
- **Target**: `$CLAUDE_PROJECT_DIR/.toolignore`. `/toolkit_sync`, `/toolkit_link`, `/toolkit_git` 가 참조해 toolkit 동기화 제외 패턴으로 사용.
- **Source** (있는 것만 모음):
  - `$CLAUDE_PROJECT_DIR/.claude/skills/*/.toolignore` — 스킬마다 자기 자신을 등록하거나 관련 자산 패턴.
  - `$CLAUDE_PROJECT_DIR/.claude/references/.toolignore` — 공통 ignore 패턴.

## Marker 구간

두 target 모두 같은 marker 형식을 쓰지만 파일 형식에 맞춰 주석 문자가 다르다.

### CLAUDE.md (markdown HTML 주석)
```
<!-- AUTO-BEGIN /set_toolkit -->
... (자동 생성 — /set_toolkit 호출 시마다 재작성)
<!-- AUTO-END /set_toolkit -->
```

### .toolignore (gitignore-style `#` 주석)
```
# AUTO-BEGIN /set_toolkit
... (자동 생성)
# AUTO-END /set_toolkit
```

공통 규칙:
- target 에 마커가 없으면: target 파일 끝(없으면 생성)에 빈 줄 두 줄 + 마커 + 생성 내용 + 마커 순서로 **append**.
- target 에 마커가 있으면: 두 마커 사이만 새 내용으로 교체. 마커 바깥(앞·뒤) 내용은 그대로.
- 마커 한 쪽만 있으면 (파일 손상): 에러 보고 후 중단. 사용자에게 마커 정리 후 재실행 안내.

## OS 별 command 정리 (호출 프로젝트의 `.claude/commands/` 한정)

본 명령은 **호출한 프로젝트의 `$CLAUDE_PROJECT_DIR/.claude/commands/` 디렉토리**에서, 현재 OS 에 맞지 않는 toolkit 변종 command 파일을 제거한다. **toolkit 원본 레포는 절대 건드리지 않는다** — 정리 대상은 항상 소비자 프로젝트의 `.claude/commands/` 한 곳뿐이다.

### 매핑 (현재 OS → 제거 대상)

| 현재 OS | 제거 대상 (호출 프로젝트의 `.claude/commands/` 에 있을 때만) | 유지 |
|---|---|---|
| **WSL · Linux · macOS** | `toolkit_sync.md` | `toolkit_link.md`, `toolkit_git.md` |
| **Windows** (MINGW · MSYS · Cygwin · native Git Bash) | `toolkit_link.md`, `toolkit_git.md` | `toolkit_sync.md` |
| **unknown** | (정리하지 않음 — OS 미감지 시 안전 기본값) | 모두 유지 |

근거: `toolkit_link` / `toolkit_git` 은 POSIX 심볼릭 링크와 `~/.claude/toolkit_dir`·`find`·`realpath` 등 POSIX 도구에 의존한다. Windows native 환경에서는 안전하지 않거나 동작하지 않으므로 그쪽에서는 `toolkit_sync` 만 남긴다. 반대로 WSL/Linux/macOS 에서는 심볼릭 기반 워크플로(`toolkit_link` + `toolkit_git`)가 권장되므로 복사 변종 `toolkit_sync` 만 정리한다.

### OS 감지

```
UNAME="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME" in
  Linux*)
    if grep -qi microsoft /proc/version 2>/dev/null; then OS_KIND="wsl";
    else OS_KIND="linux"; fi ;;
  Darwin*)              OS_KIND="darwin" ;;
  MINGW*|MSYS*|CYGWIN*) OS_KIND="win_bash" ;;
  *)                    OS_KIND="unknown" ;;
esac
```

### 정리 절차 (모든 정리 호출에 공통)

1. **타깃 디렉토리 확정**: `TARGET_DIR="$CLAUDE_PROJECT_DIR/.claude/commands"`. 없으면 정리 단계 skip (보고만).
2. **toolkit 원본 보호 가드**: `realpath "$CLAUDE_PROJECT_DIR"` 가 toolkit 원본 레포(`<dir>/.project_id` 가 toolkit ID `5a7a5dc046eda268d64df3af621de2c1640f0d66b0abe71fc2509f5e9562b319` 와 일치) 이면 **즉시 중단**하고 "`[skip] 호출 디렉토리가 toolkit 원본 — command 정리는 소비자 프로젝트에서만 수행됩니다`" 보고. 원본 파괴 방지.
3. **`.toolignore` 우선**: 위 매핑의 제거 대상 파일 경로(`commands/toolkit_*.md`) 가 호출 프로젝트의 `.toolignore` 에 명시적으로 매칭되면 **사용자 의도적 유지**로 간주하고 정리에서 제외 (보고에 `[kept by .toolignore]` 표시).
4. **실재 확인**: 제거 대상 각각에 대해 `test -f "$TARGET_DIR/<file>"` 로 존재 확인. 없으면 그 항목은 건너뜀 (이미 없는 상태가 정상이므로 silent skip 또는 `[absent]` 한 줄 보고).
5. **사전 계획 출력**: 제거 예정 파일 목록을 표로 표시.
   ```
   [os-prune] OS_KIND=<os>  TARGET_DIR=<path>
     - toolkit_sync.md           (제거 예정)
     - toolkit_link.md           (유지 — .toolignore 매칭)
     - toolkit_git.md            (이미 없음, skip)
   ```
6. **사용자 확인** (제거 대상이 1개 이상일 때): `AskUserQuestion` 으로 한 번 승인. 옵션:
   - `제거 진행 (권장)`
   - `이번 호출만 건너뛰기`
   - `중단`
   `--dry-run` 모드이면 확인 없이 계획만 표시하고 실제 `rm` 은 수행하지 않는다.
7. **실행**: 승인 받으면 각 파일에 대해 `rm -f "$TARGET_DIR/<file>"`. 심볼릭 링크라면 링크 자체만 제거 (원본 보존).
8. **사후 보고**: `[os-prune] 제거 N · 유지 M · 부재 K` 한 줄 + 각 파일 결과 한 줄씩.

### 정리는 언제 실행되는가

- **기본 동작 (인자 없음)**: CLAUDE.md / `.toolignore` 그룹 갱신 **전에** 사전 단계로 자동 수행.
- **`os-prune` 인자 단독**: 정리만 수행하고 CLAUDE.md / `.toolignore` 그룹은 건드리지 않음.
- **`--skip-os-prune` 플래그**: 기본 동작에서 OS 정리 단계만 생략 (CLAUDE.md / `.toolignore` 만 갱신).
- **`claudemd` / `toolignore` 단독 인자**: 그룹 갱신만 수행 (OS 정리 자동 수행하지 않음). 필요하면 `os-prune` 별도 호출.
- **`--dry-run`**: 정리도 미리보기만, 실제 `rm` 없음.

## 인자 동작

### 0. `help` / `-h` / `--help`

본 명령 인자 목록·동작 요약만 출력하고 종료 (파일 변경 없음).

```
/set_toolkit [인자]

  본 명령은 두 종류 source 조각을 두 target 으로 합쳐 쓰고, 추가로 호출 프로젝트의
  .claude/commands/ 에서 현재 OS 에 맞지 않는 toolkit 변종을 정리한다:
    A) CLAUDE.md  그룹: .claude/skills/<name>/CLAUDE.md  + .claude/references/CLAUDE.md
                       → $CLAUDE_PROJECT_DIR/CLAUDE.md   (markdown HTML 주석 marker)
    B) .toolignore 그룹: .claude/skills/<name>/.toolignore + .claude/references/.toolignore
                       → $CLAUDE_PROJECT_DIR/.toolignore (gitignore '#' 주석 marker)
    C) OS 정리       : WSL/Linux/macOS → toolkit_sync.md 제거
                       Windows         → toolkit_link.md, toolkit_git.md 제거
                       (호출 프로젝트의 .claude/commands/ 만 대상, toolkit 원본은 보호)

  marker 구간 사이만 자동 갱신. 마커 바깥의 사용자 수동 내용은 그대로 보존.

  (없음)             OS 정리 → 두 그룹 모두 갱신.
  <skill_name>       OS 정리 → 그 스킬만 source 로 사용 (양 그룹 모두). references 조각 포함.
  claudemd           CLAUDE.md 그룹만 갱신 (.toolignore · OS 정리 건드리지 않음).
  toolignore         .toolignore 그룹만 갱신 (CLAUDE.md · OS 정리 건드리지 않음).
  os-prune           OS 정리만 수행 (CLAUDE.md / .toolignore 그룹은 건드리지 않음).
  --skip-os-prune    기본 동작에서 OS 정리만 생략.
  --dry-run          실제 쓰기 · 제거 없이 두 그룹 본문 + OS 정리 계획 미리보기만 출력.
                     다른 인자와 조합 가능.
  help|-h|--help     이 도움말.

source / target / marker:
  CLAUDE.md  : <!-- AUTO-BEGIN /set_toolkit --> ... <!-- AUTO-END /set_toolkit -->
  .toolignore: # AUTO-BEGIN /set_toolkit ... # AUTO-END /set_toolkit

OS 정리 안전 가드:
  - 대상은 항상 $CLAUDE_PROJECT_DIR/.claude/commands/ 한 곳뿐 (toolkit 원본은 보호).
  - 호출 디렉토리가 toolkit 원본(.project_id 가 toolkit ID 와 일치)이면 정리 자동 중단.
  - .toolignore 에 명시된 toolkit_* 파일은 사용자 의도로 간주하고 정리에서 제외.
  - 제거 대상이 1개 이상이면 AskUserQuestion 으로 한 번 확인 후 진행.
```

### 1. 인자 없음 (기본 동작 — OS 정리 → 두 그룹 모두 갱신)

**0단계 — OS 정리 (사전)**: `--skip-os-prune` 가 없으면, 위 "OS 별 command 정리" 절의 절차를 먼저 수행한다. 사용자가 "이번 호출만 건너뛰기" 를 선택하거나 OS_KIND 가 `unknown` 이면 정리 단계만 skip 하고 그룹 갱신은 계속 진행. 호출 디렉토리가 toolkit 원본이면 정리는 자동 중단되지만 그룹 갱신은 동일하게 진행한다.

그 다음 CLAUDE.md 그룹과 `.toolignore` 그룹을 **각각 독립적으로** 같은 절차로 처리.

1. **Source 수집** (그룹별):
   - **CLAUDE.md 그룹**:
     - `glob $CLAUDE_PROJECT_DIR/.claude/skills/*/CLAUDE.md` (정렬: 알파벳 순).
     - `$CLAUDE_PROJECT_DIR/.claude/references/CLAUDE.md` 가 파일로 존재하면 추가.
   - **.toolignore 그룹**:
     - `glob $CLAUDE_PROJECT_DIR/.claude/skills/*/.toolignore` (정렬: 알파벳 순).
     - `$CLAUDE_PROJECT_DIR/.claude/references/.toolignore` 가 파일로 존재하면 추가.
   - 그룹별 source 가 하나도 없으면 그 그룹은 skip 하고 다른 그룹만 진행 (둘 다 없으면 `"수집된 source 없음 — 작성 중단"` 후 종료).

2. **본문 생성** (그룹별, marker 사이에 들어갈 텍스트):

   **CLAUDE.md 그룹** — markdown 형식. 각 source path 는 `##` heading 으로:
   ```
   > 이 구간은 /set_toolkit 이 자동 생성합니다. 직접 편집하지 말고 source 파일을
   > 편집한 뒤 /set_toolkit 을 다시 실행하세요.
   > 마지막 갱신: <ISO 8601 timestamp>

   ## .claude/skills/<name>/CLAUDE.md

   <스킬 1 의 CLAUDE.md 내용 그대로>

   ## .claude/references/CLAUDE.md

   <references 의 CLAUDE.md 내용 그대로>
   ```

   **.toolignore 그룹** — gitignore 형식. 각 source path 는 `#` 주석 한 줄로 구분:
   ```
   # 이 구간은 /set_toolkit 이 자동 생성. 직접 편집 금지.
   # 마지막 갱신: <ISO 8601 timestamp>

   # --- .claude/skills/<name>/.toolignore ---
   <스킬 1 의 .toolignore 내용 그대로>

   # --- .claude/references/.toolignore ---
   <references 의 .toolignore 내용 그대로>
   ```

   - **빈 source(0B) 는 collection 단계에서 스킵** — 헤더도 출력하지 않는다. 의도: 아직 채워지지 않은 placeholder 파일이 target 에 노이즈 헤더만 남기는 상황을 방지. `.claude/skills/<name>/CLAUDE.md` 또는 `.claude/references/CLAUDE.md` 가 존재하지만 빈 파일이면 그 source 는 없는 셈치고 다음으로 넘긴다. effective source 가 0개로 떨어지면 그 그룹은 skip (인자 없음 동작의 step 1 과 동일).
   - source 사이는 빈 줄 한 줄로 분리.

3. **Target 갱신** (그룹별, 마커 형식만 다름):
   - target 존재 + 마커 양쪽 모두 존재 → 마커 사이만 교체.
   - target 존재 + 마커 없음 → 파일 끝에 빈 줄 두 줄 + 마커 영역 append.
   - target 존재 + 마커 한쪽만 있음 → 에러 출력 후 그 그룹만 중단 (다른 그룹은 계속).
   - target 없음 → 새 파일로 생성.
     - `CLAUDE.md`: 첫 줄은 `# CLAUDE.md` heading, 그 다음 빈 줄, marker 영역.
     - `.toolignore`: 파일 헤더 주석 (`# .toolignore — 자동 생성 영역은 marker 사이`) 후 빈 줄, marker 영역.

4. **보고** (그룹별 한 묶음):
   ```
   [set_toolkit] CLAUDE.md
     target = <target 경로>
     sources = N개
       - .claude/skills/<name>/CLAUDE.md (<bytes>B)
       - .claude/references/CLAUDE.md (<bytes>B)
     marker 갱신: <updated|appended|created>
     결과 크기: <bytes>

   [set_toolkit] .toolignore
     target = <target 경로>
     sources = M개
       - .claude/skills/<name>/.toolignore (<bytes>B)
     marker 갱신: <updated|appended|created>
     결과 크기: <bytes>
   ```

### 2. `<skill_name>` (단일 스킬)

1. `$CLAUDE_PROJECT_DIR/.claude/skills/<skill_name>/` 존재 확인. 없으면:
   - 사용 가능한 스킬 목록 출력 후 종료.
2. **OS 정리 (사전)** 는 인자 없음 동작과 동일하게 수행 (`--skip-os-prune` 미지정 시).
3. 그 한 스킬의 `CLAUDE.md` + `.toolignore` (있는 것만) 와 references 의 조각들 (있으면) 만 source 로 사용. 나머지 절차는 인자 없음 동작과 동일.

### 3. `claudemd` / `toolignore` (그룹 선택)

- `claudemd`: CLAUDE.md 그룹만 갱신. `.toolignore` 는 건드리지 않음.
- `toolignore`: `.toolignore` 그룹만 갱신. `CLAUDE.md` 는 건드리지 않음.
- **OS 정리 자동 수행 안 함**. 정리가 필요하면 `os-prune` 을 별도 호출하거나 인자 없는 기본 동작을 쓴다.
- 다른 인자와 조합 가능 (예: `/set_toolkit md2docx toolignore` = md2docx 스킬의 `.toolignore` 만 갱신).

### 4. `os-prune` (OS 정리만 수행)

- 위 "OS 별 command 정리" 절의 절차만 단독 실행.
- CLAUDE.md / `.toolignore` 그룹은 일절 건드리지 않는다.
- `--dry-run` 과 조합 가능 (계획만 출력, 실제 `rm` 없음).
- 대상은 항상 호출한 프로젝트의 `$CLAUDE_PROJECT_DIR/.claude/commands/` 한 곳뿐. toolkit 원본은 보호 가드로 자동 차단.

### 5. `--skip-os-prune` (OS 정리 단계만 생략)

- 기본 동작 / `<skill_name>` 동작에서 OS 정리 사전 단계만 건너뛴다.
- CLAUDE.md / `.toolignore` 그룹 갱신은 평소처럼 수행.
- `claudemd` / `toolignore` 단독 인자에는 영향 없음 (어차피 OS 정리 자동 수행 안 함).

### 6. `--dry-run`

- 위 절차에서 **3. Target 갱신** 단계와 **OS 정리의 실제 `rm`** 단계를 skip.
- 대신 두 그룹 (또는 선택된 그룹) 의 "marker 영역에 들어갈 본문" 과 OS 정리 계획을 stdout 에 그대로 출력.
- target 파일·command 파일 자체는 건드리지 않음.

## 안전 정책

- 두 target 모두 marker 바깥 내용은 절대 수정 금지. 마커가 한 쪽만 발견되면 그 그룹만 중단 (다른 그룹은 계속).
- source 파일은 읽기 전용 — 본 명령은 source 를 절대 수정하지 않는다.
- `--dry-run` 외의 모든 동작은 실제 쓰기 전 본문 stat (`source 개수`, `합산 bytes`) 을 그룹별로 한 줄씩 보고. 큰 변경 (target 크기 변화 > 10KB) 은 `AskUserQuestion` 으로 한 번 확인 후 진행.
- `.toolignore` 갱신은 `/toolkit_sync`, `/toolkit_link`, `/toolkit_git` 의 차후 동작에 즉시 영향. 패턴이 잘못되어 의도치 않은 파일이 제외되면 즉시 source 수정 후 재호출.
- **OS 정리는 호출 프로젝트의 `.claude/commands/` 한 곳만 대상**. toolkit 원본 레포(`.project_id` 가 toolkit ID 와 일치)에서 호출되면 정리 자동 중단. 원본 command 파일은 어떤 경우에도 본 명령으로 삭제되지 않는다.
- 제거 대상이 1개 이상이면 `AskUserQuestion` 으로 한 번 확인 후 진행. 사용자가 의도적으로 유지하려는 경우 호출 프로젝트의 `.toolignore` 에 `commands/toolkit_<name>.md` 패턴을 등록하면 정리에서 제외된다.

## 예시

- `/set_toolkit` — OS 정리 + 모든 스킬 + references 의 CLAUDE.md 와 `.toolignore` **둘 다** 갱신.
- `/set_toolkit md2docx` — OS 정리 + md2docx 스킬의 CLAUDE.md + `.toolignore` (+ references 의 조각, 있으면) 만 사용해 두 target 갱신.
- `/set_toolkit claudemd` — CLAUDE.md 그룹만 갱신 (OS 정리 자동 수행 안 함).
- `/set_toolkit toolignore` — `.toolignore` 그룹만 갱신 (OS 정리 자동 수행 안 함).
- `/set_toolkit md2docx toolignore` — md2docx 스킬의 `.toolignore` 만 갱신.
- `/set_toolkit os-prune` — 호출 프로젝트의 `.claude/commands/` 에서 OS 부적합 toolkit 변종만 정리 (그룹 갱신 없음).
- `/set_toolkit --skip-os-prune` — OS 정리 생략 + 두 그룹 갱신.
- `/set_toolkit --dry-run` — 변경 없이 두 그룹 본문 + OS 정리 계획 미리보기만.
- `/set_toolkit os-prune --dry-run` — OS 정리 계획만 미리보기.
- `/set_toolkit help` — 사용법 출력.
