# Claude Code 권한 설정 (Anthropic 공식 기준)

2026년 4월 기준. Claude Code CLI에서 권한을 허용/차단하는 모든 방법 — permission mode, settings.json 의 permissions 블록, 와일드카드 패턴, 설정 우선순위.

## 1. Permission Mode 6종

| 모드 | 자동 허용 범위 | 용도 |
|------|----------------|------|
| `default` | 읽기만 | 민감한 작업, 초기 상태 |
| `acceptEdits` | 읽기 + 파일 편집 + 파일시스템 명령 | 반복적 코드 수정 |
| `plan` | 읽기만 (탐색), 변경 없이 계획 수립 | 복잡한 변경 전 분석 |
| `auto` | 모든 작업 (분류기가 배경에서 안전성 검사) | 신뢰 환경, 긴 작업 |
| `dontAsk` | `allow` 규칙 매칭 도구만 | CI/CD, 제한 환경 |
| `bypassPermissions` | 거의 모든 것 (보호 경로 제외) | **격리된 VM/컨테이너 전용** |

### 모드 진입

**세션 중 전환:**
- `Shift+Tab` — 모드 순환 (default → acceptEdits → plan → …)
- 상태 표시줄에 현재 모드 표시 (예: `⏵⏵ accept edits on`)

**시작 시 플래그:**
```bash
claude --permission-mode acceptEdits
claude --permission-mode plan
claude --permission-mode bypassPermissions
claude --dangerously-skip-permissions   # bypassPermissions 와 동일
```

**settings.json 기본값:**
```json
{ "permissions": { "defaultMode": "acceptEdits" } }
```

## 2. settings.json permissions 블록

```json
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(npm run *)",
      "Read(~/.zshrc)",
      "Edit(/src/**/*.ts)"
    ],
    "ask": [
      "Bash(git push *)"
    ],
    "deny": [
      "WebFetch",
      "Bash(curl *)",
      "Read(./.env)",
      "Edit(./secrets/**)"
    ],
    "additionalDirectories": ["../docs/"],
    "disableBypassPermissionsMode": "disable",
    "skipDangerousModePermissionPrompt": true
  }
}
```

**배열 평가 순서:** `deny` → `ask` → `allow`. 첫 매칭 규칙이 우선, **deny 가 최고 우선순위**.

## 3. 와일드카드 / 패턴 문법

### Bash

```json
"allow": [
  "Bash",                 // 모든 Bash 명령 허용 (Bash(*) 와 동일)
  "Bash(npm run *)",      // npm run <anything>
  "Bash(git * main)",     // git <anything> main
  "Bash(ls *)",           // 공백 경계: "ls -la" O, "lsof" X
  "Bash(ls*)",            // 경계 없음: 둘 다 매칭
  "Bash(git:*)"           // 후행 와일드카드 (Bash(git *) 동일)
]
```

**복합 명령 주의:** `Bash(safe-cmd &&)` 규칙이 있어도 `safe-cmd && other-cmd` 는 자동 허용되지 않는다. 인식 구분자: `&&`, `||`, `;`, `|`, `|&`, `&`, 개행. 승인 시 각 서브 명령마다 별도 규칙 저장 (최대 5개).

### MCP

```json
"allow": [
  "mcp__puppeteer",              // 서버의 모든 도구
  "mcp__puppeteer__*",           // 동일 (명시)
  "mcp__puppeteer__puppeteer_navigate"
]
```

### Read / Edit (gitignore 문법)

```json
"allow": [
  "Read",                 // 모든 파일 읽기
  "Edit",                 // 모든 파일 편집
  "Read(./.env)",         // 현재 디렉토리 기준
  "Read(~/.zshrc)",       // 홈 디렉토리 기준
  "Read(//etc/passwd)",   // 파일시스템 루트 기준
  "Edit(/src/**/*.ts)"    // 프로젝트 루트 기준
]
```

**경로 프리픽스:**
- `//path` — 파일시스템 루트
- `~/path` — 홈
- `/path` — 프로젝트 루트
- `path` 또는 `./path` — 현재 디렉토리

### WebFetch

```json
"allow": [
  "WebFetch(domain:github.com)",
  "WebFetch(domain:*.example.com)"
]
```

## 4. bypassPermissions vs --dangerously-skip-permissions

**둘은 동일하다.** `--dangerously-skip-permissions` 는 `--permission-mode bypassPermissions` 의 CLI 축약형.

**bypassPermissions 특징:**
- 권한 확인 완전 스킵
- 안전 검사 없음 (위험)
- **보호 경로**는 여전히 확인 요청

**진입 전 "정말 하시겠어요?" 확인 프롬프트 스킵:**
```json
{ "permissions": { "skipDangerousModePermissionPrompt": true } }
```

### 보호 경로 (Protected Paths)

bypassPermissions 모드에서도 확인 요청되는 경로:

- **디렉토리:** `.git`, `.vscode`, `.idea`, `.husky`, `.claude` (단, `.claude/commands`, `.claude/agents`, `.claude/skills`, `.claude/worktrees` 는 제외)
- **파일:** `.gitconfig`, `.gitmodules`, `.bashrc`, `.bash_profile`, `.zshrc`, `.zprofile`, `.profile`, `.ripgreprc`, `.mcp.json`, `.claude.json`

## 5. 설정 우선순위

높은 순서부터:

1. **Managed Settings** — 조직 정책, 오버라이드 불가
   - `/etc/claude-code/managed-settings.json` (Linux/WSL)
   - `/Library/Application Support/ClaudeCode/managed-settings.json` (macOS)
   - `C:\Program Files\ClaudeCode\managed-settings.json` (Windows)
   - 드롭인: `/etc/claude-code/managed-settings.d/*.json`
   - MDM: macOS `com.anthropic.claudecode`, Windows `HKLM\SOFTWARE\Policies\ClaudeCode`
2. **CLI 플래그** — 세션 단위 임시 오버라이드
3. **Local Project** — `.claude/settings.local.json` (gitignored, 개인 프로젝트별)
4. **Shared Project** — `.claude/settings.json` (git 커밋, 팀 공유)
5. **User** — `~/.claude/settings.json` (모든 프로젝트 적용, 개인)

**중요:**
- 같은 설정이 여러 레벨에 있으면 더 구체적인(상위) 레벨이 우선
- **Deny 는 어떤 레벨이든 최고 우선** — allow 로 오버라이드 불가
- Managed 는 항상 승리

## 6. settings.local.json vs settings.json vs ~/.claude/settings.json

| 위치 | Git | 범위 | 용도 |
|------|-----|------|------|
| `.claude/settings.local.json` | 제외 | 프로젝트 | 개인 오버라이드, 개인 자격증명 |
| `.claude/settings.json` | 커밋 | 프로젝트 | 팀 공유 규칙 (자격증명 금지) |
| `~/.claude/settings.json` | - | 전역 | 모든 프로젝트 개인 기본값 |

## 7. Auto Mode (Claude Code v2.1.83+)

`auto` 는 `bypassPermissions` 와 다르다. 별도 분류기 모델이 배경에서 각 작업을 검사하여 위험한 작업(예: `curl | bash`, 운영 배포, IAM 변경, main 강제 푸시)을 차단한다.

**요구 사항:**
- v2.1.83 이상
- Max / Team / Enterprise / API 플랜 (Pro 불가)
- 모델: Sonnet 4.6, Opus 4.6, Opus 4.7 (Haiku/claude-3 불가)
- Anthropic API 전용 (Bedrock / Vertex / Foundry 불가)

**신뢰 인프라 선언:**
```json
{
  "autoMode": {
    "environment": [
      "Organization: Acme Corp",
      "Source control: github.example.com/acme-corp",
      "Trusted domains: *.internal.example.com"
    ],
    "allow": ["Staging 배포는 자유 — staging 은 매일 리셋됨"],
    "soft_deny": ["프로덕션 DB 마이그레이션 금지"]
  }
}
```

### bypassPermissions vs auto 비교

| 항목 | bypassPermissions | auto |
|------|-------------------|------|
| 안전 검사 | 없음 | 배경 분류기 |
| 권한 규칙 | 무시 | 먼저 평가 |
| 권장 환경 | 격리 VM/컨테이너만 | 일반 워크스테이션 가능 |
| 인프라 신뢰 선언 | 불가 | `autoMode.environment` |

## 8. "모든 권한 허용" 실전 레시피

### 레시피 A — 가장 안전 (일반 개발, 추천)

```json
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": ["Bash", "Read", "Edit", "WebFetch", "Agent"]
  }
}
```

### 레시피 B — 격리 환경 (컨테이너/VM)

```bash
claude --dangerously-skip-permissions
```

또는:
```json
{
  "permissions": {
    "defaultMode": "bypassPermissions",
    "skipDangerousModePermissionPrompt": true
  }
}
```

### 레시피 C — Auto Mode (신뢰 환경, 자동 안전 검사)

```bash
claude --permission-mode auto
```

### 레시피 D — CI/CD (제한적 자동)

```json
{
  "permissions": {
    "defaultMode": "dontAsk",
    "allow": [
      "Bash(npm *)",
      "Bash(git *)",
      "Read",
      "Edit(/src/**)"
    ]
  }
}
```

## 9. 관리자 정책 (Enterprise)

조직 IT 가 배포하여 개발자 오버라이드를 막는 설정:

```json
{
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "disableAutoMode": "disable",
    "allowManagedPermissionRulesOnly": true
  }
}
```

## 공식 문서

- 권한 설정: https://code.claude.com/docs/en/permissions.md
- Permission Mode: https://code.claude.com/docs/en/permission-modes.md
- Settings: https://code.claude.com/docs/en/settings.md
- How Claude Code Works: https://code.claude.com/docs/en/how-claude-code-works.md
