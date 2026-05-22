# 타입 추출 시스템

## 모듈 구조

타입 추출 모듈은 언어별로 분리되어 있습니다:

### Python 타입: `service_registry/python/types.py`

| 함수 | 설명 |
|------|------|
| `extract_class_properties()` | 파일 내 모든 BaseModel 클래스 추출 |
| `extract_single_class()` | 특정 클래스만 추출 |
| `scan_py_project_types()` | 전체 Python 프로젝트 타입 스캔 |
| `map_python_to_json_type()` | Python 타입 -> JSON Schema 타입 변환 |

**Import:**
```python
from service_registry.python.types import (
    extract_class_properties,
    extract_single_class,
    scan_py_project_types,
    map_python_to_json_type,
)
```

### JavaScript 타입: `service_registry/javascript/types.py`

| 함수 | 설명 |
|------|------|
| `extract_sequelize_models_from_file()` | sequelize.define() 파싱 |
| `scan_js_project_types()` | 전체 JS 프로젝트 타입 스캔 |
| `map_sequelize_to_json_type()` | Sequelize DataTypes -> JSON Schema 타입 변환 |

**Import:**
```python
from service_registry.javascript.types import (
    extract_sequelize_models_from_file,
    scan_js_project_types,
    map_sequelize_to_json_type,
)
```

### 하위 호환 Import

기존 코드와의 호환성을 위해 루트 모듈에서도 import 가능:

```python
# Python 타입 (하위 호환)
from service_registry import extract_types

# JavaScript 타입 (하위 호환)
from service_registry import extract_types_js
```

---

## 인터페이스 기반 타입 추출 시스템

### 개요

인터페이스 기반 타입 추출 시스템은 `AbstractTypeExtractor`를 구현하는 어댑터 패턴을 사용하여 언어별 타입 추출을 통합합니다.

### 어댑터 파일

| 언어 | 어댑터 파일 | 클래스 |
|------|-------------|--------|
| **Python** | `service_registry/python/types_adapter.py` | `PythonTypeExtractor` |
| **JavaScript** | `service_registry/javascript/types_adapter.py` | `JavaScriptTypeExtractor` |

모든 어댑터는 `AbstractTypeExtractor` 인터페이스를 구현합니다.

### 사용 방법

```python
from service_registry import TypeExtractorRegistry

# 언어별 extractor 가져오기
extractor = TypeExtractorRegistry.get('python')
types = extractor.extract_types_from_file('types.py')

# 파일 확장자 기반 자동 감지
extractor = TypeExtractorRegistry.get_for_file('models.js')

# 직접 추출 (언어 자동 감지)
types = TypeExtractorRegistry.extract_from_file('any_types.py')
```

### 데이터 클래스

#### TypeInfo

타입 정보를 담는 데이터 클래스:

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | str | 타입(클래스) 이름 |
| `file` | str | 정의된 파일 경로 |
| `line` | int | 정의된 라인 번호 |
| `properties` | List[PropertyInfo] | 프로퍼티 목록 |
| `type_kind` | str | 타입 종류 (예: "pydantic_model", "sequelize_model") |
| `language` | str | 언어 ("python", "javascript") |

#### PropertyInfo

프로퍼티 정보를 담는 데이터 클래스:

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | str | 프로퍼티 이름 |
| `type` | str | 타입 (JSON Schema 타입) |
| `description` | str | 설명 |
| `is_optional` | bool | 선택적 여부 |
| `default` | Any | 기본값 |
| `examples` | List[Any] | 예시 값 목록 |

### 장점

- **통합 인터페이스**: 언어에 관계없이 동일한 API 사용
- **확장성**: 새 언어 지원 시 어댑터만 추가
- **자동 감지**: 파일 확장자 기반 언어 자동 감지
- **일관된 출력**: 모든 언어에서 동일한 TypeInfo/PropertyInfo 구조 반환

---

## Python vs JavaScript 파라미터 추출 비교

### 정보 출처 비교

| 정보 | Python AST | JS AST | JS JSDoc | 현재 사용 |
|:-----|:-----------|:-------|:---------|:----------|
| **함수명** | ✅ `node.name` | ✅ | - | 둘 다 AST |
| **파라미터 이름** | ✅ `arg.arg` | ✅ | ✅ `@param name` | Py: AST / JS: JSDoc |
| **파라미터 타입** | ✅ `arg.annotation` | ❌ | ✅ `{type}` | Py: AST / JS: JSDoc |
| **중첩 속성** | ✅ 클래스 정의 | ❌ | ✅ `@param obj.prop` | Py: AST / JS: JSDoc |
| **Optional 여부** | ✅ `Optional[...]` | △ 기본값만 | ✅ `[param]` | Py: AST / JS: JSDoc |
| **기본값** | ✅ `args.defaults` | ✅ | ❌ | 둘 다 AST |
| **반환 타입** | ✅ `returns` | ❌ | ✅ `@returns` | Py: AST / JS: JSDoc |
| **async 여부** | ✅ `AsyncFunctionDef` | ✅ | - | 둘 다 AST |
| **설명** | ❌ | ❌ | ✅ `- desc` | JS만 JSDoc |
| **메타데이터** | ✅ 데코레이터 인자 | ❌ | ✅ `@server_name` 등 | Py: AST / JS: JSDoc |

### 매칭 방식 비교

| 항목 | Python | JavaScript |
|:-----|:-------|:-----------|
| **파서** | `ast` (내장) | 정규식 (JSDoc) + esprima (선택) |
| **데코레이터 위치** | 함수 위 `@mcp_service()` | JSDoc 블록 내 `@mcp_service` |
| **매칭 방식** | AST 노드 구조 (자동) | 텍스트 위치 (수동) |
| **파라미터 출처** | AST 단독 | AST + JSDoc 병합 |
| **타입 출처** | AST 단독 | JSDoc 단독 |
| **코드-문서 동기화** | ✅ 보장 | ❌ 불일치 가능 |

### 핵심 차이

```
[Python]  소스 코드 → AST → 데코레이터 + 시그니처 + 타입 (하나의 구조에서 모두 추출)

[JavaScript]  소스 코드 → JSDoc 주석 → 메타데이터 + 타입
                       → AST/정규식 → 함수명 + async (두 소스를 위치로 매칭)
```

> **JS AST의 한계**: JavaScript는 동적 타입 언어라 AST에 타입 정보가 없음. 따라서 JSDoc이 "타입 정의 + 메타데이터" 역할을 동시에 수행.

---

## 지원 언어

| 언어 | 타입 정의 방식 | 추출 모듈 |
|------|---------------|----------|
| **Python** | Pydantic BaseModel | `service_registry/python/types.py` |
| **JavaScript** | Sequelize 모델, JSDoc | `service_registry/javascript/types.py` |
| **TypeScript** | (기본 지원) | `mcp_service_scanner.py` |

---

## 웹 에디터에서의 사용

### 사용 목적
`types_property_{server}.json`은 웹 에디터 UI에서 **타입 프로퍼티 드롭다운** 표시에 사용됩니다.

### 사용 흐름

```
types_property_{server}.json
         │
         ▼
GET /api/graph-types-properties (basemodel_routes.py)
         │
         ▼
웹 에디터 UI: 타입 프로퍼티 선택 드롭다운
         │
         ▼
사용자가 프로퍼티 선택 → inputSchema에 추가
```

### 관련 코드

| 파일 | 함수 | 역할 |
|------|------|------|
| `basemodel_routes.py` | `get_graph_types_properties()` | JSON 파일 읽어서 API 응답 |
| `tool_editor_tools.js` | `loadTypesProperties()` | API 호출하여 UI에 표시 |

### UI에서 표시되는 정보

**Python 프로젝트:**
- **클래스 목록**: FilterParams, SelectParams 등 (BaseModel)
- **프로퍼티 목록**: 각 클래스의 필드명, 타입, 설명
- **full_path**: "FilterParams.from_address" 형식으로 선택 가능

**JavaScript 프로젝트:**
- **모델 목록**: mstEmployee, mstShip 등 (Sequelize)
- **프로퍼티 목록**: 각 모델의 필드명, DataType, allowNull
- **full_path**: "mstEmployee.nameKr" 형식으로 선택 가능

---

## 요약

| 항목 | Python | JavaScript |
|------|--------|------------|
| **모듈** | `service_registry/python/types.py` | `service_registry/javascript/types.py` |
| **호출자** | `mcp_service_scanner.py` | `mcp_service_scanner.py` |
| **출력 파일** | `types_property_{server}.json` | `types_property_{server}.json` |
| **호출 시점** | 웹 에디터 시작 시 자동 | 웹 에디터 시작 시 자동 |
| **타입 소스** | Pydantic BaseModel | Sequelize 모델 |
| **서비스 데코레이터** | `@mcp_service` | JSDoc `@mcp_service` |

### 참조 스크립트

**Python:**

| 스크립트 | 함수 | 용도 |
|----------|------|------|
| `mcp_service_scanner.py` | `collect_referenced_types()` | 서비스 파라미터에서 클래스 타입 수집 |
| `mcp_service_scanner.py` | `resolve_class_file()` | import 추적하여 클래스 정의 파일 찾기 |
| `mcp_service_scanner.py` | `export_types_property()` | types_property JSON 생성 |
| `mcp_service_scanner.py` | `_parse_imports()` | 파일의 import 문 파싱 |
| `mcp_service_scanner.py` | `_resolve_module_to_file()` | 모듈명 → 파일 경로 변환 |
| `mcp_service_scanner.py` | `_is_class_type()` | 커스텀 클래스 타입 여부 확인 |
| `mcp_service_scanner.py` | `_parse_type_info()` | 타입 문자열에서 base_type, class_name, is_optional 추출 |
| `mcp_service_scanner.py` | `signature_from_parameters()` | 파라미터 메타데이터에서 시그니처 문자열 생성 |
| `service_registry/python/types.py` | `extract_class_properties()` | 파일 내 모든 BaseModel 클래스 추출 |
| `service_registry/python/types.py` | `extract_single_class()` | 특정 클래스만 추출 |
| `service_registry/python/types.py` | `scan_py_project_types()` | 전체 Python 프로젝트 타입 스캔 (자동 탐지) |
| `service_registry/python/types.py` | `export_py_types_property()` | types_property JSON 생성 |
| `service_registry/python/types.py` | `get_class_names_from_file()` | 파일 내 BaseModel 클래스 이름 목록 반환 |
| `service_registry/python/types.py` | `extract_type_from_annotation()` | AST 어노테이션에서 타입 문자열 추출 |
| `service_registry/python/types.py` | `extract_field_info()` | Field() 정의에서 메타데이터 추출 |
| `service_registry/python/types.py` | `map_python_to_json_type()` | Python 타입 → JSON Schema 타입 변환 |

**JavaScript:**

| 스크립트 | 함수 | 용도 |
|----------|------|------|
| `service_registry/javascript/types.py` | `scan_js_project_types()` | models 디렉토리에서 Sequelize 모델 스캔 |
| `service_registry/javascript/types.py` | `extract_sequelize_models_from_file()` | sequelize.define() 파싱 |
| `service_registry/javascript/types.py` | `_parse_sequelize_fields()` | Sequelize 필드 정의 파싱 |
| `service_registry/javascript/types.py` | `_parse_js_value()` | JavaScript 값 → Python 값 변환 |
| `service_registry/javascript/types.py` | `export_js_types_property()` | types_property JSON 생성 |
| `service_registry/javascript/types.py` | `map_sequelize_to_json_type()` | Sequelize DataTypes → JSON Schema 타입 |
| `service_registry/javascript/types.py` | `map_zod_to_json_type()` | Zod 타입 → JSON Schema 타입 |
| `mcp_service_scanner.py` | `find_jsdoc_mcp_services_in_js_file()` | JSDoc @mcp_service 블록 파싱 |
| `mcp_service_scanner.py` | `find_mcp_services_in_js_file()` | esprima 기반 데코레이터 스캔 |
| `mcp_service_scanner.py` | `_parse_jsdoc_block()` | JSDoc 블록에서 메타데이터 추출 |
| `mcp_service_scanner.py` | `_find_function_after_jsdoc()` | JSDoc 다음 함수 정의 탐지 |
| `mcp_service_scanner.py` | `_map_jsdoc_type()` | JSDoc 타입 → JSON Schema 타입 |
| `mcp_service_scanner.py` | `_extract_js_decorator_metadata()` | JS 데코레이터에서 메타데이터 추출 |
| `mcp_service_scanner.py` | `_extract_js_parameters()` | JS 함수에서 파라미터 추출 |
| `mcp_service_scanner.py` | `_js_signature_from_parameters()` | JS 파라미터에서 시그니처 생성 |

**공통:**

| 스크립트 | 함수 | 용도 |
|----------|------|------|
| `basemodel_routes.py` | `GET /api/graph-types-properties` | API로 타입 정보 제공 |
| `mcp_service_scanner.py` | `export_services_to_json()` | registry + types_property JSON 생성 |
| `mcp_service_scanner.py` | `scan_codebase_for_mcp_services()` | 코드베이스에서 MCP 서비스 스캔 |
| `mcp_service_scanner.py` | `find_mcp_services_in_file()` | 언어 자동 감지 후 적절한 파서 호출 |
| `mcp_service_scanner.py` | `find_mcp_services_in_python_file()` | Python @mcp_service 데코레이터 탐지 |
| `mcp_service_scanner.py` | `get_signatures_by_name()` | 서비스별 시그니처 맵 반환 |
| `mcp_service_scanner.py` | `get_services_map()` | 서비스별 전체 정보 맵 반환 |
| `mcp_service_scanner.py` | `detect_language()` | 파일 확장자로 언어 감지 |
| `mcp_service_scanner.py` | `_should_skip()` | 스킵할 경로 여부 확인 |
| `mcp_service_scanner.py` | `extract_decorator_metadata()` | Python 데코레이터 메타데이터 추출 |
| `mcp_service_scanner.py` | `_extract_parameters()` | Python 함수에서 파라미터 추출 |

---

## export_services_to_json 반환값

```python
def export_services_to_json(base_dir: str, server_name: str, output_dir: str) -> Dict[str, Any]:
    """
    Returns:
        {
            "registry": "/path/to/registry_xxx.json",      # 레지스트리 파일 경로
            "types_property": "/path/to/types_property_xxx.json",  # 타입 프로퍼티 파일 경로
            "service_count": 10,                           # 추출된 서비스 수
            "type_count": 3,                               # 추출된 타입 수
            "language": "python" | "javascript"            # 프로젝트 언어
        }
    """
```

---

## 핵심 특징

### 자동 타입 탐지 (Python)

**설정 파일 없이** 파일 경로에 특정 키워드 포함 시 자동 탐지:
- `types` - 예: `outlook_types.py`, `types/models.py`
- `models` - 예: `models.py`, `data_models/`
- `schema` - 예: `schema.py`, `schemas/user.py`

```python
# service_registry/python/types.py의 자동 탐지 로직
# DEFAULT_SKIP_DIRS로 스킵할 디렉토리 지정
DEFAULT_SKIP_DIRS = ("node_modules", ".git", "dist", "build", "__pycache__", "venv", ".venv", "env")

for py_file in Path(base_dir).rglob("*.py"):
    # 스킵 디렉토리 체크
    if any(skip in py_file.parts for skip in skip_dirs):
        continue
    file_str = str(py_file).lower()
    if "types" in file_str or "models" in file_str or "schema" in file_str:
        classes = extract_class_properties(str(py_file))
```

### 자동 클래스 추적 (Python)

서비스 파라미터의 object 타입을 발견하면 자동으로:
1. import 문 분석 (`_parse_imports()`)
2. 클래스 정의 파일 경로 추적 (`_resolve_module_to_file()`)
3. 해당 파일에서 프로퍼티 추출 (`extract_single_class()`)

**프로젝트 내 어디에 정의되어 있든** import 경로만 따라가면 자동 추출됩니다.

### 지원 Import 패턴 (Python)

| 패턴 | 예시 |
|------|------|
| 같은 파일 | 클래스가 서비스와 같은 파일에 정의 |
| 상대 import | `from .types import MyClass` |
| 절대 import | `from my_module import MyClass` |
| 부모 디렉토리 | `from ..common import MyClass` |

### 자동 탐지 (JavaScript)

파일 경로에 `model` 또는 `sequelize` 포함 시 Sequelize 모델로 스캔:

```python
# service_registry/javascript/types.py의 자동 탐지 로직
for js_file in Path(base_dir).rglob("*.js"):
    file_str = str(js_file)
    if "model" in file_str.lower() or "sequelize" in file_str.lower():
        models = extract_sequelize_models_from_file(file_str)
```

### 제한

- 외부 패키지 (pip install한 것) - 파일 경로 추적 어려움

---

## 동작 흐름

### Python 프로젝트

```
[웹 에디터 시작]
app.py:run_app()
         │
         ▼
service_registry.py:scan_all_registries()
         │
         ▼
mcp_service_scanner.py:export_services_to_json()
         │
         ├─→ scan_codebase_for_mcp_services() ← @mcp_service 데코레이터 스캔
         │            │
         │            └─→ find_mcp_services_in_python_file() ← AST 파싱
         │
         ├─→ registry_{server}.json 생성
         │
         └─→ collect_referenced_types() ← 파라미터에서 class_name 수집
                      │
                      ▼
              resolve_class_file() ← 클래스 정의 파일 찾기
                      │
                      ├─→ _parse_imports() ← import 문 분석
                      │
                      └─→ _resolve_module_to_file() ← 모듈명 → 파일 경로
                      │
                      ▼
              service_registry.python.types.extract_single_class() ← 프로퍼티 추출
                      │
                      ▼
              export_types_property() → types_property_{server}.json 생성
```

### JavaScript 프로젝트

```
[웹 에디터 시작]
app.py:run_app()
         │
         ▼
service_registry.py:scan_all_registries()
         │
         ▼
mcp_service_scanner.py:export_services_to_json()
         │
         ├─→ scan_codebase_for_mcp_services() ← JSDoc @mcp_service 스캔
         │            │
         │            ├─→ find_jsdoc_mcp_services_in_js_file() ← JSDoc 파싱
         │            │            │
         │            │            ├─→ _parse_jsdoc_block() ← 메타데이터 추출
         │            │            │
         │            │            └─→ _find_function_after_jsdoc() ← 함수 탐지
         │            │
         │            └─→ find_mcp_services_in_js_file() ← esprima 데코레이터 스캔 (fallback)
         │
         ├─→ registry_{server}.json 생성
         │
         └─→ service_registry.javascript.types.export_js_types_property()
                      │
                      ▼
              scan_js_project_types() ← models 디렉토리 스캔
                      │
                      ▼
              extract_sequelize_models_from_file() ← sequelize.define() 파싱
                      │
                      ▼
              types_property_{server}.json 생성
```

---

## 파라미터 추출 구조

### Python 파라미터 (_extract_parameters)

```python
# 추출된 파라미터 구조
{
    "name": "filter_params",
    "type": "object",               # base_type (JSON Schema 타입)
    "class_name": "FilterParams",   # 커스텀 클래스인 경우만 포함
    "is_optional": True,            # Optional[...] 또는 기본값 있으면 True
    "default": None,
    "has_default": True
}
```

### JavaScript 파라미터 (JSDoc)

```python
# JSDoc에서 추출된 파라미터 구조
{
    "name": "shipIds",
    "type": "array",                # _map_jsdoc_type() 결과
    "jsdoc_type": "Array<number>",  # 원본 JSDoc 타입
    "is_optional": True,            # [param] 형식이면 True
    "description": "선박 ID 목록",
    "default": None,
    "has_default": False,
    "properties": {                 # 중첩 속성 (obj.prop 형식)
        "limit": {
            "type": "number",
            "description": "최대 결과 수",
            "is_optional": True
        }
    }
}
```

---

## 예시

### 서비스 파일 (service.py)

```python
from some_module.data_types import FilterParams  # ← import 추적
from ..common.models import UserConfig           # ← 상대 경로도 지원

@mcp_service(...)
async def query_mail(
    filter_params: FilterParams,  # ← type:"object", class_name:"FilterParams"
    config: UserConfig            # ← type:"object", class_name:"UserConfig"
):
    ...
```

### 자동 추적 과정

```
1. filter_params 파라미터 발견
   → type:"object", class_name:"FilterParams"

2. service.py의 import 문 분석
   → "FilterParams"는 "some_module.data_types"에서 옴

3. 모듈 경로 → 파일 경로 변환
   → /project/some_module/data_types.py

4. data_types.py에서 FilterParams 클래스 프로퍼티 추출
```

---

## 출력 파일 구조

**파일**: `types_property_{server}.json`

```
{
  "version": "1.0",
  "generated_at": "2026-01-13T...",
  "server_name": "outlook",
  "classes": [                           ← 추출된 클래스 목록
    {
      "name": "FilterParams",
      "file": "/path/to/data_types.py",  ← 클래스 정의 파일 (어디든 가능)
      "line": 15,                        ← 정의 라인 번호
      "property_count": 3
    }
  ],
  "properties_by_class": {               ← 클래스별 프로퍼티 그룹
    "FilterParams": [
      {
        "name": "from_address",
        "type": "List[string]",          ← Union[str, List[str]] → List[T]
        "description": "발신자 이메일",
        "examples": [...],
        "default": null
      }
    ]
  },
  "all_properties": [                    ← 전체 프로퍼티 평탄화 목록
    {
      "name": "from_address",
      "type": "List[string]",
      "description": "발신자 이메일",
      "class": "FilterParams",
      "full_path": "FilterParams.from_address"
    }
  ]
}
```

---

## 주요 클래스 및 열거형

### Language (mcp_service_scanner.py)

```python
class Language(Enum):
    """Supported programming languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    UNKNOWN = "unknown"
```

### MCPServiceExtractor (mcp_service_scanner.py)

Python AST를 순회하며 `@mcp_service` 데코레이터가 붙은 함수를 추출하는 클래스:

```python
class MCPServiceExtractor(ast.NodeVisitor):
    """Extract MCP services with class context."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.services: Dict[str, Dict[str, Any]] = {}
        self.current_class = None  # 클래스 컨텍스트 추적

    def visit_ClassDef(self, node): ...   # 클래스 진입 추적
    def visit_FunctionDef(self, node): ...  # 일반 함수 처리
    def visit_AsyncFunctionDef(self, node): ...  # async 함수 처리
    def _process_function(self, node): ...  # 실제 서비스 추출 로직
```

---

## 주요 함수

### mcp_service_scanner.py

| 함수 | 설명 |
|------|------|
| `export_services_to_json()` | registry + types_property JSON 생성 (메인 진입점) |
| `scan_codebase_for_mcp_services()` | 코드베이스에서 MCP 서비스 스캔 |
| `find_mcp_services_in_file()` | 언어 자동 감지 후 적절한 파서 호출 |
| `find_mcp_services_in_python_file()` | Python 파일에서 @mcp_service 데코레이터 탐지 |
| `find_jsdoc_mcp_services_in_js_file()` | JS 파일에서 JSDoc @mcp_service 블록 탐지 |
| `find_mcp_services_in_js_file()` | JS 파일에서 esprima 기반 데코레이터 탐지 |
| `detect_language()` | 파일 확장자로 프로그래밍 언어 감지 |
| `_should_skip()` | 스킵할 경로 여부 확인 |
| `_parse_jsdoc_block()` | JSDoc 블록에서 메타데이터/파라미터 추출 |
| `_find_function_after_jsdoc()` | JSDoc 다음에 오는 함수 정의 탐지 |
| `_map_jsdoc_type()` | JSDoc 타입 → JSON Schema 타입 변환 |
| `_extract_js_decorator_metadata()` | JS 데코레이터에서 메타데이터 추출 |
| `_extract_js_parameters()` | JS 함수에서 파라미터 추출 |
| `_js_signature_from_parameters()` | JS 파라미터에서 시그니처 생성 |
| `_parse_imports()` | 파일의 import 문 파싱 |
| `_resolve_module_to_file()` | 모듈명 → 파일 경로 변환 |
| `resolve_class_file()` | 클래스가 정의된 파일 찾기 |
| `collect_referenced_types()` | 모든 서비스에서 참조된 타입 수집 |
| `export_types_property()` | types_property JSON 파일 생성 |
| `extract_decorator_metadata()` | Python 데코레이터 메타데이터 추출 |
| `_annotation_to_str()` | AST 어노테이션을 문자열로 변환 |
| `_is_class_type()` | 커스텀 클래스 타입 여부 확인 |
| `_parse_type_info()` | 타입 문자열에서 base_type, class_name, is_optional 추출 |
| `_default_to_value()` | AST 기본값을 Python 값으로 변환 |
| `_extract_parameters()` | Python 함수에서 파라미터 정보 추출 |
| `signature_from_parameters()` | 파라미터 메타데이터에서 시그니처 문자열 생성 |
| `get_signatures_by_name()` | 서비스별 시그니처 맵 반환 |
| `get_services_map()` | 서비스별 전체 정보 맵 반환 |

### service_registry/python/types.py

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `map_python_to_json_type()` | `(python_type: str) -> str` | Python 타입 → JSON Schema 타입 변환 |
| `extract_type_from_annotation()` | `(annotation: Optional[ast.AST]) -> str` | AST 어노테이션에서 JSON 타입 추출 |
| `extract_field_info()` | `(node: ast.AnnAssign, class_name: str) -> Optional[Dict]` | Field() 정의에서 메타데이터 추출 |
| `extract_class_properties()` | `(file_path: str) -> Dict[str, Dict[str, Any]]` | 파일 내 모든 BaseModel 클래스 추출 |
| `extract_single_class()` | `(file_path: str, class_name: str) -> Optional[Dict]` | 특정 클래스만 추출 |
| `get_class_names_from_file()` | `(file_path: str) -> List[str]` | 파일 내 BaseModel 클래스 이름 목록 반환 |
| `scan_py_project_types()` | `(base_dir: str, skip_dirs: tuple) -> Dict[str, Any]` | 전체 Python 프로젝트 타입 스캔 (자동 탐지) |
| `export_py_types_property()` | `(base_dir: str, server_name: str, output_dir: str) -> str` | types_property JSON 생성 |

### service_registry/javascript/types.py

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `map_zod_to_json_type()` | `(zod_type: str) -> str` | Zod 타입 → JSON Schema 타입 변환 |
| `map_sequelize_to_json_type()` | `(sequelize_type: str) -> str` | Sequelize DataTypes → JSON Schema 타입 변환 |
| `extract_sequelize_models_from_file()` | `(file_path: str) -> Dict[str, Dict[str, Any]]` | sequelize.define() 파싱 |
| `_parse_sequelize_fields()` | `(model_body: str) -> List[Dict[str, Any]]` | Sequelize 필드 정의 파싱 |
| `_parse_js_value()` | `(value_str: str) -> Any` | JavaScript 값 → Python 값 변환 |
| `scan_js_project_types()` | `(base_dir: str, skip_dirs: tuple) -> Dict[str, Any]` | 전체 JS 프로젝트 타입 스캔 |
| `export_js_types_property()` | `(base_dir: str, server_name: str, output_dir: str) -> str` | types_property JSON 생성 |

---

## 타입 매핑

### Python 타입 매핑 (service_registry/python/types.py - map_python_to_json_type)

```python
type_mapping = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "List": "array",
    "Dict": "object",
    "Any": "any",
    "None": "null",
    "Optional": "any",
}
# 매핑에 없는 타입 → "object"
```

| Python 타입 | 출력 타입 | 비고 |
|-------------|-----------|------|
| `str` | `string` | |
| `int` | `integer` | |
| `float` | `number` | |
| `bool` | `boolean` | |
| `list`, `List` | `array` | |
| `dict`, `Dict` | `object` | |
| `List[str]` | `List[string]` | 내부 타입 보존 |
| `List[int]` | `List[integer]` | 내부 타입 보존 |
| `Optional[T]` | T의 타입 | Optional 제거 |
| `Union[str, List[str]]` | `List[string]` | List 우선 |
| `Literal[...]` | `string` | 열거형 처리 |
| `Any` | `any` | |
| `None` | `null` | |
| 커스텀 클래스 | `object` | |

### JSDoc 타입 매핑 (mcp_service_scanner.py - JSDOC_TYPE_MAP)

```python
JSDOC_TYPE_MAP = {
    "string": "string",
    "String": "string",
    "number": "number",
    "Number": "number",
    "integer": "integer",
    "int": "integer",
    "boolean": "boolean",
    "Boolean": "boolean",
    "bool": "boolean",
    "object": "object",
    "Object": "object",
    "array": "array",
    "Array": "array",
    "any": "any",
    "*": "any",
    "null": "null",
    "undefined": "null",
    "void": "null",
    "function": "object",
    "Function": "object",
}
# 매핑에 없는 타입 → "object" (커스텀 클래스)
```

| JSDoc 타입 | 출력 타입 | 비고 |
|------------|-----------|------|
| `string`, `String` | `string` | |
| `number`, `Number` | `number` | |
| `integer`, `int` | `integer` | |
| `boolean`, `Boolean`, `bool` | `boolean` | |
| `object`, `Object` | `object` | |
| `array`, `Array` | `array` | |
| `Array<T>`, `T[]` | `array` | `_map_jsdoc_type()`에서 처리 |
| `any`, `*` | `any` | |
| `null`, `undefined`, `void` | `null` | |
| `function`, `Function` | `object` | |
| 커스텀 클래스 | `object` | 알려지지 않은 타입 |

### Zod 타입 매핑 (service_registry/javascript/types.py - ZOD_TYPE_MAP)

```python
ZOD_TYPE_MAP = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
    "enum": "string",
    "literal": "string",
    "date": "string",
    "any": "any",
    "unknown": "any",
    "null": "null",
    "undefined": "null",
}
```

| Zod 타입 | 출력 타입 |
|----------|-----------|
| `string` | `string` |
| `number` | `number` |
| `boolean` | `boolean` |
| `array` | `array` |
| `object` | `object` |
| `enum` | `string` |
| `literal` | `string` |
| `date` | `string` |
| `any`, `unknown` | `any` |
| `null`, `undefined` | `null` |

---

## API 엔드포인트

**`GET /api/graph-types-properties`**

types_property_{server}.json 파일을 읽어서 반환.
파일은 웹 에디터 시작 시 자동 생성됨.

---

## 이전 방식과 비교

| 항목 | 이전 | 현재 |
|------|------|------|
| 추출 기준 | `editor_config.json`의 `types_files` 설정 | 자동 탐지 (types/models/schema 키워드) |
| 범위 | 설정된 파일 내 모든 BaseModel | 키워드 매칭 파일 내 모든 BaseModel |
| 설정 의존 | `types_files` 경로 필수 | 없음 |
| 호출 시점 | API 호출 시 (lazy) | 웹 에디터 시작 시 |
| 클래스 위치 | 설정 파일에 명시된 경로만 | 프로젝트 내 어디든 |
| JavaScript 지원 | 제한적 | JSDoc @mcp_service 패턴 지원 |

---

## 연관 파일

- `registry_{server}.json` - 서비스 정의 (파라미터에 class_name 포함)
- `types_property_{server}.json` - 참조된 타입 프로퍼티 정보
- `profile_management.py` - 프로필 삭제 시 두 파일 모두 제거

---

## JavaScript 타입 추출

### JSDoc @mcp_service 패턴 (권장)

JavaScript 프로젝트에서 MCP 서비스를 정의하는 권장 방식:

```javascript
/**
 * @mcp_service
 * @server_name asset_management
 * @tool_name get_crew_list
 * @service_name getCrew
 * @description 전체 선원 정보 조회
 * @category crew_query
 * @tags query,search,filter
 * @param {Array<number>} [shipIds] - 선박 ID 목록
 * @param {string} where - 검색 조건
 * @param {Object} options - 옵션
 * @param {number} [options.limit] - 최대 결과 수
 * @returns {Array<Object>} 선원 목록
 */
crewService.getCrew = async (params = {}) => {
  // ...
};
```

### 지원 JSDoc 태그

| 태그 | 설명 | 예시 |
|------|------|------|
| `@mcp_service` | MCP 서비스 표시 (필수) | `@mcp_service` |
| `@server_name` | 서버 이름 | `@server_name asset_management` |
| `@tool_name` | 도구 이름 | `@tool_name get_crew_list` |
| `@service_name` | 서비스 이름 | `@service_name getCrew` |
| `@description` | 설명 | `@description 선원 정보 조회` |
| `@category` | 카테고리 | `@category crew_query` |
| `@tags` | 태그 (쉼표 구분) | `@tags query,search,filter` |
| `@param` | 파라미터 | `@param {type} [name] - description` |
| `@returns` | 반환 타입 | `@returns {type} description` |

### 지원 함수 패턴

JSDoc 블록 다음에 인식되는 함수 정의 패턴:

```javascript
// Pattern 1: obj.method = async (params) => {}
crewService.getCrew = async (params = {}) => { ... }

// Pattern 2: async function name(params) {}
async function updateUserLicense(id, updateData) { ... }

// Pattern 3: const name = async (params) => {}
const getCrew = async function(params) { ... }

// Pattern 4: exports.name = async (params) => {}
exports.getCrew = async (params) => { ... }
```

---

## Sequelize 모델 추출 (데이터 타입)

### 지원 패턴

**Sequelize 모델 정의:**
```javascript
module.exports = function(sequelize, DataTypes) {
  return sequelize.define('mstEmployee', {
    id: {
      autoIncrement: true,
      type: DataTypes.INTEGER,
      allowNull: false,
      primaryKey: true,
      field: 'ID'
    },
    nameKr: {
      type: DataTypes.STRING(40),
      allowNull: true,
      field: 'NAME_KR'
    }
  });
};
```

### Sequelize 타입 매핑 (service_registry/javascript/types.py - SEQUELIZE_TYPE_MAP)

```python
SEQUELIZE_TYPE_MAP = {
    "STRING": "string",
    "TEXT": "string",
    "CHAR": "string",
    "INTEGER": "integer",
    "BIGINT": "integer",
    "SMALLINT": "integer",
    "TINYINT": "integer",
    "FLOAT": "number",
    "DOUBLE": "number",
    "DECIMAL": "number",
    "REAL": "number",
    "BOOLEAN": "boolean",
    "DATE": "string",
    "DATEONLY": "string",
    "TIME": "string",
    "NOW": "string",
    "UUID": "string",
    "UUIDV1": "string",
    "UUIDV4": "string",
    "JSON": "object",
    "JSONB": "object",
    "BLOB": "string",
    "ENUM": "string",
    "ARRAY": "array",
    "GEOMETRY": "object",
    "GEOGRAPHY": "object",
    "VIRTUAL": "any",
}
# 매핑에 없는 타입 → "any"
```

| Sequelize DataType | 출력 타입 | 비고 |
|--------------------|-----------|------|
| `STRING`, `TEXT`, `CHAR` | `string` | |
| `INTEGER`, `BIGINT`, `SMALLINT`, `TINYINT` | `integer` | |
| `FLOAT`, `DOUBLE`, `DECIMAL`, `REAL` | `number` | |
| `BOOLEAN` | `boolean` | |
| `DATE`, `DATEONLY`, `TIME`, `NOW` | `string` | |
| `UUID`, `UUIDV1`, `UUIDV4` | `string` | |
| `JSON`, `JSONB` | `object` | |
| `BLOB` | `string` | |
| `ENUM` | `string` | |
| `ARRAY` | `array` | |
| `GEOMETRY`, `GEOGRAPHY` | `object` | 공간 데이터 |
| `VIRTUAL` | `any` | 가상 필드 |

### JavaScript 출력 파일 구조

**파일**: `types_property_{server}.json`

```json
{
  "version": "1.0",
  "generated_at": "2026-01-13T...",
  "server_name": "asset",
  "language": "javascript",
  "classes": [
    {
      "name": "mstEmployee",
      "file": "/path/to/models/mst_employee.js",
      "type": "sequelize_model",
      "property_count": 24
    }
  ],
  "properties_by_class": {
    "mstEmployee": [
      {
        "name": "id",
        "type": "integer",
        "is_optional": false,
        "is_primary_key": true,
        "db_field": "ID"
      },
      {
        "name": "nameKr",
        "type": "string",
        "is_optional": true,
        "maxLength": 40,
        "db_field": "NAME_KR"
      }
    ]
  },
  "all_properties": [
    {
      "name": "id",
      "type": "integer",
      "source": "model:mstEmployee",
      "full_path": "mstEmployee.id"
    }
  ]
}
```

### 스캔 대상 디렉토리

파일 경로에 다음이 포함된 경우 Sequelize 모델로 스캔:
- `model` (대소문자 무관)
- `sequelize`

**예시:**
- `/project/sequelize/models/*.js` - 스캔됨
- `/project/models2/*.js` - 스캔됨
- `/project/routes/*.js` - 스캔 안됨

### 스킵 디렉토리

**mcp_service_scanner.py (서비스 스캔):**
```python
DEFAULT_SKIP_PARTS = ("venv", "__pycache__", ".git", "node_modules", "backups", ".claude")
```

**service_registry/python/types.py (Python 타입 스캔):**
```python
DEFAULT_SKIP_DIRS = ("node_modules", ".git", "dist", "build", "__pycache__", "venv", ".venv", "env")
```

**service_registry/javascript/types.py (JavaScript 타입 스캔):**
```python
DEFAULT_SKIP_DIRS = ("node_modules", ".git", "dist", "build", "__pycache__", "venv")
```

---

## scan_codebase_for_mcp_services 파라미터

`mcp_service_scanner.py`의 메인 스캔 함수:

```python
DEFAULT_SKIP_PARTS = ("venv", "__pycache__", ".git", "node_modules", "backups", ".claude")

def scan_codebase_for_mcp_services(
    base_dir: str,
    server_name: Optional[str] = None,
    exclude_examples: bool = True,
    skip_parts: tuple[str, ...] = DEFAULT_SKIP_PARTS,
    languages: Optional[List[str]] = None,
    include_jsdoc_pattern: bool = True,
) -> Dict[str, Dict[str, Any]]:
```

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `base_dir` | str | (필수) | 스캔할 기본 디렉토리 |
| `server_name` | Optional[str] | None | 필터링할 서버 이름 |
| `exclude_examples` | bool | True | example 파일 제외 |
| `skip_parts` | tuple | DEFAULT_SKIP_PARTS | 스킵할 디렉토리 |
| `languages` | Optional[List[str]] | None | 스캔할 언어 ("python", "javascript", "typescript") |
| `include_jsdoc_pattern` | bool | True | JSDoc @mcp_service 패턴 스캔 포함 |

### 언어별 확장자 매핑

| 언어 | 확장자 |
|------|--------|
| python | `.py` |
| javascript | `.js`, `.mjs` |
| typescript | `.ts`, `.tsx` |
