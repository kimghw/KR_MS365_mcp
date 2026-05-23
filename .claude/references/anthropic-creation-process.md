# Skill 제작 프로세스 (6단계)

출처: Anthropic skill-creator / SKILL.md §Skill Creation Process

## 개요

1. 구체적 예시로 스킬 이해하기
2. 재사용 가능한 스킬 콘텐츠(scripts/references/assets) 계획
3. 스킬 초기화 (`init_skill.py` 실행)
4. 스킬 편집 (리소스 구현 + SKILL.md 작성)
5. 스킬 검증 (`quick_validate.py` 실행)
6. 실사용 기반 반복·포워드 테스팅

명확히 적용되지 않는 이유가 없는 한 순서대로 진행.

---

## Step 1: 구체적 예시로 스킬 이해하기

유저 예시 또는 생성된 예시(유저 피드백으로 검증)에서 이해를 얻는다.

**예시 질문 (image-editor 스킬)**:
- "이 스킬은 어떤 기능을 지원해야 하나? 편집, 회전, 그 외?"
- "사용 예시를 몇 가지 들어주실 수 있나요?"
- "'빨간눈 제거' 같은 요청이나 '이미지 회전' 같은 요청을 상상할 수 있는데, 다른 사용 방식이 있을까요?"
- "유저가 어떤 말을 하면 이 스킬이 트리거되어야 하나요?"
- "어디에 만들까요? 선호가 없으면 `~/.claude/skills` (또는 플러그인 스킬 경로)에 둡니다."

유저를 압도하지 않도록 **한 메시지에 너무 많은 질문을 하지 말 것**. 가장 중요한 질문부터 시작, 필요 시 후속 질문.

## Step 2: 재사용 콘텐츠 계획

각 구체적 예시를 분석:
1. 처음부터 수행하는 방법 고려
2. 반복 실행 시 유용할 scripts/references/assets 식별

**예**: `pdf-editor` 스킬 — 매번 같은 회전 코드를 재작성 → `scripts/rotate_pdf.py`로 저장

**예**: `frontend-webapp-builder` — 매번 같은 HTML/React 보일러플레이트 → `assets/hello-world/` 템플릿

**예**: `big-query` — 매번 테이블 스키마를 재발견 → `references/schema.md`

## Step 3: 스킬 초기화

스킬이 존재하지 않을 때만 수행. `init_skill.py` 스크립트가 템플릿 디렉토리를 생성:

```bash
scripts/init_skill.py <skill-name> --path <output-directory> \
  [--resources scripts,references,assets] [--examples]
```

**예시**:

```bash
scripts/init_skill.py my-skill --path ~/.claude/skills
scripts/init_skill.py my-skill --path ~/.claude/skills --resources scripts,references
scripts/init_skill.py my-skill --path ~/work/skills --resources scripts --examples
```

스크립트가 하는 일:
- 지정 경로에 스킬 디렉토리 생성
- frontmatter + TODO 플레이스홀더가 있는 SKILL.md 템플릿 생성
- (옵션) `--resources`에 따라 리소스 디렉토리 생성
- (옵션) `--examples` 시 예시 파일 추가

> Claude Code 로컬 프로젝트에서는 `.claude/skills/<name>/SKILL.md`에 직접 생성해도 무방. init 스크립트는 참고 구조로 활용.

## Step 4: 스킬 편집

**핵심**: 스킬은 **다른 Claude 인스턴스가 사용**하도록 만든다. 다른 Claude에게 유익하고 **비자명한** 정보를 넣어라. 절차적 지식, 도메인 디테일, 재사용 자산이 다른 Claude의 실행을 돕도록.

### 재사용 리소스부터 시작

- `scripts/`, `references/`, `assets/` 먼저 구현
- 유저 입력이 필요할 수 있음 (예: `brand-guidelines` 스킬 → 유저가 브랜드 에셋 제공)
- **스크립트는 반드시 실제 실행해 테스트**. 유사 스크립트가 많으면 대표 샘플만 테스트해도 무방.

### SKILL.md 작성

- **명령형/부정사형** 일관 사용
- frontmatter: [anthropic-frontmatter.md](anthropic-frontmatter.md) 참조
- 본문: 스킬·번들 리소스 사용 지침

## Step 5: 검증

```bash
scripts/quick_validate.py <path/to/skill-folder>
```

YAML frontmatter 포맷, 필수 필드, 네이밍 룰을 검사. 실패 시 수정 후 재실행.

## Step 6: 반복 (Iterate)

실사용 후 피드백 반영. 복잡한 스킬은 **포워드 테스팅** 고려.

### 포워드 테스팅 워크플로우

1. 실제 작업에 스킬 사용
2. 어려움·비효율 관찰
3. SKILL.md 또는 번들 리소스 개선 포인트 식별
4. 변경 구현 후 재테스트
5. 합리적이면 포워드 테스트

### 포워드 테스팅 방법

서브에이전트를 **스킬 테스트 중임을 모르게** 시작. 프롬프트는 **유저의 실제 요청처럼**:

✅ 올바른 프롬프트:
```
Use $skill-x at /path/to/skill-x to solve problem y
```

❌ 잘못된 프롬프트:
```
Review the skill at /path/to/skill-x; pretend a user asks you to...
```

### 포워드 테스팅 결정 규칙

- 기본: **포워드 테스팅 쪽으로 기울여라**
- 다음 경우 유저 승인 요청:
  - 시간이 오래 걸릴 위험
  - 추가 승인이 필요
  - 라이브 프로덕션 시스템 수정
- 이 경우 제안 프롬프트를 보여주고 (1) yes/no, (2) 수정안을 요청

### 포워드 테스팅 주의사항

- 독립 패스를 위해 **fresh thread** 사용
- 유저가 요청하듯 스킬·요청 전달
- **원본 아티팩트** 전달, 결론은 금지
- 기대 답·의도한 수정 노출 금지
- 반복 사이 소스 아티팩트로부터 컨텍스트 재구성
- 서브에이전트 출력·추론·아티팩트 검토
- **반복 사이 디스크에 아티팩트 남기지 말 것** (오염 방지)

> 누설된 컨텍스트가 있어야만 포워드 테스팅이 성공한다면, 스킬이나 테스트 셋업을 먼저 조여야 한다.
