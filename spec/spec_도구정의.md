# spec_도구정의 — MCP 도구 계약을 spec 으로 관리한다

MCP 서버가 노출하는 도구(tool)의 이름·설명·파라미터(타입/필수여부/기본값/옵션/필터)를
**어디를 원본으로 두고 어떻게 파생시킬지**에 대한 사양서다.

- 파라미터 리스트(`param_spec`)의 **필드 정의·적용 규칙 원본은
  [CLAUDE.md](../CLAUDE.md) "API·툴 파라미터" 절**, **형식 정본은
  [mcp_common/param_spec.py](../mcp_common/param_spec.py) 모듈 docstring** 이다. 이 문서는
  그것을 베끼지 않고 링크하며, 이 프로젝트에 고유한 결정과 현재 상태만 기록한다.
- 그 계약을 **어떻게 실어 나르는가**(stdio·Streamable HTTP 구동, 3파일 구조, 부트스트랩)는
  [spec_MCP트랜스포트.md](spec_MCP트랜스포트.md) 가 원본이다.

---

## ① 질의·요청 히스토리

| 날짜 | 요청 요지 |
|---|---|
| 2026-08-12 | "지금 API 로 된 도구들의 툴 정의를 spec 으로 문서화했으면 좋겠다 — 도구 함수와 설명, 추출 파라미터, 옵션, 필터, 필수 여부, 초기값까지 관리할 수 있게." |
| 2026-08-12 | 문서화·정리 **대상 범위를 MCP 등록 6개 서버(outlook / calendar / teams / onedrive / onenote / todo)로 확정**. time·file_handler·asset_management 는 이번 범위 밖으로 빼고 ④에 후속으로 남긴다. |
| 2026-08-12 | teams·onedrive·onenote 의 인라인 `MCP_TOOLS` 하드코딩을 폐지하고 나머지 서버와 같은 방식으로 통일할 것을 확정. |
| 2026-08-12 | 기본값은 `param_spec` 한 곳에서만 정의하고, 서비스 시그니처·`inputSchema.default`·핸들러 리터럴의 3중 관리를 끝낼 것을 확정. |
| 2026-08-12 | 스키마 정규화 진입점은 `schema_normalize.py` 하나뿐임을 재확인. 인라인 서버들이 이 파이프라인을 우회하는 현 상태를 해소 대상으로 확정. |
| 2026-08-12 | (조사 결과) `param_spec.yaml` 은 당시 프로젝트에 **0개**. CLAUDE.md 가 규정한 SSOT 가 어느 프로필에도 존재하지 않았다. |
| 2026-08-12 | **"진자템플릿은 더이상 사용하지 않을거야. 생성기를 사용하지 않고 spec 으로 api를 관리할거야"** — **방향 전환 확정.** 생성기(`generate_universal_server.py`)·jinja 템플릿·자동 생성물(`tool_definition_templates.yaml`)·에디터(`mcp_editor`)를 전부 폐지하고, `spec/param_spec/<도메인>.yaml` **하나만이 계약**이 된다. 이 문서의 "초안→확정→**생성**→검증"(구 S3)과 `tool_definition_templates.yaml` 을 자동 생성물로 다루던 서술은 이 결정으로 무효가 되어 삭제했다. |
| 2026-08-12 | 범위를 8개 도메인 전체(+ time, file_handler)로 넓혀 이관 완료. |
| 2026-08-12 | "MCP 서버 툴에 래핑된 함수도 spec 에 정의된 것인가? 이것에 따라 툴이 정의되면 좋겠다" — **`service:` 필드 추가 확정.** 도구→서비스 함수 바인딩(예: `mail_list_keyword` → `MailService.fetch_search`)이 그때까지 `handlers.py` 코드에만 보였는데, 도구 레벨 필수 필드 `service:`(`클래스.메서드`)로 spec 에 선언하게 했다. 60개 도구 전량 주입, 누락 시 기동 실패. 핸들러는 이 선언의 배선일 뿐이며 다르게 배선하면 위반이다. CLAUDE.md 필드 규정에도 반영. |

---

## ② 확정 사양

### 2.1 SSOT 와 파생 관계 — 중간 산출물이 없다

도구 계약의 유일한 손편집 원본은 **`spec/param_spec/<도메인>.yaml`** 이다. **이 파일이 곧
API 사양이다.**

```
spec/param_spec/<도메인>.yaml          ← 손편집 · 유일한 원본
        │ 기동 시 파생 (mcp_common/param_spec.py — load_param_spec)
        ├─ mcp_tools()   → inputSchema (name·description·inputSchema 3키)
        └─ call_args()   → 서비스 함수 호출 인자
                ▼
mcp_<도메인>/mcp_server/handlers.py    ← 배선만. 도구 정의를 적지 않는다.
```

- **미리 구워 둔 산출물이 없다.** 생성 단계가 없으므로 spec 과 런타임이 어긋날 수 없고,
  "생성물을 손으로 고쳐 앞서 나가는" 사고 자체가 불가능하다.
- 파일 위치는 `mcp_common/param_spec.py:517` 의 `spec_dir()` 가 정하며,
  환경변수 `MCP_PARAM_SPEC_DIR` 로만 덮어쓸 수 있다. (구 `MCP_YAML_PATH` 는 **더 이상 읽히지
  않는다** — ④ O3.)
- 필드 정의(`name`/`type`/`required`/`expose`/`default`/`enum`/`items`/`fields`/`baseModel`/
  `targetParam`/`order`)와 적용 규칙은 **CLAUDE.md 와 `param_spec.py` docstring 이 원본**이다.
  여기 중복 기술하지 않는다.

### 2.2 이 프로젝트 고유의 결정

| # | 결정 | 근거·귀결 |
|---|---|---|
| D1 | **대상은 8개 도메인 전부** (outlook, calendar, teams, onedrive, onenote, todo, time, file_handler) | 처음엔 등록 6개만이었으나 트랜스포트 통합과 함께 전량 이관했다. |
| D2 | **인라인 `MCP_TOOLS` 리터럴 폐지** | teams·onedrive·onenote·time 은 도구 정의가 stdio/stream 두 파일에 각각 복사돼 있었다. 전부 param_spec 으로 통일했다. |
| D3 | **기본값은 param_spec 한 곳에서만 정의** | 과거엔 ①서비스 시그니처 ②`inputSchema.default` ③핸들러 리터럴(+인라인 스키마) 3~4중이었다. 이제 핸들러는 `SPEC.call_args()` 결과를 그대로 넘긴다 — **핸들러 코드에 기본값 리터럴을 적지 않는다.** |
| D4 | **스키마 정규화 진입점은 `mcp_common/schema_normalize.py` 하나** | `mcp_editor` 에서 이관했다. jinja 런타임 사본(`_schema_helpers.jinja2`)과 동기화 테스트는 생성기와 함께 소멸했다 — 사본이 없으므로 동기화 문제 자체가 없다. |
| D5 | **도구 description 의 원본은 param_spec** | `@mcp_service(description=...)` 은 메타데이터 표식으로 강등됐다(`mcp_common/service_meta.py`). **런타임 무영향**이며, 둘이 어긋나면 param_spec 이 이긴다. |
| D6 | **필수 여부의 원본은 param_spec 의 `required`** | AST 사본(`mcp_service.parameters[].is_required`)은 생성기와 함께 사라졌다. 이중 관리가 소멸했다. |
| D7 | **계약 위반은 기동을 막는다** | 잘못된 스키마를 에이전트에게 노출한 채 도는 것보다 죽는 편이 안전하다(2.5). |

### 2.3 계약으로 관리하는 항목

도구 하나에 대해 관리하는 항목. 사양서·spec 파일이 **같은 열 이름**을 쓴다(두 벌 어휘 금지).

| 층위 | 항목 |
|---|---|
| 서버 | `server.name`, `server.version`, `server.port`, `server.description` |
| 도구 | `name`, `description`, `service`(필수 — 래핑하는 서비스 함수 `클래스.메서드`. 바인딩의 유일한 선언처, 누락 시 기동 실패) |
| 파라미터 | `name`, `type`, `required`, `default`, `enum`, `expose`, `description`, `order` |
| 배열·객체 | `items`(배열 원소 스키마), `fields`(객체 하위 필드), `baseModel`(대응 Pydantic 모델명) |
| 매핑 | `targetParam` — 서비스 인자 이름이 도구 파라미터 이름과 다를 때 |

> **"필터"는 별도 개념이 아니다.** Pydantic 복합 타입 파라미터를 `type: object` + `fields` 로
> 적은 것이며, `expose` 가 노출(`tool`)이냐 주입(`internal`)이냐를 가른다. 새 어휘를 만들지
> 않는다.

- `fields` 의 요점은 **필드별 설명이 spec 에 남는다**는 것이다. 이 정보는 함수 시그니처에서
  복원할 수 없으므로 여기서 잃으면 영영 잃는다.
- `items` 를 적지 않으면 **배열 원소 계약이 통째로 사라진다**. 실제로 4개 도메인에서 유실된
  적이 있다(3.4 결함 1).

### 2.4 계약을 바꾸는 절차

생성 단계가 없으므로 절차가 짧다.

| 순서 | 작업 | 하지 말 것 |
|---|---|---|
| 1 | `spec/param_spec/<도메인>.yaml` **만** 고친다 | 핸들러에 기본값 리터럴을 적지 않는다(D3 로의 회귀 경로) |
| 2 | 서버를 재기동한다 | — |
| 3 | 기동에 실패하면 계약 위반이다. 메시지대로 spec 을 고친다(2.5) | 검증을 우회하는 코드를 만들지 않는다 |
| 4 | `/health` 200 + `tools/list` 개수로 확인한다 | — |

- 서비스 함수 시그니처와 spec 이 다르면 **spec 이 이긴다.** 단 타입·필수 여부가 어긋나면
  조용히 덮지 말고 차이를 보고한다.
- 시그니처에 있는데 spec 에 없는 파라미터가 필수면 오류, 선택이면 `expose: hidden` 으로
  간주한다. spec 에만 있고 시그니처에 없으면 오류다.
- **새 파라미터를 늘릴 때 손댈 파일은 spec 1개다.** 도구를 새로 만들 때만 `handlers.py` 에
  핸들러 함수 1개가 추가된다.

### 2.5 기동 시 검증 — 위반은 서버를 띄우지 않는다

`load_param_spec()` 이 로드 시점에 아래를 **즉시 오류(`ParamSpecError`)로 올린다.**

| 위반 | 예 |
|---|---|
| `required: true` 인데 `default` 가 있다 | 필수/선택 일관성(CLAUDE.md) |
| `expose: internal` 인데 주입값(`default`/`fields`)이 없다 | 무엇을 주입할지 알 수 없다 |
| `type` / `expose` 값이 목록 밖이다 | 오타를 조용히 넘기지 않는다 |
| `description` 이 비었다 | 에이전트가 읽는 문구다 |
| 같은 도구 안에 파라미터 이름이 중복 | — |
| 도구 이름 중복 · `tools` 가 비었음 · `server.name` 없음 | — |

### 2.6 boolean 과 정규화의 단일 진입점

- **spec 에는 boolean 을 boolean 으로 적는다.** `enabled`/`disabled` 문자열 enum 변환은
  `mcp_common/schema_normalize.py` 가 담당한다(OpenAI function-calling 이 boolean 타입을 받지
  않기 때문에 노출 스키마에서만 문자열이 된다). spec 에 직접 enum 을 적으면 변환이 두 벌이
  되어 드리프트한다.
- **되돌리는 곳도 한 곳이다.** `SPEC.call_args()` 가 `enabled`/`disabled` 를 원래 bool 로
  되돌려 서비스에 넘긴다.
- **들어온 인자의 boolean 보정은 `ToolRuntime.call()` 이 검증 직전에 한 번** 한다
  (`mcp_common/runtime.py:126`). 구형 클라이언트가 진짜 `true` 를 보내도 거절되지 않는다.
  **도메인 핸들러에 우회 코드를 만들지 않는다** — 실제로 우회가 생겨 걷어낸 적이 있다(3.4 결함 2).

---

## ③ 구현 상태 (2026-08-12 — 8개 도메인 이관 완료)

### 3.1 도메인별 param_spec (전량 존재 · 1,850줄)

| 도메인 | 포트 | 파일 | 도구 | 줄 | 이관 대조 |
|---|---:|---|---:|---:|---|
| outlook | 5001 | `spec/param_spec/outlook.yaml` | 10 | 602 | `top` 2곳에 `default: 50` 추가(개선) |
| calendar | 5002 | `spec/param_spec/calendar.yaml` | 7 | 235 | **완전 동일** |
| teams | 5003 | `spec/param_spec/teams.yaml` | 14 | 291 | **완전 동일** |
| onedrive | 5004 | `spec/param_spec/onedrive.yaml` | 9 | 176 | **완전 동일** |
| onenote | 5005 | `spec/param_spec/onenote.yaml` | 4 | 122 | **완전 동일** |
| todo | 5006 | `spec/param_spec/todo.yaml` | 8 | 287 | **완전 동일** |
| time | 5007 | `spec/param_spec/time.yaml` | 1 | 22 | 신규(인라인 1개 이관) |
| file_handler | 5008 | `spec/param_spec/file_handler.yaml` | 7 | 115 | `search_metadata` 개선(아래) |

계약 이관은 **동작 보존이 기준**이었다. 의도적으로 다르게 한 곳은 2건뿐이다.

| 도메인 | 변경 | 이유 |
|---|---|---|
| file_handler | `search_metadata` 의 `properties: {}` → `keyword`/`file_url` 명시 | 빈 스키마라 에이전트가 무엇을 넣을지 알 수 없었다 |
| outlook | `top` 2곳에 `default: 50` 추가 | 코드에 하드코딩돼 있던 값을 spec 으로 승격(D3) |

### 3.2 param_spec 기능 사용 현황

| 기능 | 사용처 |
|---|---|
| `expose: tool` | 200개 파라미터 (대다수) |
| `expose: internal` | outlook 4개 (`FilterParams`/`SelectParams` 계열 주입) |
| `expose: hidden` | outlook `mail_attachment_meta.select_params` 1개 (3.4 결함 5) |
| `fields` (객체 하위 필드) | outlook 9곳 |
| `items` (배열 원소) | todo `categories` 2, teams `names`, calendar `schedules`, file_handler `keywords` |
| `baseModel` | outlook (Pydantic 모델 표식) |
| `targetParam` | 전 도메인 (todo 는 35개 전부 항등 매핑까지 명시) |

핸들러가 `type: object` 를 Pydantic 모델로 만드는 지점은 도메인 고유 배선이다 —
`mcp_outlook/mcp_server/handlers.py:61-71` (`_model()`: 값이 없거나 `{}` 면 모델을 만들지 않고
None 을 넘겨 기존 동작을 보존).

### 3.3 이관 중 드러나 고친 결함 6종

| # | 결함 | 실태 | 조치 |
|---|---|---|---|
| 1 | **`items` 유실** | 배열 원소 스키마가 통째로 빠져 있었다 — todo 2, teams 1, calendar 1, file_handler 1 | `param_spec` 에 `items` 를 추가해 복원 |
| 2 | **`coerce_arguments()` 가 무효** | 변환 **전** 스키마를 넘겨 아무 일도 하지 않았다(`type: boolean` 을 넘기면 그 함수는 손대지 않는다) | `ToolRuntime.call()` 로 일원화(2.6) |
| 3 | **`mail_query_url` 이 원래 깨져 있었다** | 구 정의의 `targetParam: select` 인데 `MailService.fetch_url` 의 인자는 `select_params` — **호출할 때마다 TypeError** | `spec/param_spec/outlook.yaml:544` 를 `select_params` 로 바로잡음 |
| 4 | `mail_fetch_filter` 의 테스트 잔재 | `signature_defaults` 에 `test_field: test_value` — `FilterParams` 에 없는 필드라 Pydantic 이 무시해 왔다 | 이관하지 않음 |
| 5 | `mail_attachment_meta.select_params` | 구 정의는 `internal`(주입)이었으나 **생성기가 누락해 실제로는 한 번도 주입된 적이 없다** | 동작 보존을 위해 `expose: hidden` + 주석(`outlook.yaml:259-267`). 주입을 원하면 `internal` 로 바꾸면 된다 |
| 6 | **todo 계약 위반 6건** | `title`/`task_id`/`display_name` 등이 스키마상 필수인데 시그니처 기본값이 `""` 라 **조용히 빈 값으로 진행**됐다 | `required: true` + default 없음으로 확정. 이제 검증에서 거절된다 |

추가로, **calendar 의 `mcp_service_factors` 는 7개 도구 전부 비어 있어 1,180줄 분량의 주입
로직이 죽은 코드였다.** 이관과 함께 소멸했다.

### 3.4 폐지되어 사라진 것

| 대상 | 결말 |
|---|---|
| `mcp_editor` (에디터 + 생성기 + 템플릿 + 프로필) | **116파일 통째 삭제.** 삭제 후 8개 도메인 import·6개 서버 기동 정상 확인 |
| `tool_definition_templates.yaml` (프로필 4개) | 계약을 `spec/param_spec/` 로 이관 후 삭제 |
| `_schema_helpers.jinja2` 런타임 사본 + 동기화 테스트 | 사본이 없어져 동기화 문제 자체가 소멸 |
| `mcp_service.parameters[]` AST 사본 · `mcp_service.signature` | 생성기 전용이었다 |
| `editor_config.json` 유령 프로필 경로 | 파일째 소멸 |
| `INTERNAL_ARG_TYPES` 프로토콜 비대칭 | 트랜스포트별 사본이 없어져 소멸 |
| `@mcp_service` 데코레이터 | `mcp_common/service_meta.py` 로 이관해 **메타데이터 표식으로만** 존치(런타임 무영향, D5) |

### 3.5 검증 결과

| 항목 | 결과 |
|---|---|
| 계약 이관 대조 (onenote·onedrive·teams·todo·calendar) | **완전 동일** |
| `tools/list` 도구 개수 (6개 등록 서버) | **전부 일치** |
| 실제 Graph API 호출 | `todo_lists_view top=3` → 요청 URL 에 `$top=3` 반영 **성공** |
| `/health` (5001~5006) | 전부 **200 healthy** |

> 트랜스포트 쪽 검증(Streamable HTTP 준수 8/8, stdio 결함 해소)은
> [spec_MCP트랜스포트.md](spec_MCP트랜스포트.md) ③-3·③-4 참조.

---

## ④ 미결 / 후속

| # | 항목 | 내용 | 우선도 |
|---|---|---|---|
| O1 | **todo.yaml 의 낡은 주석** | `spec/param_spec/todo.yaml:24-28` 이 "`items` 미지원이라 `categories` 원소 계약이 유실됐다"고 적고 있으나, `items` 는 지원되고 `:195`·`:263` 에 이미 복원돼 있다. 주석을 지워야 한다 | 높음 |
| O2 | **플레이스홀더 description** | outlook `mail_list_keyword`·`test_handler` 의 설명이 구 생성기 기본값(`New tool description`)에서 유래한다. 에이전트에게 그대로 노출된다. `test_handler` 를 도구로 유지할지 자체가 미결 | 중 |
| O3 | **`MCP_YAML_PATH` 문서 잔재** | `docs/environment_variables.md:172` 가 삭제된 경로(`mcp_editor/mcp_<서버>/tool_definition_templates.yaml`)를 가리킨다. 실제 override 는 `MCP_PARAM_SPEC_DIR` 이다. `.env.example:71`·`mcp_outlook/README.md:257`·`mcp_file_handler/README.md:66` 도 같이 본다 | 중 |
| O4 | **outlook 서비스 함수 1:N 매핑** | `fetch_search` 가 2개 도구(`mail_list_keyword`/`mail_fetch_search`), `fetch_filter` 가 2개 도구(`mail_fetch_filter`/`test_handler`)에 매핑된다. 같은 함수인데 필수 파라미터 이름이 `search_keywords` vs `search_term` 으로 갈린다. 의도인지 확정 필요 | 중 |
| O5 | **calendar 복합 타입 미계약** | 서비스 시그니처의 `EventFilterParams`·`EventSelectParams` 는 구 정의에서 주입된 적이 없어(3.3) 현재 spec 에도 없다. `expose: internal` 로 계약화할지, 노출 파라미터로 평탄화할지 미결 | 중 |
| O6 | **`mail_attachment_meta.select_params` 처분** | 3.3 결함 5 — 현재 `hidden`(현행 동작 보존). 원래 의도대로 `internal` 주입으로 돌릴지 사용자 확정 필요 | 중 |
| O7 | **공통 enum 집합의 중복 정의** | todo 의 status 5값이 `todo_tasks_view.status_filter` 와 `todo_task_update.status` 에, importance 3값이 두 도구에 각각 적혀 있다. 공통 옵션 집합을 참조로 둘지 미결 | 낮음 |
| O8 | **docstring `Args:` 와 spec description 의 관계** | calendar·outlook 서비스는 docstring `Args:` 블록을 성실히 작성 중인데 이제 아무도 읽지 않는다. spec 으로 흡수할지, 사문으로 둘지 미결 | 낮음 |
| O9 | **`asset_management` 미이관** | 도구 이름이 `new_tool_1768316544612` 등 생성기 기본값 그대로였고, `mcp_editor` 삭제와 함께 정의가 사라졌다. 이 서버를 되살릴지 자체가 미결 | 낮음 |

> 새 도메인을 추가하는 표준 절차(스캐폴드 부재)와 merge 기능 소멸은 구동 쪽 문제라
> [spec_MCP트랜스포트.md](spec_MCP트랜스포트.md) ④-2 가 원본이다.

---

## 참조

| 문서·파일 | 역할 |
|---|---|
| [CLAUDE.md](../CLAUDE.md) | param_spec 필드 정의·적용 규칙의 원본 |
| [mcp_common/param_spec.py](../mcp_common/param_spec.py) | **형식 정본**(모듈 docstring) + 로더·검증 |
| [mcp_common/schema_normalize.py](../mcp_common/schema_normalize.py) | 스키마 정규화 단일 진입점 |
| [mcp_common/runtime.py](../mcp_common/runtime.py) | 기본값 병합·검증·boolean 보정·디스패치 |
| [mcp_common/service_meta.py](../mcp_common/service_meta.py) | `@mcp_service` — 메타데이터 표식(런타임 무영향) |
| [spec_MCP트랜스포트.md](spec_MCP트랜스포트.md) | 계약을 실어 나르는 방법(stdio·Streamable HTTP) |
