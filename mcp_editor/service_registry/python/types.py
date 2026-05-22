"""
Python Type Extractor Module

Python 프로젝트에서 **데이터 모델(타입 정의)**을 추출하는 모듈.
mcp_service_scanner.py에서 import하여 사용.

## 역할 분담

| 모듈 | 역할 |
|------|------|
| mcp_service_scanner.py | 서비스(tool) 스캔 + 파라미터 추출 |
| extract_types.py | 데이터 모델 추출 (Pydantic BaseModel 등) |

## Pydantic vs Sequelize 비교

| 항목 | Pydantic (Python) | Sequelize (JavaScript) |
|------|-------------------|------------------------|
| 역할 | 데이터 모델/검증 | ORM (DB 모델) |
| 타입 정의 | 클래스 속성 + 타입 힌트 | init() 메서드에 필드 정의 |
| 용도 | API 스키마, 검증 | DB 테이블 매핑 |

### 예시 비교

Pydantic (Python):
    class FilterParams(BaseModel):
        user_email: str = Field(..., description="User email")
        top: int = Field(50, description="Maximum results")
        filter: Optional[str] = None

Sequelize (JavaScript):
    mstEmployee.init({
        id: { type: DataTypes.INTEGER, primaryKey: true },
        nameKr: { type: DataTypes.STRING },
        nameEn: { type: DataTypes.STRING, allowNull: true },
    }, { sequelize, modelName: 'mstEmployee' });

## 소스 경로 탐지 방식

파일 경로에 "types", "models", 또는 "schema"가 포함되면 자동 파싱:

    for py_file in Path(base_dir).rglob("*.py"):
        file_str = str(py_file)
        if "types" in file_str.lower() or "models" in file_str.lower() or "schema" in file_str.lower():
            classes = extract_class_properties(file_str)

## 경로 흐름

    scan_all_registries()
            ↓
    get_source_path_for_profile("outlook")
            ↓
    base_dir = "../mcp_outlook"  ← editor_config 또는 컨벤션
            ↓
    export_services_to_json(base_dir, ...)
            ↓
    extract_types.export_py_types_property(base_dir, ...)
            ↓
    Path(base_dir).rglob("*.py")  ← 모든 .py 파일 스캔
            ↓
    "types" in path → outlook_types.py 탐지!

## 주요 함수

- extract_class_properties(file_path): 파일 내 모든 BaseModel 클래스 추출
- extract_single_class(file_path, class_name): 특정 클래스만 추출
- scan_py_project_types(base_dir): 전체 Python 프로젝트 타입 스캔 (자동 탐지)
- export_py_types_property(base_dir, server_name, output_dir): types_property JSON 생성
- map_python_to_json_type(python_type): Python 타입 → JSON Schema 타입 변환
"""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def map_python_to_json_type(python_type: str) -> str:
    """Map Python type to JSON Schema type.

    Args:
        python_type: Python type string (e.g., "str", "int", "List")

    Returns:
        JSON Schema type string (e.g., "string", "integer", "array")
    """
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
    return type_mapping.get(python_type, "object")


def extract_type_from_annotation(annotation: Optional[ast.AST]) -> str:
    """Extract type string from AST annotation node.

    Args:
        annotation: AST annotation node

    Returns:
        JSON Schema compatible type string
    """
    if annotation is None:
        return "any"

    # Handle Optional[T]
    if isinstance(annotation, ast.Subscript):
        if hasattr(annotation.value, "id") and annotation.value.id == "Optional":
            if isinstance(annotation.slice, ast.Name):
                return map_python_to_json_type(annotation.slice.id)
            else:
                # Recursive call already returns JSON type, don't re-map
                return extract_type_from_annotation(annotation.slice)

        # Handle List[T] - preserve inner type info
        elif hasattr(annotation.value, "id") and annotation.value.id == "List":
            if isinstance(annotation.slice, ast.Name):
                inner_type = map_python_to_json_type(annotation.slice.id)
                return f"List[{inner_type}]"
            return "List"

        # Handle Union types
        elif hasattr(annotation.value, "id") and annotation.value.id == "Union":
            # Check if Union contains List - if so, treat as List[T]
            # e.g., Union[str, List[str]] -> List[string]
            if isinstance(annotation.slice, ast.Tuple):
                list_inner_type = None
                first_type = None
                for elt in annotation.slice.elts:
                    if isinstance(elt, ast.Subscript):
                        if hasattr(elt.value, "id") and elt.value.id == "List":
                            # Extract inner type of List[T]
                            if isinstance(elt.slice, ast.Name):
                                list_inner_type = map_python_to_json_type(elt.slice.id)
                            else:
                                list_inner_type = "any"
                            break
                    elif isinstance(elt, ast.Name) and elt.id != "None":
                        if first_type is None:
                            first_type = elt.id

                if list_inner_type:
                    return f"List[{list_inner_type}]"
                elif first_type:
                    return map_python_to_json_type(first_type)
            return "any"

        # Handle Literal types
        elif hasattr(annotation.value, "id") and annotation.value.id == "Literal":
            return "string"  # Literals are typically string enums

    # Handle simple types
    elif isinstance(annotation, ast.Name):
        return map_python_to_json_type(annotation.id)

    elif isinstance(annotation, ast.Constant):
        return map_python_to_json_type(type(annotation.value).__name__)

    return "any"


def extract_field_info(node: ast.AnnAssign, class_name: str) -> Optional[Dict[str, Any]]:
    """Extract field information from a Pydantic Field assignment.

    Args:
        node: AST AnnAssign node (annotated assignment)
        class_name: Name of the containing class

    Returns:
        Dictionary with field metadata or None if not a valid field
    """
    if not isinstance(node.target, ast.Name):
        return None

    field_name = node.target.id
    field_info = {
        "name": field_name,
        "type": extract_type_from_annotation(node.annotation),
        "description": "",
        "examples": [],
        "default": None,
    }

    # Extract Field() parameters
    if isinstance(node.value, ast.Call):
        if hasattr(node.value.func, "id") and node.value.func.id == "Field":
            # Process Field arguments
            for i, arg in enumerate(node.value.args):
                if i == 0:  # First positional arg is default value
                    if isinstance(arg, ast.Constant):
                        # Handle Ellipsis (...) - convert to None
                        if arg.value is ...:
                            field_info["default"] = None
                        else:
                            field_info["default"] = arg.value

            # Process keyword arguments
            for keyword in node.value.keywords:
                if keyword.arg == "description" and isinstance(keyword.value, ast.Constant):
                    field_info["description"] = keyword.value.value
                elif keyword.arg == "examples" and isinstance(keyword.value, ast.List):
                    examples = []
                    for elt in keyword.value.elts:
                        if isinstance(elt, ast.Constant):
                            examples.append(elt.value)
                        elif isinstance(elt, ast.List):
                            # Handle list of lists
                            inner_list = []
                            for inner_elt in elt.elts:
                                if isinstance(inner_elt, ast.Constant):
                                    inner_list.append(inner_elt.value)
                            if inner_list:
                                examples.append(inner_list)
                    field_info["examples"] = examples
                elif keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                    field_info["default"] = keyword.value.value

    return field_info


def extract_class_properties(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Extract properties from all Pydantic BaseModel classes in a file.

    Args:
        file_path: Path to Python source file

    Returns:
        Dictionary mapping class names to their metadata:
        {
            "ClassName": {
                "file": "/path/to/file.py",
                "line": 15,
                "properties": [
                    {"name": "field1", "type": "string", ...},
                    ...
                ]
            }
        }
    """
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    classes_info: Dict[str, Dict[str, Any]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if it's a BaseModel subclass
            is_base_model = False
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "BaseModel":
                    is_base_model = True
                    break

            if is_base_model:
                class_properties = []

                # Extract field definitions
                for item in node.body:
                    if isinstance(item, ast.AnnAssign):
                        field_info = extract_field_info(item, node.name)
                        if field_info and not field_info["name"].startswith("_"):
                            # Skip private/internal fields
                            class_properties.append(field_info)

                classes_info[node.name] = {
                    "file": file_path,
                    "line": node.lineno,
                    "properties": class_properties,
                }

    return classes_info


def extract_single_class(file_path: str, class_name: str) -> Optional[Dict[str, Any]]:
    """Extract properties from a specific class in a file.

    Args:
        file_path: Path to Python source file
        class_name: Name of the class to extract

    Returns:
        Class metadata dictionary or None if not found:
        {
            "file": "/path/to/file.py",
            "line": 15,
            "properties": [...]
        }
    """
    all_classes = extract_class_properties(file_path)
    return all_classes.get(class_name)


def get_class_names_from_file(file_path: str) -> List[str]:
    """Get list of BaseModel class names defined in a file.

    Args:
        file_path: Path to Python source file

    Returns:
        List of class names
    """
    all_classes = extract_class_properties(file_path)
    return list(all_classes.keys())


# =============================================================================
# Directory Scanning (자동 타입 탐지)
# =============================================================================

DEFAULT_SKIP_DIRS = ("node_modules", ".git", "dist", "build", "__pycache__", "venv", ".venv", "env")


def scan_py_project_types(
    base_dir: str,
    skip_dirs: tuple = DEFAULT_SKIP_DIRS
) -> Dict[str, Any]:
    """Scan a Python project for type definitions (Pydantic BaseModel).

    Pydantic BaseModel = Python 데이터 모델 (API 스키마, 검증)

    탐지 방식:
        - base_dir 하위의 모든 .py 파일 재귀 스캔
        - 파일 경로에 "types", "models", "schema" 포함 시 파싱
        - 예: mcp_outlook/outlook_types.py

    Note: Tool parameter 추출은 mcp_service_scanner.py에서 처리함.
          이 함수는 BaseModel 타입 정의만 추출.

    Args:
        base_dir: Base directory to scan (예: "../mcp_outlook")
        skip_dirs: Directory names to skip (node_modules, .git 등)

    Returns:
        Dictionary with classes:
        {
            "classes": {...},        # BaseModel classes (데이터 타입 정의)
            "all_properties": [...]  # Flattened property list
        }
    """
    result = {
        "classes": {},
        "all_properties": []
    }

    base_path = Path(base_dir)
    if not base_path.exists():
        print(f"  Warning: Directory does not exist: {base_dir}")
        return result

    # Scan for Python files
    for py_file in base_path.rglob("*.py"):
        # Skip excluded directories
        if any(skip in py_file.parts for skip in skip_dirs):
            continue

        file_str = str(py_file).lower()

        # Look for type definition files
        # Matches: *_types.py, *types*.py, models/*.py, schema/*.py
        if "types" in file_str or "models" in file_str or "schema" in file_str:
            try:
                classes = extract_class_properties(str(py_file))
                for class_name, class_info in classes.items():
                    result["classes"][class_name] = class_info
            except Exception as e:
                print(f"  Warning: Could not parse {py_file}: {e}")

    # Build flattened properties list
    for class_name, class_info in result["classes"].items():
        for prop in class_info.get("properties", []):
            result["all_properties"].append({
                "name": prop.get("name", ""),
                "type": prop.get("type", "any"),
                "description": prop.get("description", ""),
                "source": f"class:{class_name}",
                "full_path": f"{class_name}.{prop.get('name', '')}",
                "examples": prop.get("examples", []),
                "default": prop.get("default")
            })

    return result


def export_py_types_property(
    base_dir: str,
    server_name: str,
    output_dir: str
) -> str:
    """Export Python types (Pydantic BaseModel) to types_property_{server_name}.json.

    출력 경로: mcp_{server}/types_property_{server}.json

    BaseModel 클래스를 스캔하여 데이터 스키마 정보 추출:
        - 클래스 목록 (예: FilterParams, MailMessage 등)
        - 프로퍼티 (필드명, 타입, 설명, 기본값 등)

    Note: Tool parameter 정보는 registry_{server_name}.json에 포함됨.
          이 함수는 BaseModel 타입 정의만 추출하여 저장.

    Args:
        base_dir: Base directory to scan (예: "../mcp_outlook")
        server_name: Server name for the output file (예: "outlook")
        output_dir: Output directory path (예: "mcp_editor/mcp_outlook")

    Returns:
        Path to the generated file (예: mcp_outlook/types_property_outlook.json)
    """
    # Scan the project for BaseModel classes
    scan_result = scan_py_project_types(base_dir)

    # Build output structure compatible with existing API
    output = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "server_name": server_name,
        "language": "python",
        "classes": [],  # Pydantic BaseModel classes
        "properties_by_class": {},
        "all_properties": scan_result["all_properties"]
    }

    # Add BaseModel classes
    for class_name, class_info in scan_result["classes"].items():
        properties = class_info.get("properties", [])
        output["classes"].append({
            "name": class_name,
            "file": class_info.get("file", ""),
            "line": class_info.get("line", 0),
            "type": "pydantic_model",
            "property_count": len(properties)
        })
        output["properties_by_class"][class_name] = properties

    # Save to file
    output_path = Path(output_dir) / f"types_property_{server_name}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  Exported Python types: {len(scan_result['classes'])} classes")

    return str(output_path)
