# editor_config.json 데이터 흐름

## 파일 위치
`mcp_editor/editor_config.json`

## 생성 시점
- **최초 생성**: `python -m service_registry.config_generator` 또는 `./test/generate_config.sh` 실행 시
- **자동 생성**: 웹 에디터 시작 시 `app.py`가 자동으로 생성 스크립트 실행
- **업데이트**: 프로필 생성/삭제 시 자동 갱신

## 쉘 스크립트 사용법

`mcp_editor/test/generate_config.sh` 스크립트로 편리하게 설정 파일을 생성/관리할 수 있습니다.

```bash
cd mcp_editor/test

# 기본 생성 (editor_config.json 생성)
./generate_config.sh

# 발견된 서버만 표시 (파일 생성 안함)
./generate_config.sh --dry-run

# 기존 config 삭제 후 새로 생성
./generate_config.sh --clean

# 현재 config 내용 표시
./generate_config.sh --show

# 도움말 표시
./generate_config.sh --help
```

> **참고**: 스크립트는 내부적으로 `python3 $MCP_EDITOR_DIR/service_registry/config_generator.py`를 실행합니다.

### 스크립트 동작 방식
1. 프로젝트 루트에서 `@mcp_service` 데코레이터/JSDoc 스캔
2. `mcp_*` 디렉토리 패턴 스캔
3. 발견된 서버로 `editor_config.json` 생성

## 자동 설정 (데코레이터/JSDoc 기반)

**개발자는 `@mcp_service`만 설정하면 됩니다.** 나머지는 자동 처리됩니다.

### Python 프로젝트

데코레이터 방식으로 `server_name`을 지정합니다:

```python
@mcp_service(server_name="outlook")
async def query_mail_list(...):
    ...
```

### JavaScript 프로젝트

JSDoc 주석 방식으로 `@server_name`을 지정합니다:

```javascript
/**
 * @mcp_service
 * @server_name asset_management
 * @tool_name update_user_license
 * @description 선원 라이센스 수정
 * @param {number} id - 라이센스 레코드 ID
 * @param {Object} updateData - 수정할 라이센스 정보
 */
async function updateUserLicense(id, updateData) {
    ...
}
```

### 흐름
```
Python: @mcp_service(server_name="outlook")     ← 개발자가 설정
JavaScript: @mcp_service + @server_name xxx    ← 개발자가 설정
        ↓
웹 에디터 시작 (app.py)
        ↓
service_registry.config_generator 자동 실행
  - Python: AST 파싱으로 데코레이터에서 server_name 추출
  - JavaScript: 정규식으로 JSDoc에서 @server_name 추출
        ↓
editor_config.json 자동 생성/갱신
```

### 컨벤션 기반 자동 유추

| 설정 | 자동 생성 결과 |
|:-----|:--------------|
| `server_name="outlook"` (Python) | 경로: `../mcp_outlook`, 포트: 순차 할당 |
| `@server_name asset_management` (JS) | 경로: `../mcp_asset_management`, 포트: 순차 할당 |

### 수동 설정이 필요 없는 항목
- `template_definitions_path` → `mcp_{server_name}/tool_definition_templates.py`
- `tool_definitions_path` → `../mcp_{server_name}/mcp_server/tool_definitions.py`
- `backup_dir` → `mcp_{server_name}/backups`
- `types_files` → 자동 탐지 (아래 "types_files 자동 탐지" 섹션 참조)
- `language` → 자동 탐지 (`python` 또는 `javascript`)
- `host` → `0.0.0.0`
- `port` → 8001부터 순차 할당

### types_files 자동 탐지

**Python:**
- AST 분석으로 `@mcp_service` 함수의 타입 힌트 추출
- import 문 분석으로 타입 정의 파일 경로 자동 탐지
- 예: `FilterParams` → `from .outlook_types import FilterParams` → `outlook_types.py`

**JavaScript (두 가지 방식 지원):**

1. **컨벤션 기반 자동 탐지 (기본 동작)**
   - `@param`/`@returns`의 타입 이름에서 camelCase → snake_case 변환
   - 예: `mstEmployee` → `mst_employee.js`
   - Sequelize 모델 디렉토리 패턴: `**/sequelize/models`, `**/sequelize/models2`
   - 파일 내 `sequelize.define('mstEmployee', ...)` 패턴으로 검증

2. **명시적 `@types_file` 태그 (선택, 컨벤션 불일치 시)**
   ```javascript
   /**
    * @mcp_service
    * @server_name asset_management
    * @types_file ../custom_models
    */
   ```

**컨벤션 기반 탐지가 실패하는 경우 조치:**
| 상황 | 조치 |
|:-----|:-----|
| 파일명이 snake_case 아님 (예: `MstEmployee.js`) | `@types_file` 태그로 직접 지정 |
| 비 Sequelize 프로젝트 | `@types_file` 태그로 직접 지정 |
| 모델 디렉토리가 `sequelize/models` 패턴 아님 | `@types_file` 태그로 직접 지정 |
| 타입명과 파일명 매칭 실패 | `@types_file` 태그로 직접 지정 |

### 수동 경로 입력이 필요한 경우

다음 상황에서는 `editor_config.json`에 경로를 직접 입력해야 합니다:

1. **`mcp_` 접두사를 사용할 수 없는 경우**
   - 기존 프로젝트 폴더명이 `mcp_`로 시작하지 않는 경우
   - 예: `my_service/`, `legacy_api/` 등

2. **자동 인식이 실패하는 경우**
   - `@mcp_service` 데코레이터/JSDoc이 파싱되지 않는 경우
   - 비표준 프로젝트 구조를 사용하는 경우

3. **수동 설정 예시**
   ```json
   {
     "my_custom_server": {
       "template_definitions_path": "custom_path/tool_definition_templates.py",
       "tool_definitions_path": "../my_service/mcp_server/tool_definitions.py",
       "backup_dir": "custom_path/backups",
       "types_files": ["../my_service/types.py"],
       "language": "python",
       "host": "0.0.0.0",
       "port": 8010
     }
   }
   ```

> **참고**: 자동 생성 스크립트 실행 시 수동 설정한 프로필은 덮어쓰지 않음

> **결론**: 일반적으로 수동 편집 불필요. `mcp_` 컨벤션을 따르지 못하는 경우에만 직접 입력

## 참조 파일 및 함수

| 파일 | 함수 | 용도 |
|:-----|:-----|:-----|
| `config.py` | `_load_config_file()` | 설정 파일 로딩 (메인 진입점) |
| `config.py` | `get_profile_config()` | 특정 프로필 설정 조회 |
| `config.py` | `list_profile_names()` | 프로필 목록 반환 |
| `config.py` | `save_config_file()` | 설정 파일 저장 |
| `config.py` | `get_source_path_for_profile()` | 소스 경로 유추 (컨벤션 기반) |
| `config.py` | `resolve_paths()` | 상대 경로를 절대 경로로 변환 |
| `config.py` | `migrate_config_schema()` | 기존 설정을 새 스키마로 마이그레이션 |
| `config.py` | `update_derived_profiles_list()` | base 프로필의 derived_profiles 목록 업데이트 |
| `profile_management.py` | `copy_yaml_templates()` | YAML 템플릿 복사 |
| `profile_management.py` | `update_editor_config_for_reuse()` | 재사용 프로필 설정 추가 |
| `profile_management.py` | `create_server_project_folder()` | 서버 프로젝트 폴더 생성 |
| `profile_management.py` | `create_reused_profile()` | 재사용 프로필 생성 |
| `profile_management.py` | `create_derived_profile()` | 파생 프로필 생성 |
| `profile_management.py` | `delete_mcp_profile()` | 프로필 삭제 |
| `profile_management.py` | `delete_mcp_server_only()` | MCP 서버만 삭제 (서비스 코드 유지) |
| `profile_management.py` | `update_base_derived_relationship()` | base-derived 관계 업데이트 |
| `profile_management.py` | `remove_from_derived_list()` | derived_profiles에서 제거 |
| `app.py` | `run_app()` | 시작 시 자동 생성 트리거 |

> **참고**: MCP 서버 자체는 `editor_config.json`을 참조하지 않음. MCP 서버는 `tool_definitions.py`만 로드.

## 구조 예시

### 기본 프로필 (자동 생성)
```json
{
  "asset_management": {
    "template_definitions_path": "mcp_asset_management/tool_definition_templates.py",
    "tool_definitions_path": "../mcp_asset_management/mcp_server/tool_definitions.py",
    "backup_dir": "mcp_asset_management/backups",
    "types_files": [
      "../mcp_asset_management/asset-api/sequelize/models2/employee_account.js",
      "../mcp_asset_management/asset-api/sequelize/models2/employee_license.js",
      "../mcp_asset_management/asset-api/sequelize/models2/mst_employee.js"
    ],
    "language": "javascript",
    "host": "0.0.0.0",
    "port": 8001
  },
  "calendar": {
    "template_definitions_path": "mcp_calendar/tool_definition_templates.py",
    "tool_definitions_path": "../mcp_calendar/mcp_server/tool_definitions.py",
    "backup_dir": "mcp_calendar/backups",
    "types_files": ["../mcp_calendar/calendar_types.py"],
    "language": "python",
    "host": "0.0.0.0",
    "port": 8002
  },
  "file_handler": {
    "template_definitions_path": "mcp_file_handler/tool_definition_templates.py",
    "tool_definitions_path": "../mcp_file_handler/mcp_server/tool_definitions.py",
    "backup_dir": "mcp_file_handler/backups",
    "types_files": [],
    "language": "python",
    "host": "0.0.0.0",
    "port": 8003
  },
  "outlook": {
    "template_definitions_path": "mcp_outlook/tool_definition_templates.py",
    "tool_definitions_path": "../mcp_outlook/mcp_server/tool_definitions.py",
    "backup_dir": "mcp_outlook/backups",
    "types_files": [
      "../mcp_outlook/graph_mail_client.py",
      "../mcp_outlook/outlook_types.py"
    ],
    "language": "python",
    "host": "0.0.0.0",
    "port": 8004
  }
}
```

### 파생 프로필 (수동 추가 시)
```json
{
  "outlook": {
    "template_definitions_path": "mcp_outlook/tool_definition_templates.py",
    "tool_definitions_path": "../mcp_outlook/mcp_server/tool_definitions.py",
    "backup_dir": "mcp_outlook/backups",
    "types_files": ["../mcp_outlook/outlook_types.py"],
    "language": "python",
    "host": "0.0.0.0",
    "port": 8004,
    "is_base": true,
    "derived_profiles": ["outlook_read"]
  },
  "outlook_read": {
    "template_definitions_path": "mcp_outlook_read/tool_definition_templates.py",
    "tool_definitions_path": "../mcp_outlook_read/mcp_server/tool_definitions.py",
    "backup_dir": "mcp_outlook_read/backups",
    "types_files": ["../mcp_outlook/outlook_types.py"],
    "language": "python",
    "host": "0.0.0.0",
    "port": 8091,
    "base_profile": "outlook",
    "is_reused": true
  }
}
```

> **포트 규칙**: `config_generator.py` 실행 시 8001부터 순차 할당

## 프로필 스키마

| 필드 | 타입 | 설명 |
|:-----|:-----|:-----|
| `source_dir` | str | 서비스 소스 경로 (선택, 하위 호환성용) |
| `template_definitions_path` | str | 웹 에디터에서 편집하는 템플릿 경로 (`.py` 확장자) |
| `tool_definitions_path` | str | Jinja2로 생성될 Python 파일 경로 (MCP 서버가 로드) |
| `backup_dir` | str | 템플릿 저장 시 자동 백업 위치 |
| `types_files` | list | Pydantic/dataclass/Sequelize 타입 정의 파일 (타입 자동완성용, 빈 배열 가능) |
| `language` | str | 서비스 언어 (`python` 또는 `javascript`), 자동 탐지 |
| `host` | str | MCP 서버 바인드 호스트 (기본: `0.0.0.0`) |
| `port` | int | MCP 서버 포트 번호 (프로필별 고유) |
| `is_base` | bool | Base 프로필 여부 (`true`면 부모가 될 수 있음, 파생 프로필 생성 시 추가) |
| `base_profile` | str | 파생된 부모 프로필명 (선택, 파생 프로필에만 존재) |
| `derived_profiles` | list | Base에서 파생된 자식 프로필 목록 (선택, base 프로필에만 존재) |
| `is_reused` | bool | 기존 서비스 재사용 여부 (호환성, 파생 프로필에만 존재) |

### 필드 관계도
```
[Base 프로필]                    [Derived 프로필]
is_base: true          ←───→     base_profile: "outlook"
derived_profiles: [...]          is_reused: true
```

---


## 읽기 (Load)

| 함수 | 파일 | 설명 |
|------|------|------|
| `_load_config_file()` | `config.py` | 메인 로딩 함수 |
| `_get_config_path()` | `config.py` | 설정 파일 경로 반환 (환경변수 지원) |
| `get_profile_config()` | `config.py` | 특정 프로필 설정 조회 |
| `list_profile_names()` | `config.py` | 프로필 목록 조회 |
| `get_source_path_for_profile()` | `config.py` | 소스 경로 유추 (컨벤션 기반, 하위호환) |
| `resolve_paths()` | `config.py` | 상대 경로를 절대 경로로 변환 |

### 로딩 흐름
```
1. _get_config_path(): MCP_EDITOR_CONFIG 환경변수 확인 → 없으면 기본 경로 사용
2. 파일 존재 시:
   - JSON 파싱 시도
   - 실패 시 _generate_config_from_template() 호출
3. 파일 없으면:
   - _generate_config_from_template() 호출하여 자동 생성
   - 실패 시 DEFAULT_PROFILE로 기본 설정 생성
```

---

## 쓰기 (Save)

| 함수 | 파일 | 설명 |
|------|------|------|
| `save_config_file()` | `config.py` | 설정 전체 저장 |
| `update_derived_profiles_list()` | `config.py` | base 프로필의 derived_profiles 목록 업데이트 |
| `update_editor_config_for_reuse()` | `profile_management.py` | 재사용 프로필 추가 |
| `delete_mcp_profile()` | `profile_management.py` | 프로필 삭제 |
| `delete_mcp_server_only()` | `profile_management.py` | MCP 서버만 삭제 (서비스 코드 유지) |

---

## 자동 생성 (Generate)

### 파일 위치

| 파일 | 경로 | 설명 |
|------|------|------|
| **config_generator.py** | `mcp_editor/service_registry/config_generator.py` | 메인 설정 생성기 |
| **generate_config.sh** | `mcp_editor/test/generate_config.sh` | 쉘 스크립트 래퍼 |

> **참고**: `config_generator.py`는 `mcp_editor/service_registry/` 디렉토리에 위치하며, 인터페이스 기반 스캐너 시스템(`interfaces.py`, `registry.py`)과 동일한 디렉토리에 있습니다.

### Import 방법

```python
# config_generator 모듈 사용
from service_registry.config_generator import (
    scan_codebase_for_servers,
    scan_codebase_for_server_info,
    generate_editor_config_json,
    ServerInfo
)

# 인터페이스 기반 스캐너 시스템 사용 (대안)
from service_registry.registry import ScannerRegistry, TypeExtractorRegistry
from service_registry.interfaces import ServiceInfo, TypeInfo
```

### 인터페이스 기반 스캐너 시스템

`config_generator.py`는 자체 AST/JSDoc 파싱 로직을 사용하지만, `service_registry/` 패키지는 확장 가능한 인터페이스 기반 아키텍처도 제공합니다:

| 파일 | 설명 |
|------|------|
| `interfaces.py` | 추상 인터페이스 정의 (`AbstractServiceScanner`, `AbstractTypeExtractor`) |
| `registry.py` | 스캐너/타입 추출기 레지스트리 (`ScannerRegistry`, `TypeExtractorRegistry`) |
| `python/scanner_adapter.py` | Python 스캐너 구현체 |
| `javascript/scanner_adapter.py` | JavaScript 스캐너 구현체 |

**새 언어 지원 추가 방법:**
1. `service_registry/{language}/` 패키지 생성
2. `AbstractServiceScanner` 및 `AbstractTypeExtractor` 구현
3. `registry.py`의 `register_all_default_scanners()`에 등록

### 주요 함수

| 함수 | 파일 | 설명 |
|------|------|------|
| `scan_codebase_for_servers()` | `config_generator.py` | Python/JS 통합 스캔 (`*.py`, `*.js`, `*.mjs`) - 서버명만 반환 (하위호환) |
| `scan_codebase_for_server_info()` | `config_generator.py` | Python/JS 통합 스캔 - `ServerInfo` 반환 (language, types_files 포함) |
| `extract_server_info_from_py_file()` | `config_generator.py` | Python AST 파싱 - 타입 힌트 및 import 분석 포함 |
| `extract_server_info_from_js_file()` | `config_generator.py` | JavaScript JSDoc 파싱 - `@param`/`@returns` 타입 분석 포함 |
| `extract_server_name_from_py_file()` | `config_generator.py` | Python 파싱 (하위호환용, 서버명만 반환) |
| `extract_server_name_from_js_file()` | `config_generator.py` | JavaScript 파싱 (하위호환용, 서버명만 반환) |
| `scan_mcp_directories()` | `config_generator.py` | `mcp_*` 디렉토리 스캔 (mcp_server/server.py 존재 확인) |
| `generate_editor_config_json()` | `config_generator.py` | 설정 파일 생성 (포트 8001부터 순차 할당, `ServerInfo` 지원) |
| `detect_module_paths()` | `config_generator.py` | 모듈 경로 탐지 (types 파일 자동 탐색, `ServerInfo` 지원) |
| `find_sequelize_model_dirs()` | `config_generator.py` | Sequelize 모델 디렉토리 탐지 (`**/sequelize/models*` 패턴) |
| `find_sequelize_model_file()` | `config_generator.py` | 타입명으로 모델 파일 찾기 (camelCase → snake_case 변환) |
| `extract_types_from_jsdoc()` | `config_generator.py` | JSDoc에서 타입명 추출 (`@param`, `@returns`) |
| `extract_imports_from_py_file()` | `config_generator.py` | Python import 문 분석 (타입 소스 파일 탐지용) |
| `main()` | `config_generator.py` | 메인 진입점 (CLI 실행) |

### ServerInfo 클래스

```python
class ServerInfo:
    """Holds information about a discovered MCP server."""
    def __init__(self, name: str, language: str, source_file: str):
        self.name = name
        self.language = language  # "python" or "javascript"
        self.source_file = source_file
        self.types_files: Set[str] = set()  # Auto-detected type files
        self.type_names: Set[str] = set()   # Type names used in functions
```

### 스캔 방식

| 언어 | 스캔 대상 | 파싱 방식 |
|------|----------|----------|
| **Python** | `*.py` | AST 파싱 → `@mcp_service(server_name="xxx")` 추출 |
| **JavaScript** | `*.js`, `*.mjs` | 정규식 → JSDoc `@mcp_service` + `@server_name xxx` 추출 |

### 스킵 디렉토리 (SKIP_DIRS)
```python
("venv", "__pycache__", ".git", "node_modules", "backups", "dist", "build")
```

### 자동 생성 흐름
```
프로젝트 루트 전체 스캔
    │
    ├── [Pre-scan] Sequelize 모델 디렉토리 탐지
    │   └── find_sequelize_model_dirs() → **/sequelize/models* 패턴
    │
    ├── [Method 1] @mcp_service 데코레이터/JSDoc 스캔 (with 타입 분석)
    │   ├── [Python] extract_server_info_from_py_file()
    │   │   ├── AST 파싱 → @mcp_service(server_name="xxx") 추출
    │   │   ├── 함수 파라미터/리턴 타입 힌트 분석
    │   │   └── import 문 분석 → 타입 소스 파일 경로 추출
    │   │
    │   └── [JavaScript] extract_server_info_from_js_file()
    │       ├── JSDoc 정규식 → @mcp_service + @server_name 추출
    │       ├── @param/@returns에서 타입명 추출
    │       └── camelCase → snake_case 변환 → Sequelize 모델 파일 매칭
    │
    ├── [Method 2] mcp_* 디렉토리 스캔
    │   └── mcp_server/server.py 존재 확인 → server_name 추출
    │
    └── 두 결과 병합 (union)
           ↓
    detect_module_paths()로 경로 탐지 (ServerInfo 활용)
    - AST 분석으로 탐지된 types_files 우선 사용
    - 없으면 컨벤션 기반 탐색: {server_name}_types.py, outlook_types.py, types.py, graph_types.py
           ↓
    generate_editor_config_json() 호출
    (포트 8001부터 순차 할당, language 자동 설정)
           ↓
    editor_config.json 생성
```

---

## 파생 서버 지원 (Phase 1)

| 함수 | 파일 | 설명 |
|------|------|------|
| `get_base_profile()` | `config.py` | Base 프로필명 반환 (없으면 None) |
| `get_derived_profiles()` | `config.py` | 파생 프로필 목록 반환 |
| `get_sibling_profiles()` | `config.py` | 동일 base를 공유하는 형제 프로필 목록 |
| `is_base_profile()` | `config.py` | Base 여부 확인 (is_base 또는 base_profile 없음) |
| `get_profile_family()` | `config.py` | 프로필 패밀리 조회 (base, derived, current, is_base) |
| `migrate_config_schema()` | `config.py` | 기존 설정을 새 스키마로 마이그레이션 |
| `update_derived_profiles_list()` | `config.py` | base의 derived_profiles 추가/제거 |

### 프로필 관계
```
base 프로필 (outlook)
    ├── is_base: true
    └── derived_profiles: ["outlook_read", "outlook_write"]
              ↓
derived 프로필 (outlook_read)
    ├── base_profile: "outlook"
    ├── is_reused: true
    ├── template_definitions_path: "mcp_outlook_read/..."
    ├── tool_definitions_path: "../mcp_outlook_read/..."
    └── types_files: [...] (base와 동일)
```

### get_profile_family() 반환값 예시
```python
{
    "base": "outlook",           # base 프로필명
    "derived": ["outlook_read"], # 파생 프로필 목록
    "current": "outlook_read",   # 현재 프로필명
    "is_base": False             # 현재 프로필이 base인지
}
```

---

## 프로필 관리 함수

| 함수 | 파일 | 설명 |
|------|------|------|
| `copy_yaml_templates()` | `profile_management.py` | 템플릿 복사 (`.py` 파일) |
| `update_editor_config_for_reuse()` | `profile_management.py` | editor_config.json에 재사용 프로필 추가 |
| `create_server_project_folder()` | `profile_management.py` | 서버 프로젝트 폴더 생성 (`mcp_{profile}/mcp_server/`) |
| `create_reused_profile()` | `profile_management.py` | 재사용 프로필 생성 (통합 함수) |
| `create_derived_profile()` | `profile_management.py` | 파생 프로필 생성 (base-derived 관계 설정 포함) |
| `delete_mcp_profile()` | `profile_management.py` | 프로필 완전 삭제 (editor + project + config) |
| `delete_mcp_server_only()` | `profile_management.py` | MCP 서버만 삭제 (서비스 코드 유지) |
| `update_base_derived_relationship()` | `profile_management.py` | base-derived 관계 업데이트 |
| `remove_from_derived_list()` | `profile_management.py` | derived_profiles 목록에서 제거 |

---

## 결과물 (Output)

editor_config.json이 사용되는 곳:

| 용도 | 설명 |
|------|------|
| 웹 에디터 프로필 전환 | 드롭다운에서 프로필 선택 |
| 템플릿 경로 해석 | `tool_definition_templates.yaml` 위치 |
| 서버 코드 생성 경로 | `tool_definitions.py` 출력 위치 |
| 타입 파일 참조 | Pydantic 타입 정의 경로 |
| 서버 실행 설정 | host/port 정보 |
| 파생 프로필 관리 | Base-Derived 관계 추적 |

---

## 환경 변수

| 변수 | 설명 |
|------|------|
| `MCP_EDITOR_CONFIG` | 설정 파일 경로 오버라이드 |

---

## 데이터 관계

```
editor_config.json          mcp_{server}/registry_{server}.json
─────────────────          ─────────────────────────────────────
프로필 설정                  서비스 메타데이터
├── 경로 설정                ├── handler.file (소스 경로)
├── 서버 설정 (host/port)    ├── handler.module_path
└── 프로필 관계              ├── parameters
                            └── metadata
         ↓                           ↓
    웹 에디터 UI              서비스 스캔/호출
```

## Registry 파일 경로

| 파일 | 경로 |
|------|------|
| **registry** | `mcp_editor/mcp_{server}/registry_{server}.json` |
| **types_property** | `mcp_editor/mcp_{server}/types_property_{server}.json` |

> **변경됨**: 기존 `mcp_service_registry/` 경로에서 `mcp_{server}/` 경로로 통일

## 삭제 함수 비교

| 함수 | 삭제 대상 | 유지 대상 |
|------|----------|----------|
| `delete_mcp_profile()` | editor 폴더, project 폴더, types_property, config | 없음 |
| `delete_mcp_server_only()` | editor 폴더, mcp_server/, registry, types_property, config | service.py, types.py 등 |

### delete_mcp_server_only() 사용 시나리오
- 서비스 로직은 유지하면서 MCP 서버만 재생성할 때
- tool_definitions.py만 다시 생성하고 싶을 때

---

## MCP 서버 생성 연동

editor_config.json은 Jinja 템플릿 기반 서버 생성에서도 사용됩니다.

### 서버 생성 시 참조되는 필드

| 필드 | 서버 생성에서 사용 |
|:-----|:-----------------|
| `language` | Python/JavaScript 템플릿 선택 |
| `types_files` | 타입 import 생성 |
| `port` | 기본 서버 포트 |
| `tool_definitions_path` | TOOLS 정의 로드 (tool_definitions.py) |

### 서버 생성 방법

```bash
cd /home/kimghw/Connector_auth/mcp_editor/jinja

# editor_config.json의 프로필 사용
python generate_universal_server.py outlook --protocol stream

# 포트 오버라이드
python generate_universal_server.py outlook --port 9000
```

### 전체 흐름

```
[웹 에디터에서 도구 편집]
        ↓
editor_config.json (프로필 설정)
        ↓
registry_{server}.json (서비스 메타데이터)
        ↓
tool_definitions.py (도구 정의)
        ↓
generate_universal_server.py (Jinja 렌더링)
        ↓
server_stream.py (실행 가능한 MCP 서버)
```

> **참고**: 자세한 서버 생성 방법은 `workflow1.md`의 "MCP 서버 생성 (Jinja 템플릿)" 섹션을 참조하세요.
