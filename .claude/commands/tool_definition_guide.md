# tool_definition_templates.yaml 작성 지침

> **공통 지침**: 작업 전 [common.md](common.md) 참조

## 개요

`tool_definition_templates.yaml`은 MCP 서버의 **Single Source of Truth**로, LLM이 도구를 이해하고 사용하는 데 필요한 모든 정보를 정의합니다.

---

## 1. 도구 선정 기준 (우선순위)

### 1.1 필수 포함 도구 (Priority: High)

| 기준 | 설명 |
|------|------|
| **핵심 CRUD** | 서비스의 기본 생성/조회/수정/삭제 기능 |
| **진입점 도구** | 다른 도구 사용의 선행 조건이 되는 도구 |
| **고빈도 사용** | 실제 사용자가 자주 호출하는 기능 |

### 1.2 선택적 포함 도구 (Priority: Medium)

| 기준 | 설명 |
|------|------|
| **보조 기능** | 핵심 기능을 보완하는 도구 |
| **고급 필터링** | 세부 조건 검색/필터 |

### 1.3 제외 권장 도구 (Priority: Low)

| 기준 | 설명 | 이유 |
|------|------|------|
| **내부 전용** | 시스템 내부에서만 사용 | LLM 노출 불필요 |
| **중복 기능** | 다른 도구로 대체 가능 | 도구 수 최소화 |
| **위험 작업** | 복구 불가능한 작업 | 신중한 노출 필요 |

---

## 2. 도구 정의 구조

### 2.1 기본 템플릿

```yaml
tools:
- name: <tool_name>                    # snake_case, 서비스_동작 형태
  description: |                       # LLM이 도구 선택 시 참고
    간단한 설명.

    [선행 조건] (있는 경우)
    - 이 도구 호출 전 필요한 조건

    [사용 시나리오]
    - 언제 이 도구를 사용해야 하는지
  inputSchema:
    type: object
    properties:
      <param_name>:
        type: <string|integer|boolean|array|object>
        description: 파라미터 설명
        targetParam: <service_param_name>  # 서비스 파라미터와 매핑
        default: <default_value>           # 선택적
    required:
    - <required_param_1>
    - <required_param_2>
  mcp_service:
    name: <service_method_name>        # *_service.py의 메서드명
    parameters: [...]                  # 자동 생성됨 (스캔 결과)
    signature: <method_signature>      # 자동 생성됨
  mcp_service_factors:                 # Internal/기본값 파라미터
    <factor_name>:
      source: internal | signature_defaults
      type: <type>
      targetParam: <param>
      description: <desc>
      parameters: [...]                # 복합 객체의 경우
```

---

## 3. description 작성 가이드

### 3.1 좋은 description의 특징

```yaml
# Good
description: |
  지정된 조건으로 데이터를 조회합니다.
  전체 내용이 아닌 핵심 정보만 효율적으로 반환합니다.

  [선행 조건]
  - 없음 (진입점 도구)

  [후속 도구]
  - <detail_tool>: 상세 조회
  - <related_tool>: 관련 정보 확인

# Bad
description: 데이터 조회
```

### 3.2 핵심 요소

| 요소 | 필수 | 설명 |
|------|------|------|
| **기능 설명** | O | 1-2문장으로 핵심 기능 |
| **선행 조건** | △ | 다른 도구 호출이 필요한 경우 |
| **후속 도구** | △ | 이 도구 결과로 사용 가능한 도구 |
| **제약 사항** | △ | 옵션 간 상호 의존성 |
| **사용 시나리오** | △ | 언제 이 도구를 선택해야 하는지 |

---

## 4. inputSchema 작성 가이드

### 4.1 파라미터 분류

```yaml
inputSchema:
  type: object
  properties:
    # 1. LLM이 직접 제공하는 파라미터 (Signature)
    query_term:
      type: string
      description: 검색어
      targetParam: query_term

    # 2. 기본값이 있지만 LLM이 변경 가능 (Signature Defaults)
    limit:
      type: integer
      description: 반환할 최대 결과 수
      default: 50
      targetParam: limit

    # 3. 복합 객체 (Nested Object)
    filter_params:
      type: object
      description: 필터 조건
      properties:
        date_from:
          type: string
          description: 시작 날짜 (ISO 8601)
          targetParam: date_from
      baseModel: FilterParams  # 타입 정보
      targetParam: filter_params
```

### 4.2 타입별 작성 예시

```yaml
# String
identifier:
  type: string
  description: 고유 식별자
  targetParam: identifier

# Integer
limit:
  type: integer
  description: 최대 결과 수 (1-1000)
  default: 50
  targetParam: limit

# Boolean
include_details:
  type: boolean
  description: 상세 정보 포함 여부
  default: true
  targetParam: include_details

# Array
item_ids:
  type: array
  description: 항목 ID 목록
  items:
    type: string
  targetParam: item_ids

# Enum
output_type:
  type: string
  description: 출력 형식
  enum:
  - json
  - text
  - csv
  default: json
  targetParam: output_type

# Object
options:
  type: object
  description: 추가 옵션
  properties:
    verbose:
      type: boolean
      targetParam: verbose
  baseModel: OptionsParams
  targetParam: options
```

---

## 5. mcp_service_factors 작성 가이드

### 5.1 Internal 파라미터 (LLM에게 숨김)

```yaml
mcp_service_factors:
  system_filter:
    source: internal           # LLM에게 노출 안 함
    type: FilterParams
    targetParam: system_filter
    description: 시스템 필터링 조건
    parameters:
    - name: exclude_list
      type: array
      default:
      - system_item_1
      - system_item_2
      description: 제외 항목
```

### 5.2 Signature Defaults (LLM 기본값)

```yaml
mcp_service_factors:
  select_fields:
    source: signature_defaults  # LLM에게 보이되 기본값 제공
    type: SelectParams
    targetParam: select_fields
    description: 조회 필드 선택
    parameters:
    - name: include_id
      type: boolean
      default: true
      description: ID 필드 포함
```

---

## 6. 서비스 분석 방법

### 6.1 *_service.py 분석 체크리스트

```python
# 1. @mcp_service 데코레이터 확인
@mcp_service(
    tool_name="<handler_name>",         # → YAML의 name 참고
    server_name="<server>",             # → 서버 식별
    service_name="<method_name>",       # → mcp_service.name
    category="<category>",              # → 도구 분류
    tags=["<tag1>", "<tag2>"],          # → 검색/필터 키워드
    priority=5,                         # → 중요도 (1-10)
    description="<description>",        # → description 초안
)

# 2. 메서드 시그니처 분석
async def method_name(
    self,
    required_param: str,                # → required 파라미터
    optional_param: Optional[...],      # → optional, mcp_service_factors 고려
    with_default: int = 50,             # → default 값 있음
) -> Dict[str, Any]:
```

### 6.2 레거시 핸들러 마이그레이션

레거시 핸들러가 있는 경우:

1. **핸들러 함수명** → `tool name` 후보
2. **핸들러 docstring** → `description` 초안
3. **핸들러 파라미터** → `inputSchema.properties`
4. **내부 하드코딩 값** → `mcp_service_factors (internal)`

---

## 7. 도구 간 관계 정의

### 7.1 워크플로우 체인

```yaml
# 진입점 도구 (Entry Point)
- name: list_items
  description: |
    항목 목록 조회 (진입점)

    [후속 도구]
    - get_item_detail: ID로 상세 조회
    - get_item_metadata: 메타데이터 확인

# 중간 도구 (Intermediate)
- name: get_item_metadata
  description: |
    항목 메타데이터 조회

    [선행 조건]
    - list_* 호출로 item_id 획득 필요

    [후속 도구]
    - download_item: 실제 다운로드

# 종단 도구 (Terminal)
- name: download_item
  description: |
    항목 다운로드

    [선행 조건]
    - get_item_metadata 호출로 관련 ID 획득
```

---

## 8. 작성 체크리스트

### 새 도구 추가 시

- [ ] `*_service.py`에서 `@mcp_service` 데코레이터 확인
- [ ] `priority` 값으로 중요도 판단 (5 이상 권장)
- [ ] `tags`로 도구 분류 파악
- [ ] 필수 파라미터와 선택 파라미터 구분
- [ ] Internal 파라미터 식별 (LLM에게 숨길 것)
- [ ] 선행/후속 도구 관계 파악

### 최종 검토

- [ ] `name`이 서비스_동작 형태의 snake_case인가?
- [ ] `description`에 핵심 기능이 명확히 설명되었는가?
- [ ] `required` 배열에 필수 파라미터만 있는가?
- [ ] `targetParam`이 서비스 메서드 파라미터와 일치하는가?
- [ ] `mcp_service_factors`에 시스템 기본값이 설정되었는가?

---

## 9. 예시: 완전한 도구 정의

```yaml
tools:
- name: view_schedule
  description: |
    지정된 기간의 일정을 조회합니다.
    반복 일정의 개별 인스턴스도 포함됩니다.

    [사용 시나리오]
    - 특정 기간의 일정 확인
    - 일정 충돌 확인
  inputSchema:
    type: object
    properties:
      user_id:
        type: string
        description: 조회할 사용자 식별자
        targetParam: user_id
      start_datetime:
        type: string
        description: '조회 시작 (ISO 8601, 예: 2024-01-01T00:00:00)'
        targetParam: start_datetime
      end_datetime:
        type: string
        description: '조회 종료 (ISO 8601, 예: 2024-01-31T23:59:59)'
        targetParam: end_datetime
    required:
    - start_datetime
    - end_datetime
  mcp_service:
    name: view_schedule
    parameters:
    - name: user_id
      type: str
      is_required: true
    - name: start_datetime
      type: str
      is_required: true
    - name: end_datetime
      type: str
      is_required: true
    - name: limit
      type: int
      is_optional: true
      default: 50
    signature: 'user_id: str, start_datetime: str, end_datetime: str, limit: int = 50'
  mcp_service_factors:
    limit:
      source: internal
      type: integer
      targetParam: limit
      description: 최대 반환 항목 수
      default: 100
```

---

## 관련 문서

| 문서 | 역할 |
|------|------|
| [web.md](web.md) | 웹에디터 사용법 |
| [mcp_service.md](mcp_service.md) | 서비스 구현 가이드 |
| [terminology.md](terminology.md) | 용어 정의 |

---
*Last Updated: 2026-01-12*
*Version: 1.0*
