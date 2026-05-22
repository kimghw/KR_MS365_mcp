#!/usr/bin/env python3
"""
Generate editor_config.json automatically from @mcp_service decorators and MCP server directories

This script:
1. Scans the codebase for @mcp_service decorators to extract server_name values
   - Python: AST parsing of @mcp_service(server_name="xxx") decorators
   - JavaScript: JSDoc parsing of @mcp_service + @server_name tags
2. Extracts type information from function signatures
   - Python: Type hints + import statements analysis
   - JavaScript: @param/@returns JSDoc tags
3. Detects MCP server directories (mcp_* pattern)
4. Generates editor_config.json with appropriate profiles including language info

Note: This module is now located in service_registry folder.
When run as script, it determines project_root as parent of mcp_editor folder.
"""

import ast
import os
import re
import json
from pathlib import Path
from typing import Dict, Any, Set, List, Tuple, Optional


# =============================================================================
# Data Structures for Server Info
# =============================================================================

class ServerInfo:
    """Holds information about a discovered MCP server."""
    def __init__(self, name: str, language: str, source_file: str):
        self.name = name
        self.language = language  # "python" or "javascript"
        self.source_file = source_file
        self.types_files: Set[str] = set()  # Auto-detected type files
        self.type_names: Set[str] = set()  # Type names used in functions


# =============================================================================
# JavaScript JSDoc Parser
# =============================================================================

def extract_types_from_jsdoc(jsdoc_block: str) -> Set[str]:
    """Extract type names from JSDoc @param and @returns tags.

    Parses patterns like:
        @param {Array<mstEmployee>} employees
        @param {employeeLicense} licenseData
        @returns {mstEmployee}
        @param {Object} updateData

    Returns:
        Set of type names (excluding primitives like string, number, Object, Array)
    """
    type_names = set()

    # Primitive types to exclude (case-insensitive check for primitives)
    primitives = {
        'string', 'number', 'boolean', 'object', 'array',
        'null', 'undefined', 'void', 'any', 'function', 'promise'
    }

    # Pattern for @param {Type} or @returns {Type}
    # Handles: {Type}, {Array<Type>}, {Type|null}, etc.
    type_pattern = r'@(?:param|returns?)\s*\{([^}]+)\}'

    for match in re.finditer(type_pattern, jsdoc_block):
        type_str = match.group(1)

        # Extract type names (camelCase or PascalCase identifiers)
        # Matches: mstEmployee, employeeLicense, Employee, Array, etc.
        inner_types = re.findall(r'[a-zA-Z][a-zA-Z0-9_]*', type_str)

        for type_name in inner_types:
            # Case-insensitive primitive check
            if type_name.lower() not in primitives:
                type_names.add(type_name)

    return type_names


def extract_types_file_from_jsdoc(jsdoc_block: str) -> Optional[str]:
    """Extract @types_file path from JSDoc block.

    Parses patterns like:
        @types_file ../sequelize/models2
        @types_file ./models

    Returns:
        The types file/directory path if found, None otherwise
    """
    match = re.search(r'@types_file\s+([^\s*]+)', jsdoc_block)
    if match:
        return match.group(1).strip()
    return None


def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case.

    Examples:
        mstEmployee -> mst_employee
        employeeLicense -> employee_license
        shipEquipment -> ship_equipment
    """
    # Insert underscore before uppercase letters and convert to lowercase
    result = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    return result.lower()


def find_sequelize_model_dirs(base_dir: str) -> List[str]:
    """Find Sequelize model directories in a project.

    Looks for directories named 'models' or 'models2' under 'sequelize' directory.

    Returns:
        List of absolute paths to model directories
    """
    model_dirs = []

    # Common patterns for Sequelize model directories
    patterns = [
        '**/sequelize/models',
        '**/sequelize/models2',
        '**/models',
    ]

    for pattern in patterns:
        for dir_path in Path(base_dir).glob(pattern):
            if dir_path.is_dir():
                # Check if it contains .js files that look like Sequelize models
                js_files = list(dir_path.glob('*.js'))
                if js_files:
                    # Verify it's a Sequelize model directory by checking for define() pattern
                    for js_file in js_files[:3]:  # Check first 3 files
                        try:
                            with open(js_file, 'r', encoding='utf-8') as f:
                                content = f.read()
                                if 'sequelize.define' in content or 'DataTypes' in content:
                                    model_dirs.append(str(dir_path))
                                    break
                        except:
                            continue

    return list(set(model_dirs))


def find_sequelize_model_file(type_name: str, model_dirs: List[str]) -> Optional[str]:
    """Find Sequelize model file for a given type name.

    Converts camelCase type name to snake_case filename and searches in model directories.

    Args:
        type_name: The type name from JSDoc (e.g., 'mstEmployee')
        model_dirs: List of model directories to search

    Returns:
        Absolute path to the model file if found, None otherwise
    """
    # Convert camelCase to snake_case for filename
    snake_name = camel_to_snake(type_name)
    possible_filenames = [
        f'{snake_name}.js',
        f'{type_name}.js',  # Some projects might use camelCase filenames
    ]

    for model_dir in model_dirs:
        for filename in possible_filenames:
            file_path = os.path.join(model_dir, filename)
            if os.path.exists(file_path):
                # Verify this file defines the expected model
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Check if this file defines the model we're looking for
                        if f"'{type_name}'" in content or f'"{type_name}"' in content:
                            return file_path
                except:
                    continue

    return None


def extract_server_info_from_js_file(
    file_path: str,
    model_dirs: Optional[List[str]] = None
) -> Dict[str, ServerInfo]:
    """Extract server info including types from JSDoc @mcp_service comments in JavaScript file.

    Supports two methods for types_files detection:
    1. Explicit @types_file tag in JSDoc (e.g., @types_file ../sequelize/models2)
    2. Convention-based: Find Sequelize model files matching type names

    Parses JSDoc blocks like:
        /**
         * @mcp_service
         * @server_name asset_management
         * @tool_name update_user_license
         * @types_file ../sequelize/models2
         * @param {employeeLicense} licenseData
         * @returns {mstEmployee}
         */

    Args:
        file_path: Path to JavaScript file
        model_dirs: Optional list of Sequelize model directories for convention-based detection

    Returns:
        Dict mapping server_name to ServerInfo
    """
    servers: Dict[str, ServerInfo] = {}
    explicit_types_dirs: Dict[str, Set[str]] = {}  # server_name -> set of explicit @types_file paths

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find all JSDoc comment blocks: /** ... */
        jsdoc_pattern = r"/\*\*[\s\S]*?\*/"

        for match in re.finditer(jsdoc_pattern, content):
            jsdoc_block = match.group()

            # Check if this JSDoc block contains @mcp_service tag
            if "@mcp_service" not in jsdoc_block:
                continue

            # Extract @server_name value
            server_name_match = re.search(r"@server_name\s+(\w+)", jsdoc_block)
            if server_name_match:
                server_name = server_name_match.group(1)

                # Create or update ServerInfo
                if server_name not in servers:
                    servers[server_name] = ServerInfo(server_name, "javascript", file_path)
                    print(f"  Found @server_name='{server_name}' in {file_path}")

                # Method 1: Extract explicit @types_file path
                types_file_path = extract_types_file_from_jsdoc(jsdoc_block)
                if types_file_path:
                    if server_name not in explicit_types_dirs:
                        explicit_types_dirs[server_name] = set()
                    # Resolve relative path from the JS file's directory
                    js_dir = os.path.dirname(file_path)
                    resolved_path = os.path.normpath(os.path.join(js_dir, types_file_path))
                    explicit_types_dirs[server_name].add(resolved_path)
                    print(f"    @types_file: {resolved_path}")

                # Extract type names from @param and @returns
                type_names = extract_types_from_jsdoc(jsdoc_block)
                servers[server_name].type_names.update(type_names)
                if type_names:
                    print(f"    Types found: {type_names}")

        # Resolve types_files for each server
        for server_name, server in servers.items():
            # Method 1: Use explicit @types_file directories
            if server_name in explicit_types_dirs:
                for types_dir in explicit_types_dirs[server_name]:
                    if os.path.isdir(types_dir):
                        # Add the directory itself (will contain model files)
                        # Find matching model files for each type name
                        for type_name in server.type_names:
                            snake_name = camel_to_snake(type_name)
                            possible_files = [
                                os.path.join(types_dir, f'{snake_name}.js'),
                                os.path.join(types_dir, f'{type_name}.js'),
                            ]
                            for pf in possible_files:
                                if os.path.exists(pf):
                                    server.types_files.add(pf)
                                    print(f"    Type '{type_name}' -> {pf}")
                                    break
                    elif os.path.isfile(types_dir):
                        # Direct file path
                        server.types_files.add(types_dir)

            # Method 2: Convention-based detection using model_dirs
            elif model_dirs:
                for type_name in server.type_names:
                    model_file = find_sequelize_model_file(type_name, model_dirs)
                    if model_file:
                        server.types_files.add(model_file)
                        print(f"    Type '{type_name}' (convention) -> {model_file}")

    except Exception as e:
        print(f"Error processing JS file {file_path}: {e}")

    return servers


def extract_server_name_from_js_file(file_path: str) -> Set[str]:
    """Legacy function: Extract server_name values from JSDoc (backward compatibility)."""
    servers = extract_server_info_from_js_file(file_path)
    return set(servers.keys())


# =============================================================================
# Python AST Parser
# =============================================================================

def extract_imports_from_py_file(file_path: str) -> Dict[str, Tuple[str, int]]:
    """Extract import mappings from a Python file.

    Returns:
        Dict mapping imported name to (module_path, level) tuple
        level: 0 = absolute, 1 = relative (.), 2 = parent (..), etc.
        e.g., {'FilterParams': ('outlook_types', 1), 'BaseModel': ('pydantic', 0)}
    """
    imports = {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)

        for node in ast.walk(tree):
            # from module import name1, name2
            if isinstance(node, ast.ImportFrom):
                module = node.module or ''
                level = node.level  # 0 = absolute, 1 = ., 2 = .., etc.
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports[name] = (module, level)

            # import module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports[name] = (alias.name, 0)

    except Exception as e:
        print(f"Error extracting imports from {file_path}: {e}")

    return imports


def extract_type_names_from_annotation(annotation: ast.expr) -> Set[str]:
    """Extract type names from a type annotation AST node.

    Handles:
        - Simple types: FilterParams
        - Optional: Optional[FilterParams]
        - Union: Union[str, FilterParams]
        - List: List[str]
        - Dict: Dict[str, Any]
    """
    type_names = set()

    # Primitives to exclude
    primitives = {
        'str', 'int', 'float', 'bool', 'None', 'Any', 'Dict', 'List',
        'Set', 'Tuple', 'Optional', 'Union', 'Callable', 'Type'
    }

    if isinstance(annotation, ast.Name):
        if annotation.id not in primitives:
            type_names.add(annotation.id)

    elif isinstance(annotation, ast.Subscript):
        # Handle generics like Optional[X], List[X], Dict[K, V]
        # Extract the subscript value
        if isinstance(annotation.slice, ast.Name):
            if annotation.slice.id not in primitives:
                type_names.add(annotation.slice.id)
        elif isinstance(annotation.slice, ast.Tuple):
            for elt in annotation.slice.elts:
                type_names.update(extract_type_names_from_annotation(elt))
        elif isinstance(annotation.slice, ast.Subscript):
            type_names.update(extract_type_names_from_annotation(annotation.slice))
        elif isinstance(annotation.slice, ast.BinOp):
            # Handle X | Y (Python 3.10+ union syntax)
            type_names.update(extract_type_names_from_annotation(annotation.slice.left))
            type_names.update(extract_type_names_from_annotation(annotation.slice.right))

    elif isinstance(annotation, ast.BinOp):
        # Handle X | Y (Python 3.10+ union syntax)
        type_names.update(extract_type_names_from_annotation(annotation.left))
        type_names.update(extract_type_names_from_annotation(annotation.right))

    elif isinstance(annotation, ast.Constant):
        # String annotation like "FilterParams"
        if isinstance(annotation.value, str) and annotation.value not in primitives:
            type_names.add(annotation.value)

    return type_names


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
    servers: Dict[str, ServerInfo] = {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)

        # First, extract all imports
        imports = extract_imports_from_py_file(file_path)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Check if function has @mcp_service decorator
                for decorator in node.decorator_list:
                    decorator_name = None
                    server_name = None

                    # Handle simple decorator: @mcp_service
                    if isinstance(decorator, ast.Name):
                        decorator_name = decorator.id
                    # Handle decorator with args: @mcp_service(...)
                    elif isinstance(decorator, ast.Call):
                        if isinstance(decorator.func, ast.Name):
                            decorator_name = decorator.func.id

                    if decorator_name == "mcp_service":
                        # Extract server_name from decorator arguments
                        if isinstance(decorator, ast.Call):
                            for keyword in decorator.keywords:
                                if keyword.arg == "server_name" and isinstance(keyword.value, ast.Constant):
                                    server_name = keyword.value.value
                                    break

                        if server_name:
                            # Create or update ServerInfo
                            if server_name not in servers:
                                servers[server_name] = ServerInfo(server_name, "python", file_path)
                                print(f"  Found server_name='{server_name}' in {file_path}")

                            # Extract types from function parameters
                            for arg in node.args.args:
                                if arg.annotation:
                                    type_names = extract_type_names_from_annotation(arg.annotation)
                                    servers[server_name].type_names.update(type_names)

                            # Extract types from return annotation
                            if node.returns:
                                type_names = extract_type_names_from_annotation(node.returns)
                                servers[server_name].type_names.update(type_names)

        # Resolve type names to source files
        for server in servers.values():
            for type_name in server.type_names:
                if type_name in imports:
                    module, level = imports[type_name]
                    # Convert relative import to file path
                    if level > 0:
                        # Relative import (level=1 means ., level=2 means .., etc.)
                        base_dir = os.path.dirname(file_path)
                        # Go up directories based on level (level=1 stays in same dir)
                        for _ in range(level - 1):
                            base_dir = os.path.dirname(base_dir)
                        # Convert module name to path
                        module_path = module.replace('.', os.sep)
                        type_file = os.path.join(base_dir, f"{module_path}.py")
                        if os.path.exists(type_file):
                            server.types_files.add(type_file)
                            print(f"    Type '{type_name}' from: {type_file}")

            if server.type_names:
                print(f"    Types used: {server.type_names}")

    except Exception as e:
        print(f"Error processing Python file {file_path}: {e}")

    return servers


def extract_server_name_from_py_file(file_path: str) -> Set[str]:
    """Legacy function: Extract server_name values from decorators (backward compatibility)."""
    servers = extract_server_info_from_py_file(file_path)
    return set(servers.keys())


# =============================================================================
# Unified Scanner
# =============================================================================

SKIP_DIRS = ("venv", "__pycache__", ".git", "node_modules", "backups", "dist", "build")


def scan_codebase_for_servers(base_dir: str) -> Set[str]:
    """Scan entire codebase for @mcp_service and extract server names.

    Supports:
    - Python (.py): AST parsing of @mcp_service(server_name="xxx") decorators
    - JavaScript (.js, .mjs): JSDoc parsing of @mcp_service + @server_name tags

    This is a legacy function for backward compatibility.
    Use scan_codebase_for_server_info() for full type information.
    """
    all_server_names = set()

    print(f"Scanning codebase in: {base_dir}")

    # Scan Python files
    print("\n[Python files]")
    for py_file in Path(base_dir).rglob("*.py"):
        if any(skip in py_file.parts for skip in SKIP_DIRS):
            continue
        server_names = extract_server_name_from_py_file(str(py_file))
        all_server_names.update(server_names)

    # Scan JavaScript files
    print("\n[JavaScript files]")
    for js_ext in ("*.js", "*.mjs"):
        for js_file in Path(base_dir).rglob(js_ext):
            if any(skip in js_file.parts for skip in SKIP_DIRS):
                continue
            server_names = extract_server_name_from_js_file(str(js_file))
            all_server_names.update(server_names)

    return all_server_names


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
    all_servers: Dict[str, ServerInfo] = {}

    print(f"Scanning codebase in: {base_dir}")

    # Pre-scan: Find Sequelize model directories for convention-based detection
    print("\n[Detecting Sequelize model directories]")
    model_dirs = find_sequelize_model_dirs(base_dir)
    if model_dirs:
        for md in model_dirs:
            print(f"  Found model directory: {md}")
    else:
        print("  No Sequelize model directories found")

    # Scan Python files
    print("\n[Python files]")
    for py_file in Path(base_dir).rglob("*.py"):
        if any(skip in py_file.parts for skip in SKIP_DIRS):
            continue
        servers = extract_server_info_from_py_file(str(py_file))
        for name, info in servers.items():
            if name in all_servers:
                # Merge types_files from multiple files
                all_servers[name].types_files.update(info.types_files)
                all_servers[name].type_names.update(info.type_names)
            else:
                all_servers[name] = info

    # Scan JavaScript files
    print("\n[JavaScript files]")
    for js_ext in ("*.js", "*.mjs"):
        for js_file in Path(base_dir).rglob(js_ext):
            if any(skip in js_file.parts for skip in SKIP_DIRS):
                continue
            # Pass model_dirs for convention-based type file detection
            servers = extract_server_info_from_js_file(str(js_file), model_dirs)
            for name, info in servers.items():
                if name in all_servers:
                    # If already exists with different language, prefer first found
                    all_servers[name].type_names.update(info.type_names)
                    all_servers[name].types_files.update(info.types_files)
                else:
                    all_servers[name] = info

    return all_servers


def scan_mcp_directories(base_dir: str) -> Set[str]:
    """Scan for MCP server directories (mcp_* pattern)"""
    server_names = set()

    for item in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item)

        # Check if it's a directory starting with mcp_
        if os.path.isdir(item_path) and item.startswith("mcp_"):
            mcp_server_path = os.path.join(item_path, "mcp_server")

            # Check if it has mcp_server subdirectory with server.py
            if os.path.isdir(mcp_server_path):
                server_py = os.path.join(mcp_server_path, "server.py")
                if os.path.exists(server_py):
                    # Extract server name from directory name (mcp_XXX -> XXX)
                    server_name = item.replace("mcp_", "")
                    server_names.add(server_name)
                    print(f"  Found MCP directory: {item} -> server: {server_name}")

    return server_names


def detect_module_paths(
    server_name: str,
    base_dir: str,
    server_info: Optional[ServerInfo] = None
) -> Dict[str, Any]:
    """
    Detect appropriate file paths for a server based on naming conventions

    Looks for patterns like:
    - mcp_{server_name}/
    - {server_name}_mcp/
    - mcp{server_name}/

    Args:
        server_name: The server name
        base_dir: Base directory of the project
        server_info: Optional ServerInfo with auto-detected types_files
    """
    # Normalize server name for directory patterns
    possible_patterns = [f"mcp_{server_name}", f"{server_name}_mcp", f"mcp{server_name}", server_name]

    # Find matching directory
    module_dir = None
    for pattern in possible_patterns:
        candidate = os.path.join(base_dir, pattern)
        if os.path.isdir(candidate):
            module_dir = pattern
            print(f"  Detected module directory: {module_dir}")
            break

    if not module_dir:
        # Default fallback
        module_dir = f"mcp_{server_name}"
        print(f"  No directory found, using default: {module_dir}")

    # Construct paths
    mcp_server_dir = f"{module_dir}/mcp_server"

    # Collect types_files from multiple sources
    types_files_set: Set[str] = set()

    # 1. Auto-detected types from AST analysis (if server_info provided)
    if server_info and server_info.types_files:
        for type_file in server_info.types_files:
            # Convert absolute path to relative path from mcp_editor
            rel_path = os.path.relpath(type_file, os.path.join(base_dir, "mcp_editor"))
            types_files_set.add(rel_path)
            print(f"    Auto-detected types file: {rel_path}")

    # 2. Convention-based types files (fallback patterns)
    possible_type_files = [
        os.path.join(base_dir, module_dir, f"{server_name}_types.py"),
        os.path.join(base_dir, module_dir, "outlook_types.py"),  # Special case for outlook
        os.path.join(base_dir, module_dir, "types.py"),
        os.path.join(base_dir, module_dir, "graph_types.py"),
    ]

    for type_file_path in possible_type_files:
        if os.path.exists(type_file_path):
            # Get relative path from mcp_editor directory
            rel_path = os.path.relpath(type_file_path, os.path.join(base_dir, "mcp_editor"))
            if rel_path not in types_files_set:
                types_files_set.add(rel_path)
                print(f"    Found types file (convention): {rel_path}")
            break

    # Convert to sorted list for consistent output
    types_files = sorted(list(types_files_set))

    # If no types file found, leave empty array (optional types)
    if not types_files:
        print(f"    No types file found for {server_name}")

    # For new directory structure (profiles in mcp_editor/mcp_{server_name}/)
    editor_profile_dir = f"mcp_{server_name}"

    # Determine language
    language = "python"  # default
    if server_info:
        language = server_info.language

    return {
        "template_definitions_path": f"{editor_profile_dir}/tool_definition_templates.py",
        "tool_definitions_path": f"../{mcp_server_dir}/tool_definitions.py",
        "backup_dir": f"{editor_profile_dir}/backups",
        "types_files": types_files,
        "language": language,
        "host": "0.0.0.0",
        # port는 generate_editor_config_json에서 순차 할당
    }


def generate_editor_config_json(
    server_names: Set[str],
    base_dir: str,
    output_path: str,
    server_infos: Optional[Dict[str, ServerInfo]] = None
):
    """
    Generate editor_config.json with profiles for each discovered server

    Args:
        server_names: Set of server names discovered
        base_dir: Base directory of the project
        output_path: Path where editor_config.json will be saved
        server_infos: Optional dict of ServerInfo with language and types info
    """
    print(f"\nGenerating profiles for {len(server_names)} server(s):")

    # Prepare server configurations
    config = {}
    base_port = 8001  # MCP 서버 포트 시작 번호
    for idx, server_name in enumerate(sorted(server_names)):
        port = base_port + idx

        # Get ServerInfo if available
        server_info = server_infos.get(server_name) if server_infos else None
        language = server_info.language if server_info else "python"

        print(f"  - {server_name} (port: {port}, language: {language})")
        server_config = detect_module_paths(server_name, base_dir, server_info)
        server_config["port"] = port  # 순차 포트 할당

        # Use server_name as the profile key (mcp_ prefix not needed)
        config[server_name] = server_config

    # Write config file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Generated {output_path}")
    print(f"  Total profiles: {len(config)}")
    print(f"  Profiles: {', '.join(config.keys())}")


def main():
    """Main entry point"""
    # Determine project root
    # When run from service_registry folder: script_dir -> mcp_editor -> project_root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_editor_dir = os.path.dirname(script_dir)
    project_root = os.path.dirname(mcp_editor_dir)

    print("=" * 60)
    print("Generate editor_config.json from MCP servers")
    print("=" * 60)
    print()

    # Method 1: Scan codebase for @mcp_service decorators with full type info
    server_infos = scan_codebase_for_server_info(project_root)
    decorator_servers = set(server_infos.keys())

    # Method 2: Scan for mcp_* directories
    directory_servers = scan_mcp_directories(project_root)

    # Combine both methods (union of both sets)
    all_server_names = decorator_servers | directory_servers

    if not all_server_names:
        print("\n[WARN] No servers found via decorators or directories")
        print("  Creating default config with 'outlook' server")
        all_server_names = {"outlook"}

    print(f"\nDiscovered {len(all_server_names)} unique server name(s):")
    for name in sorted(all_server_names):
        info = server_infos.get(name)
        if info:
            print(f"  - {name} ({info.language})")
            if info.types_files:
                for tf in info.types_files:
                    print(f"      types: {tf}")
        else:
            print(f"  - {name} (unknown language, from directory scan)")

    # Generate config in mcp_editor directory
    config_output_path = os.path.join(mcp_editor_dir, "editor_config.json")

    # Backup existing config if it exists
    if os.path.exists(config_output_path):
        backup_path = config_output_path + ".backup"
        import shutil

        shutil.copy2(config_output_path, backup_path)
        print(f"\n[BACKUP] Backed up existing config to: {backup_path}")

    # Generate new config with full server info
    generate_editor_config_json(all_server_names, project_root, config_output_path, server_infos)

    print("\n" + "=" * 60)
    print("[OK] Done!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Review the generated config file")
    print("  2. Adjust paths if needed")
    print("  3. Restart the web editor to load new profiles")


if __name__ == "__main__":
    main()
