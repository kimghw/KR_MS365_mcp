"""
JavaScript Type Extractor Module

JavaScript 프로젝트에서 **데이터 모델(타입 정의)**을 추출하는 모듈.
mcp_service_scanner.py에서 import하여 사용.

## 역할 분담

| 모듈 | 역할 |
|------|------|
| mcp_service_scanner.py | 서비스(tool) 스캔 + JSDoc 파라미터 추출 |
| extract_types_js.py | 데이터 모델 추출 (Sequelize 모델 등) |

## Sequelize vs Pydantic 비교

| 항목 | Pydantic (Python) | Sequelize (JavaScript) |
|------|-------------------|------------------------|
| 역할 | 데이터 모델/검증 | ORM (DB 모델) |
| 타입 정의 | 클래스 속성 + 타입 힌트 | init() 메서드에 필드 정의 |
| 용도 | API 스키마, 검증 | DB 테이블 매핑 |

### 예시 비교

Pydantic (Python):
    class Employee(BaseModel):
        id: int
        name_kr: str
        name_en: Optional[str] = None

Sequelize (JavaScript):
    mstEmployee.init({
        id: { type: DataTypes.INTEGER, primaryKey: true },
        nameKr: { type: DataTypes.STRING },
        nameEn: { type: DataTypes.STRING, allowNull: true },
    }, { sequelize, modelName: 'mstEmployee' });

## 소스 경로 탐지 방식

파일 경로에 "model" 또는 "sequelize"가 포함되면 자동 파싱:

    for js_file in Path(base_dir).rglob("*.js"):
        file_str = str(js_file)
        if "model" in file_str.lower() or "sequelize" in file_str.lower():
            models = extract_sequelize_models_from_file(file_str)

## 경로 흐름

    scan_all_registries()
            ↓
    get_source_path_for_profile("asset_management")
            ↓
    base_dir = "AssetManagement/asset-api"  ← editor_config 또는 컨벤션
            ↓
    export_services_to_json(base_dir, ...)
            ↓
    extract_types_js.export_js_types_property(base_dir, ...)
            ↓
    Path(base_dir).rglob("*.js")  ← 모든 .js 파일 스캔
            ↓
    "model" in path → sequelize/models2/*.js 탐지!

## 주요 함수

- extract_sequelize_models_from_file(file_path): Sequelize 모델 프로퍼티 추출
- scan_js_project_types(base_dir): 전체 JS 프로젝트 타입 스캔
- export_js_types_property(base_dir, server_name, output_dir): types_property JSON 생성
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


# =============================================================================
# Zod Type Mapping (mcp_service_scanner.py에서도 사용)
# =============================================================================

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


def map_zod_to_json_type(zod_type: str) -> str:
    """Map Zod type to JSON Schema type."""
    return ZOD_TYPE_MAP.get(zod_type.lower(), "any")


# =============================================================================
# Sequelize Type Mapping
# =============================================================================

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


def map_sequelize_to_json_type(sequelize_type: str) -> str:
    """Map Sequelize DataTypes to JSON Schema type."""
    base_type = sequelize_type.split("(")[0].upper()
    return SEQUELIZE_TYPE_MAP.get(base_type, "any")


# =============================================================================
# Sequelize Model Extraction
# =============================================================================

def extract_sequelize_models_from_file(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Extract Sequelize model definitions from a JavaScript file.

    Parses patterns like:
        sequelize.define('modelName', {
            fieldName: {
                type: DataTypes.STRING(50),
                allowNull: false,
                field: 'DB_FIELD_NAME'
            },
            ...
        })

    Returns:
        Dictionary mapping model names to their properties
    """
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return {}

    models = {}

    # Pattern to find sequelize.define() calls
    define_pattern = r"sequelize\.define\s*\(\s*['\"](\w+)['\"]\s*,\s*\{"

    for match in re.finditer(define_pattern, content):
        model_name = match.group(1)
        start_pos = match.end() - 1  # Position of opening {

        # Find the matching closing brace
        brace_count = 1
        end_pos = start_pos + 1
        while brace_count > 0 and end_pos < len(content):
            if content[end_pos] == "{":
                brace_count += 1
            elif content[end_pos] == "}":
                brace_count -= 1
            end_pos += 1

        model_body = content[start_pos:end_pos]

        # Extract field definitions
        properties = _parse_sequelize_fields(model_body)

        models[model_name] = {
            "name": model_name,
            "file": file_path,
            "properties": properties
        }

    return models


def _parse_sequelize_fields(model_body: str) -> List[Dict[str, Any]]:
    """Parse Sequelize field definitions from model body."""
    properties = []

    # Pattern for field definition
    # fieldName: { type: DataTypes.XXX, allowNull: true/false, ... }
    field_pattern = r"(\w+)\s*:\s*\{\s*([^}]+(?:\{[^}]*\}[^}]*)*)\}"

    for match in re.finditer(field_pattern, model_body):
        field_name = match.group(1)
        field_body = match.group(2)

        # Skip special fields
        if field_name in ("timestamps", "tableName", "modelName"):
            continue

        prop_info = {
            "name": field_name,
            "type": "any",
            "is_optional": True,
            "description": "",
            "db_field": None,
        }

        # Extract type
        type_match = re.search(r"type\s*:\s*(?:DataTypes|Sequelize)\.(\w+)(?:\(([^)]*)\))?", field_body)
        if type_match:
            seq_type = type_match.group(1)
            prop_info["type"] = map_sequelize_to_json_type(seq_type)

            # Extract size for string types
            if type_match.group(2):
                size_val = type_match.group(2).strip()
                if size_val.isdigit():
                    prop_info["maxLength"] = int(size_val)

        # Extract allowNull
        allow_null_match = re.search(r"allowNull\s*:\s*(true|false)", field_body)
        if allow_null_match:
            prop_info["is_optional"] = allow_null_match.group(1) == "true"

        # Extract primary key
        pk_match = re.search(r"primaryKey\s*:\s*true", field_body)
        if pk_match:
            prop_info["is_primary_key"] = True

        # Extract DB field name
        field_match = re.search(r"field\s*:\s*['\"]([^'\"]+)['\"]", field_body)
        if field_match:
            prop_info["db_field"] = field_match.group(1)

        # Extract default value
        default_match = re.search(r"defaultValue\s*:\s*([^,}\n]+)", field_body)
        if default_match:
            default_val = default_match.group(1).strip()
            prop_info["default"] = _parse_js_value(default_val)

        properties.append(prop_info)

    return properties


def _parse_js_value(value_str: str) -> Any:
    """Parse a JavaScript value string to Python value."""
    value_str = value_str.strip()

    if value_str == "true":
        return True
    elif value_str == "false":
        return False
    elif value_str == "null":
        return None
    elif value_str.startswith(("'", '"')):
        return value_str[1:-1]
    elif value_str.isdigit():
        return int(value_str)
    elif re.match(r"^\d+\.\d+$", value_str):
        return float(value_str)

    return value_str


# =============================================================================
# Directory Scanning
# =============================================================================

DEFAULT_SKIP_DIRS = ("node_modules", ".git", "dist", "build", "__pycache__", "venv")


def scan_js_project_types(
    base_dir: str,
    skip_dirs: tuple = DEFAULT_SKIP_DIRS
) -> Dict[str, Any]:
    """Scan a JavaScript project for type definitions (Sequelize models).

    Sequelize 모델 = DB 테이블의 JavaScript 표현 (Pydantic과 유사한 역할)

    탐지 방식:
        - base_dir 하위의 모든 .js 파일 재귀 스캔
        - 파일 경로에 "model" 또는 "sequelize" 포함 시 파싱
        - 예: AssetManagement/asset-api/sequelize/models2/*.js

    Note: Tool parameter 추출은 mcp_service_scanner.py에서 처리함.
          이 함수는 Sequelize 모델 타입 정의만 추출.

    Args:
        base_dir: Base directory to scan (예: "AssetManagement/asset-api")
        skip_dirs: Directory names to skip (node_modules, .git 등)

    Returns:
        Dictionary with models:
        {
            "models": {...},         # Sequelize models (DB 테이블 정의)
            "all_properties": [...]  # Flattened property list (700+ 프로퍼티)
        }
    """
    result = {
        "models": {},
        "all_properties": []
    }

    base_path = Path(base_dir)

    # Scan for JavaScript files
    for js_file in base_path.rglob("*.js"):
        # Skip excluded directories
        if any(skip in js_file.parts for skip in skip_dirs):
            continue

        file_str = str(js_file)

        # Look for Sequelize models
        if "model" in file_str.lower() or "sequelize" in file_str.lower():
            models = extract_sequelize_models_from_file(file_str)
            result["models"].update(models)

    # Build flattened properties list
    for model_name, model_info in result["models"].items():
        for prop in model_info.get("properties", []):
            result["all_properties"].append({
                "name": prop.get("name", ""),
                "type": prop.get("type", "any"),
                "description": prop.get("description", ""),
                "source": f"model:{model_name}",
                "full_path": f"{model_name}.{prop.get('name', '')}"
            })

    return result


def export_js_types_property(
    base_dir: str,
    server_name: str,
    output_dir: str
) -> str:
    """Export JavaScript types (Sequelize models) to types_property_{server_name}.json.

    출력 경로: mcp_{server}/types_property_{server}.json

    Sequelize 모델을 스캔하여 데이터 스키마 정보 추출:
        - 51개 모델 (예: mstEmployee, employeeCrew 등)
        - 700개 프로퍼티 (필드명, 타입, nullable 등)

    Note: Tool parameter 정보는 registry_{server_name}.json에 포함됨.
          이 함수는 Sequelize 모델 타입 정의만 추출하여 저장.

    Args:
        base_dir: Base directory to scan (예: "AssetManagement/asset-api")
        server_name: Server name for the output file (예: "asset_management")
        output_dir: Output directory path (예: "mcp_editor/mcp_asset_management")

    Returns:
        Path to the generated file (예: mcp_asset_management/types_property_asset_management.json)
    """
    # Scan the project for Sequelize models
    scan_result = scan_js_project_types(base_dir)

    # Build output structure compatible with existing API
    output = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "server_name": server_name,
        "language": "javascript",
        "classes": [],  # Sequelize models (equivalent to Python BaseModel)
        "properties_by_class": {},
        "all_properties": scan_result["all_properties"]
    }

    # Add Sequelize models as "classes"
    for model_name, model_info in scan_result["models"].items():
        properties = model_info.get("properties", [])
        output["classes"].append({
            "name": model_name,
            "file": model_info.get("file", ""),
            "type": "sequelize_model",
            "property_count": len(properties)
        })
        output["properties_by_class"][model_name] = properties

    # Save to file
    output_path = Path(output_dir) / f"types_property_{server_name}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  Exported JS types: {len(scan_result['models'])} models")

    return str(output_path)
