# Progressive Disclosure (점진적 공개)

출처: Anthropic skill-creator / SKILL.md §Progressive Disclosure Design Principle

## 3-레벨 로딩 시스템

| 레벨 | 내용 | 로드 시점 | 크기 제한 |
|------|------|-----------|-----------|
| 1 | Metadata (name + description) | **항상** 컨텍스트에 상주 | ~100 words |
| 2 | SKILL.md 본문 | 스킬이 트리거될 때 | < 5,000 words |
| 3 | Bundled resources | 필요 시 Claude가 로드 | 무제한 (스크립트는 읽지 않고 실행 가능) |

## 핵심 가이드

- SKILL.md 본문은 **500 lines 이하**로 유지 (컨텍스트 팽창 최소화)
- 한계에 근접하면 별도 파일로 분리
- 분리 시 **SKILL.md에서 명시적으로 참조**하고 **언제 읽을지 명확히 서술** (독자가 파일의 존재·시점을 알 수 있어야 함)

**핵심 원칙**: 다중 변형·프레임워크·옵션을 지원할 때는 **핵심 워크플로우와 선택 가이드**만 SKILL.md에 두고, 변형별 세부사항(패턴·예시·설정)은 별도 참고 파일로 분리한다.

---

## 패턴 1: 하이 레벨 가이드 + 참조

```markdown
# PDF Processing

## Quick start
Extract text with pdfplumber: [code example]

## Advanced features
- **Form filling**: See [FORMS.md](FORMS.md)
- **API reference**: See [REFERENCE.md](REFERENCE.md)
- **Examples**: See [EXAMPLES.md](EXAMPLES.md)
```

Claude는 필요할 때만 해당 파일을 로드한다.

## 패턴 2: 도메인별 조직화

여러 도메인을 다루는 스킬은 도메인별로 분리해 불필요한 컨텍스트 로드를 방지:

```
bigquery-skill/
├── SKILL.md           # 개요 + 내비게이션
└── reference/
    ├── finance.md     # 매출, 청구 지표
    ├── sales.md       # 기회, 파이프라인
    ├── product.md     # API 사용, 기능
    └── marketing.md   # 캠페인, 어트리뷰션
```

유저가 sales 관련 질문을 하면 Claude는 `sales.md`만 읽는다.

프레임워크·변형별도 같은 방식:

```
cloud-deploy/
├── SKILL.md           # 워크플로우 + 프로바이더 선택
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
```

## 패턴 3: 조건부 상세 (Conditional details)

기본 콘텐츠를 보여주고, 고급 콘텐츠는 링크:

```markdown
# DOCX Processing

## Creating documents
Use docx-js for new documents. See [DOCX-JS.md](DOCX-JS.md).

## Editing documents
For simple edits, modify the XML directly.

**For tracked changes**: See [REDLINING.md](REDLINING.md)
**For OOXML details**: See [OOXML.md](OOXML.md)
```

## 중요 가이드라인

- **깊이 중첩 금지**: references는 SKILL.md에서 **1단계**만 내려가도록. 모든 reference 파일은 SKILL.md에서 직접 링크되어야 함.
- **긴 레퍼런스 구조화**: 100 lines 초과 파일은 **상단에 목차(TOC)** 를 두어 Claude가 미리보기 때 전체 스코프를 파악할 수 있게 함.
