# Anthropic Skill 개발 레퍼런스

Anthropic이 공개한 **skill-creator** 스킬(원본: `~/.codex/skills/.system/skill-creator/`)에서 추출·정리한 Skill 개발 공식 지침 모음.

## 인덱스

| 파일 | 내용 |
|------|------|
| [anthropic-skill-anatomy.md](anthropic-skill-anatomy.md) | Skill 디렉토리 구조, SKILL.md 구성, 번들 리소스(scripts/references/assets) |
| [anthropic-skill-principles.md](anthropic-skill-principles.md) | 핵심 원칙 3종: Concise is Key, Degrees of Freedom, Validation Integrity |
| [anthropic-progressive-disclosure.md](anthropic-progressive-disclosure.md) | 3-레벨 로딩 시스템과 3가지 공개 패턴 |
| [anthropic-frontmatter.md](anthropic-frontmatter.md) | YAML frontmatter 작성법 (name, description 트리거 규칙) |
| [anthropic-creation-process.md](anthropic-creation-process.md) | 6단계 Skill 제작 프로세스 + 포워드 테스팅 |
| [anthropic-agents-yaml.md](anthropic-agents-yaml.md) | `agents/openai.yaml` (UI 메타데이터) 필드 스펙 |
| [anthropic-permissions.md](anthropic-permissions.md) | Claude Code 권한 체계: permission mode 6종, settings.json 패턴, "모두 허용" 레시피 |

## 원본 출처

- `~/.codex/skills/.system/skill-creator/SKILL.md` (416 lines)
- `~/.codex/skills/.system/skill-creator/references/openai_yaml.md` (50 lines)
- `~/.codex/skills/.system/skill-creator/scripts/` (init_skill.py, quick_validate.py, generate_openai_yaml.py)

## 관련 로컬 스킬

- `.claude/skills/howto-skill/SKILL.md` — 한국어로 현지화된 Skill 작성 지침 (trigger 패턴, 흔한 함정 추가 수록)
