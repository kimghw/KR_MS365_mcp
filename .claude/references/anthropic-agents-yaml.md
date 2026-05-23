# agents/openai.yaml 스펙

출처: Anthropic skill-creator / references/openai_yaml.md

> **참고**: `agents/openai.yaml`은 제품(harness)이 읽는 **UI 메타데이터** 설정이지 에이전트가 읽는 것이 아니다. 제품별 설정을 `agents/` 폴더에 함께 둘 수 있다.
>
> Claude Code 표준 스킬(`.claude/skills/<name>/`)은 보통 이 파일이 없어도 동작하지만, Codex 호환 스킬 또는 UI 카드 메타데이터가 필요한 경우 사용.

## 전체 예시

```yaml
interface:
  display_name: "Optional user-facing name"
  short_description: "Optional user-facing description"
  icon_small: "./assets/small-400px.png"
  icon_large: "./assets/large-logo.svg"
  brand_color: "#3B82F6"
  default_prompt: "Optional surrounding prompt to use the skill with"

dependencies:
  tools:
    - type: "mcp"
      value: "github"
      description: "GitHub MCP server"
      transport: "streamable_http"
      url: "https://api.githubcopilot.com/mcp/"

policy:
  allow_implicit_invocation: true
```

## 최상위 제약

- 모든 문자열 값은 **따옴표**로 감쌀 것
- 키는 따옴표 없이
- `interface.default_prompt`는 스킬 기반 짧은(대개 1문장) 시작 프롬프트를 생성. 반드시 `$skill-name` 형식으로 스킬을 **명시적으로 멘션** (예: `"Use $skill-name-here to draft a concise weekly status update."`)

## 필드 설명

### interface (UI 표시)

| 필드 | 설명 |
|------|------|
| `display_name` | UI 스킬 목록·칩에 보이는 사람 친화적 제목 |
| `short_description` | UI용 짧은 설명 (25–64자) — 빠른 스캔용 |
| `icon_small` | 작은 아이콘 경로 (skill dir 상대). 기본 `./assets/`, 아이콘은 `assets/` 폴더에 배치 |
| `icon_large` | 큰 로고 경로. 기본 `./assets/` |
| `brand_color` | UI 액센트 용 16진수 색상 (예: 배지) |
| `default_prompt` | 스킬 호출 시 삽입되는 기본 프롬프트 스니펫 |

### dependencies (의존성)

| 필드 | 설명 |
|------|------|
| `tools[].type` | 의존성 카테고리. 현재 `mcp`만 지원 |
| `tools[].value` | 도구·의존성 식별자 |
| `tools[].description` | 사람이 읽는 설명 |
| `tools[].transport` | `type=mcp`일 때의 연결 방식 |
| `tools[].url` | MCP 서버 URL (`type=mcp`) |

### policy (정책)

| 필드 | 설명 |
|------|------|
| `allow_implicit_invocation` | `false`면 스킬이 기본으로 모델 컨텍스트에 주입되지 않음. 단 `$skill`로 명시적 호출은 가능. 기본값 `true`. |

## 생성 방법

스킬을 읽어서 `display_name`, `short_description`, `default_prompt`를 생성한 뒤 결정론적으로 스크립트에 전달:

```bash
scripts/generate_openai_yaml.py <path/to/skill-folder> --interface key=value
```

또는 초기화 시점에:

```bash
scripts/init_skill.py my-skill --path ~/.claude/skills \
  --interface display_name="My Skill" \
  --interface short_description="Does X" \
  --interface default_prompt="Use \$my-skill to do X"
```

- 아이콘·브랜드 컬러 등 기타 옵션 필드는 **유저가 명시적으로 제공할 때만** 포함
- 스킬을 업데이트했을 때 `agents/openai.yaml`이 SKILL.md와 여전히 일치하는지 검증. 불일치 시 재생성.
