# 변경 시 서브 에이전트에서 readme.md 작성

## OneNote DB 관리 (onenote_items 테이블)

### 테이블 위치
- `database/onenote.db` > `onenote_items`, `onenote_page_summaries`, `onenote_page_changes` 테이블

### 컬럼 구조
| 컬럼 | 설명 |
|------|------|
| user_id | 사용자 이메일 |
| item_type | `'section'` 또는 `'page'` |
| item_id | 페이지/섹션 고유 ID (**UNIQUE** — upsert 기준) |
| item_name | 페이지 제목 또는 섹션 이름 (빈 문자열로 upsert 시 기존 값 유지) |
| notebook_id | 소속 노트북 ID |
| notebook_name | 소속 노트북 이름 |
| section_id | 소속 섹션 ID |
| section_name | 소속 섹션 이름 |
| web_url | OneNote 웹 브라우저 URL |
| last_accessed | 최근 접근 시각 |
| created_at / updated_at | 생성/수정 시각 |

- 이름 기반 UNIQUE 제약은 없음 (다른 섹션의 동명 페이지 허용 — 구버전 DB는 초기화 시 자동 마이그레이션)

### DB 저장 시점
- **페이지 생성 시**: `create_page()` 호출 후 자동으로 DB에 저장
- **sync_db 호출 시**: `/me/onenote/pages`로 전체 페이지를 조회하여 DB 동기화
  - notebook_id, notebook_name, section_id, section_name, web_url 모두 포함
  - 5000개 제한(403) 회피를 위해 섹션별이 아닌 **전체 페이지 기준**으로 조회

### Graph API 호출
- `list_pages`에서 `$expand=parentSection($expand=parentNotebook)` 사용
- 한 번의 API 호출로 페이지 + 섹션 + 노트북 정보를 모두 가져옴

### 주요 파일
- `mcp_onenote/onenote_db_service.py` — DB 저장/조회/동기화
- `mcp_onenote/onenote_service.py` — Facade (create_page, sync_db)
- `mcp_onenote/graph_onenote_client.py` — Graph API 호출
- `mcp_onenote/onenote_types.py` — PageInfo 데이터 모델

# API·툴 파라미터 — "파라미터 리스트(param_spec)" 하나로 관리

API/툴의 파라미터를 코드·스키마·핸들러에서 각각 파싱하지 않는다. **원하는 파라미터·옵션·
필수/선택·타입을 리스트 1개로 선언**하고, `inputSchema`·핸들러 인자·기본값은 전부 그
리스트에서 파생시킨다.

## 리스트 위치 (SSOT)

| 파일 | 성격 | 규칙 |
|------|------|------|
| `mcp_editor/<프로필>/param_spec.yaml` | **손으로 쓰는 원본** | 사람이 확정한 파라미터 계약. 자동 생성기가 덮어쓰지 않는다. |
| `mcp_editor/<프로필>/tool_definition_templates.yaml` | 자동 생성 | AST 시그니처 추출 결과 + param_spec 적용 결과. 직접 편집 금지. |

- `param_spec.yaml` 이 없는 프로필은 기존 동작(AST 자동 추출) 그대로 둔다. 필요해지는
  시점에만 만든다.
- 파라미터 이야기를 사양서에 적을 때도 **같은 열 이름**의 표로 적는다(두 벌 어휘 금지).

## 리스트 한 줄의 필드

```yaml
tools:
  - name: calendar_view            # MCP 도구 이름
    params:
      - name: user_email           # 필수 — 서비스 함수 시그니처의 파라미터 이름
        type: string               # 필수 — string|integer|number|boolean|array|object
        required: true             # 필수 — inputSchema.required 포함 여부
        expose: tool               # 필수 — tool | internal | hidden
        description: 조회할 사용자의 이메일 주소   # 필수 — 에이전트가 읽는 설명
      - name: top
        type: integer
        required: false
        expose: tool
        default: 50                # 선택 — required:false 일 때의 기본값
        description: 최대 결과 수
      - name: orderby
        type: string
        required: false
        expose: tool
        enum: [start, subject]     # 선택 — 허용 옵션 목록
        description: 정렬 기준
      - name: select_params
        type: object
        required: false
        expose: internal           # 툴 입력으로 노출하지 않고 서버가 고정값 주입
        default: null
        targetParam: select_params # 선택 — 서비스 인자 이름이 다를 때 매핑
        description: 내부 조회 필드 지정
```

- `expose` 의미 — `tool`: `inputSchema.properties` 에 노출 / `internal`:
  `mcp_service_factors` 로 나가 서버가 값을 주입(`default` 필수) / `hidden`: 호출에
  쓰지 않음(시그니처 기본값에 맡김).
- `order` (선택, 정수): 에디터·스키마에서의 표시 순서.

## 적용 규칙

- **필수/선택 일관성**: `required: true` 인데 `default` 가 있으면 오류로 보고하고 고치기
  전까지 생성하지 않는다.
- **boolean 은 boolean 으로 적는다**. `enabled`/`disabled` 문자열 enum 변환은 리스트가
  아니라 [mcp_editor/service_registry/schema_normalize.py](mcp_editor/service_registry/schema_normalize.py)
  가 담당한다 — 리스트에 직접 enum 을 적어 두면 변환이 두 벌이 되어 드리프트한다.
- **정규화 진입점은 하나**: 스키마 형태 보정·`required` 정규화·boolean 변환은 전부
  `schema_normalize.py` 를 쓴다. 새 파싱/정규화 함수를 만들지 않는다. 이 모듈을 고치면
  런타임 사본인 `mcp_editor/jinja/python/_schema_helpers.jinja2` 도 같이 고친다.
- **충돌 시 리스트가 이긴다**: AST 로 뽑은 시그니처와 `param_spec.yaml` 이 다르면
  리스트를 따르되, 타입·필수 여부가 어긋나면 **조용히 덮지 말고 차이를 보고**한다.
- **누락 처리**: 시그니처에 있는데 리스트에 없는 파라미터가 필수면 오류, 선택이면
  `expose: hidden` 으로 간주한다. 리스트에만 있고 시그니처에 없으면 오류.
- **추가·변경 순서**: 파라미터를 늘리거나 필수/선택을 바꿀 때는 `param_spec.yaml` 을 먼저
  고치고 생성기를 돌린다. 생성물(`tool_definition_templates.yaml`, 서버 코드)을 손으로
  고쳐 앞서 나가지 않는다.

# 파일 크기 상한 — 1,200줄 초과 금지·900줄 이하 권고

- app 계층 소스 파일(`app/**/*.py`·`app/static/**/*.js`)은 **1,200줄 초과 금지**,
  900줄 이하 권고(2026-08-09 사용자 확정 — vendor 는 독립 코드라 권고만 적용). 초과가
  예상되면 기능 추가 전에 분할한다.
- 분할 방식: 관문 파일 유지(외부가 보는 모듈 이름 불변 — 이동 심볼은 관문에서 재수출,
  새 관문 신설 금지) + 내부 헬퍼의 위성 모듈 이동. 여러 위성이 공유하는 커널은 비공개
  모듈로 내려 순환 import 를 차단하고, 테스트가 monkeypatch 하는 심볼은 정의 모듈에
  두고 사용처는 모듈 속성 접근(`core.X`)으로 호출한다. 원본은
  [spec/spec_아키텍처.md](spec/spec_아키텍처.md) ②.

# 지식저장소 <cwd>/references — 모듈과 무관한 재사용 지식

- 대상: 외부 시스템의 동작 방식·제약(API 스펙, 스크래핑 방법, 한도 등). 프로젝트 내부 구현
  이력은 사양서에 두고 여기 중복하지 않는다.
- 갱신 트리거: 외부 시스템에 대해 새로 알아낸 사실이 있으면 **답변 완료 시점**에 반영한다.
  관련 파일이 이미 있으면 그 파일에 추가한다.
- 사용자 요청 시 관련 자료가 있는지 우선적으로 참조한다.

# 문서 갱신 검토 (서브에이전트)

- **사용자가 요청할 때만 실행한다**(2026-08-05 사용자 확정 — 자동 실행은 턴당 수 분의
  지연 비용이 커서 폐지). 검토가 유용해 보이는 갱신이면 **AskUserQuestion 으로 실행
  여부를 묻고**, "한다"고 답하지 않으면(다른 선택·무응답 포함) 검토 없이 그냥 진행한다.
- 실행할 때의 판별 기준은 분량이 아니라 **의미**: 확정 사양·확정 사실이 새로 생기거나
  바뀌면 한 줄이어도 일관성·논리성을 검토하고, 이력 추가(①)·상태 갱신(③)·오타 수정은
  문서가 새것이어도 생략한다.

# 요구사항·질의 관리 — <cwd>/spec 의 "주제별 사양서 하나"로 통합

- 질의·요청의 히스토리와 그것을 정리한 사양은 **주제/기능별 사양서 1개**(`spec_<주제>.md`)로
  합쳐 관리한다.
- 사양서 구조: ① 질의·요청 히스토리(날짜·원문 요지) ② 확정 사양 ③ 구현 상태 ④ 미결/후속.
- 작성 주체: 사용자 또는 코드 에이전트. 비자명한 구현은 착수 전에 ②를 먼저 만들고, 구현 후 ③을 갱신한다.
- 조회성 질문의 답도 해당 주제 사양서 ①에 한 줄로 남긴다. 단:
  - 답이 외부 시스템 지식뿐이면 원본은 references 에 두고, 관련 사양서가 **이미 있을 때만** ①에 한 줄+링크.
  - 프로젝트와 무관한 일회성 조회는 사양서를 새로 만들지 않는다.
- 원본-링크 원칙: 같은 사실은 한 문서가 원본, 다른 문서는 링크만. 진행 상태는 그 주제 사양서 ③에만 기록.
- 구형 사양서(①~④ 절 없는 것)는 일괄 개편하지 않는다 — 그 주제를 다시 다룰 때 ①~④ 절을
  추가하고 기존 본문은 ②로 간주해 점진 이관한다.
