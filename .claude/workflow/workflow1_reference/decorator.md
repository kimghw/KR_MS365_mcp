# @mcp_service 데코레이터 / JSDoc

> **Python**: 데코레이터 사용 시 반드시 `service_registry.python.decorator`를 import하거나 fallback 패턴을 구현해야 합니다.
> **JavaScript**: JSDoc 주석 방식으로 `@mcp_service` 태그 사용 (데코레이터 문법 불필요)

## 요약

| 항목 | 내용 |
|:-----|:-----|
| **사용 스크립트** | `service_registry/scanner.py`, `service_registry/config_generator.py` |
| **사용 함수** | `scan_codebase_for_mcp_services()`, `find_mcp_services_in_python_file()`, `find_jsdoc_mcp_services_in_js_file()` |
| **입력** | Python: `@mcp_service` 데코레이터, JavaScript: `@mcp_service` JSDoc 주석 |
| **출력** | `mcp_{server}/registry_{server}.json`, `mcp_{server}/types_property_{server}.json`, `editor_config.json` |

```
[Python]     @mcp_service 데코레이터 → AST 스캔 → registry/types_property/config JSON 생성
[JavaScript] @mcp_service JSDoc 주석 → 정규식 스캔 → registry/types_property/config JSON 생성
```

## 파일 위치

- **Python 데코레이터**: `service_registry/python/decorator.py` (mcp_editor 기준 상대 경로)
- **JavaScript 스캐너**: `service_registry/scanner.py` (`find_jsdoc_mcp_services_in_js_file()`)

> **참고**: `service_registry` 패키지는 `mcp_editor/service_registry/`에 위치하며, interface 기반 시스템의 일부로 동작합니다. 하위 호환성을 유지하면서 확장 가능한 구조를 제공합니다.

## Import 방법

### Python

```python
# 방법 1: 직접 import (권장)
from service_registry.python.decorator import mcp_service

# 방법 2: 루트에서 import (하위 호환성 지원)
from service_registry import mcp_service
```

> **Interface 기반 시스템**: 데코레이터는 이제 interface 기반 시스템(`service_registry/interfaces.py`)의 일부이지만, 기존 import 경로를 통한 하위 호환성을 완전히 유지합니다. `service_registry/__init__.py`에서 re-export되어 두 가지 import 방식 모두 동작합니다.

### JavaScript (JSDoc 주석 방식)

JavaScript는 import 없이 JSDoc 주석으로 서비스를 정의합니다:

```javascript
/**
 * @mcp_service
 * @server_name your_server
 * @tool_name your_tool
 * @description 기능 설명
 */
```

## 지원 언어

| 언어 | 확장자 | 파서 | 서비스 정의 방식 |
|:-----|:------|:-----|:--------------|
| Python | `.py` | `ast` (내장) | `@mcp_service` 데코레이터 |
| JavaScript | `.js`, `.mjs` | regex (내장) + `esprima` (선택) | `@mcp_service` JSDoc 주석 |
| TypeScript | `.ts`, `.tsx` | `esprima` (선택) | `@McpService` 데코레이터 (기본 지원) |

> **참고**: JavaScript는 JSDoc 주석 방식을 기본으로 사용하며, esprima 파서는 선택적입니다

## 참조하는 파일

### 정의 파일
| 언어 | 파일 | 상태 |
|:-----|:-----|:-----|
| Python | `service_registry/python/decorator.py` | 구현됨 (interface 기반 시스템 통합) |
| JavaScript | JSDoc 주석 방식 (파일 불필요) | 구현됨 |

> **참고**: JavaScript는 JSDoc 주석을 사용하므로 별도 데코레이터 정의 파일 불필요
> **참고**: Python 데코레이터는 `service_registry/__init__.py`를 통해 re-export되어 하위 호환성 유지

### 서비스 정의 예시 파일
| 파일 | 언어 | 용도 |
|:-----|:-----|:-----|
| `mcp_outlook/outlook_service.py` | Python | Outlook 서비스 |
| `mcp_calendar/calendar_service.py` | Python | Calendar 서비스 |
| `mcp_asset_management/asset-api/services/crew.service.js` | JavaScript | 선원 관리 서비스 |
| `mcp_asset_management/asset-api/services/ship.service.js` | JavaScript | 선박 관리 서비스 |

### 스캔 함수
| 파일 | 함수 | 용도 |
|:-----|:-----|:-----|
| `service_registry/scanner.py` | `scan_codebase_for_mcp_services()` | 통합 스캔 (Python + JS + TS) |
| `service_registry/scanner.py` | `find_mcp_services_in_python_file()` | Python AST 파싱 |
| `service_registry/scanner.py` | `find_mcp_services_in_js_file()` | JavaScript/TypeScript esprima 파싱 |
| `service_registry/scanner.py` | `find_jsdoc_mcp_services_in_js_file()` | JavaScript JSDoc 정규식 파싱 |
| `service_registry/scanner.py` | `export_services_to_json()` | registry + types_property JSON 생성 |
| `service_registry/config_generator.py` | `extract_server_info_from_py_file()` | Python server_name + 타입 정보 추출 |
| `service_registry/config_generator.py` | `extract_server_info_from_js_file()` | JavaScript server_name + 타입 정보 추출 |
| `service_registry/config_generator.py` | `extract_server_name_from_py_file()` | Python server_name 추출 (레거시) |
| `service_registry/config_generator.py` | `extract_server_name_from_js_file()` | JavaScript server_name 추출 (레거시) |
| `service_registry/config_generator.py` | `scan_codebase_for_server_info()` | 전체 서버 정보 스캔 (타입 정보 포함) |
| `service_registry/config_generator.py` | `scan_codebase_for_servers()` | 전체 서버명 스캔 (레거시) |

### 메타데이터 활용
| 파일 | 용도 |
|:-----|:-----|
| `service_registry.py` | 서비스 레지스트리 구축 |
| `meta_registry.py` | 메타 레지스트리 관리 |
| `tool_loader.py` | 툴 정의 로딩 시 서비스 팩터 추출 |

---

## 서비스 정의 문법

### 파라미터 비교

| 파라미터 | Python | JavaScript JSDoc | TypeScript | 필수 |
|:---------|:-------|:-----------------|:-----------|:-----|
| Tool 이름 | `tool_name` | `@tool_name` | `toolName` | O |
| 서버 식별자 | `server_name` | `@server_name` | `serverName` | O |
| 메서드명 | `service_name` | `@service_name` | `serviceName` | 선택 (기본: 함수명) |
| 기능 설명 | `description` | `@description` | `description` | O |
| 카테고리 | `category` | `@category` | `category` | 권장 |
| 태그 | `tags` | `@tags` | `tags` | 권장 |
| **타입 파일 경로** | import 문에서 자동 추출 | `@types_file` | - | 선택 (컨벤션 불일치 시 사용) |
| 우선순위 | `priority` | - | - | 선택 |
| 관련 객체 | `related_objects` | - | - | 선택 |
| 시그니처 오버라이드 | `service_signature` | - | - | 선택 |
| 레지스트리 포함 | `include_in_registry` | - | - | 선택 (기본: True) |
| 파라미터 | 함수 시그니처 | `@param` | 함수 시그니처 | 자동 |
| 반환 타입 | 타입 힌트 | `@returns` | 타입 힌트 | 자동 |

### Python

```python
from service_registry.python.decorator import mcp_service

@mcp_service(
    tool_name="handler_mail_list",       # 필수: MCP Tool 이름
    server_name="outlook",               # 필수: 서버 식별자, 사용: editor_config.json
    service_name="query_mail_list",      # 필수: 메서드명
    description="메일 리스트 조회 기능",    # 필수: 기능 설명
    category="outlook_mail",             # 권장: 카테고리
    tags=["query", "search"],            # 권장: 태그
    priority=5,                          # 선택: 우선순위 (1-10)
    related_objects=["mcp_outlook/outlook_types.py"],  # 선택: 관련 객체
    service_signature=None,              # 선택: 시그니처 오버라이드
    include_in_registry=True,            # 선택: 레지스트리 포함 여부
)
async def query_mail_list(
    self,
    user_email: str,
    filter_params: Optional[FilterParams] = None,
    top: int = 50,
) -> Dict[str, Any]:
    ...
```

### JavaScript (JSDoc 주석)

```javascript
/**
 * @mcp_service
 * @tool_name get_crew_list
 * @server_name asset_management
 * @service_name getCrew
 * @description 전체 선원 정보 조회 (육상, 선박 전체). 선박ID, 이름, 선박명, 핸드폰으로 필터링 가능
 * @category crew_query
 * @tags query,search,filter
 * @param {Array<number>} [shipIds] - 선박 ID 목록으로 필터링
 * @param {string} [where] - 검색 조건 (name|ship|mobile)
 * @param {string} [query] - 검색어
 * @returns {Array<mstEmployee>} 선원 목록
 */
crewService.getCrew = async (params = {}) => {
    ...
}
```

> **JSDoc 규칙**:
> - `@mcp_service` 태그가 반드시 있어야 스캔 대상
> - `@server_name` 태그로 서버 식별자 지정 (필수)
> - `@tool_name` 태그로 MCP Tool 이름 지정 (필수)
> - `[param]` 대괄호는 optional 파라미터
> - `@tags`는 쉼표로 구분 (배열로 파싱됨)
> - **타입은 Sequelize 모델명으로 명시** (아래 "타입 명확화" 섹션 참조)
> - 파일 상단에 `@mcp_server {server_name}` 주석으로 서버 선언 가능 (선택사항)

### JavaScript `@types_file` 태그 (선택)

컨벤션 기반 자동 탐지가 실패하는 경우에만 `@types_file` 태그를 사용합니다:

```javascript
/**
 * @mcp_service
 * @server_name asset_management
 * @types_file ../custom_models
 * @tool_name update_license
 * @param {employeeLicense} licenseData
 * @returns {mstEmployee}
 */
```

> **`@types_file` 사용 시점** (컨벤션 불일치 시):
> - 모델 디렉토리가 `**/sequelize/models` 패턴이 아닐 때
> - 파일명이 snake_case 규칙을 따르지 않을 때 (예: `MstEmployee.js`)
> - 비 Sequelize 프로젝트일 때
>
> **기본 동작 (컨벤션 기반 자동 탐지)**:
> - `@param`/`@returns`의 타입명에서 camelCase → snake_case 변환
> - 예: `mstEmployee` → `mst_employee.js` 검색
> - Sequelize 모델 디렉토리 패턴: `**/sequelize/models`, `**/sequelize/models2`

### TypeScript (experimentalDecorators 필요)

> **주의**: TypeScript는 기본 지원이며, esprima 파서가 설치된 경우에만 완전한 파싱이 가능합니다.

```typescript
@McpService({
    toolName: "handler_mail_list",
    serverName: "outlook",
    serviceName: "query_mail_list",
    description: "메일 리스트 조회 기능",
    category: "outlook_mail",
    tags: ["query", "search"],
})
async function queryMailList(userEmail: string, top: number = 50) {
    ...
}
```

> TypeScript에서도 JavaScript JSDoc 스타일을 사용할 수 있습니다.

---

## 자동 추출 정보

### Python (AST 스캐너 + 런타임 데코레이터)

| 추출 항목 | 소스 (AST 스캔) | 소스 (런타임) |
|:---------|:--------------|:------------|
| `parameters` | `_extract_parameters()` | `inspect.signature(func)` |
| `is_optional` | `Optional[...]` 또는 기본값 여부 | 기본값 없는 파라미터 |
| `class_name` | 커스텀 클래스명 추출 | - |
| `return_type` | `_annotation_to_str()` | `get_type_hints(func)["return"]` |
| `is_async` | `isinstance(node, ast.AsyncFunctionDef)` | `inspect.iscoroutinefunction(func)` |
| `module` | `Path(file_path).stem` | `func.__module__` |
| `function_name` | `node.name` | `func.__name__` |
| `class` | `MCPServiceExtractor.current_class` | - |
| `instance` | snake_case 변환 | - |
| `signature` | `signature_from_parameters()` | `str(sig)` |

### JavaScript (JSDoc 파싱)

| 추출 항목 | 소스 | 비고 |
|:---------|:-----|:-----|
| `parameters` | `@param {type} name - description` | `_parse_jsdoc_block()` |
| `is_optional` | `[param]` 대괄호 여부 | 대괄호 제거 후 플래그 설정 |
| `jsdoc_type` | `{type}` 원본 타입 | 원본 타입명 보존 |
| `type` | JSON Schema 타입으로 변환 | `_map_jsdoc_type()` |
| `return_type` | `@returns {type}` | `returns` 객체에 저장 |
| `is_async` | 함수 정의 `async` 키워드 | `_find_function_after_jsdoc()` |
| `function_name` | 함수 정의에서 추출 | 4가지 패턴 지원 |
| `object` | 객체 메서드의 경우 객체명 | `crewService.getCrew` → `crewService` |
| `line` | 함수 정의 위치 | JSDoc 블록 다음 라인 기준 |
| `pattern` | `"jsdoc"` | JSDoc 파싱 방식 표시 |

---

## 글로벌 레지스트리 (Python 런타임)

```python
MCP_SERVICE_REGISTRY: Dict[str, Dict[str, Any]] = {}
```

데코레이터가 적용된 함수는 런타임에 자동으로 글로벌 레지스트리에 등록됩니다.
(`include_in_registry=False`로 설정하면 등록하지 않음)

> **Import**: `MCP_SERVICE_REGISTRY`도 루트에서 import 가능: `from service_registry import MCP_SERVICE_REGISTRY`

### 레지스트리 조회 함수 (`service_registry/python/decorator.py`)

| 함수 | 용도 |
|:-----|:-----|
| `get_mcp_service_info(func_or_name)` | 특정 서비스 메타데이터 조회 (함수 객체 또는 이름) |
| `list_mcp_services()` | 전체 서비스 목록 반환 |
| `generate_inputschema_from_service(name)` | JSON Schema inputSchema 생성 |

### 서비스 메타데이터 구조

```python
service_metadata = {
    "name": final_service_name,       # tool_name 또는 함수명
    "function": func.__name__,        # 원본 함수명
    "module": func.__module__,        # 모듈 경로
    "description": description,       # 설명
    "server_name": server_name,       # 서버 식별자
    "service_name": service_name,     # 서비스명
    "category": category,             # 카테고리
    "tags": tags or [],               # 태그 목록
    "priority": priority,             # 우선순위
    "related_objects": related_objects or [],  # 관련 객체
    "is_async": bool,                 # 비동기 여부
    "parameters": param_info,         # 파라미터 정보
    "required_parameters": required_params,    # 필수 파라미터
    "return_type": str,               # 반환 타입
    "signature": str,                 # 시그니처 문자열
}
```

---

## 데이터 흐름

```
[Python]
@mcp_service(server_name="outlook")  ← 개발자 설정
        ↓
AST 스캔 (find_mcp_services_in_python_file)
        ↓
export_services_to_json() 호출
        ↓
├── mcp_outlook/registry_outlook.json 생성 (서비스 정의)
├── mcp_outlook/types_property_outlook.json 생성 (타입 정보)
└── collect_referenced_types() → extract_types.extract_single_class()
        ↓
editor_config.json 자동 생성 (generate_editor_config.py)
        ↓
웹 에디터에서 프로필 표시

[JavaScript]
/** @mcp_service @server_name asset_management */  ← 개발자 설정
        ↓
JSDoc 스캔 (find_jsdoc_mcp_services_in_js_file)
        ↓
export_services_to_json() 호출
        ↓
├── mcp_asset_management/registry_asset_management.json 생성
├── mcp_asset_management/types_property_asset_management.json 생성
└── extract_types_js.export_js_types_property() (Sequelize 모델)
        ↓
editor_config.json 자동 생성 (generate_editor_config.py)
        ↓
웹 에디터에서 프로필 표시
```

---

## 웹 에디터 API (레지스트리 조회)

웹 에디터 UI(JavaScript)는 Flask API를 통해 파싱된 레지스트리 데이터를 조회합니다:

| JS 호출 | Python 엔드포인트 | 데이터 소스 |
|:--------|:-----------------|:-----------|
| `fetch('/api/services')` | `registry_routes.py` | `registry_{server}.json` |
| `fetch('/api/profiles')` | `profile_routes.py` | `editor_config.json` |
| `fetch('/api/services/{profile}/list')` | `registry_routes.py` | 레지스트리 스캔 결과 |

### 예시
```javascript
// 서비스 목록 조회
const response = await fetch('/api/services/outlook/list');
const services = await response.json();
// → 데코레이터에서 추출된 서비스 메타데이터
```

---


## 핵심 필드: server_name

`server_name`은 가장 중요한 필드입니다:

- **프로필 생성 기준**: `editor_config.json`의 프로필 키
- **경로 컨벤션**: `server_name="outlook"` → `../mcp_outlook`
- **레지스트리 경로**: `mcp_outlook/registry_outlook.json`
- **타입 정보 경로**: `mcp_outlook/types_property_outlook.json`
- **포트 할당**: 프로필별 순차 할당 (8001부터)

> **결론**: `server_name`만 올바르게 설정하면 나머지는 자동 처리됨

---

## 스캔 함수 파라미터

### `scan_codebase_for_mcp_services()`

```python
def scan_codebase_for_mcp_services(
    base_dir: str,                      # 스캔할 기본 디렉토리
    server_name: Optional[str] = None,  # 특정 서버만 필터링 (None=전체)
    exclude_examples: bool = True,      # 예제 파일 제외
    skip_parts: tuple = DEFAULT_SKIP_PARTS,  # 건너뛸 디렉토리
    languages: Optional[List[str]] = None,   # 스캔할 언어 (None=전체)
    include_jsdoc_pattern: bool = True,      # JSDoc 패턴 포함
) -> Dict[str, Dict[str, Any]]:
```

**DEFAULT_SKIP_PARTS**:
```python
DEFAULT_SKIP_PARTS = ("venv", "__pycache__", ".git", "node_modules", "backups", ".claude")
```

### `export_services_to_json()`

```python
def export_services_to_json(
    base_dir: str,      # 스캔할 기본 디렉토리
    server_name: str,   # 서버 이름 (출력 파일명에 사용)
    output_dir: str,    # 출력 디렉토리
) -> Dict[str, Any]:    # 생성된 파일 정보 반환
```

**반환값**:
```python
{
    "registry": "/path/to/registry_xxx.json",
    "types_property": "/path/to/types_property_xxx.json",
    "service_count": 10,
    "type_count": 3,
    "language": "python"  # 또는 "javascript"
}
```

---

## JSDoc 타입 매핑

JavaScript JSDoc 타입은 `_map_jsdoc_type()` 함수에 의해 JSON Schema 타입으로 변환됩니다:

| JSDoc 타입 | JSON Schema 타입 | 비고 |
|:-----------|:----------------|:-----|
| `{string}`, `{String}` | `"string"` | |
| `{number}`, `{Number}` | `"number"` | |
| `{integer}`, `{int}` | `"integer"` | |
| `{boolean}`, `{Boolean}`, `{bool}` | `"boolean"` | |
| `{object}`, `{Object}` | `"object"` | |
| `{array}`, `{Array}`, `{Array<T>}`, `{T[]}` | `"array"` | 배열 패턴 감지 |
| `{*}`, `{any}` | `"any"` | |
| `{null}`, `{undefined}`, `{void}` | `"null"` | |
| `{function}`, `{Function}` | `"object"` | |
| `{mstEmployee}` 등 커스텀 타입 | `"object"` | `jsdoc_type`에 원본 보존 |

### JSDOC_TYPE_MAP 상수

```python
JSDOC_TYPE_MAP = {
    "string": "string", "String": "string",
    "number": "number", "Number": "number",
    "integer": "integer", "int": "integer",
    "boolean": "boolean", "Boolean": "boolean", "bool": "boolean",
    "object": "object", "Object": "object",
    "array": "array", "Array": "array",
    "any": "any", "*": "any",
    "null": "null", "undefined": "null", "void": "null",
    "function": "object", "Function": "object",
}
```

### 커스텀 타입 처리

Sequelize 모델명 등 **알 수 없는 타입은 `object`로 매핑**되며, 원본 타입명은 `jsdoc_type` 필드에 보존됩니다:

```json
{
  "name": "crewData",
  "type": "object",              // JSON Schema용
  "jsdoc_type": "mstEmployee"    // 원본 타입명 보존
}
```

> **변경 이력**: 이전에는 알 수 없는 타입을 `any`로 매핑했으나, 커스텀 클래스는 객체이므로 `object`로 변경 (`service_registry/scanner.py`)

---

## Python 타입 처리

### `_parse_type_info()` 함수

Python 타입 힌트를 파싱하여 base_type, class_name, is_optional을 추출합니다:

```python
# 예시
'Optional[str]' -> {'base_type': 'str', 'class_name': None, 'is_optional': True}
'str' -> {'base_type': 'str', 'class_name': None, 'is_optional': False}
'Optional[FilterParams]' -> {'base_type': 'object', 'class_name': 'FilterParams', 'is_optional': True}
'FilterParams' -> {'base_type': 'object', 'class_name': 'FilterParams', 'is_optional': False}
'List[str]' -> {'base_type': 'List[str]', 'class_name': None, 'is_optional': False}
```

### 커스텀 클래스 판별 (`_is_class_type()`)

다음 조건을 만족하면 커스텀 클래스로 판별:
- 대문자로 시작
- Generic 타입 접두사가 아님 (`List[`, `Dict[`, `Union[`, `Optional[`, `Set[`, `Tuple[`, `Callable[`)
- Python 내장 타입이 아님 (`None`, `Any`, `NoReturn`, `Type`, `Literal`)

### 파라미터 추출 결과 구조

```python
{
    "name": "filter_params",
    "type": "object",           # JSON Schema 호환 타입
    "class_name": "FilterParams",  # 원본 클래스명 (커스텀 클래스인 경우)
    "is_optional": True,
    "default": None,
    "has_default": True
}
```

---

## Nested Object Properties 지원

JSDoc에서 `@param {type} obj.prop` 형식으로 객체의 중첩 속성을 정의할 수 있습니다:

### JSDoc 작성법

```javascript
/**
 * @mcp_service
 * @tool_name create_crew
 * @server_name asset_management
 * @description 새로운 선원 정보 생성
 * @param {mstEmployee} crewData - 선원 정보
 * @param {string} crewData.nameKr - 한글 이름
 * @param {string} crewData.nameEng - 영문 이름 (필수)
 * @param {string} [crewData.nameChi] - 중국어 이름 (선택)
 * @param {string} [crewData.gender] - 성별 (Male/Female)
 * @param {string} [crewData.address] - 주소
 */
crewService.createCrew = async (crewData) => { ... }
```

### 파싱 결과

```json
{
  "name": "crewData",
  "type": "object",
  "jsdoc_type": "mstEmployee",
  "description": "선원 정보",
  "properties": {
    "nameKr": {
      "type": "string",
      "description": "한글 이름",
      "is_optional": false
    },
    "nameEng": {
      "type": "string",
      "description": "영문 이름 (필수)",
      "is_optional": false
    },
    "nameChi": {
      "type": "string",
      "description": "중국어 이름 (선택)",
      "is_optional": true
    },
    "gender": {
      "type": "string",
      "description": "성별 (Male/Female)",
      "is_optional": true
    }
  }
}
```

### 규칙

| 형식 | 의미 | 예시 |
|:-----|:-----|:-----|
| `@param {type} name` | 최상위 파라미터 | `@param {mstEmployee} crewData` |
| `@param {type} obj.prop` | 객체의 속성 | `@param {string} crewData.nameKr` |
| `@param {type} [obj.prop]` | 선택적 속성 | `@param {string} [crewData.nameChi]` |

### 파서 동작

1. 모든 `@param` 태그를 정규식으로 수집
2. `.`이 포함된 이름은 nested property로 분류 (`parts = name.split(".")`)
3. 부모 객체의 `properties` 필드에 저장 (없으면 생성)
4. `[param]` 대괄호는 `is_optional: true`로 처리

> **구현 위치**: `service_registry/scanner.py` → `_parse_jsdoc_block()` 함수

---

## JavaScript 타입 명확화 (Sequelize 모델명 사용)

JSDoc에서 `{Object}` 대신 **Sequelize 모델명을 명시**하면 필드 정보를 자동 추출할 수 있습니다.

```javascript
@param {employeeLicense} updateData - 수정할 라이센스 정보
@returns {Array<mstEmployee>} 선원 목록
```

### 타입 추출 흐름

```
JSDoc: @param {employeeLicense} updateData
        ↓
JSDoc 파서가 "employeeLicense" 모델명 추출
        ↓
Sequelize 모델 정의에서 필드 정보 조회
        ↓
types_property_{server}.json에 필드 정보 저장
```

### Sequelize 모델 타입 예시

| 모델명 | 설명 |
|:-------|:-----|
| `mstEmployee` | 선원 기본 정보 |
| `mstShip` | 선박 정보 |
| `mstPosition` | 직급 정보 |
| `employeeLicense` | 선원 라이센스 |
| `employeeEducation` | 선원 교육 이력 |
| `employeeCareer` | 선원 경력 |

### 배열 타입

```javascript
@returns {Array<mstEmployee>}  // 선원 목록
@returns {Array<mstPosition>}  // 직급 목록
```

### <<중요>> 복합 객체는 지원되지 않음

**복합 객체 (여러 모델 조합) 파싱은 구현되지 않았습니다.** 반드시 **단일 모델**로 지정하세요.

```javascript
// X 복합 객체 - 파싱 불가
return { crew, remoteAuth };    // 두 모델 조합
return { position, crew };      // 두 모델 조합

// O 단일 모델로 지정
@param {employeeLicense} updateData
@returns {mstEmployee} 선원 정보
@returns {Array<mstPosition>} 직급 목록
```

> 복합 객체를 반환해야 하는 경우 `{Object}`로 유지하되, **필드 자동 추출은 불가**합니다.

---

### JSDoc 함수 정의 패턴 지원

`_find_function_after_jsdoc()` 함수는 다음 JavaScript 함수 정의 패턴을 인식합니다:

```javascript
// 패턴 1: 객체 메서드 (obj.method = async (params) => { 또는 obj.method = async function(params) {)
crewService.getCrew = async (params) => { ... }

// 패턴 2: 일반 함수 (async function name(params) { 또는 function name(params) {)
async function updateUserLicense(id, updateData) { ... }

// 패턴 3: const/let/var 함수 (const name = async (params) => { 또는 = async function(params) {)
const getCrew = async function(params) { ... }

// 패턴 4: exports 패턴
exports.getCrew = async (params) => { ... }
```

> **구현 위치**: `service_registry/scanner.py` → `_find_function_after_jsdoc()` 함수

---

## ServerInfo 클래스 및 타입 자동 추출

`generate_editor_config.py`에서 서버 정보와 타입 정보를 함께 관리하는 `ServerInfo` 클래스가 추가되었습니다.

### ServerInfo 클래스

```python
class ServerInfo:
    """Holds information about a discovered MCP server."""
    def __init__(self, name: str, language: str, source_file: str):
        self.name = name
        self.language = language  # "python" or "javascript"
        self.source_file = source_file
        self.types_files: Set[str] = set()  # Auto-detected type files
        self.type_names: Set[str] = set()  # Type names used in functions
```

> **구현 위치**: `service_registry/config_generator.py`

### 서버 정보 스캔 함수

| 함수 | 용도 | 반환값 |
|:-----|:-----|:------|
| `scan_codebase_for_server_info()` | 전체 코드베이스 스캔 (타입 정보 포함) | `Dict[str, ServerInfo]` |
| `extract_server_info_from_py_file()` | Python 파일에서 서버 정보 추출 | `Dict[str, ServerInfo]` |
| `extract_server_info_from_js_file()` | JavaScript 파일에서 서버 정보 추출 | `Dict[str, ServerInfo]` |

### `scan_codebase_for_server_info()`

```python
def scan_codebase_for_server_info(base_dir: str) -> Dict[str, ServerInfo]:
    """Scan entire codebase for @mcp_service and extract full server info including types.

    Supports:
    - Python (.py): AST parsing of @mcp_service decorators + type hints + imports
    - JavaScript (.js, .mjs): JSDoc parsing of @mcp_service + @param/@returns types
      - Explicit: @types_file tag for specifying model directories
      - Convention-based: Auto-detect Sequelize model directories and match type names

    Returns:
        Dict mapping server_name to ServerInfo with language and types_files
    """
```

> **구현 위치**: `service_registry/config_generator.py`

### `extract_server_info_from_py_file()`

```python
def extract_server_info_from_py_file(file_path: str) -> Dict[str, ServerInfo]:
    """Extract server info including types from @mcp_service decorators in a Python file.

    Analyzes:
    1. @mcp_service(server_name="xxx") decorators
    2. Function parameter type hints
    3. Return type hints
    4. Import statements to find type source files

    Returns:
        Dict mapping server_name to ServerInfo
    """
```

> **구현 위치**: `service_registry/config_generator.py`

### `extract_server_info_from_js_file()`

```python
def extract_server_info_from_js_file(
    file_path: str,
    model_dirs: Optional[List[str]] = None
) -> Dict[str, ServerInfo]:
    """Extract server info including types from JSDoc @mcp_service comments in JavaScript file.

    Supports two methods for types_files detection:
    1. Explicit @types_file tag in JSDoc (e.g., @types_file ../sequelize/models2)
    2. Convention-based: Find Sequelize model files matching type names

    Args:
        file_path: Path to JavaScript file
        model_dirs: Optional list of Sequelize model directories for convention-based detection

    Returns:
        Dict mapping server_name to ServerInfo
    """
```

> **구현 위치**: `service_registry/config_generator.py`

### 타입 추출 흐름 (Python)

```
@mcp_service(server_name="outlook")
async def query_mail(filter_params: FilterParams) -> List[Mail]:
        ↓
extract_server_info_from_py_file() 호출
        ↓
├── AST 파싱: @mcp_service에서 server_name 추출
├── 타입 힌트 분석: FilterParams, List[Mail]
├── import 문 분석: from .outlook_types import FilterParams
└── 파일 경로 해석: ./outlook_types.py → types_files에 추가
        ↓
ServerInfo(name="outlook", language="python", types_files={...})
```

### 타입 추출 흐름 (JavaScript)

```
/**
 * @mcp_service
 * @server_name asset_management
 * @param {mstEmployee} data
 * @returns {employeeLicense}
 */
        ↓
extract_server_info_from_js_file() 호출
        ↓
├── JSDoc 파싱: @server_name 추출
├── 타입 추출: mstEmployee, employeeLicense
├── @types_file 확인 (명시적 경로)
│   └── 있으면: 해당 경로에서 모델 파일 검색
├── Convention 기반 탐지 (model_dirs 제공 시)
│   ├── camelCase → snake_case 변환
│   └── mstEmployee → mst_employee.js 검색
└── types_files에 모델 파일 경로 추가
        ↓
ServerInfo(name="asset_management", language="javascript", types_files={...})
```

### Sequelize 모델 디렉토리 탐지

`find_sequelize_model_dirs()` 함수는 프로젝트에서 Sequelize 모델 디렉토리를 자동 탐지합니다:

```python
def find_sequelize_model_dirs(base_dir: str) -> List[str]:
    """Find Sequelize model directories in a project.

    Looks for directories named 'models' or 'models2' under 'sequelize' directory.
    Patterns: **/sequelize/models, **/sequelize/models2, **/models
    """
```

> **구현 위치**: `service_registry/config_generator.py`

### camelCase -> snake_case 변환

JavaScript 타입명을 Sequelize 모델 파일명으로 변환:

| 타입명 | 파일명 |
|:-------|:-------|
| `mstEmployee` | `mst_employee.js` |
| `employeeLicense` | `employee_license.js` |
| `shipEquipment` | `ship_equipment.js` |

```python
def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    result = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    return result.lower()
```

> **구현 위치**: `service_registry/config_generator.py`

---

## MCP 서버 생성과 연동

데코레이터/JSDoc에서 추출된 레지스트리 정보는 Jinja 템플릿을 통해 MCP 서버로 변환됩니다.

### 연동 흐름

```
@mcp_service 데코레이터/JSDoc
        ↓
registry_{server}.json (서비스 메타데이터)
        ↓
generate_universal_server.py (Jinja 템플릿 렌더링)
        ↓
server_stream.py (실행 가능한 MCP 서버)
```

### 레지스트리 데이터 활용

| 레지스트리 필드 | 서버 템플릿에서 사용 |
|:--------------|:-----------------|
| `services.handler.class_name` | 서비스 클래스 import |
| `services.handler.method` | 도구 실행 시 호출 메서드 |
| `services.handler.file` | 모듈 경로 생성 |
| `services.parameters` | 도구 파라미터 정의 |
| `services.metadata.tool_name` | MCP Tool 이름 |

### 서버 생성 명령

```bash
cd /home/kimghw/Connector_auth/mcp_editor/jinja
python generate_universal_server.py outlook --protocol stream --port 8080
```

> **참고**: 자세한 서버 생성 방법은 `workflow1.md`의 "MCP 서버 생성 (Jinja 템플릿)" 섹션을 참조하세요.
