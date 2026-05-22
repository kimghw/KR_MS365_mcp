# 레지스트리 서버 데이터 흐름

## 웹 에디터에서의 사용

### 사용 목적 (2가지)

1. **서비스 목록 드롭다운 표시** - 도구 편집 시 연결할 서비스 선택
2. **저장 시 signature/parameters 보강** - tool_definition_templates.yaml에 서비스 메타데이터 추가

### 사용 흐름 1: 서비스 목록 표시

```
mcp_editor/mcp_{server}/registry_{server}.json
         │
         ▼
GET /api/mcp-services (registry_routes.py)
         │
         ▼
웹 에디터 UI: mcp_service 드롭다운
         │
         ▼
사용자가 서비스 선택 (예: query_mail_list)
```

### 사용 흐름 2: 저장 시 보강

```
웹 에디터에서 도구 저장
         │
         ▼
tool_saver.py:save_tool_definitions()
         │
         ▼
service_registry.py:load_services_for_server()
         │
         ▼
registry_{server}.json에서 signature/parameters 읽기
         │
         ▼
tool_definition_templates.yaml에 mcp_service 정보 추가
    - signature: "user_email: str, filter_params: Optional[FilterParams]..."
    - parameters: [{name, type, is_optional, default, class_name}, ...]
```

### 관련 코드

| 파일 | 함수 | 역할 |
|------|------|------|
| `tool_editor_core/routes/registry_routes.py` | `get_mcp_services()` | 서비스 목록 API |
| `tool_editor_core/routes/registry_routes.py` | `get_registry()` | 레지스트리 파일 직접 반환 |
| `tool_editor_core/service_registry.py` | `load_services_for_server()` | 저장 시 메타데이터 로드 |
| `tool_editor_core/service_registry.py` | `scan_all_registries()` | 웹 에디터 시작 시 전체 프로필 스캔 |
| `tool_editor_core/tool_saver.py` | `save_tool_definitions()` | registry 정보로 YAML 보강 |
| `static/js/tool_editor_tools.js` | `loadMcpServices()` | API 호출하여 UI에 표시 |

---

## 스캐너 모듈 구조

스캐너 모듈은 언어별로 분리되어 재구성되었습니다.

### 모듈 구조

```
service_registry/
├── scanner.py           # 통합 진입점 (re-exports)
├── base.py              # 기본 유틸리티
├── python/
│   └── scanner.py       # Python 스캐너
└── javascript/
    └── scanner.py       # JavaScript 스캐너
```

### 1. 메인 스캐너: `service_registry/scanner.py`

통합 진입점으로, 모든 하위 모듈의 함수를 re-export합니다.

| 함수 | 설명 |
|------|------|
| `scan_codebase_for_mcp_services()` | 전체 코드베이스 스캔 (Python/JS 자동 감지) |
| `export_services_to_json()` | 레지스트리 및 타입 파일 생성 |
| `get_services_map()` | 서비스 맵 조회 |

### 2. Python 스캐너: `service_registry/python/scanner.py`

Python 코드의 `@mcp_service` 데코레이터를 AST 기반으로 파싱합니다.

| 함수/클래스 | 설명 |
|------------|------|
| `MCPServiceExtractor` | AST 기반 서비스 추출 클래스 |
| `find_mcp_services_in_python_file()` | 단일 Python 파일 스캔 |
| `extract_decorator_metadata()` | 데코레이터에서 메타데이터 추출 |

### 3. JavaScript 스캐너: `service_registry/javascript/scanner.py`

JavaScript/TypeScript 코드의 MCP 서비스를 파싱합니다.

| 함수 | 설명 | 의존성 |
|------|------|--------|
| `find_mcp_services_in_js_file()` | esprima 기반 스캔 | `esprima` (선택) |
| `find_jsdoc_mcp_services_in_js_file()` | JSDoc 패턴 스캔 | 없음 (regex) |

### 4. 기본 유틸리티: `service_registry/base.py`

공통 유틸리티와 상수를 제공합니다.

| 항목 | 설명 |
|------|------|
| `Language` enum | `PYTHON`, `JAVASCRIPT`, `TYPESCRIPT`, `UNKNOWN` |
| `detect_language()` | 파일 확장자로 언어 감지 |
| `DEFAULT_SKIP_PARTS` | 스캔 제외 디렉토리 목록 |

**DEFAULT_SKIP_PARTS**: `("venv", "__pycache__", ".git", "node_modules", "backups", ".claude")`

### 5. 인터페이스 기반 스캐너 시스템

언어별 스캐너는 공통 인터페이스(`AbstractServiceScanner`)를 구현하며, `ScannerRegistry`를 통해 통합적으로 관리됩니다.

#### 어댑터 파일 구조

```
service_registry/
├── python/
│   └── scanner_adapter.py    # PythonServiceScanner (implements AbstractServiceScanner)
└── javascript/
    └── scanner_adapter.py    # JavaScriptServiceScanner (implements AbstractServiceScanner)
```

#### 인터페이스 기반 사용법

```python
from service_registry import ScannerRegistry

# 언어별 스캐너 가져오기
scanner = ScannerRegistry.get('python')
services = scanner.scan_file('service.py')

# 파일 확장자로 스캐너 자동 감지
scanner = ScannerRegistry.get_for_file('service.js')

# 직접 스캔 (스캐너 자동 선택)
services = ScannerRegistry.scan_file('any_file.py')
```

#### ServiceInfo 데이터클래스

`scan_file()` 메서드가 반환하는 서비스 정보 구조입니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `function_name` | `str` | 함수/메서드 이름 |
| `signature` | `str` | 함수 시그니처 문자열 |
| `parameters` | `List[Dict]` | 파라미터 정보 배열 |
| `metadata` | `Dict` | 데코레이터/JSDoc 메타데이터 |
| `is_async` | `bool` | 비동기 함수 여부 |
| `file` | `str` | 소스 파일 절대 경로 |
| `line` | `int` | 함수 정의 라인 번호 |
| `language` | `str` | 언어 ("python" \| "javascript") |
| `class_name` | `Optional[str]` | 클래스명 (Python) |
| `instance` | `Optional[str]` | 인스턴스 변수명 (Python) |
| `method` | `str` | 호출할 메서드명 |
| `pattern` | `Optional[str]` | 스캔 패턴 ("jsdoc" 등) |

---

## 요약

| 항목 | 내용 |
|------|------|
| **메인 스캐너** | `service_registry/scanner.py` |
| **Python 스캐너** | `service_registry/python/scanner.py` |
| **JavaScript 스캐너** | `service_registry/javascript/scanner.py` |
| **기본 유틸리티** | `service_registry/base.py` |
| **출력 경로** | `mcp_editor/mcp_{server}/registry_{server}.json` |
| **호출 시점** | 웹 에디터 시작 시 `scan_all_registries()` 자동 호출 |
| **API 엔드포인트** | `GET /api/mcp-services`, `GET /api/registry` |

### 참조 스크립트

| 스크립트 | 함수/메서드 | 용도 |
|----------|-------------|------|
| `service_registry/scanner.py` | `export_services_to_json()` | 레지스트리 및 타입 파일 생성 |
| `service_registry/scanner.py` | `scan_codebase_for_mcp_services()` | 소스 코드 스캔 |
| `service_registry/scanner.py` | `get_services_map()` | 서비스 맵 조회 |
| `service_registry/python/scanner.py` | `MCPServiceExtractor` | Python AST 기반 서비스 추출 |
| `service_registry/python/scanner.py` | `find_mcp_services_in_python_file()` | Python 파일 스캔 |
| `service_registry/python/scanner.py` | `extract_decorator_metadata()` | 데코레이터 메타데이터 추출 |
| `service_registry/javascript/scanner.py` | `find_jsdoc_mcp_services_in_js_file()` | JavaScript JSDoc 기반 스캔 |
| `service_registry/javascript/scanner.py` | `find_mcp_services_in_js_file()` | JavaScript esprima 기반 스캔 (선택) |
| `service_registry/base.py` | `Language` enum | 언어 타입 정의 |
| `service_registry/base.py` | `detect_language()` | 언어 자동 감지 |
| `service_registry.py` | `load_services_for_server()` | 서비스 메타데이터 로드 |
| `service_registry.py` | `scan_all_registries()` | 전체 프로필 스캔 및 레지스트리 갱신 |
| `registry_routes.py` | `get_mcp_services()` | API 응답 생성 |
| `registry_routes.py` | `get_registry()` | 레지스트리 파일 직접 반환 |
| `registry_routes.py` | `get_template_sources()` | 템플릿 소스 파일 목록 |
| `registry_routes.py` | `load_from_template_source()` | 템플릿에서 MCP_TOOLS 로드 |

### 지원 언어 및 패턴

| 언어 | 확장자 | 서비스 정의 패턴 | 파서 |
|------|--------|-----------------|------|
| Python | `.py` | `@mcp_service` 데코레이터 | `ast` (내장) |
| JavaScript | `.js`, `.mjs` | `@mcp_service` JSDoc 주석 | regex (내장) |
| TypeScript | `.ts`, `.tsx` | `@McpService` 데코레이터 | `esprima` (선택) |

**JavaScript JSDoc 패턴** (권장):
```javascript
/**
 * @mcp_service
 * @server_name asset_management
 * @tool_name search_ships
 * @description 선박을 검색합니다
 * @category ship_query
 * @tags query,search
 * @param {string} [name] - 선박 이름
 * @param {string} [imo] - IMO 번호
 * @returns {Array<Object>} 선박 목록
 */
async function searchShips(name, imo) { ... }
```

**주의사항**:
- JavaScript JSDoc 패턴: **esprima 불필요** (regex 기반 파싱)
- TypeScript 데코레이터 패턴: `pip install esprima` 필요
- JSDoc 태그: `@mcp_service`, `@server_name`, `@tool_name`, `@service_name`, `@description`, `@category`, `@tags`, `@param`, `@returns`

---

## registry_{server}.json 구조

**파일 위치**: `mcp_editor/mcp_{server}/registry_{server}.json`

### Python 레지스트리 구조 (실제 예시: registry_outlook.json)

```json
{
  "version": "1.0",                       // 레지스트리 포맷 버전
  "generated_at": "2026-01-14T00:02:12.691289",  // 생성 시간 (ISO datetime)
  "server_name": "outlook",               // 서버 이름
  "language": "python",                   // 프로젝트 언어 ("python" | "javascript")
  "services": {                           // 서비스별 메타데이터
    "query_mail_list": {
      "service_name": "query_mail_list",
      "handler": {
        "class_name": "MailService",      // 클래스명 (없으면 null)
        "instance": "mail_service",       // 인스턴스 변수명 (snake_case)
        "method": "query_mail_list",      // 호출할 메서드명
        "is_async": true,                 // 비동기 함수 여부
        "file": "/home/kimghw/Connector_auth/mcp_outlook/outlook_service.py",
        "line": 64                        // 함수 정의 라인 번호
      },
      "signature": "user_email: str, query_method: Optional[QueryMethod] = \"QueryMethod.FILTER\", filter_params: Optional[FilterParams] = None, ...",
      "parameters": [
        {
          "name": "user_email",           // 파라미터 이름
          "type": "str",                  // JSON Schema 호환 타입
          "is_optional": false,           // Optional 여부 (false = 필수)
          "default": null,                // 기본값
          "has_default": false            // 기본값 존재 여부
        },
        {
          "name": "query_method",
          "type": "object",               // 클래스 타입은 "object"
          "class_name": "QueryMethod",    // 원본 클래스/Enum 이름
          "is_optional": true,
          "default": "QueryMethod.FILTER",
          "has_default": true
        },
        {
          "name": "filter_params",
          "type": "object",
          "class_name": "FilterParams",   // 원본 클래스 이름 (선택적)
          "is_optional": true,            // Optional 여부 (true = 선택)
          "default": null,
          "has_default": true
        }
      ],
      "metadata": {
        "tool_name": "handler_mail_list", // MCP 도구 이름
        "server_name": "outlook",         // 서버 식별자
        "service_name": "query_mail_list",// 서비스 이름
        "category": "outlook_mail",       // 카테고리
        "tags": ["query", "search"],      // 태그 목록
        "priority": 5,                    // 우선순위
        "description": "메일 리스트 조회 기능"  // 기능 설명
      },
      "pattern": null                     // 스캔 패턴 (Python은 null)
    }
  }
}
```

### JavaScript 레지스트리 구조 (실제 예시: registry_asset_management.json)

```json
{
  "version": "1.0",
  "generated_at": "2026-01-14T00:02:18.569255",
  "server_name": "asset_management",
  "language": "javascript",               // JavaScript 프로젝트
  "services": {
    "getCrew": {
      "service_name": "getCrew",
      "handler": {
        "class_name": null,               // JS 함수는 클래스 없음
        "instance": null,
        "method": "getCrew",
        "is_async": true,
        "file": "/home/kimghw/Connector_auth/mcp_asset_management/asset-api/services/crew.service.js",
        "line": 27
      },
      "signature": "shipIds: Array<number>, where: string, query: string",
      "parameters": [
        {
          "name": "shipIds",
          "type": "array",                // JSON Schema 타입
          "jsdoc_type": "Array<number>",  // 원본 JSDoc 타입 (JS 전용)
          "is_optional": true,
          "description": "선박 ID 목록으로 필터링",  // 파라미터 설명 (JS 전용)
          "default": null,
          "has_default": false
        },
        {
          "name": "where",
          "type": "string",
          "jsdoc_type": "string",
          "is_optional": true,
          "description": "검색 조건 (name|ship|mobile)",
          "default": null,
          "has_default": false
        },
        {
          "name": "query",
          "type": "string",
          "jsdoc_type": "string",
          "is_optional": true,
          "description": "검색어",
          "default": null,
          "has_default": false
        }
      ],
      "metadata": {
        "tool_name": "get_crew_list",
        "server_name": "asset_management",
        "description": "전체 선원 정보 조회 (육상, 선박 전체). 선박ID, 이름, 선박명, 핸드폰으로 필터링 가능",
        "category": "crew_query",
        "tags": ["query", "search", "filter"]
      },
      "pattern": "jsdoc"                  // "jsdoc" = JSDoc 패턴으로 스캔됨
    },
    "createCrew": {
      "service_name": "createCrew",
      "handler": {
        "class_name": null,
        "instance": null,
        "method": "createCrew",
        "is_async": true,
        "file": "/home/kimghw/Connector_auth/mcp_asset_management/asset-api/services/crew.service.js",
        "line": 276
      },
      "signature": "crewData: mstEmployee",
      "parameters": [
        {
          "name": "crewData",
          "type": "object",
          "jsdoc_type": "mstEmployee",
          "is_optional": false,
          "description": "선원 정보",
          "default": null,
          "has_default": false,
          "properties": {                  // 중첩 속성 (JS 전용)
            "nameKr": {
              "type": "string",
              "jsdoc_type": "string",
              "description": "한글 이름",
              "is_optional": false
            },
            "nameEng": {
              "type": "string",
              "jsdoc_type": "string",
              "description": "영문 이름 (필수)",
              "is_optional": false
            },
            "nameChi": {
              "type": "string",
              "jsdoc_type": "string",
              "description": "중국어 이름",
              "is_optional": true
            },
            "mobile": {
              "type": "string",
              "jsdoc_type": "string",
              "description": "전화번호",
              "is_optional": true
            }
          }
        }
      ],
      "metadata": {
        "tool_name": "create_crew",
        "server_name": "asset_management",
        "description": "새로운 선원 정보 생성",
        "category": "crew_crud",
        "tags": ["create", "crew"]
      },
      "pattern": "jsdoc"
    }
  }
}
```

### 언어별 필드 차이

| 필드 | Python | JavaScript |
|------|--------|------------|
| `language` | `"python"` | `"javascript"` |
| `handler.class_name` | 클래스명 (예: `"MailService"`) | `null` (함수 기반) |
| `handler.instance` | snake_case 인스턴스명 (예: `"mail_service"`) | `null` |
| `parameters[].class_name` | Python 클래스명 (예: `"FilterParams"`) | (없음) |
| `parameters[].jsdoc_type` | (없음) | JSDoc 원본 타입 (예: `"Array<number>"`) |
| `parameters[].description` | (없음) | JSDoc 파라미터 설명 |
| `parameters[].properties` | (없음) | 중첩 객체 속성 |
| `metadata.priority` | 정수 (예: `5`) | (없음) |
| `metadata.service_name` | 서비스 이름 | (없음) |
| `pattern` | `null` | `"jsdoc"` |

> **참고**:
> - `is_required` 대신 `is_optional` 사용 (반대 의미)
> - `module_path` 대신 `file`에서 절대 경로 제공

---

## API 엔드포인트

**파일**: `mcp_editor/tool_editor_core/routes/registry_routes.py`

| 엔드포인트 | 메서드 | 파라미터 | 설명 |
|------------|--------|----------|------|
| `/api/registry` | GET | `profile` | 특정 프로필의 레지스트리 파일 조회 |
| `/api/mcp-services` | GET | `profile` | MCP 서비스 목록 및 상세 정보 |
| `/api/template-sources` | GET | `profile` | 템플릿 소스 파일 목록 조회 |
| `/api/template-sources/load` | POST | `path` (body) | 특정 템플릿 파일에서 MCP_TOOLS 로드 |

### GET /api/registry 응답

레지스트리 JSON 파일의 전체 내용을 반환합니다.

**함수**: `get_registry()`

```python
@registry_bp.route("/api/registry", methods=["GET"])
def get_registry():
    profile = request.args.get("profile")
    # profile이 없으면 첫 번째 프로필 사용
    # registry_path: mcp_editor/mcp_{server}/registry_{server}.json
    return jsonify(registry_data)
```

**응답 예시**:
```json
{
  "version": "1.0",
  "generated_at": "2026-01-14T00:02:12.691289",
  "server_name": "outlook",
  "language": "python",
  "services": { ... }
}
```

### GET /api/mcp-services 응답

웹 에디터 UI용으로 가공된 서비스 목록입니다.

**함수**: `get_mcp_services()`

**레지스트리 파일 검색 우선순위**:
1. `mcp_editor/mcp_{server}/registry_{server}.json` (신규 형식)
2. `mcp_editor/{server}/{server}_mcp_services.json` (구형식)
3. `mcp_editor/{server}_mcp_services.json` (레거시)

**응답 예시**:
```json
{
  "services": ["query_mail_list", "fetch_and_process"],
  "services_with_signatures": [
    {
      "name": "query_mail_list",
      "parameters": [
        {
          "name": "user_email",
          "type": "str",
          "is_optional": false,
          "default": null,
          "has_default": false
        }
      ],
      "signature": "user_email: str, query_method: Optional[QueryMethod] = \"QueryMethod.FILTER\", ...",
      "class_name": "MailService",
      "file": "/home/kimghw/Connector_auth/mcp_outlook/outlook_service.py"
    }
  ],
  "groups": {
    "MailService": ["query_mail_list", "fetch_and_process"]
  },
  "is_merged": false,
  "source_profiles": []
}
```

**응답 필드 설명:**

| 필드 | 설명 |
|------|------|
| `services` | 서비스 이름 목록 (드롭다운용) |
| `services_with_signatures` | 서비스 상세 정보 배열 |
| `services_with_signatures[].name` | 서비스 이름 (service_name 사용) |
| `services_with_signatures[].parameters` | 파라미터 배열 |
| `services_with_signatures[].signature` | 시그니처 문자열 |
| `services_with_signatures[].class_name` | 클래스명 (Python) 또는 "Unknown" (JS) |
| `services_with_signatures[].file` | 소스 파일 절대 경로 |
| `groups` | 클래스별 서비스 그룹화 (병합 프로필용) |
| `is_merged` | 병합 프로필 여부 |
| `source_profiles` | 병합된 원본 프로필 목록 |

### GET /api/template-sources 응답

**함수**: `get_template_sources()`

사용 가능한 템플릿 소스 파일 목록을 반환합니다.

```json
{
  "sources": [
    {
      "name": "Current Template",
      "path": "/path/to/tool_definition_templates.py",
      "type": "current",
      "count": 5,
      "modified": "2026-01-14T00:00:00"
    },
    {
      "name": "tool_definitions_20260114.py",
      "path": "/path/to/backups/tool_definitions_20260114.py",
      "type": "backup",
      "count": 3,
      "modified": "2026-01-14T00:00:00"
    }
  ]
}
```

### POST /api/template-sources/load 응답

**함수**: `load_from_template_source()`

특정 템플릿 파일에서 MCP_TOOLS를 로드합니다.

**요청**:
```json
{
  "path": "/path/to/tool_definition_templates.py"
}
```

**응답**:
```json
{
  "success": true,
  "tools": [...],
  "source": "/path/to/tool_definition_templates.py",
  "count": 5
}
```

---

## 데이터 흐름

```
[웹 에디터 시작]

소스 코드 (@mcp_service 데코레이터/JSDoc)
         │
         ▼
service_registry.py:scan_all_registries()
         │
         ├─── _load_config_file() → editor_config.json 로드
         │
         ├─── 각 프로필에 대해:
         │    │
         │    ├─ is_merged 프로필 스킵 (registry 보존)
         │    │
         │    ├─ get_source_path_for_profile() → 소스 경로 추출
         │    │    (예: /home/kimghw/Connector_auth/mcp_outlook)
         │    │
         │    └─ service_registry/scanner.py:export_services_to_json()
         │         │
         │         ├─ Python: python/scanner.py:find_mcp_services_in_python_file()
         │         │
         │         └─ JavaScript: javascript/scanner.py:find_jsdoc_mcp_services_in_js_file()
         │
         ▼
mcp_editor/mcp_{server}/registry_{server}.json 생성
mcp_editor/mcp_{server}/types_property_{server}.json 생성 (타입 정보)
         │
         ▼
[런타임: API 호출]
         │
         ├─ GET /api/mcp-services
         │    └─ registry_routes.py:get_mcp_services()
         │         └─ JSON 응답 → 웹 UI 드롭다운 표시
         │
         └─ 도구 저장 시
              └─ service_registry.py:load_services_for_server()
                   └─ registry JSON에서 signature/parameters 로드
```

### scan_all_registries() 로직

**파일**: `mcp_editor/tool_editor_core/service_registry.py`

```python
def scan_all_registries():
    """Scan all profiles and update their registry and types_property files on startup."""
    from .config import _load_config_file

    config = _load_config_file()  # editor_config.json 로드

    for profile_name, profile_config in config.items():
        # 병합 프로필 스킵
        if profile_config.get("is_merged"):
            print(f"  Skipping {profile_name}: merged profile (registry preserved)")
            continue

        # 소스 경로 추출 (컨벤션 기반)
        source_path = get_source_path_for_profile(profile_name, profile_config)
        if not os.path.exists(source_path):
            print(f"  Skipping {profile_name}: source path not found: {source_path}")
            continue

        # 서버 이름 추출 (mcp_outlook -> outlook)
        server_name = profile_name.replace("mcp_", "") if profile_name.startswith("mcp_") else profile_name

        # 출력 디렉토리: mcp_editor/mcp_{server}/
        output_dir = os.path.join(BASE_DIR, f"mcp_{server_name}")
        os.makedirs(output_dir, exist_ok=True)

        print(f"  Scanning {profile_name} from {source_path}...")

        # 레지스트리 및 타입 파일 생성
        result = export_services_to_json(source_path, server_name, output_dir)
        print(f"    -> Exported {result['service_count']} services, {result['type_count']} types")
```

---

## type vs class_name 분리

### 배경
기존에는 `type` 필드에 클래스 이름이 직접 저장됨 (예: `"type": "FilterParams"`)
이는 JSON Schema 타입과 혼동되어 일관성 문제 발생

### 변경 후 구조 (Python)

| 상황 | type | class_name |
|------|------|------------|
| 기본 타입 | `str`, `int`, `bool` | (없음) |
| 제네릭 타입 | `List[str]`, `Dict[str, Any]` | (없음) |
| 커스텀 클래스 | `object` | `FilterParams` |

### JavaScript 타입 구조

| 상황 | type | jsdoc_type |
|------|------|------------|
| 기본 타입 | `string`, `number`, `boolean` | `string`, `number`, `boolean` |
| 배열 | `array` | `Array<number>`, `string[]` |
| 객체/커스텀 | `object` | `mstEmployee`, `Object` |
| 불명확 | `any` | `*`, `any` |

### 판별 로직 (`service_registry/python/scanner.py:_is_class_type`)

```python
def _is_class_type(type_str: str) -> bool:
    """커스텀 클래스인지 판별 (PascalCase이고 제네릭 아닌 경우)"""
    if not type_str or not type_str[0].isupper():
        return False

    # 제네릭 타입 프리픽스는 클래스가 아님
    generic_prefixes = ("List[", "Dict[", "Union[", "Optional[", "Set[", "Tuple[", "Callable[")
    if any(type_str.startswith(prefix) for prefix in generic_prefixes):
        return False

    # Python/typing 프리미티브도 제외
    primitives = ("None", "Any", "NoReturn", "Type", "Literal")
    if type_str in primitives:
        return False

    return True
```

### JSDoc 타입 매핑 (`service_registry/javascript/scanner.py:_map_jsdoc_type`)

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

def _map_jsdoc_type(jsdoc_type: str) -> str:
    """JSDoc 타입을 JSON Schema 타입으로 변환"""
    # Array<T> 또는 T[] 처리
    if jsdoc_type.startswith("Array<") or jsdoc_type.endswith("[]"):
        return "array"
    # 제네릭 타입 처리
    if "<" in jsdoc_type:
        base_type = jsdoc_type.split("<")[0]
        return JSDOC_TYPE_MAP.get(base_type, "object")
    # 알려진 타입 매핑, 모르면 object
    return JSDOC_TYPE_MAP.get(jsdoc_type, "object")
```

---

## 핵심 개념

### Handler vs Metadata

| 구분 | Handler | Metadata |
|------|---------|----------|
| 역할 | 실행 라우팅 정보 | 분류/설명 정보 |
| 예시 | class_name, method, file | category, tags, description |
| 사용 | 런타임 호출 | UI 표시, 검색 필터링 |

---

## load_services_for_server() 상세

**파일**: `mcp_editor/tool_editor_core/service_registry.py`

도구 저장 시 서비스 메타데이터를 로드하는 함수입니다.

### 함수 시그니처

```python
def load_services_for_server(
    server_name: str | None,
    scan_dir: str | None,
    force_rescan: bool = False
) -> dict:
    """Load service metadata from registry JSON first, fallback to AST scanning."""
```

### 동작 흐름

```
1. server_name에서 mcp_ 접두사 제거
   (mcp_outlook → outlook)
         │
         ▼
2. 레지스트리 파일 경로 결정
   mcp_editor/mcp_{server}/registry_{server}.json
         │
         ▼
3. 레지스트리 파일 존재 확인
   ├── 없으면: FileNotFoundError 발생
   └── 있으면: 계속
         │
         ▼
4. force_rescan이 False면:
   └── JSON에서 서비스 정보 로드하여 반환
         │
         ▼
5. force_rescan이 True면:
   └── get_services_map()으로 소스 재스캔 (캐시 사용)
```

### 반환 형식

```python
{
    "query_mail_list": {
        "signature": "user_email: str, query_method: Optional[QueryMethod] = \"QueryMethod.FILTER\", ...",
        "parameters": [...],
        "metadata": {...}
    },
    "fetch_and_process": { ... }
}
```

### 실제 코드

```python
def load_services_for_server(server_name: str | None, scan_dir: str | None, force_rescan: bool = False):
    if not server_name:
        return {}

    # server_name 변환: mcp_outlook -> outlook
    registry_name = server_name.replace("mcp_", "") if server_name.startswith("mcp_") else server_name

    # 레지스트리 파일 경로: mcp_editor/mcp_{server}/registry_{server}.json
    registry_path = os.path.join(BASE_DIR, f"mcp_{registry_name}", f"registry_{registry_name}.json")

    # 파일 존재 확인
    if not os.path.exists(registry_path):
        error_msg = f"Registry file not found: {registry_path}"
        print(f"ERROR: {error_msg}")
        raise FileNotFoundError(error_msg)

    if not force_rescan:
        # JSON에서 로드
        with open(registry_path, "r", encoding="utf-8") as f:
            registry_data = json.load(f)
            services = {}
            for service_name, service_info in registry_data.get("services", {}).items():
                services[service_name] = {
                    "signature": service_info.get("signature", ""),
                    "parameters": service_info.get("parameters", []),
                    "metadata": service_info.get("metadata", {}),
                }
            print(f"Loaded {len(services)} services from registry_{registry_name}.json")
            return services

    # force_rescan이 True면 소스 재스캔
    if not scan_dir:
        return {}

    cache_key = (server_name or "", scan_dir)
    if not force_rescan and cache_key in SERVICE_SCAN_CACHE:
        return SERVICE_SCAN_CACHE[cache_key]

    services = get_services_map(scan_dir, server_name)
    SERVICE_SCAN_CACHE[cache_key] = services
    return services
```

---

## JavaScript 서비스 스캔

### JSDoc 패턴 스캔

**함수**: `service_registry/javascript/scanner.py:find_jsdoc_mcp_services_in_js_file(file_path: str) -> Dict[str, Dict[str, Any]]`

regex 기반으로 JSDoc 주석의 `@mcp_service` 블록을 파싱하여 서비스 정보 추출.

### 지원하는 함수 패턴

```javascript
// 패턴 1: 객체 메서드 (crewService.getCrew = async ...)
crewService.getCrew = async (params = {}) => { ... }

// 패턴 2: 일반 함수 (async function name(...))
async function updateUserLicense(id, updateData) { ... }

// 패턴 3: const 화살표 함수 (const name = async function...)
const getCrew = async function(params) { ... }

// 패턴 4: exports 패턴 (exports.name = async...)
exports.getCrew = async (params) => { ... }
```

### 추출되는 정보 (실제 예시)

```javascript
/**
 * @mcp_service
 * @server_name asset_management    // → metadata.server_name
 * @tool_name get_crew_list         // → metadata.tool_name
 * @service_name getCrew            // → service_name (없으면 함수명 사용)
 * @description 전체 선원 정보 조회 (육상, 선박 전체). 선박ID, 이름, 선박명, 핸드폰으로 필터링 가능
 * @category crew_query             // → metadata.category
 * @tags query,search,filter        // → metadata.tags (콤마 구분)
 * @param {Array<number>} [shipIds] - 선박 ID 목록으로 필터링  // → parameters (optional)
 * @param {string} [where] - 검색 조건 (name|ship|mobile)     // → parameters (optional)
 * @param {string} [query] - 검색어                           // → parameters (optional)
 * @returns {Array<Object>} 선원 목록    // → returns
 */
crewService.getCrew = async (params = {}) => { ... }  // → is_async: true
```

**중첩 속성이 있는 객체 파라미터 예시:**
```javascript
/**
 * @mcp_service
 * @server_name asset_management
 * @tool_name create_crew
 * @description 새로운 선원 정보 생성
 * @category crew_crud
 * @tags create,crew
 * @param {mstEmployee} crewData - 선원 정보
 * @param {string} crewData.nameKr - 한글 이름
 * @param {string} crewData.nameEng - 영문 이름 (필수)
 * @param {string} [crewData.nameChi] - 중국어 이름
 * @param {string} [crewData.mobile] - 전화번호
 * @returns {Object} 생성된 선원 정보
 */
crewService.createCrew = async (crewData) => { ... }
```

### JSDoc 타입 매핑

| JSDoc 타입 | JSON Schema 타입 | 비고 |
|-----------|-----------------|------|
| `{string}` | `"string"` | |
| `{number}` | `"number"` | |
| `{integer}`, `{int}` | `"integer"` | |
| `{boolean}`, `{bool}` | `"boolean"` | |
| `{Object}` | `"object"` | |
| `{Array}`, `{Array<T>}`, `{T[]}` | `"array"` | |
| `{*}`, `{any}` | `"any"` | |
| `{null}`, `{undefined}`, `{void}` | `"null"` | |
| `{mstEmployee}` (커스텀) | `"object"` | jsdoc_type에 원본 저장 |
| `[param]` (대괄호) | - | `is_optional: true` |

### 중첩 속성 지원

JSDoc의 `@param {type} parent.child` 패턴을 파싱하여 `properties` 객체로 변환:

```javascript
/**
 * @param {Object} crewData - 선원 정보
 * @param {string} crewData.nameKr - 한글 이름
 * @param {string} [crewData.mobile] - 전화번호 (선택)
 */
```

결과:
```json
{
  "name": "crewData",
  "type": "object",
  "properties": {
    "nameKr": {
      "type": "string",
      "description": "한글 이름",
      "is_optional": false
    },
    "mobile": {
      "type": "string",
      "description": "전화번호 (선택)",
      "is_optional": true
    }
  }
}
```

### 언어 자동 감지 및 타입 추출

**함수**: `service_registry/scanner.py:export_services_to_json(base_dir, server_name, output_dir) -> Dict[str, Any]`

프로젝트 언어를 자동 감지하고 적절한 타입 추출기를 사용합니다.

```python
def export_services_to_json(base_dir: str, server_name: str, output_dir: str) -> Dict[str, Any]:
    # 먼저 server_name 필터 없이 스캔하여 언어 감지
    all_services = scan_codebase_for_mcp_services(base_dir, server_name=None)

    # 스캔된 서비스에서 language 필드 확인
    has_js_services = any(s.get("language") == "javascript" for s in all_services.values())
    has_py_services = any(s.get("language") == "python" for s in all_services.values())

    # JavaScript만 있으면 JS 프로젝트로 판단 (server_name 필터 없이 사용)
    if has_js_services and not has_py_services:
        services = all_services
        # → extract_types_js.py 사용 (Sequelize 모델 추출)
        types_property_path = extract_types_js.export_js_types_property(
            base_dir, server_name, output_dir
        )
    else:
        # Python 프로젝트: server_name으로 필터링
        services = scan_codebase_for_mcp_services(base_dir, server_name)
        # → extract_types.py 사용 (Python BaseModel 추출)
        referenced_types = collect_referenced_types(services)
        types_property_path = export_types_property(referenced_types, server_name, output_dir)

    # 반환값
    return {
        "registry": str(registry_path),
        "types_property": types_property_path,
        "service_count": len(registry_output["services"]),
        "type_count": type_count,
        "language": "javascript" if is_js_project else "python",
    }
```

### JavaScript 스캔 방법

**함수**: `service_registry/scanner.py:scan_codebase_for_mcp_services()`

두 가지 스캔 방법을 순차적으로 시도:

1. **JSDoc 패턴** (기본, esprima 불필요): `javascript/scanner.py:find_jsdoc_mcp_services_in_js_file()`
2. **데코레이터 패턴** (esprima 필요, 선택적): `javascript/scanner.py:find_mcp_services_in_js_file()`

```python
def scan_codebase_for_mcp_services(
    base_dir: str,
    server_name: Optional[str] = None,
    exclude_examples: bool = True,
    skip_parts: tuple[str, ...] = DEFAULT_SKIP_PARTS,
    languages: Optional[List[str]] = None,
    include_jsdoc_pattern: bool = True,
) -> Dict[str, Dict[str, Any]]:

    # scan_codebase_for_mcp_services() 내부
    if ext in (".js", ".mjs", ".ts", ".tsx"):
        services = {}
        # 1. JSDoc 패턴 (주 방법) - esprima 불필요
        if include_jsdoc_pattern:
            jsdoc_services = find_jsdoc_mcp_services_in_js_file(file_str)
            services.update(jsdoc_services)
        # 2. esprima 데코레이터 패턴 (보조) - esprima 필요
        esprima_services = find_mcp_services_in_js_file(file_str)
        # JSDoc이 우선, esprima는 없는 것만 추가
        for name, info in esprima_services.items():
            if name not in services:
                services[name] = info
```
