---
description: MCP 웹에디터 데이터 흐름 및 핸들러 처리 가이드 (project)
---

> **공통 지침**: 작업 전 [common.md](../commands/common.md) 참조

# MCP 웹에디터 데이터 흐름 및 핸들러 처리 가이드

> **본 문서는 MCP 웹에디터의 전체 데이터 흐름을 상세히 설명하는 종합 참조 문서입니다.**

## 관련 문서 (역할 분리)

| 문서 | 역할 | 참조 시점 |
|------|------|----------|
| [web.md](../commands/web.md) | 웹에디터 **사용 방법** 및 **실행 지침** | 웹에디터 사용 시 |
| [handler.md](../commands/handler.md) | 파라미터 체계 **핵심 개념** 요약 | 빠른 참조 시 |
| **web_dataflow.md** (본 문서) | 데이터 흐름 및 내부 구현 **상세** | 구현/디버깅 시 |

---

## 목차
1. [전체 시스템 아키텍처](#1-전체-시스템-아키텍처)
2. [Phase별 데이터 흐름 (빌드 타임)](#2-phase별-데이터-흐름-빌드-타임)
3. [파라미터 매핑 구조](#3-파라미터-매핑-구조)
4. [핸들러 처리 흐름 (런타임)](#4-핸들러-처리-흐름-런타임)
5. [파라미터 병합 체계](#5-파라미터-병합-체계)
6. [핵심 저장 위치 요약](#6-핵심-저장-위치-요약)
7. [전체 데이터 변환 흐름](#7-전체-데이터-변환-흐름)
8. [호출 함수/메서드 명세](#8-호출-함수메서드-명세)
9. [registry_{server}.json의 역할 - 중간 저장소](#9-registry_serverjson의-역할---중간-저장소-bridge)
10. [서버 병합 데이터 흐름](#10-서버-병합-데이터-흐름)
11. [대시보드 및 프로토콜별 제어](#11-대시보드-및-프로토콜별-제어)
12. [파일 경로 참조](#12-파일-경로-참조)

---

## 1. 전체 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           데이터 소스 (Source Files)                         │
├────────────────────────────────┬────────────────────────────────────────────┤
│ 1. 소스코드                     │ 2. 템플릿 정의                              │
│ @mcp_service 데코레이터         │ tool_definition_templates.yaml             │
│                                │ (LLM 스키마 + mcp_service_factors)          │
└────────────────┬───────────────┴────────────────┬───────────────────────────┘
                 │                                │
                 ▼                                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                        웹에디터 (tool_editor_web.py)                        │
│  ┌──────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐   │
│  │ AST Scanner  │  │ JSON Registry   │  │ mcp_service_factors 추출    │   │
│  │ (fallback)   │  │ (primary)       │  │ (Internal/SignatureDefaults)│   │
│  └──────────────┘  └─────────────────┘  └─────────────────────────────┘   │
│         ↓                   ↓                          ↓                   │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                      웹 UI (tool_editor.html)                       │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │ Save / Generate
                                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                     저장 & 생성 (Save & Generate)                          │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ POST /api/tools/save-all                                            │  │
│  │  → tool_definition_templates.yaml (Single Source of Truth)          │  │
│  │    (mcp_service_factors 포함, tool_definitions.py는 더 이상 생성 안함)│  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ POST /api/server/generate                                           │  │
│  │  → 3가지 프로토콜 서버 생성 (REST, STDIO, Stream)                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                       서버 생성 (Jinja2 Rendering)                         │
│  ┌─────────────────────┐    ┌─────────────────────────────────────────┐   │
│  │ Input Files:        │    │ Output Files:                           │   │
│  │ • registry.json     │───▶│ • server_rest.py                        │   │
│  │ • templates.yaml    │    │ • server_stdio.py                       │   │
│  │   (mcp_service_     │    │ • server_stream.py                      │   │
│  │    factors 포함)    │    │                                         │   │
│  │ • *.jinja2          │    │ (런타임에 YAML에서 MCP_TOOLS 로드)       │   │
│  └─────────────────────┘    └─────────────────────────────────────────┘   │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         런타임 실행 (Runtime)                              │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ LLM 호출 → 파라미터 추출 → 병합 → 서비스 실행 → 결과 반환           │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Phase별 데이터 흐름 (빌드 타임)

### Phase 1: 데이터 수집 (웹에디터 시작)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Phase 1: 데이터 수집                              │
└──────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────┐
  │  @mcp_service       │
  │  데코레이터가 있는   │
  │  Python 파일        │
  └──────────┬──────────┘
             │ AST Scanner
             ▼
  ┌─────────────────────┐      ┌──────────────────────────┐
  │ registry_{server}   │      │ tool_definition_         │
  │ .json               │      │ templates.yaml           │
  └──────────┬──────────┘      └───────────┬──────────────┘
             │ JSON.load()                 │ yaml.safe_load()
             ▼                             ▼
  ┌─────────────────────┐      ┌──────────────────────────┐
  │ services dict       │      │ MCP_TOOLS 리스트         │
  │ (메모리)            │      │ + mcp_service_factors    │
  └─────────────────────┘      │   (Internal/SigDefaults) │
                               └──────────────────────────┘
                                          │
                                          ▼ extract_internal_args_from_tools()
                               ┌──────────────────────────┐
                               │ internal_args dict       │
                               │ (from mcp_service_factors│
                               │  with source='internal') │
                               └──────────────────────────┘
```

---

### Phase 2: 웹 UI 편집

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Phase 2: 웹 UI 편집                               │
└──────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │                        웹에디터 UI                                   │
  │  ┌───────────────────────────────────────────────────────────────┐  │
  │  │  Tool 목록                                                     │  │
  │  │  ├─ mail_fetch_filter                                         │  │
  │  │  │   ├─ description: "Outlook 메일을 조회합니다..."           │  │
  │  │  │   ├─ inputSchema.properties (LLM 노출 파라미터)            │  │
  │  │  │   ├─ mcp_service (서비스 매핑 메타데이터)                  │  │
  │  │  │   └─ mcp_service_factors (Internal 파라미터 설정)          │  │
  │  │  └─ ...                                                        │  │
  │  └───────────────────────────────────────────────────────────────┘  │
  │                                                                      │
  │  [속성 추가/삭제/수정]  [Internal toggle 설정]                      │
  └─────────────────────────────────────────────────────────────────────┘
```

---

### Phase 3: Save 시 데이터 분리

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Phase 3: Save 데이터 분리                         │
└──────────────────────────────────────────────────────────────────────────┘

                    ┌───────────────────┐
                    │   웹에디터 Save   │
                    │   버튼 클릭       │
                    └─────────┬─────────┘
                              │
              │
              ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ tool_definition_templates.yaml (Single Source of Truth)    │
  └─────────────────────────────────────────────────────────────┘
              │
              ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ • name                                                      │
  │ • description                                               │
  │ • inputSchema                                               │
  │ • mcp_service (서비스 매핑)                                 │
  │ • mcp_service_factors                                       │
  │   ├─ Internal 파라미터 (source: "internal")                 │
  │   └─ Signature Defaults (source: "signature_defaults")      │
  │                                                             │
  │ 용도: 웹에디터 저장 + 서버 런타임 로드                        │
  │ (tool_definitions.py는 더 이상 생성 안함)                    │
  └─────────────────────────────────────────────────────────────┘
```

---

### Phase 4: Generate Server

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Phase 4: Generate Server                          │
└──────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │                    generate_universal_server.py                      │
  │                         prepare_context()                            │
  └─────────────────────────────────────────────────────────────────────┘
                                   │
       ┌───────────────────────────┼───────────────────────────┐
       │                           │                           │
       ▼                           ▼                           ▼
  ┌──────────┐              ┌──────────┐              ┌──────────┐
  │  REST    │              │  STDIO   │              │  Stream  │
  │ Template │              │ Template │              │ Template │
  └────┬─────┘              └────┬─────┘              └────┬─────┘
       │                         │                         │
       ▼                         ▼                         ▼
  ┌──────────┐              ┌──────────┐              ┌──────────┐
  │ server_  │              │ server_  │              │ server_  │
  │ rest.py  │              │ stdio.py │              │ stream.py│
  └──────────┘              └──────────┘              └──────────┘


  Context 구조:
  ┌─────────────────────────────────────────────────────────────────────┐
  │ {                                                                    │
  │   'server_name': 'outlook',                                         │
  │   'protocol_type': 'rest' | 'stdio' | 'stream',                     │
  │   'services': { 서비스 라우팅 정보 },                               │
  │   'tools': [ 도구별 파라미터/핸들러 정보 ],                         │
  │   'param_types': [ Pydantic 타입 목록 ],                            │
  │   'type_info': { import 경로 정보 }                                 │
  │ }                                                                    │
  └─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 파라미터 매핑 구조

### targetParam 매핑 흐름

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       targetParam 매핑 흐름                               │
└──────────────────────────────────────────────────────────────────────────┘

  inputSchema (LLM이 보는 이름)          실제 서비스 메서드
  ─────────────────────────────          ─────────────────────

  ┌─────────────────────┐                ┌─────────────────────┐
  │ 'DatePeriodFilter'  │ ──targetParam──▶│ 'filter_params'     │
  │ (Schema Property)   │                │ (메서드 파라미터)   │
  └─────────────────────┘                └─────────────────────┘

  tool_definition_templates.py:
  ┌─────────────────────────────────────────────────────────────────────┐
  │ 'inputSchema': {                                                     │
  │     'properties': {                                                  │
  │         'DatePeriodFilter': {           ← LLM이 보는 이름            │
  │             'targetParam': 'filter_params',  ← 실제 파라미터명       │
  │             'baseModel': 'FilterParams',                             │
  │             ...                                                      │
  │         }                                                            │
  │     }                                                                │
  │ }                                                                    │
  └─────────────────────────────────────────────────────────────────────┘
```

---

### Internal Args 매핑 흐름 (mcp_service_factors 기반)

```
┌──────────────────────────────────────────────────────────────────────────┐
│              Internal Args 매핑 흐름 (mcp_service_factors 기반)           │
└──────────────────────────────────────────────────────────────────────────┘

  tool_definition_templates.py           실제 서비스 메서드
  (mcp_service_factors)                  ─────────────────────
  ─────────────────────────

  ┌─────────────────────┐                ┌─────────────────────┐
  │ 'select_internal'   │ ──targetParam──▶│ 'select_params'     │
  │ (Internal arg 이름) │                │ (메서드 파라미터)   │
  └─────────────────────┘                └─────────────────────┘

  mcp_service_factors 구조 (tool_definition_templates.py 내):
  ┌─────────────────────────────────────────────────────────────────────┐
  │ "mcp_service_factors": {                                            │
  │     "select_internal": {                  ← Internal arg 이름        │
  │         "source": "internal",             ← LLM에게 완전히 숨김      │
  │         "baseModel": "SelectParams",                                 │
  │         "description": "선택 필드 설정",                             │
  │         "parameters": {                                              │
  │             "id": {"default": true},                                 │
  │             "subject": {"default": true}                             │
  │         }                                                            │
  │     }                                                                │
  │ }                                                                    │
  └─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 핸들러 처리 흐름 (런타임)

### 전체 처리 흐름도

```
┌─────────────────┐
│  LLM 입력(args) │
└────────┬────────┘
         ↓
┌─────────────────────┐
│ 1. 파라미터 추출    │ ← 필수/선택 파라미터 분리
└────────┬────────────┘
         ↓
┌─────────────────────────┐
│ 2. 딕셔너리 → 객체 변환 │ ← Pydantic 타입 변환 + 첫 번째 병합
└────────┬────────────────┘
         ↓
┌──────────────────────┐
│ 3. call_args 구성    │ ← Signature 파라미터 설정
└────────┬─────────────┘
         ↓
┌────────────────────────────┐
│ 4. Signature Defaults 적용 │ ← LLM 미입력 시 기본값 적용
└────────┬───────────────────┘
         ↓
┌──────────────────────┐
│ 5. Internal 구성     │ ← 시스템 고정값 로드
└────────┬─────────────┘
         ↓
┌──────────────────────────────────────────────────────┐
│ 6. 파라미터 병합                                     │
│    ← (Signature > Signature Defaults > Internal)    │
└────────┬─────────────────────────────────────────────┘
         ↓
┌──────────────────────┐
│ 7. 서비스 함수 호출  │ ← 비즈니스 로직 실행
└────────┬─────────────┘
         ↓
┌──────────────────┐
│   결과 반환      │
└──────────────────┘
```

---

### 단계별 상세 설명

#### 1단계: 파라미터 추출 (Extract parameters from args)

LLM이 전달한 `args` 딕셔너리에서 각 파라미터를 추출합니다.

```python
# 필수 파라미터 - 직접 접근
user_email = args["user_email"]

# 선택 파라미터 - .get() 사용하여 안전하게 추출
query_method_raw = args.get("query_method")

# Enum 타입 기본값 처리
query_method = query_method_raw if query_method_raw is not None else QueryMethod.FILTER

# 일반 기본값 처리
top = args.get("top") if args.get("top") is not None else 50
```

**핵심 포인트:**
- 필수 파라미터: `args["key"]` 직접 접근
- 선택 파라미터: `args.get("key")` 사용
- 기본값이 있는 경우 None 체크 후 할당

---

#### 2단계: 파라미터 객체 변환 - 첫 번째 병합

딕셔너리 형태의 복합 파라미터를 Pydantic 객체로 변환합니다.
**첫 번째 병합: Signature 파라미터 내부의 Internal 데이터와 사용자 입력 병합**

```python
# Internal 데이터 준비 (파라미터별 Internal 값이 있을 경우)
DatePeriodFilter_internal_data = {}  # 예: {"start": "2024-01-01"}

# 첫 번째 병합: 파라미터 내부의 Internal과 사용자 입력 병합
DatePeriodFilter_data = merge_param_data(
    DatePeriodFilter_internal_data,  # base: 파라미터별 Internal 데이터
    DatePeriodFilter                 # overlay: 사용자가 입력한 값
)

# Pydantic 객체로 변환
if DatePeriodFilter_data is not None:
    DatePeriodFilter_params = FilterParams(**DatePeriodFilter_data)
else:
    DatePeriodFilter_params = None
```

**핵심 포인트:**
- 각 Signature 파라미터가 자체 Internal 데이터를 가질 수 있음
- `merge_param_data()`로 파라미터 내부 병합 수행
- **병합 우선순위: 사용자 입력 > 파라미터별 Internal**

---

#### 3단계: 호출 인자 준비 (Prepare call arguments)

실제 서비스 함수 호출을 위한 딕셔너리를 구성합니다.

```python
call_args = {}

# Signature 파라미터들을 call_args에 추가
call_args["user_email"] = user_email
call_args["query_method"] = query_method
call_args["filter_params"] = DatePeriodFilter_params
call_args["select_params"] = select_params_params
```

**핵심 포인트:**
- 서비스 함수의 실제 파라미터명을 키로 사용
- 변환된 Pydantic 객체들을 값으로 할당

---

#### 4단계: Signature Defaults 적용

LLM이 값을 제공하지 않은 Signature 파라미터에 기본값을 적용합니다.
`mcp_service_factors`에서 `source: "signature_defaults"`로 정의된 값들입니다.

```python
# Signature Defaults 파라미터 적용 (LLM이 값을 제공하지 않은 경우)
if "top" not in call_args or call_args["top"] is None:
    top_defaults = get_signature_defaults("mail_list_period", "top")
    if top_defaults:
        call_args["top"] = top_defaults
```

**핵심 포인트:**
- LLM에게 노출되지만, 값을 제공하지 않으면 기본값 사용
- `source: "signature_defaults"`로 설정된 파라미터에 적용
- Signature(사용자 입력)보다 우선순위 낮음, Internal보다 높음

---

#### 5단계: Internal 파라미터 처리

`mcp_service_factors`에 정의된 숨겨진 파라미터를 구성합니다. (source: "internal")

```python
# Internal 파라미터 빌드 (mcp_service_factors에서 로드)
_internal_select = build_internal_param("mail_list_period", "select")
```

**핵심 포인트:**
- Internal 파라미터는 LLM에 노출되지 않는 시스템 고정값
- `build_internal_param()`으로 `mcp_service_factors`에서 값 로드

---

#### 6단계: 파라미터 병합 - 두 번째 병합

Signature 파라미터, Signature Defaults, Internal 파라미터를 병합합니다.
**두 번째 병합: 도구 레벨의 Internal 파라미터와 Signature 파라미터 병합**

```python
if "select_params" in call_args:
    # Signature에 이미 select_params가 있는 경우
    existing_value = call_args["select_params"]

    if hasattr(existing_value, '__dict__') and hasattr(_internal_select, '__dict__'):
        # 두 번째 병합: 객체의 속성 단위로 병합
        internal_dict = {k: v for k, v in vars(_internal_select).items() if v is not None}
        existing_dict = {k: v for k, v in vars(existing_value).items() if v is not None}

        # Internal을 base로, Signature로 덮어씀
        merged_dict = {**internal_dict, **existing_dict}
        call_args["select_params"] = type(existing_value)(**merged_dict)
else:
    # Signature에 없으면 Internal 값만 사용
    call_args["select_params"] = _internal_select
```

**핵심 포인트:**
- **targetParam 매핑**: Internal이 Signature의 특정 파라미터로 매핑될 수 있음
- **병합 우선순위: Signature(사용자 입력) > Internal(도구 레벨 기본값)**
- None 값은 병합에서 제외 (기존 값 유지)

---

#### 7단계: 서비스 함수 호출

최종 준비된 인자로 실제 비즈니스 로직을 호출합니다.

```python
return await mail_service.query_mail_list(**call_args)
```

---

### 생성된 핸들러 예시

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       생성된 핸들러 예시                                   │
└──────────────────────────────────────────────────────────────────────────┘

  async def handle_mail_list_period(args):

      ┌─────────────────────────────────────────────────────────────────┐
      │ Step 1: inputSchema에서 온 파라미터 추출                        │
      └─────────────────────────────────────────────────────────────────┘
      DatePeriodFilter_raw = args.get("DatePeriodFilter")
      filter_params = FilterParams(**DatePeriodFilter_raw)
                │
                │  LLM 입력 → Pydantic 객체 변환
                ▼
      ┌─────────────────────────────────────────────────────────────────┐
      │ Step 2: Internal args 빌드 (targetParam으로 매핑)               │
      └─────────────────────────────────────────────────────────────────┘
      select_params = build_internal_param("mail_list_period", "select")
                │
                │  JSON 설정 → Pydantic 객체 생성
                ▼
      ┌─────────────────────────────────────────────────────────────────┐
      │ Step 3: 서비스 메서드 호출                                      │
      └─────────────────────────────────────────────────────────────────┘
      return await mail_service.query_mail_list(
          filter_params=filter_params,      ← inputSchema에서 변환
          select_params=select_params       ← Internal args에서 생성
      )
```

---

## 5. 파라미터 병합 체계

### 파라미터 4단계 구조

1. **Signature 파라미터** (사용자 입력)
   - LLM이 직접 제공하는 값
   - 최고 우선순위

2. **Signature Defaults** (기본값)
   - LLM에게 노출되지만, 값을 제공하지 않으면 적용되는 기본값
   - `source: "signature_defaults"`로 정의
   - 4단계에서 적용됨

3. **Signature 내부 Internal** (파라미터별 Internal)
   - 특정 Signature 파라미터가 가진 자체 Internal 데이터
   - 예: `DatePeriodFilter_internal_data = {"start": "2024-01-01"}`
   - 2단계에서 병합됨

4. **도구 레벨 Internal** (전역 Internal)
   - `mcp_service_factors`에 정의된 도구 전체 Internal (source: "internal")
   - targetParam으로 특정 Signature 파라미터에 매핑
   - 6단계에서 병합됨

### 두 번의 병합 과정

#### 첫 번째 병합 (2단계)
```
Signature 내부 Internal + 사용자 입력 = Signature 파라미터 객체
```
- 각 Signature 파라미터 내부에서 발생
- 파라미터별 Internal과 사용자 입력 병합

#### 두 번째 병합 (6단계)
```
도구 레벨 Internal + Signature Defaults + Signature 파라미터 객체 = 최종 파라미터
```
- 도구 전체 레벨에서 발생
- targetParam 매핑을 통해 특정 파라미터로 병합
- Signature Defaults는 4단계에서 먼저 적용됨

### 최종 우선순위

```
사용자 입력 > Signature 내부 Internal > 도구 레벨 Internal > 기본값
```

### 주요 원칙

**None 값 처리:**
- 병합 시 None 값은 제외됨
- 이를 통해 부분 업데이트 가능
- 명시적으로 설정하지 않은 필드는 기본값 유지

**타입 안전성:**
- Pydantic을 통한 타입 검증
- 딕셔너리를 타입 안전한 객체로 변환
- 런타임 타입 체크 보장

---

## 6. 핵심 저장 위치 요약

```
┌────────────────┬──────────────────┬───────────────────────────┬──────────────────┐
│     데이터     │       소스       │        저장 위치           │       용도       │
├────────────────┼──────────────────┼───────────────────────────┼──────────────────┤
│ 클래스/메서드  │ @mcp_service     │ registry_{server}.json    │ 서비스 라우팅    │
│ 정보           │ 데코레이터       │                           │                  │
├────────────────┼──────────────────┼───────────────────────────┼──────────────────┤
│ 파라미터       │ 함수 시그니처    │ registry_{server}.json    │ 타입 검증        │
│ 타입/기본값    │                  │                           │                  │
├────────────────┼──────────────────┼───────────────────────────┼──────────────────┤
│ LLM용 스키마   │ 웹에디터 편집    │ tool_definition_          │ Claude API       │
│                │                  │ templates.yaml            │                  │
├────────────────┼──────────────────┼───────────────────────────┼──────────────────┤
│ targetParam    │ 웹에디터 설정    │ tool_definition_          │ 파라미터 변환    │
│ 매핑           │                  │ templates.yaml            │                  │
├────────────────┼──────────────────┼───────────────────────────┼──────────────────┤
│ Internal       │ 웹에디터 토글    │ tool_definition_          │ 런타임 주입      │
│ 파라미터       │                  │ templates.yaml            │                  │
│                │                  │ (mcp_service_factors)     │                  │
├────────────────┼──────────────────┼───────────────────────────┼──────────────────┤
│ Signature      │ 웹에디터 토글    │ tool_definition_          │ 기본값 제공      │
│ Defaults       │                  │ templates.yaml            │                  │
│                │                  │ (mcp_service_factors)     │                  │
└────────────────┴──────────────────┴───────────────────────────┴──────────────────┘
```

---

## 7. 전체 데이터 변환 흐름

```
[소스코드]                  [웹에디터]                [생성된 서버]
────────────                ──────────                ────────────

@mcp_service ──────────▶ registry.json ──────────▶ import 경로
     │                        │                        │
     ▼                        ▼                        ▼
outlook_service.py ────▶ mcp_service ────────────▶ 핸들러 서명
     │                   .parameters                   │
     ▼                        │                        ▼
outlook_types.py ──────▶ inputSchema ────────────▶ Pydantic 변환
     │                   .baseModel                    │
     ▼                        │                        ▼
(웹에서 편집) ─────────▶ mcp_service_ ───────────▶ build_internal
                         factors                   _param()
                         (source별 구분)
```

---

## 8. 호출 함수/메서드 명세

### 빌드 타임 호출 체인

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        빌드 타임 호출 체인                                 │
└──────────────────────────────────────────────────────────────────────────┘

1. 레지스트리 스캔 (웹에디터 시작 시)
────────────────────────────────────────
mcp_editor/mcp_service_registry/mcp_service_scanner.py
  └─→ scan_codebase_for_mcp_services()     # L252
        │
        ├─→ AST NodeVisitor로 @mcp_service 데코레이터 파싱
        │
        └─→ registry_{server}.json 생성/업데이트


2. 서버 생성 (Generate Server 클릭 시)
────────────────────────────────────────
mcp_editor/tool_editor_web.py
  └─→ generate_server_from_web()           # L1738 - POST /api/server-generator
        │
        └─→ jinja/generate_universal_server.py
              │
              ├─→ extract_internal_args_from_tools()  # L24
              │     └─→ mcp_service_factors에서 source='internal' 추출
              │
              ├─→ prepare_context()        # L238
              │     ├─→ registry_{server}.json 로드
              │     ├─→ tool_definition_templates.py 로드
              │     ├─→ internal_args를 context에 포함
              │     └─→ Jinja2 context 딕셔너리 생성
              │
              └─→ generate_server()        # L465
                    ├─→ universal_server_template.jinja2 렌더링
                    └─→ server_{protocol}.py 파일 생성
```

### 런타임 호출 체인

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        런타임 호출 체인                                    │
└──────────────────────────────────────────────────────────────────────────┘

LLM 요청 수신 (MCP 서버)
────────────────────────────────────────
mcp_{service}/mcp_server/server_{protocol}.py

  1. 핸들러 함수 호출
  └─→ handle_{tool_name}(args)            # 자동 생성된 핸들러
        │
        ├─→ args["param"] / args.get("param")  # 파라미터 추출
        │
        ├─→ build_internal_param()        # L180 (server_rest.py 예시)
        │     │
        │     │   정의 위치: jinja/universal_server_template.jinja2 L213
        │     │   생성 위치: mcp_{service}/mcp_server/server_{protocol}.py
        │     │
        │     ├─→ INTERNAL_ARGS[tool_name][arg_name] 조회
        │     ├─→ runtime_value와 병합 (있는 경우)
        │     └─→ Pydantic 객체 생성 및 반환
        │
        ├─→ merge_param_data()            # L229 (server_rest.py 예시)
        │     │
        │     │   정의 위치: jinja/universal_server_template.jinja2 L262
        │     │   생성 위치: mcp_{service}/mcp_server/server_{protocol}.py
        │     │
        │     ├─→ internal_data (base)와 runtime_data (overlay) 병합
        │     ├─→ None 값 필터링
        │     └─→ 병합된 딕셔너리 반환
        │
        └─→ {service_instance}.{method}(**call_args)  # 비즈니스 로직 호출
              │
              │   예: mail_service.query_mail_list(**call_args)
              │
              └─→ 결과 반환
```

### 핵심 함수 상세

| 함수명 | 정의 위치 | 호출 시점 | 역할 |
|--------|----------|----------|------|
| `scan_codebase_for_mcp_services()` | `mcp_service_scanner.py:252` | 웹에디터 시작/Reload | @mcp_service 스캔 → registry.json |
| `extract_internal_args_from_tools()` | `generate_universal_server.py:24` | Generate Server | mcp_service_factors에서 Internal 추출 |
| `prepare_context()` | `generate_universal_server.py:238` | Generate Server | 템플릿 렌더링용 context 생성 |
| `generate_server()` | `generate_universal_server.py:465` | Generate Server | Jinja2로 서버 코드 생성 |
| `build_internal_param()` | `universal_server_template.jinja2:204` | 런타임 핸들러 | Internal 파라미터 빌드 |
| `merge_param_data()` | `universal_server_template.jinja2:253` | 런타임 핸들러 | 파라미터 병합 |
| `handle_{tool_name}()` | 생성된 `server_{protocol}.py` | LLM 요청 수신 | MCP Tool 핸들러 |

### registry_{server}.json 구조

```json
{
  "version": "1.0",
  "server_name": "outlook",
  "services": {
    "query_mail_list": {
      "service_name": "query_mail_list",
      "handler": {
        "class_name": "MailService",           // 클래스명
        "module_path": "outlook.outlook_service", // import 경로
        "instance": "mail_service",            // 인스턴스 변수명
        "method": "query_mail_list",           // 메서드명
        "is_async": true,
        "file": "/path/to/outlook_service.py",
        "line": 62
      },
      "signature": "user_email: str, filter_params: Optional[FilterParams] = None, ...",
      "parameters": [
        {
          "name": "user_email",
          "type": "str",
          "default": null,
          "has_default": false,
          "is_required": true
        },
        {
          "name": "filter_params",
          "type": "Optional[FilterParams]",
          "default": null,
          "has_default": true,
          "is_required": false
        }
      ],
      "metadata": {
        "description": "메일 리스트 조회 기능",
        "category": "outlook_mail",
        "tags": ["query", "search"],
        "tool_names": ["Handle_query_mail_list"],
        "priority": 5
      }
    }
  }
}
```

### 호출 흐름 요약도

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           호출 흐름 요약                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [빌드 타임]                                                            │
│                                                                         │
│  @mcp_service 데코레이터                                                │
│       │                                                                 │
│       ▼                                                                 │
│  scan_codebase_for_mcp_services()  ──→  registry_{server}.json         │
│                                                                         │
│  웹에디터 편집                                                          │
│       │                                                                 │
│       ▼                                                                 │
│  tool_definition_templates.py (mcp_service_factors 포함)               │
│       │                                                                 │
│       ▼                                                                 │
│  prepare_context()  ──→  generate_server()  ──→  server_{protocol}.py  │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [런타임]                                                               │
│                                                                         │
│  LLM 요청 (args)                                                        │
│       │                                                                 │
│       ▼                                                                 │
│  handle_{tool_name}(args)                                               │
│       │                                                                 │
│       ├──→ build_internal_param()  ──→  Internal 파라미터 생성         │
│       │                                                                 │
│       ├──→ merge_param_data()  ──→  Signature + Internal 병합          │
│       │                                                                 │
│       └──→ service.method(**call_args)  ──→  결과 반환                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 9. registry_{server}.json의 역할 - 중간 저장소 (Bridge)

### 핵심 개념

`registry_{server}.json`은 **소스코드와 웹에디터 사이의 중간 저장소(Bridge)** 역할을 합니다.

```
┌─────────────────────────┐     스캔      ┌─────────────────────────┐     표시      ┌─────────────────┐
│   outlook_service.py    │  ──────────>  │  registry_outlook.json  │  ──────────>  │    웹에디터     │
│   (@mcp_service 데코레이터)│              │    (중간 저장소)          │               │   (UI 표시)     │
└─────────────────────────┘               └─────────────────────────┘               └─────────────────┘
                                                     │
                                                     │ 서버 생성
                                                     ▼
                                          ┌─────────────────────────┐
                                          │  server_{protocol}.py   │
                                          │  (생성된 서버 파일)       │
                                          └─────────────────────────┘
```

### 저장되는 정보

| 정보 | 설명 | 용도 |
|------|------|------|
| **handler** | 실제 호출할 클래스/메서드 정보 | 서버 코드 생성 시 import 경로, 인스턴스 생성에 사용 |
| **parameters** | 메서드의 파라미터 목록, 타입, 기본값 | 타입 검증, 핸들러 코드 생성에 사용 |
| **metadata** | 카테고리, 태그, tool_names 등 | 웹에디터 UI 표시, 도구 분류에 사용 |

### handler 구조 상세

```json
{
  "handler": {
    "class_name": "MailService",              // 서비스 클래스명
    "module_path": "outlook.outlook_service", // Python import 경로
    "instance": "mail_service",               // 인스턴스 변수명
    "method": "query_mail_list",              // 호출할 메서드명
    "is_async": true,                         // 비동기 여부
    "file": "/path/to/outlook_service.py",    // 소스 파일 경로
    "line": 62                                // 정의된 라인 번호
  }
}
```

### 데이터 흐름 상세

1. **소스코드** (`outlook_service.py`)에 `@mcp_service` 데코레이터가 붙은 함수들
2. **스캐너** (`mcp_service_scanner.py`)가 자동 스캔하여 `registry_outlook.json` 생성/갱신
3. **웹에디터**가 이 JSON을 읽어서 UI에 도구 목록 표시
4. **서버 생성** 시 이 정보 + `tool_definition_templates.py`를 조합하여 최종 서버 파일 생성

### 다른 파일들과의 관계

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          2개 파일의 역할 분담 (단순화)                        │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  registry_{server}.json                    tool_definition_templates.yaml  │
│  (구현 정보)                               (LLM 스키마 + 파라미터 설정)      │
│                                                                            │
│  ┌──────────────────┐                   ┌──────────────────────────────┐  │
│  │ • 어떤 클래스?    │                   │ • LLM에게 뭘 보여줄지?          │  │
│  │ • 어떤 메서드?    │                   │ • inputSchema                 │  │
│  │ • 파라미터 타입?  │                   │ • description                 │  │
│  │ • async 여부?    │                   │ • mcp_service 매핑            │  │
│  └──────────────────┘                   │ • mcp_service_factors         │  │
│           │                              │   (Internal + SignatureDefaults)│  │
│           │                              └──────────────────────────────┘  │
│           │                                           │                    │
│           └────────────────────┬──────────────────────┘                    │
│                                │                                            │
│                                ▼                                            │
│               ┌──────────────────────────────────────┐                     │
│               │  generate_universal_server.py         │                     │
│               │  (2개 파일 조합 → 서버 코드 생성)      │                     │
│               └──────────────────────────────────────┘                     │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### mcp_service_factors 구조

```json
{
  "mcp_service_factors": {
    "exclude_params_internal": {
      "source": "internal",           // LLM에게 숨김
      "baseModel": "ExcludeParams",
      "parameters": { ... }
    },
    "select_params": {
      "source": "signature_defaults", // LLM에게 보이지만 기본값 있음
      "baseModel": "SelectParams",
      "parameters": { ... }
    }
  }
}
```

### 변경 시점

| 파일 | 변경 시점 | 변경 주체 |
|------|----------|----------|
| `registry_{server}.json` | 소스코드 변경 후 스캔 시 | `mcp_service_scanner.py` 자동 생성 |
| `tool_definition_templates.yaml` | 웹에디터에서 Save 시 | 웹에디터 UI (mcp_service_factors 포함) |

---

## 10. 서버 병합 데이터 흐름

### 병합 개념

여러 MCP 서버(예: outlook + calendar)를 하나의 통합 서버(ms365)로 병합합니다.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         서버 병합 데이터 흐름                                  │
└─────────────────────────────────────────────────────────────────────────────┘

  소스 서버들                          병합 프로세스                   결과
  ────────────                        ──────────────                 ──────

  ┌───────────────┐
  │ mcp_outlook   │───┐
  │ • 7개 도구    │   │
  │ • registry    │   │      ┌─────────────────────┐
  │ • YAML        │   ├────▶│ generate_universal_ │
  └───────────────┘   │      │ server.py merge     │
                      │      │                     │
  ┌───────────────┐   │      │ • merge_tool_       │      ┌───────────────┐
  │ mcp_calendar  │───┘      │   definitions()     │────▶│ mcp_ms365     │
  │ • 6개 도구    │          │ • merge_registries()│      │ • 13개 도구   │
  │ • registry    │          │ • 타입 스캔 통합     │      │ • 3 프로토콜  │
  │ • YAML        │          └─────────────────────┘      └───────────────┘
  └───────────────┘
```

### 병합 시 데이터 처리

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         병합 시 데이터 변환                                 │
└──────────────────────────────────────────────────────────────────────────┘

1. YAML 병합 (merge_tool_definitions)
   ───────────────────────────────────
   outlook/tool_definition_templates.yaml  ─┐
                                            ├──▶ ms365/tool_definition_templates.yaml
   calendar/tool_definition_templates.yaml ─┘

2. Registry 병합 (merge_registries)
   ───────────────────────────────────
   registry_outlook.json  ─┐
                           ├──▶ registry_ms365.json
   registry_calendar.json ─┘

   * module_path 정규화: outlook → mcp_outlook

3. 타입 스캔 통합 (find_type_locations_multi)
   ───────────────────────────────────
   mcp_outlook/*_types.py   ─┐
                              ├──▶ 통합 type_info
   mcp_calendar/*_types.py  ─┘

4. 도구 이름 충돌 해결
   ───────────────────────────────────
   prefix 모드: auto / always / none
   충돌 시: outlook_mail_list, calendar_list_events
```

### 병합 관련 API

| API | 메서드 | 설명 |
|-----|--------|------|
| `/api/merge-servers` | POST | 서버 병합 실행 |

### 병합 설정 (editor_config.json)

```json
{
  "ms365": {
    "is_merged": true,
    "source_profiles": ["outlook", "calendar"],
    "tool_definitions_path": "../mcp_ms365/mcp_server/tool_definitions.py",
    "port": 8090
  }
}
```

---

## 11. 대시보드 및 프로토콜별 제어

### 대시보드 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         대시보드 데이터 흐름                                   │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌───────────────────┐         ┌─────────────────────┐         ┌─────────────┐
  │  웹에디터 UI      │  GET    │  /api/server/       │  조회    │ 프로세스    │
  │  (MCP 로고 클릭)  │────────▶│  dashboard          │────────▶│ 상태 확인   │
  └───────────────────┘         └─────────────────────┘         └─────────────┘
                                         │
                                         ▼
                                ┌─────────────────────┐
                                │  응답 구조           │
                                │  {                  │
                                │    profiles: [      │
                                │      {              │
                                │        profile,     │
                                │        protocols: { │
                                │          rest: {},  │
                                │          stdio: {}, │
                                │          stream: {} │
                                │        }            │
                                │      }              │
                                │    ]                │
                                │  }                  │
                                └─────────────────────┘
```

### 프로토콜별 독립 제어

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      프로토콜별 프로세스 관리                               │
└──────────────────────────────────────────────────────────────────────────┘

  outlook 프로필
  ─────────────────────────────────────────────────────────────

  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
  │  REST Server    │   │  STDIO Server   │   │  Stream Server  │
  │  (독립 프로세스) │   │  (독립 프로세스) │   │  (독립 프로세스) │
  └────────┬────────┘   └────────┬────────┘   └────────┬────────┘
           │                     │                     │
           ▼                     ▼                     ▼
  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
  │ PID: 12345      │   │ PID: 12346      │   │ PID: 12347      │
  │ Port: 8091      │   │ (stdio)         │   │ Port: 8092      │
  │ Log: rest.log   │   │ Log: stdio.log  │   │ Log: stream.log │
  └─────────────────┘   └─────────────────┘   └─────────────────┘
```

### 대시보드 API

| API | 메서드 | 설명 |
|-----|--------|------|
| `/api/server/dashboard` | GET | 전체 프로필 상태 조회 |
| `/api/server/start?profile=X&protocol=Y` | POST | 특정 프로토콜 시작 |
| `/api/server/stop?profile=X&protocol=Y` | POST | 특정 프로토콜 중지 |
| `/api/server/restart?profile=X&protocol=Y` | POST | 특정 프로토콜 재시작 |
| `/api/server/logs?profile=X&protocol=Y&lines=N` | GET | 프로토콜별 로그 조회 |
| `/api/server/port` | PUT | 포트 변경 |

### 프로필 계층 구조

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         프로필 타입 구분                                    │
└──────────────────────────────────────────────────────────────────────────┘

  Base Profile                  Reused Profile               Merged Profile
  ────────────                  ──────────────               ──────────────

  ┌─────────────┐              ┌─────────────┐              ┌─────────────┐
  │  outlook    │───────────▶ │outlook_read │              │   ms365     │
  │             │  재사용      │             │              │             │
  │ is_base:true│              │is_reused:   │              │is_merged:   │
  │             │              │ true        │              │ true        │
  │ source_dir: │              │base_profile:│              │source_      │
  │ mcp_outlook │              │ outlook     │              │ profiles:   │
  └─────────────┘              └─────────────┘              │[outlook,    │
                                                            │ calendar]   │
                                                            └─────────────┘
```

### 관련 파일

| 파일 | 역할 |
|------|------|
| `mcp_editor/mcp_server_controller.py` | 프로토콜별 프로세스 관리 |
| `mcp_editor/static/js/tool_editor_dashboard.js` | 대시보드 UI 로직 |
| `mcp_editor/static/js/tool_editor_server.js` | 서버 제어 UI |
| `mcp_editor/tool_editor_core/routes/server_routes.py` | 서버/대시보드 API |

---

## 12. 파일 경로 참조

| 구분 | 경로 |
|------|------|
| 웹에디터 | `mcp_editor/tool_editor_web.py` |
| 레지스트리 스캐너 | `mcp_editor/mcp_service_registry/mcp_service_scanner.py` |
| 레지스트리 | `mcp_editor/mcp_service_registry/registry_{server}.json` |
| 템플릿 정의 | `mcp_editor/mcp_{server}/tool_definition_templates.yaml` |
| 서버 생성 | `jinja/generate_universal_server.py` |
| Jinja2 템플릿 | `jinja/universal_server_template.jinja2` |
| 생성된 서버 | `mcp_{service}/mcp_server/server_{protocol}.py` |
| 서버 컨트롤러 | `mcp_editor/mcp_server_controller.py` |
| 대시보드 JS | `mcp_editor/static/js/tool_editor_dashboard.js` |

> **Note**: `tool_definitions.py`는 더 이상 생성되지 않음. 서버 코드가 런타임에 YAML에서 직접 로드.

---

*관련: [terminology.md](../commands/terminology.md), [web.md](../commands/web.md), [handler.md](../commands/handler.md)*
*Version: 3.3*
*Last Updated: 2026-01-11*
*변경사항: 역할 분리 명시 - 본 문서가 전체 플로우 상세 담당*
