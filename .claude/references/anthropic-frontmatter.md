# YAML Frontmatter 작성법

출처: Anthropic skill-creator / SKILL.md §Update SKILL.md

## 필수 필드

```yaml
---
name: skill-name-here
description: What the skill does + when to use it (all trigger conditions here)
---
```

**다른 필드는 포함하지 말 것.** (단, Codex variant에서는 `metadata:` 서브필드를 허용하지만 Claude Code 표준 스킬에서는 `name`/`description`만 권장.)

## name 필드

- 소문자·숫자·하이픈만 사용. 유저 입력 제목은 하이픈-케이스로 정규화 (예: "Plan Mode" → `plan-mode`)
- **64자 미만**으로 생성
- 짧고 **동사 주도(verb-led)** 구문 선호 (행동을 서술)
- 도구로 네임스페이스를 주는 것이 명확성·트리거에 유리하면 사용 (예: `gh-address-comments`, `linear-address-issue`)
- **Skill 폴더명은 name과 정확히 일치해야 함**

## description 필드 — 가장 중요

`description`은 **스킬의 주요 트리거 메커니즘**이며 Claude가 언제 이 스킬을 사용할지 판단하는 근거다.

### 필수 포함

1. **스킬이 하는 일 (What)**
2. **언제 써야 하는지 (When to use) — 구체적 트리거와 컨텍스트**

### 핵심 규칙

> 모든 "when to use" 정보는 **description에** 담는다. 본문(body)이 아니다.
> 본문은 트리거된 **뒤에만** 로드되므로, 본문에 있는 "When to Use This Skill" 섹션은 Claude의 트리거 판정에 도움이 되지 않는다.

### 예시 (docx skill)

```yaml
description: >
  Comprehensive document creation, editing, and analysis with support for
  tracked changes, comments, formatting preservation, and text extraction.
  Use when Codex needs to work with professional documents (.docx files) for:
  (1) Creating new documents,
  (2) Modifying or editing content,
  (3) Working with tracked changes,
  (4) Adding comments, or any other document tasks
```

### TRIGGER / DO NOT TRIGGER 패턴 (Claude Code 로컬 관행)

로컬 `howto-skill`에서 채택된 패턴 — description 말미에 명시적으로 추가:

```yaml
description: >
  ... what the skill does ...
  TRIGGER when <구체적 조건>.
  DO NOT TRIGGER when <비유사 태스크로 오인되기 쉬운 경우>.
```

이는 유사 스킬 간 오트리거를 줄이는 데 효과적이다.

## 본문(Body) 작성 가이드

- **명령형/부정사형(imperative/infinitive)** 사용 일관
- "When to Use" 섹션 본문에 두지 말 것 → description으로
- 구체 예시 우선, 장황한 설명 회피
