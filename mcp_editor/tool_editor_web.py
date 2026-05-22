"""
Web interface for editing MCP Tool Definitions

=== WEB EDITOR UI ELEMENTS DOCUMENTATION ===

## 클릭 가능한 메뉴와 버튼들 (번호별)

### 1. 상단 툴바 버튼들 (Header Buttons)
   - [Reload] 버튼: loadTools() 호출 → GET /api/tools
     * 저장된 도구 정의를 다시 로드
   - [Backups] 버튼: showBackups() 호출 → GET /api/backups
     * 백업 목록 모달 표시
   - [Validate] 버튼: validateTools() 호출 → POST /api/tools/validate
     * 현재 도구 정의 유효성 검사
   - [Save Tools] 버튼: saveTools() 호출 → POST /api/tools/save-all
     * tools + internal_args 동시 저장
   - [Generate Server] 버튼: openGeneratorModal() 호출
     * 서버 생성 모달 열기

### 2. MCP 서버 컨트롤 버튼들
   - [Start] 버튼 (id="btn-start"): startServer() 호출 → POST /api/server/start
   - [Stop] 버튼 (id="btn-stop"): stopServer() 호출 → POST /api/server/stop
   - [Restart] 버튼 (id="btn-restart"): restartServer() 호출 → POST /api/server/restart

### 3. 도구별 액션 버튼들 (인덱스 기반)
   - [Add New Tool] 버튼: addNewTool() 호출
     * 새 도구 추가 (인덱스 자동 생성)
   - [Delete Tool] 버튼: deleteTool(index) 호출 → DELETE /api/tools/{index}
     * 특정 인덱스의 도구 삭제
   - [Expand All] 버튼: expandAllProperties() 호출
     * 모든 속성 펼치기
   - [Collapse All] 버튼: collapseAllProperties() 호출
     * 모든 속성 접기

### 4. 속성 관리 버튼들
   - [Add Property] 버튼: addProperty(index) 호출
     * 도구에 새 속성 추가 (도구 인덱스 필요)
   - [Remove Property] 버튼: removeProperty(index, propName) 호출
     * 특정 속성 제거 (도구 인덱스 + 속성명)
   - [BaseModel] 버튼: showBaseModelSelector(index, propName) 호출
     * BaseModel 스키마 적용 (도구 인덱스 + 속성명)

### 5. 중첩 속성 버튼들
   - [Add Nested Properties] 버튼: openNestedGraphTypesModal(index, propName)
     * 중첩 속성 추가 모달 (도구 인덱스 + 부모 속성명)
   - 중첩 속성 체크박스: data-tool-index + data-parent-prop + data-nested-prop 속성
   - [Remove Nested] 버튼: removeNestedPropertyInline(index, propName, nestedPropName)

## 입력 가능한 필드들 (저장 위치)

### 1. 도구 기본 정보 (tools[index])
   - name: 도구 이름 입력 → tools[index].name
   - description: 도구 설명 → tools[index].description
   - mcp_service: 서비스 선택/입력 → tools[index].mcp_service

### 2. 속성 정보 (tools[index].inputSchema.properties[propName])
   - 속성 이름 입력 → properties의 key
   - type: 타입 선택 (string/number/boolean 등) → properties[propName].type
   - description: 속성 설명 → properties[propName].description
   - default: 기본값 → properties[propName].default
   - enum: 열거값 → properties[propName].enum
   - format: 포맷 (uri, email 등) → properties[propName].format

### 3. Internal Args & Signature Defaults (mcp_service_factors에 저장)
   - Internal toggle: 체크 시 → mcp_service_factors[propName] (source: 'internal')
   - Signature Defaults toggle: 체크 시 → mcp_service_factors[propName] (source: 'signature_defaults')
   - 저장 위치: tool_definition_templates.py의 mcp_service_factors 필드

### 4. 파일 저장 경로
   - tool_definitions.py: 클린 버전 (mcp_service 제외)
   - tool_definition_templates.py: 템플릿 버전 (mcp_service + mcp_service_factors 포함)
   - backups/: 백업 파일들

## 데이터 인덱싱 구조
- tools[]: 0부터 시작하는 도구 배열 인덱스
- properties{}: 속성명을 key로 하는 객체
- mcp_service_factors{}: 파라미터명 → {source, baseModel, parameters} 구조
- 중첩 속성: data-tool-index + data-parent-prop + data-nested-prop

## API 엔드포인트 매핑
- GET /api/tools: 도구 목록 로드
- POST /api/tools/save-all: 전체 저장 (권장)
- DELETE /api/tools/{index}: 특정 도구 삭제
- POST /api/tools/validate: 유효성 검사
- GET /api/backups: 백업 목록
- POST /api/server/start: 서버 시작
- POST /api/server/stop: 서버 중지
- GET /api/mcp-services: 서비스 목록

=== END OF UI DOCUMENTATION ===

## 모듈 구조

이 파일은 모듈화된 tool_editor_web 패키지의 진입점입니다.

실제 구현은 tool_editor_core/ 디렉토리에 분리되어 있습니다:
- config.py: 설정 관리
- schema_utils.py: 스키마 처리 유틸리티
- backup_utils.py: 백업 관리
- tool_loader.py: 도구 정의 로딩
- tool_saver.py: 도구 정의 저장
- service_registry.py: 서비스 레지스트리
- profile_management.py: 프로필 재사용/삭제
- routes/: Flask 라우트 모듈들
- app.py: Flask 앱 팩토리
"""

import os
import sys

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import from modular package
from tool_editor_core.app import create_app, run_app

# Create the Flask app instance for backwards compatibility
app = create_app()

# Re-export commonly used functions for backwards compatibility
from tool_editor_core.config import (
    BASE_DIR,
    ROOT_DIR,
    CONFIG_PATH,
    DEFAULT_PROFILE,
    JINJA_DIR,
    SERVER_TEMPLATES,
    DEFAULT_SERVER_TEMPLATE,
    GENERATOR_SCRIPT_PATH,
    EDITOR_CONFIG_TEMPLATE,
    EDITOR_CONFIG_GENERATOR,
    get_profile_config,
    list_profile_names,
    resolve_paths,
    ensure_dirs,
    discover_mcp_modules,
    load_generator_module,
)

from tool_editor_core.schema_utils import (
    order_schema_fields,
    remove_defaults,
    clean_newlines_from_schema,
    ensure_target_params,
    convert_params_dict_to_list,
    convert_params_list_to_dict,
    is_all_none_defaults,
    prune_internal_properties,
)

from tool_editor_core.backup_utils import (
    backup_file,
    cleanup_old_backups,
)

from tool_editor_core.tool_loader import (
    load_tool_definitions,
    extract_service_factors,
    get_file_mtimes,
)

from tool_editor_core.tool_saver import (
    save_tool_definitions,
)

from tool_editor_core.service_registry import (
    SERVICE_SCAN_CACHE,
    load_services_for_server as _load_services_for_server,
    scan_all_registries,
)

from tool_editor_core.profile_management import (
    copy_yaml_templates,
    update_editor_config_for_reuse,
    create_server_project_folder,
    create_reused_profile,
    delete_mcp_profile,
)

# Global profiles list (for backwards compatibility)
profiles = list_profile_names()


if __name__ == "__main__":
    run_app()
