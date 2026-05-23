---
description: "마크다운 문서 검토 — markdownlint 정적 룰 + LLM 의미·한국어 톤 검토 하이브리드"
allowed-tools: Read, Glob, Grep, Bash
argument-hint: "[file|dir|--staged] (없으면 staged *.md diff)"
---

# /md-review 명령

인자: $ARGUMENTS

## 목적

마크다운 문서를 **하이브리드**로 검토한다 — 외부 lint 도구(markdownlint)로 구조·포맷 룰을 기계적으로 잡고, 그 위에 LLM 이 의미·논리·한국어 톤·기술 정합성을 검토한다. 사용자가 지정한 범위(staged diff / 파일 / 디렉터리)에 대해 카테고리별로 그룹화된 리포트를 출력한다.

## 인자 처리

| 인자 | 동작 |
|---|---|
| `help` / `-h` / `--help` | 사용법 출력 후 종료 |
| 없음 / `--staged` | `git diff --cached --name-only -- '*.md'` 으로 staged 마크다운만 검토 |
| `<파일경로>.md` | 해당 파일 1개 검토 |
| `<디렉터리경로>` | `<dir>/**/*.md` 트리 일괄 검토 |

대상 파일이 0개면 "검토할 마크다운 없음" 출력 후 종료.

## 동작 규칙

### 1. 입력 범위 확정

- staged 모드: `git diff --cached --name-only --diff-filter=ACMR -- '*.md'` 로 변경된 마크다운 목록 수집. 각 파일의 diff 도 `git diff --cached -- <file>` 로 따로 수집해 "이번 변경분에서 도입된 이슈" 를 우선 표시.
- 파일/디렉터리 모드: 해당 경로의 `*.md` 를 `Glob` 으로 수집. 디렉터리는 재귀 (`**/*.md`).
- 후보 파일이 너무 많으면(>20개) 사용자에게 "전체 N개 — 계속?" 한 번 확인.

### 2. 정적 lint 실행 (Bash)

외부 도구 우선순위 (먼저 발견되는 것 사용):

1. `markdownlint-cli2` — `markdownlint-cli2 "<files>" --json` 으로 호출. JSON 출력 파싱.
2. `markdownlint` — `markdownlint <files> --json` 으로 호출.
3. `pymarkdown` — `pymarkdown scan <files>`.
4. 모두 없으면 정적 lint 단계 건너뛰고 LLM 검토만 수행 ("정적 lint 도구 미설치" 메모 표시).

`md2docx` skill 의 [lint.py](.claude/skills/md2docx/lint.py) 가 이미 동일한 우선순위로 markdownlint 를 호출하므로, 가능하면 그것을 재사용 (`python .claude/skills/md2docx/lint.py <file>`). 단, lint.py 는 모호성 검출(MD001/MD003/MD004/MD025/MD029/MD030) 위주이므로 검토 항목 전체를 다 잡진 못한다 — 가능한 경우 raw markdownlint 의 모든 룰을 실행하는 게 우선.

한국어 문서는 MD013(line-length) 을 비활성/완화 권장 — 호출 시 `--disable MD013` 또는 `.markdownlint.json` 에 `{"MD013": false}` 가 있는지 확인.

### 3. LLM 검토 — 카테고리별

각 대상 파일을 `Read` 로 읽고, 다음 카테고리로 검토. 정적 lint 가 이미 잡은 항목은 중복 보고하지 말고, 보강·해석만 추가.

| 카테고리 | 핵심 검토 항목 |
|---|---|
| **구조** | H1 단일성(MD025), heading 단계 연속성(MD001), 섹션 흐름, 도입/결론 균형 |
| **포맷** | bullet/번호 일관성(MD004/MD029), 코드블록 언어 표기(MD040), 표 정렬·열 수(MD055/056/058), 링크 형식, trailing whitespace(MD009) |
| **콘텐츠** | 중복·누락 섹션, 논리 비약, placeholder(TBD/TODO) 잔존, 이미지 alt 누락(MD045), 깨진 링크(MD051~054), 설명적 링크 텍스트(MD059) |
| **기술** | 코드 예제 실제 동작 가능성, CLI 옵션·버전 표기 정확성, 명령어와 본문 일치, 외부 의존성 명시 |
| **포용성** | 편향·차별 언어(alex 류), 색맹 친화 표기, heading-only 내비게이션 가능성 |

### 4. 한국어 톤 검토 (한국어 문서일 때만)

문서 본문에 한글 비중이 30% 이상이면 추가로:

- **조사/어미 띄어쓰기**: "을/를", "은/는", "이/가" 붙여쓰기 일관성
- **백틱 일관성**: 영문 기술 용어(`API`, `JSON`)의 백틱 사용 일관성 — 같은 단어가 어떤 곳은 백틱, 어떤 곳은 평문이면 지적
- **톤 일관성**: 존댓말/평어 혼용 ("~합니다" vs "~한다") 검출
- **외래어 표기**: 서버/써버, 디스플레이/디스플레이, 메시지/메세지 같은 표기 흔들림
- **영문/한글 띄어쓰기**: "API 를" vs "API를" (한국어 정서법은 후자 — 띄지 않음)

## 출력 형식

```
[md-review] 대상: <범위 요약 — staged 3개 / file: foo.md / dir: docs/ (12개)>
[lint-tool] <markdownlint-cli2 v0.x / 미설치>

## 🔴 ERROR (N개)
### 구조
- `docs/intro.md:15` — H1 이 2개 (MD025). "# 개요" 와 "# 시작하기" 중 하나를 H2 로 강등 권장
  수정 제안:
  ```diff
  -# 시작하기
  +## 시작하기
  ```

### 기술
- `docs/api.md:42` — `curl -X POST` 예제의 `Content-Type` 헤더 누락, 본문 설명과 불일치

## 🟡 WARNING (M개)
### 포맷
- `docs/intro.md:8,12,20` — bullet 기호 혼용 (`-` 과 `*`). `-` 로 통일 권장 (MD004)

### 한국어 톤
- `docs/intro.md:25` — "API 를 호출하면" → "API를 호출하면" (조사 붙여쓰기)
- `docs/intro.md:전체` — 존댓말/평어 혼용 — 11곳 평어, 4곳 존댓말. 톤 통일 권장

## 🔵 SUGGESTION (K개)
### 콘텐츠
- `docs/api.md:1-50` — 도입부에 "사용 시점" 문단 추가하면 독자 onboarding 개선

---
통계: error N, warning M, suggestion K
1줄 총평: <전체 품질에 대한 한 줄 평가>
```

severity 카테고리 안에 항목이 없으면 해당 헤더 자체를 출력하지 않는다 (빈 섹션 제거).

## 가이드

- 정적 lint 가 보고한 룰 코드는 출력에 그대로 인용 (MD025 등) — 사용자가 추적 가능하도록.
- 자동 수정 가능한 항목은 `diff` 코드블록으로 제안. 의미·논리 항목은 산문으로만.
- 한 줄 총평은 잘난체하지 말고, "주요 이슈 N건, 톤은 일관됨" 같이 사실 기반.
- LLM 단독 추측("아마 ~일 듯")은 출력하지 마라. 근거가 약하면 SUGGESTION 으로만.
- 외부 lint 도구가 없으면 출력 상단에 명시 — 사용자가 설치 여부를 알 수 있어야 한다.

## 제약

- 파일을 **수정하지 마라**. 리뷰 출력만. 사용자가 따로 요청해야 수정 진행.
- staged 모드에서 diff 가 비어 있으면 즉시 종료 ("staged 마크다운 변경 없음").
- 1개 파일이 500줄을 넘으면 LLM 검토는 가장 변경이 잦은 섹션 또는 사용자가 지정한 라인 범위로 한정 — 무한정 토큰 소모 방지.
