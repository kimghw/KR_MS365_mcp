# Skill 구조 (Anatomy)

출처: Anthropic skill-creator / SKILL.md §Anatomy of a Skill

## 디렉토리 구조

```
skill-name/
├── SKILL.md                    # 필수
│   ├── YAML frontmatter (필수: name, description)
│   └── Markdown 본문 (필수)
├── agents/                     # 권장
│   └── openai.yaml             # UI 메타데이터
└── 번들 리소스 (선택)
    ├── scripts/                # 실행 코드 (Python/Bash 등)
    ├── references/             # 컨텍스트 로드용 참고 문서
    └── assets/                 # 산출물에 사용되는 파일 (템플릿·아이콘·폰트)
```

## SKILL.md (필수)

- **Frontmatter (YAML)**: `name`, `description` 2개 필드만. Claude가 트리거 판정 시 읽는 유일한 부분이라 **명확·포괄적** 작성 필수.
- **Body (Markdown)**: 스킬 사용 지침. **트리거된 뒤**에만 로드됨.

## Bundled Resources

### scripts/ — 실행 코드
- **포함 기준**: 같은 코드를 반복 작성하거나 결정론적 신뢰성이 필요할 때
- **예**: `scripts/rotate_pdf.py`
- **장점**: 토큰 효율적, 결정론적. 컨텍스트에 로드 없이 실행 가능
- **주의**: 패치·환경 조정을 위해 Claude가 읽어야 할 수 있음

### references/ — 참고 문서
- **포함 기준**: 작업 중 참조할 문서 (DB 스키마, API 문서, 도메인 지식, 정책)
- **장점**: SKILL.md를 가볍게 유지. 필요할 때만 로드
- **베스트 프랙티스**: 큰 파일(>10k words)이면 SKILL.md에 grep 패턴 포함
- **중복 금지**: 동일 정보를 SKILL.md와 references에 동시에 두지 말 것. 상세·레퍼런스성 내용은 references로 이동, SKILL.md는 핵심 절차·워크플로우만 유지.

### assets/ — 출력물 리소스
- **포함 기준**: 최종 출력물에 사용될 파일 (로고, 템플릿, 폰트, 보일러플레이트)
- **예**: `assets/logo.png`, `assets/slides.pptx`, `assets/frontend-template/`
- **장점**: 컨텍스트에 로드하지 않고 복사·수정하여 사용

## 포함하지 말아야 할 것

Skill에는 **기능에 직접 기여하는 필수 파일만** 포함한다. 다음은 만들지 않음:

- `README.md`
- `INSTALLATION_GUIDE.md`
- `QUICK_REFERENCE.md`
- `CHANGELOG.md`
- 기타 메타·가이드 문서

> Skill은 AI 에이전트가 작업을 수행하는 데 필요한 정보만 담아야 한다. 제작 과정·셋업·유저 문서는 혼란만 유발한다.
