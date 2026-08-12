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
| `spec/param_spec/<도메인>.yaml` | **손으로 쓰는 유일한 원본** | 도구 계약 그 자체. 기동 시 `mcp_common.param_spec` 가 읽어 `inputSchema`·기본값·호출 인자를 파생시킨다. |

- **코드 생성은 폐지됐다**(2026-08-12 사용자 확정). jinja 템플릿·`generate_universal_server.py`·
  `tool_definition_templates.yaml` 은 없다. 미리 구워 둔 산출물이 없으므로 spec 과 런타임이
  어긋날 수 없다.
- 도메인 서버는 `mcp_<도메인>/mcp_server/` 의 3파일이다 — `handlers.py`(배선만),
  `server_stdio.py`, `server_stream.py`. **도구 정의를 이 파일들에 적지 않는다.**
- 형식의 정본은 [mcp_common/param_spec.py](mcp_common/param_spec.py) 모듈 docstring 이다.
  필드를 늘릴 때는 거기와 이 문서를 함께 고친다.
- 파라미터 이야기를 사양서에 적을 때도 **같은 열 이름**의 표로 적는다(두 벌 어휘 금지).

## 리스트 한 줄의 필드

```yaml
server:
  name: calendar
  version: "1.0.0"
  port: 5002

tools:
  - name: calendar_view            # MCP 도구 이름
    description: 캘린더 일정 조회   # 필수 — 에이전트가 읽는 도구 설명
    service: CalendarService.calendar_view   # 필수 — 이 도구가 래핑하는 서비스 함수
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

- `service` (필수, 도구 레벨): 이 도구가 래핑하는 서비스 함수(`클래스.메서드`,
  예: `MailService.fetch_search`). **바인딩의 유일한 선언처다** — 도구 이름과 함수
  이름은 다를 수 있고(1:N 도 가능), 어떤 함수를 부르는지 알려고 `handlers.py` 를
  열게 만들지 않는다. 핸들러 배선이 이 선언과 다르면 위반이다. 없으면 기동 실패.
- `expose` 의미 — `tool`: `inputSchema.properties` 에 노출 / `internal`: 노출하지 않고
  서버가 값을 주입(`default` 또는 `fields` 필수) / `hidden`: 호출에 쓰지 않음(시그니처
  기본값에 맡김).
- `order` (선택, 정수): 스키마에서의 표시 순서.
- `items` (선택): `type: array` 일 때 원소 스키마. JSON Schema 조각을 그대로 싣는다.
  **적지 않으면 원소 계약이 사라진다** — 실제로 4개 도메인에서 유실된 적이 있다.
- `fields` (선택): `type: object` 일 때 하위 필드. `expose: tool` 이면 중첩
  `inputSchema.properties` 가 되고, `expose: internal` 이면 각 필드의 `default` 를 모아
  주입할 dict 가 된다(핸들러가 그것으로 Pydantic 모델을 만든다). 어느 쪽이든 **필드별
  설명이 spec 에 남는 것**이 요점이다 — 시그니처에서 복원할 수 없는 정보다.
- `baseModel` (선택): 그 객체가 대응하는 Pydantic 모델 이름. 표식이며 스키마에 실린다.

**YAML 주의**: 설명에 `: `(콜론+공백)나 `#` 가 들어가면 파싱이 깨진다. `description` 은
항상 따옴표로 감싼다. `"[claude]"` 처럼 대괄호로 시작하는 기본값도 마찬가지다.

## 적용 규칙

- **로드 시 검증이 기동을 막는다**: `required: true` 인데 `default` 가 있거나,
  `expose: internal` 인데 주입값(`default`/`fields`)이 없거나, `type`·`expose` 값이
  틀렸거나, `description` 이 비었거나, 이름이 중복되면 **서버가 뜨지 않는다.** 잘못된
  스키마를 에이전트에게 노출한 채 도는 것보다 죽는 편이 안전하다.
- **boolean 은 boolean 으로 적는다**. `enabled`/`disabled` 문자열 enum 변환은 리스트가
  아니라 [mcp_common/schema_normalize.py](mcp_common/schema_normalize.py) 가 담당한다 —
  리스트에 직접 enum 을 적어 두면 변환이 두 벌이 되어 드리프트한다.
- **정규화 진입점은 하나**: 스키마 형태 보정·`required` 정규화·boolean 변환은 전부
  `mcp_common/schema_normalize.py` 를 쓴다. 새 파싱/정규화 함수를 만들지 않는다.
  들어온 인자의 boolean 보정은 [mcp_common/runtime.py](mcp_common/runtime.py) 의
  `ToolRuntime.call()` 이 **검증 직전에 한 번** 한다 — 도메인 핸들러에 우회 코드를
  만들지 않는다(실제로 우회가 생겨 걷어낸 적이 있다).
- **충돌 시 spec 이 이긴다**: 서비스 함수 시그니처와 param_spec 이 다르면 param_spec 을
  따르되, 타입·필수 여부가 어긋나면 **조용히 덮지 말고 차이를 보고**한다.
- **누락 처리**: 시그니처에 있는데 spec 에 없는 파라미터가 필수면 오류, 선택이면
  `expose: hidden` 으로 간주한다. spec 에만 있고 시그니처에 없으면 오류.
- **추가·변경 순서**: 파라미터를 늘리거나 필수/선택을 바꿀 때는
  `spec/param_spec/<도메인>.yaml` **만** 고친다. 핸들러의 `SPEC.call_args()` 가 그대로
  반영한다. **기본값을 핸들러 코드에 적지 않는다** — 그것이 기본값 3중 관리로 되돌아가는
  경로다.

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
