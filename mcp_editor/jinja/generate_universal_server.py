#!/usr/bin/env python3
"""
Universal MCP server generator using registry data
Generates server.py from registry JSON files and universal template
"""
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader

SCRIPT_DIR = Path(__file__).resolve().parent  # mcp_editor/jinja/
EDITOR_DIR = SCRIPT_DIR.parent                 # mcp_editor/
PROJECT_ROOT = Path(os.environ.get("MCP_EDITOR_ROOT", EDITOR_DIR.parent))  # Connector_auth/
EDITOR_CONFIG_PATH = EDITOR_DIR / "editor_config.json"


def load_editor_config() -> Dict[str, Any]:
    """Load editor_config.json"""
    if EDITOR_CONFIG_PATH.exists():
        with open(EDITOR_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def scan_types_files(source_dir: str) -> List[str]:
    """
    source_dir 내에서 *_types.py 패턴의 타입 파일을 자동 스캔

    Args:
        source_dir: 스캔할 소스 디렉토리 (예: '../mcp_outlook')

    Returns:
        발견된 타입 파일 경로 목록 (상대 경로)
    """
    types_files = []
    source_path = PROJECT_ROOT / source_dir.lstrip('../')

    if not source_path.exists():
        return types_files

    # *_types.py 패턴으로 재귀 스캔
    for types_file in source_path.rglob("*_types.py"):
        # __pycache__, venv 등 제외
        if any(part.startswith('.') or part in ('__pycache__', 'venv', 'node_modules', 'test', 'tests')
               for part in types_file.parts):
            continue

        # 상대 경로로 변환 (PROJECT_ROOT 기준)
        try:
            rel_path = types_file.relative_to(PROJECT_ROOT)
            types_files.append(f"../{rel_path}")
        except ValueError:
            # PROJECT_ROOT 밖에 있는 경우 절대 경로 사용
            types_files.append(str(types_file))

    return sorted(types_files)


def scan_service_files(source_dir: str) -> List[str]:
    """
    source_dir 내에서 *_service.py 패턴의 서비스 파일을 자동 스캔

    Args:
        source_dir: 스캔할 소스 디렉토리 (예: '../mcp_outlook')

    Returns:
        발견된 서비스 파일 경로 목록 (상대 경로)
    """
    service_files = []
    source_path = PROJECT_ROOT / source_dir.lstrip('../')

    if not source_path.exists():
        return service_files

    # *_service.py 패턴으로 재귀 스캔
    for service_file in source_path.rglob("*_service.py"):
        # __pycache__, venv 등 제외
        if any(part.startswith('.') or part in ('__pycache__', 'venv', 'node_modules', 'test', 'tests')
               for part in service_file.parts):
            continue

        # 상대 경로로 변환 (PROJECT_ROOT 기준)
        try:
            rel_path = service_file.relative_to(PROJECT_ROOT)
            service_files.append(f"../{rel_path}")
        except ValueError:
            service_files.append(str(service_file))

    return sorted(service_files)


def resolve_service_paths(profile_name: str, editor_config: dict, auto_scan: bool = True) -> dict:
    """
    파생 프로필인 경우 base 프로필의 서비스 경로 사용
    auto_scan=True이면 *_types.py, *_service.py 파일 자동 스캔

    Args:
        profile_name: 현재 프로필명
        editor_config: editor_config.json 내용
        auto_scan: 타입/서비스 파일 자동 스캔 여부 (기본: True)

    Returns:
        {
            "source_dir": str,           # 실제 소스 디렉토리 (base 또는 현재)
            "types_files": list,         # 타입 파일 목록 (설정 + 자동 스캔)
            "service_files": list,       # 서비스 파일 목록 (자동 스캔)
            "module_prefix": str,        # import용 모듈 프리픽스 (예: 'mcp_outlook')
            "is_derived": bool,          # 파생 프로필 여부
            "base_profile": str | None   # base 프로필명
        }
    """
    profile_config = editor_config.get(profile_name, {})

    # Check if this is a derived profile (has base_profile field)
    base_profile = profile_config.get('base_profile')

    if base_profile:
        # This is a derived profile - use base profile's service paths
        base_config = editor_config.get(base_profile, {})
        source_dir = base_config.get('source_dir', f'../mcp_{base_profile}')
        config_types_files = base_config.get('types_files', [])
        module_prefix = f'mcp_{base_profile}'
        is_derived = True
    else:
        # This is a base profile - use its own paths
        source_dir = profile_config.get('source_dir', f'../mcp_{profile_name}')
        config_types_files = profile_config.get('types_files', [])
        module_prefix = f'mcp_{profile_name}'
        is_derived = False
        base_profile = None

    # 자동 스캔으로 타입/서비스 파일 찾기
    if auto_scan:
        scanned_types = scan_types_files(source_dir)
        scanned_services = scan_service_files(source_dir)

        # 설정된 타입 파일과 스캔된 파일 병합 (중복 제거)
        all_types = list(config_types_files)
        for f in scanned_types:
            if f not in all_types:
                all_types.append(f)
        types_files = all_types
        service_files = scanned_services
    else:
        types_files = list(config_types_files)
        service_files = []

    return {
        "source_dir": source_dir,
        "types_files": types_files,
        "service_files": service_files,
        "module_prefix": module_prefix,
        "is_derived": is_derived,
        "base_profile": base_profile
    }


def to_python_repr(value: Any) -> str:
    """Convert a Python value to its Python code representation.

    Unlike json.dumps, this produces valid Python syntax:
    - True/False instead of true/false
    - None instead of null
    - repr() for strings to preserve quotes
    """
    if value is None:
        return 'None'
    elif isinstance(value, bool):
        return 'True' if value else 'False'
    elif isinstance(value, str):
        return repr(value)
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, (list, dict)):
        return repr(value)
    else:
        return repr(value)


def convert_boolean_to_enabled_disabled(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Convert boolean type properties to enabled/disabled enum for OpenAI compatibility.

    OpenAI API does not support boolean type in function parameters.
    This converts:
        type: boolean, default: true  -> type: string, enum: ["enabled", "disabled"], default: "enabled"
        type: boolean, default: false -> type: string, enum: ["enabled", "disabled"], default: "disabled"

    Args:
        schema: JSON Schema dict with properties

    Returns:
        Modified schema with boolean types converted to enabled/disabled enums
    """
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    # Process 'properties' if present
    if 'properties' in result:
        new_properties = {}
        for prop_name, prop_def in result['properties'].items():
            if isinstance(prop_def, dict) and prop_def.get('type') == 'boolean':
                # Convert boolean to enabled/disabled enum
                new_prop = dict(prop_def)
                new_prop['type'] = 'string'
                new_prop['enum'] = ['enabled', 'disabled']

                # Convert default value
                if 'default' in new_prop:
                    new_prop['default'] = 'enabled' if new_prop['default'] else 'disabled'

                # Update description to clarify the values
                if 'description' in new_prop:
                    new_prop['description'] = f"{new_prop['description']} (enabled=true, disabled=false)"

                new_properties[prop_name] = new_prop
            elif isinstance(prop_def, dict) and prop_def.get('type') == 'object':
                # Recursively process nested objects
                new_properties[prop_name] = convert_boolean_to_enabled_disabled(prop_def)
            else:
                new_properties[prop_name] = prop_def
        result['properties'] = new_properties

    return result


def convert_enabled_disabled_default(value: Any, param_type: str) -> str:
    """Convert enabled/disabled default value to Python repr.

    Args:
        value: The default value (bool or string)
        param_type: The parameter type

    Returns:
        Python code representation
    """
    if param_type == 'boolean' or isinstance(value, bool):
        # Convert bool to enabled/disabled string
        return repr('enabled' if value else 'disabled')
    return to_python_repr(value)


def load_registry(registry_path: str) -> Dict[str, Any]:
    """Load service registry JSON file and normalize service info"""
    with open(registry_path, 'r', encoding='utf-8') as f:
        registry = json.load(f)

    # Normalize service info - promote handler fields to top level if missing
    services = registry.get('services', {})
    for service_name, service_info in services.items():
        handler = service_info.get('handler', {})
        if handler:
            # Promote handler fields to top level if not present
            if not service_info.get('class_name') and handler.get('class_name'):
                service_info['class_name'] = handler['class_name']
            if not service_info.get('file') and handler.get('file'):
                service_info['file'] = handler['file']
            if not service_info.get('instance') and handler.get('instance'):
                service_info['instance'] = handler['instance']
            if not service_info.get('method') and handler.get('method'):
                service_info['method'] = handler['method']
            if not service_info.get('is_async') and handler.get('is_async'):
                service_info['is_async'] = handler['is_async']
            # Generate module_path from file if not present
            if not service_info.get('module_path') and service_info.get('file'):
                file_path = service_info['file']
                # Convert file path to module path (e.g., /path/to/mcp_outlook/outlook_service.py -> mcp_outlook.outlook_service)
                if file_path.endswith('.py'):
                    parts = file_path.replace('.py', '').split('/')
                    # Find mcp_* folder and use from there
                    for i, part in enumerate(parts):
                        if part.startswith('mcp_'):
                            service_info['module_path'] = '.'.join(parts[i:])
                            break

    return registry


def _convert_params_list_to_dict(params_list: list) -> dict:
    """Convert parameters from list format to dict format.

    Input (list format):
        [{'name': 'subject', 'type': 'boolean', 'is_optional': False, 'default': True, 'description': '메시지 제목'}]

    Output (dict format):
        {'subject': {'default': True, 'description': '메시지 제목', 'type': 'boolean'}}
    """
    if not params_list or not isinstance(params_list, list):
        return {}

    params_dict = {}
    for param in params_list:
        name = param.get("name")
        if not name:
            continue

        param_dict = {"type": param.get("type", "string")}
        # Only add default if has_default is True
        if param.get("has_default", False):
            param_dict["default"] = param.get("default")
        if param.get("description"):
            param_dict["description"] = param["description"]

        params_dict[name] = param_dict

    return params_dict


def extract_service_factors_from_tools(tools: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Extract service factors from mcp_service_factors in tool definitions

    Processes both 'internal' and 'signature_defaults' sources.
    Requires explicit targetParam field in each factor.

    Returns:
        Dict with structure:
        {
            tool_name: {
                'internal': { factor_name: {...}, ... },
                'signature_defaults': { factor_name: {...}, ... }
            }
        }
    """
    service_factors = {}

    for tool in tools:
        tool_name = tool.get('name', '')
        mcp_service_factors = tool.get('mcp_service_factors', {})

        tool_factors = {
            'internal': {},
            'signature_defaults': {}
        }

        for factor_name, factor_data in mcp_service_factors.items():
            source = factor_data.get('source', '')

            # Only process 'internal' and 'signature_defaults' sources
            if source not in ('internal', 'signature_defaults'):
                continue

            # Support both 'type' (new) and 'baseModel' (legacy) field names
            factor_type = factor_data.get('type') or factor_data.get('baseModel', '')

            # targetParam is REQUIRED - no auto-matching
            if 'targetParam' not in factor_data:
                raise ValueError(
                    f"Tool '{tool_name}': mcp_service_factors['{factor_name}'] "
                    f"requires 'targetParam' field to specify target mcp_service parameter"
                )
            target_param = factor_data['targetParam']

            # Get parameters - handle both list format (new) and dict format (legacy)
            raw_params = factor_data.get('parameters', [])
            if isinstance(raw_params, list):
                params_dict = _convert_params_list_to_dict(raw_params)
            else:
                params_dict = raw_params  # Already a dict

            # Extract default values from parameters (for object types)
            default_values = {}
            for param_name, param_def in params_dict.items():
                if 'default' in param_def:
                    default_values[param_name] = param_def['default']

            # Extract primitive default (for primitive types like integer, string, boolean)
            # This is used when the factor itself has a default value, not nested parameters
            primitive_default = factor_data.get('default')

            # If no explicit default, try to get from mcp_service.parameters using targetParam
            if primitive_default is None and not params_dict:
                mcp_service = tool.get('mcp_service', {})
                service_params = mcp_service.get('parameters', [])
                for sp in service_params:
                    if sp.get('name') == target_param and sp.get('default') is not None:
                        primitive_default = sp['default']
                        break

            # Determine value: use object properties defaults or primitive default
            if default_values:
                value = default_values
            elif primitive_default is not None:
                value = primitive_default
            else:
                value = {}

            # Build the factor structure
            factor_info = {
                'targetParam': target_param,
                'type': factor_type,
                'source': source,
                'value': value,
                'primitive_default': primitive_default,  # Store separately for template rendering
                'original_schema': {
                    'targetParam': target_param,
                    'properties': params_dict,
                    'type': 'object'
                }
            }

            tool_factors[source][factor_name] = factor_info

        # Only add if there are any factors
        if tool_factors['internal'] or tool_factors['signature_defaults']:
            service_factors[tool_name] = tool_factors

    return service_factors


def extract_internal_args_from_tools(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract internal args from mcp_service_factors in tool definitions (legacy compatibility)

    Requires explicit targetParam field in each factor.
    """
    service_factors = extract_service_factors_from_tools(tools)

    # Convert to legacy internal_args format for backward compatibility
    internal_args = {}
    for tool_name, factors in service_factors.items():
        tool_internal = {}
        # Combine internal factors
        for factor_name, factor_info in factors.get('internal', {}).items():
            tool_internal[factor_name] = {
                'targetParam': factor_info['targetParam'],
                'type': factor_info['type'],
                'value': factor_info['value'],
                'original_schema': factor_info['original_schema']
            }
        if tool_internal:
            internal_args[tool_name] = tool_internal

    return internal_args


def load_tool_definitions(tool_def_path: str) -> List[Dict[str, Any]]:
    """Load tool definitions from Python module, JSON, or YAML file"""
    import yaml
    path = Path(tool_def_path)

    # Try YAML file first (preferred format)
    yaml_path = path.with_suffix('.yaml') if path.suffix == '.py' else path
    if yaml_path.suffix == '.yaml' and yaml_path.exists():
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data.get('tools', data.get('MCP_TOOLS', data))

    if path.suffix == '.json':
        with open(path, 'r') as f:
            data = json.load(f)
            return data.get('MCP_TOOLS', data)
    elif path.suffix == '.py':
        # Check for companion YAML file
        yaml_companion = path.with_suffix('.yaml')
        if yaml_companion.exists():
            with open(yaml_companion, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get('tools', data.get('MCP_TOOLS', data))

        # Use AST to parse the file without importing
        import ast

        with open(path, 'r') as f:
            tree = ast.parse(f.read())

        for node in tree.body:
            # Handle regular assignment (MCP_TOOLS = [...])
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == 'MCP_TOOLS':
                        # Handle json.loads pattern
                        if isinstance(node.value, ast.Call):
                            func = node.value.func
                            if hasattr(func, 'attr') and func.attr == 'loads':
                                # json.loads("""...""")
                                if node.value.args and isinstance(node.value.args[0], ast.Constant):
                                    return json.loads(node.value.args[0].value)
                        # Handle literal list/dict (skip function calls)
                        if not isinstance(node.value, ast.Call):
                            return ast.literal_eval(node.value)

            # Handle type-annotated assignment
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == 'MCP_TOOLS':
                    if isinstance(node.value, ast.Call):
                        func = node.value.func
                        if hasattr(func, 'attr') and func.attr == 'loads':
                            if node.value.args and isinstance(node.value.args[0], ast.Constant):
                                return json.loads(node.value.args[0].value)
                        # Skip other function calls (like _load_tools_from_yaml())
                        # Try to load from YAML companion file
                        yaml_companion = path.with_suffix('.yaml')
                        if yaml_companion.exists():
                            with open(yaml_companion, 'r', encoding='utf-8') as f:
                                data = yaml.safe_load(f)
                                return data.get('tools', data.get('MCP_TOOLS', data))
                    else:
                        return ast.literal_eval(node.value)

        raise ValueError("Could not find MCP_TOOLS in the Python file")
    elif path.suffix == '.yaml':
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data.get('tools', data.get('MCP_TOOLS', data))
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")


def find_type_locations(server_name: str) -> Dict[str, str]:
    """Find the locations of types for a server

    Returns dict mapping type names to their import paths
    """
    import ast
    import glob

    type_locations = {}

    # Search patterns for finding type definitions
    search_paths = [
        PROJECT_ROOT / f"mcp_{server_name}" / "*.py",
        PROJECT_ROOT / f"{server_name}" / "*.py",
        PROJECT_ROOT / "mcp_editor" / f"mcp_{server_name}" / "*.py",
    ]

    for pattern in search_paths:
        for file_path in glob.glob(str(pattern)):
            try:
                with open(file_path, 'r') as f:
                    tree = ast.parse(f.read())

                # Extract module name from file path
                module_parts = Path(file_path).stem
                if 'mcp_' in str(file_path):
                    if 'mcp_editor' in str(file_path):
                        module_name = f"mcp_editor.mcp_{server_name}.{module_parts}"
                    else:
                        module_name = f"mcp_{server_name}.{module_parts}"
                else:
                    module_name = f"{server_name}.{module_parts}"

                # Find class definitions and enums
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        # Check if it's an Enum
                        is_enum = any(
                            base.id == 'Enum' if isinstance(base, ast.Name) else
                            (base.attr == 'Enum' if isinstance(base, ast.Attribute) else False)
                            for base in node.bases
                        )

                        if node.name not in type_locations:
                            type_locations[node.name] = {
                                'module': module_name,
                                'is_enum': is_enum,
                                'file': file_path
                            }
            except:
                # Skip files that can't be parsed
                continue

    return type_locations


def extract_default_implementation(services: Dict[str, Any], server_name: str) -> Dict[str, Any]:
    """Extract default implementation from registry services

    Finds the most common class_name/module_path/instance pattern
    from the services and returns it as the default implementation.

    Args:
        services: Dict of services extracted from registry
        server_name: Server name (used as fallback for module path)

    Returns:
        Dict with class_name, module_path, instance, method keys
    """
    if not services:
        # Ultimate fallback with generic naming based on server_name
        return {
            'class_name': f'{server_name.title().replace("_", "")}Service',
            'module_path': f'mcp_{server_name}.{server_name}_service',
            'instance': f'{server_name}_service',
            'method': ''
        }

    # Count occurrences of each (class_name, module_path, instance) tuple
    from collections import Counter
    impl_counter = Counter()

    for service_info in services.values():
        class_name = service_info.get('class_name', '')
        module_path = service_info.get('module_path', '')
        instance = service_info.get('instance', '')

        if class_name:
            impl_counter[(class_name, module_path, instance)] += 1

    if not impl_counter:
        # Fallback if no valid implementations found
        first_service = next(iter(services.values()), {})
        return {
            'class_name': first_service.get('class_name', ''),
            'module_path': first_service.get('module_path', ''),
            'instance': first_service.get('instance', ''),
            'method': ''
        }

    # Get the most common implementation
    most_common = impl_counter.most_common(1)[0][0]
    class_name, module_path, instance = most_common

    # Normalize module_path for mcp_* convention
    # If module_path is like 'outlook.outlook_service', convert to 'mcp_outlook.outlook_service'
    if module_path and not module_path.startswith('mcp_'):
        parts = module_path.split('.')
        if len(parts) >= 1 and parts[0] == server_name:
            module_path = f'mcp_{server_name}.' + '.'.join(parts[1:])

    return {
        'class_name': class_name,
        'module_path': module_path,
        'instance': instance,
        'method': ''  # Will be set per-tool based on service_name
    }


def extract_type_info(registry: Dict[str, Any], tools: List[Dict[str, Any]], server_name: str = None) -> Dict[str, Any]:
    """Extract type information from registry and tools

    Returns:
        Dict with:
        - param_types: List of parameter type names
        - enum_types: List of enum type names
        - type_imports: Dict mapping types to their import paths
    """
    param_types = set()
    enum_types = set()
    type_imports = {}

    builtin_types = {
        # Python primitives
        'str', 'int', 'float', 'bool', 'dict', 'list',
        # JSON Schema primitives (some sources may already use these)
        'string', 'integer', 'number', 'boolean', 'object', 'array',
        # Other common sentinels
        'any', 'null', 'None', 'Any',
    }

    def _normalize_param_type(param: Dict[str, Any]) -> str:
        """Normalize registry/tool param to a concrete type name.

        Supports both formats:
        - legacy: {'type': 'FilterParams'}
        - new:    {'type': 'object', 'class_name': 'FilterParams'}
        """
        return (param.get('class_name') or param.get('type') or '').strip()

    # Extract from registry parameters
    for service_name, service_data in registry.get('services', {}).items():
        for param in service_data.get('parameters', []):
            param_type = _normalize_param_type(param)

            # Extract custom types (not built-ins)
            if param_type and param_type not in builtin_types:
                # Handle Optional[XXX] -> XXX (legacy format)
                clean_type = param_type
                if 'Optional[' in clean_type:
                    clean_type = clean_type.replace('Optional[', '').replace(']', '')
                # Ignore generics like List[str], Union[..., ...] which are not importable identifiers
                if not clean_type or not clean_type.isidentifier():
                    continue

                # Categorize types
                if 'Params' in clean_type:
                    param_types.add(clean_type)
                elif clean_type and clean_type[0].isupper():  # Likely an enum or class
                    enum_types.add(clean_type)

    # Extract from tool definitions
    for tool in tools:
        # Check mcp_service parameters
        mcp_service = tool.get('mcp_service', {})
        if isinstance(mcp_service, dict):
            for param in mcp_service.get('parameters', []):
                param_type = _normalize_param_type(param)
                if param_type and param_type not in builtin_types:
                    clean_type = param_type
                    if 'Optional[' in clean_type:
                        clean_type = clean_type.replace('Optional[', '').replace(']', '')
                    # Ignore generics like List[str], Union[..., ...] which are not importable identifiers
                    if not clean_type or not clean_type.isidentifier():
                        continue

                    if 'Params' in clean_type:
                        param_types.add(clean_type)
                    elif clean_type and clean_type[0].isupper():
                        enum_types.add(clean_type)

    # Find type locations if server_name is provided
    type_locations = {}
    if server_name:
        type_locations = find_type_locations(server_name)

    return {
        'param_types': sorted(list(param_types)),
        'enum_types': sorted(list(enum_types)),
        'all_types': sorted(list(param_types | enum_types)),
        'type_locations': type_locations
    }


def prepare_context(registry: Dict[str, Any], tools: List[Dict[str, Any]], server_name: str, internal_args: Dict[str, Any] = None, protocol_type: str = 'rest', service_factors: Dict[str, Dict[str, Any]] = None, profile_name: str = None, port: int = None, base_profile: str = None, base_service_paths: dict = None) -> Dict[str, Any]:
    """Prepare Jinja2 context from registry, tools, internal args, and service factors

    Args:
        registry: Service registry JSON
        tools: Tool definitions list
        server_name: MCP server name (e.g., 'outlook')
        internal_args: Internal arguments for tools
        protocol_type: Server protocol type ('rest', 'stdio', 'stream')
        service_factors: Service factors including internal and signature_defaults
        profile_name: Profile name (e.g., 'outlook_read' for reused profiles), defaults to server_name
        port: Server port number (used in template for REST/Stream protocols)
        base_profile: Base profile name if this is a derived profile
        base_service_paths: Service paths resolved from base profile (from resolve_service_paths)
    """
    if internal_args is None:
        internal_args = {}
    if service_factors is None:
        service_factors = {}
    if profile_name is None:
        profile_name = server_name

    # Extract services with proper structure
    # Note: load_registry normalizes service_data by promoting handler fields to root level
    services = {}
    for service_name, service_data in registry.get('services', {}).items():
        impl = service_data.get('implementation', service_data.get('handler', {}))
        # First check root level (normalized), then fall back to impl (handler)
        services[service_name] = {
            'class_name': service_data.get('class_name') or impl.get('class_name', impl.get('class', '')),
            'module_path': service_data.get('module_path') or impl.get('module_path', impl.get('module', '')),
            'instance': service_data.get('instance') or impl.get('instance', impl.get('instance_name', '')),
            'method': service_data.get('method') or impl.get('method', service_name)
        }

    # Map tools to their implementations
    tools_map = {}
    for service_name, service_data in registry.get('services', {}).items():
        # Get tool names from metadata
        metadata = service_data.get('metadata', {})
        tool_names = metadata.get('tool_names', [])

        impl = service_data.get('implementation', service_data.get('handler', {}))

        for tool_name in tool_names:
            # Clean up tool name (remove Handle_ prefix if present)
            clean_name = tool_name
            if tool_name.startswith('Handle_'):
                clean_name = tool_name[7:]
            elif tool_name.startswith('handle_'):
                clean_name = tool_name[7:]

            tools_map[clean_name] = {
                'implementation': {
                    'class_name': impl.get('class_name', impl.get('class', '')),
                    'method': impl.get('method', service_name),
                    'instance': impl.get('instance', impl.get('instance_name', ''))
                }
            }

    # Extract type information
    type_info = extract_type_info(registry, tools, server_name)

    # Create unique_services for compatibility with STDIO/STREAM templates
    unique_services = {}
    for service_name, service_info in services.items():
        class_name = service_info['class_name']
        if class_name not in unique_services:
            unique_services[class_name] = service_info

    # Process tools with internal args, signature_defaults, and implementation info
    processed_tools = []
    for tool in tools:
        tool_name = tool.get('name', '')
        tool_internal_args = internal_args.get(tool_name, {})
        tool_service_factors = service_factors.get(tool_name, {})

        # Add internal_args and signature_defaults to the tool
        tool_with_internal = dict(tool)
        tool_with_internal['internal_args'] = tool_internal_args
        tool_with_internal['signature_defaults'] = tool_service_factors.get('signature_defaults', {})
        tool_with_internal['service_factors'] = tool_service_factors

        # Find implementation info from registry
        # Check mcp_service for the service name mapping
        mcp_service = tool.get('mcp_service', {})
        if isinstance(mcp_service, str):
            service_name = mcp_service
        else:
            service_name = mcp_service.get('name', tool_name)

        # Get implementation from services
        if service_name in services:
            tool_with_internal['implementation'] = services[service_name]
        elif tool_name in tools_map:
            tool_with_internal['implementation'] = tools_map[tool_name]['implementation']
        else:
            # Fallback: Auto-extract default implementation from registry services
            # Uses the most common class_name/module_path/instance pattern
            default_impl = extract_default_implementation(services, server_name)
            default_impl['method'] = service_name  # Set method from mcp_service
            tool_with_internal['implementation'] = default_impl

        # Build params from mcp_service.parameters or inputSchema.properties
        params = {}
        object_params = {}
        call_params = {}
        boolean_params = []  # Track boolean params for conversion

        # First, get the inputSchema to understand the mappings
        input_schema = tool.get('inputSchema', {})
        properties = input_schema.get('properties', {})

        # Convert boolean properties to enabled/disabled for OpenAI compatibility
        converted_input_schema = convert_boolean_to_enabled_disabled(input_schema)
        tool_with_internal['inputSchema'] = converted_input_schema
        converted_properties = converted_input_schema.get('properties', {})

        # Create a mapping from inputSchema property name to targetParam (service method param name)
        param_mappings = {}
        for prop_name, prop_def in properties.items():
            target_param = prop_def.get('targetParam', prop_name)
            param_mappings[prop_name] = target_param

        # Build a set of Internal parameter targetParams
        # Note: Internal parameters may also have Signature counterparts with the same targetParam
        internal_target_params = set()
        for arg_name, arg_info in tool_internal_args.items():
            target_param = arg_info.get('targetParam') or arg_info.get('original_schema', {}).get('targetParam', arg_name)
            internal_target_params.add(target_param)

        # Build a set of Signature targetParams (from inputSchema properties)
        signature_target_params = set()
        for prop_name, prop_def in properties.items():
            target_param = prop_def.get('targetParam', prop_name)
            signature_target_params.add(target_param)

        # Get parameters from mcp_service if available
        if isinstance(mcp_service, dict):
            for param in mcp_service.get('parameters', []):
                param_name = param.get('name', '')
                raw_param_type = param.get('type', 'str')
                # New registry format: type may be 'object' with separate class_name
                param_class_name = param.get('class_name')
                param_type = param_class_name or raw_param_type

                # Skip Internal parameters ONLY if they don't have a Signature counterpart in inputSchema
                # If both Internal and Signature exist with same targetParam, process it (merge will happen)
                if param_name in internal_target_params and param_name not in signature_target_params:
                    continue

                # Compute is_required: it's required if not optional and no default
                has_default = param.get('has_default', False)
                is_optional = param.get('is_optional', False) or has_default
                is_required = param.get('is_required', not is_optional)  # Use is_required if provided, else derive from is_optional
                default = param.get('default')

                # Find the input schema property name that maps to this service parameter
                input_param_name = None
                for inp_name, tgt_name in param_mappings.items():
                    if tgt_name == param_name:
                        input_param_name = inp_name
                        break

                # If not found in mappings, check if param_name exists directly in inputSchema
                if input_param_name is None:
                    if param_name in properties:
                        input_param_name = param_name
                    else:
                        # This parameter is NOT in inputSchema - skip it
                        # (It's neither a Signature parameter nor Internal, likely a service-only param)
                        continue

                # Check if this param was originally a boolean (from inputSchema)
                original_prop = properties.get(input_param_name, {})
                is_boolean_param = original_prop.get('type') == 'boolean'

                # For boolean params, convert default to enabled/disabled
                if is_boolean_param:
                    boolean_params.append(input_param_name)
                    default_json = convert_enabled_disabled_default(default, 'boolean')
                else:
                    default_json = to_python_repr(default)

                params[input_param_name] = {
                    'type': param_type,
                    'is_required': is_required,
                    'has_default': has_default,
                    'default': default,
                    'default_json': default_json,
                    'is_boolean': is_boolean_param  # Track original boolean type
                }

                # Check if it's an object type (Params class)
                schema_is_object = original_prop.get('type') == 'object'
                schema_base_model = original_prop.get('baseModel')
                if schema_is_object or 'Params' in param_type:
                    # Prefer schema baseModel (authoritative), then registry class_name, then type string
                    class_name = schema_base_model or param_class_name or param_type
                    # Strip Optional[...] legacy wrappers if present
                    class_name = class_name.replace('Optional[', '').replace(']', '')

                    # Get the targetParam for this input param
                    target_param = param_mappings.get(input_param_name, param_name)

                    # Find matching internal and signature_defaults by targetParam
                    internal_defaults = {}
                    sig_defaults_values = {}

                    for factor_name, factor_info in tool_service_factors.get('internal', {}).items():
                        if factor_info.get('targetParam') == target_param:
                            internal_defaults = factor_info.get('value', {})
                            break

                    for factor_name, factor_info in tool_service_factors.get('signature_defaults', {}).items():
                        if factor_info.get('targetParam') == target_param:
                            sig_defaults_values = factor_info.get('value', {})
                            break

                    object_params[input_param_name] = {
                        'class_name': class_name,
                        'is_optional': is_optional,
                        'has_default': has_default,
                        'default_json': to_python_repr(default) if default is not None else None,
                        'target_param': target_param,
                        'internal_defaults': internal_defaults,
                        'signature_defaults_values': sig_defaults_values
                    }

                # Build call_params (how to pass to service method)
                # Map from service param name to the value expression
                if input_param_name in object_params:
                    call_params[param_name] = {'value': input_param_name, 'source_param': input_param_name}
                else:
                    call_params[param_name] = {'value': input_param_name, 'source_param': input_param_name}

        # Fallback: extract from inputSchema if no mcp_service parameters
        if not params:
            input_schema = tool.get('inputSchema', {})
            properties = input_schema.get('properties', {})
            required = input_schema.get('required', [])

            for prop_name, prop_def in properties.items():
                prop_type = prop_def.get('type', 'string')
                is_required = prop_name in required
                default = prop_def.get('default')

                params[prop_name] = {
                    'type': prop_type,
                    'is_required': is_required,
                    'has_default': default is not None,
                    'default': default,
                    'default_json': to_python_repr(default)
                }

                # Get targetParam from inputSchema property or default to prop_name
                target_param = prop_def.get('targetParam', prop_name)

                if prop_type == 'object':
                    base_model = prop_def.get('baseModel', '')

                    # Find matching internal and signature_defaults by targetParam
                    internal_defaults = {}
                    sig_defaults_values = {}

                    for factor_name, factor_info in tool_service_factors.get('internal', {}).items():
                        if factor_info.get('targetParam') == target_param:
                            internal_defaults = factor_info.get('value', {})
                            break

                    for factor_name, factor_info in tool_service_factors.get('signature_defaults', {}).items():
                        if factor_info.get('targetParam') == target_param:
                            sig_defaults_values = factor_info.get('value', {})
                            break

                    object_params[prop_name] = {
                        'class_name': base_model or 'dict',
                        'is_optional': not is_required,
                        'has_default': default is not None,
                        'default_json': to_python_repr(default) if default is not None else None,
                        'target_param': target_param,
                        'internal_defaults': internal_defaults,
                        'signature_defaults_values': sig_defaults_values
                    }

                call_params[target_param] = {'value': prop_name, 'source_param': prop_name}

        # Internal args are handled separately with targetParam mappings
        # They are processed in the template itself (lines 260-291 in universal_server_template.jinja2)
        # Do NOT add them to call_params here as they need to be built at runtime

        tool_with_internal['params'] = params
        tool_with_internal['object_params'] = object_params
        tool_with_internal['call_params'] = call_params
        tool_with_internal['boolean_params'] = boolean_params  # Track boolean params for enabled/disabled conversion
        internal_overrides = {}
        for arg_name, arg_info in tool_internal_args.items():
            if not arg_name.endswith("_internal"):
                continue
            base_name = arg_name[: -len("_internal")]
            if base_name in object_params:
                internal_overrides[base_name] = {
                    "name": arg_name,
                    "info": arg_info
                }
        tool_with_internal['internal_overrides'] = internal_overrides

        processed_tools.append(tool_with_internal)

    # Prepare context
    context = {
        'server_name': server_name,
        'profile_name': profile_name,  # Profile name for reused profiles (e.g., outlook_read)
        'server_title': f"{server_name.replace('_', ' ').title()} MCP Server",
        'protocol_type': protocol_type,  # Add protocol type to context
        'port': port,  # Server port for REST/Stream protocols
        'base_profile': base_profile,  # Base profile name if derived profile
        'base_service_paths': base_service_paths,  # Service paths from base profile
        'services': services,
        'unique_services': unique_services,  # Add unique_services for STDIO/STREAM templates
        'tools': processed_tools,  # List of tools with implementation info for template iteration
        'tools_map': tools_map,    # Dict for quick lookup by name
        'param_types': type_info['param_types'],  # Parameter types (FilterParams, etc.)
        'enum_types': type_info['enum_types'],     # Enum types (QueryMethod, etc.)
        'all_types': type_info['all_types'],       # All custom types
        'type_info': type_info,                    # Full type information
        'MCP_TOOLS': processed_tools,  # Tool definitions with internal args (same as tools)
        'internal_args': internal_args,  # Full internal args for reference (legacy)
        'service_factors': service_factors  # Full service factors (internal + signature_defaults)
    }

    return context


def generate_server(
    template_path: str,
    output_path: str,
    registry_path: str,
    tools_path: str,
    server_name: str,
    protocol_type: str = 'rest',
    port: int = 8080,
    profile_name: str = None
):
    """Generate server.py from registry and template

    Args:
        template_path: Path to Jinja2 template file
        output_path: Path for generated server.py
        registry_path: Path to service registry JSON
        tools_path: Path to tool definitions
        server_name: Name of the server (outlook, file_handler, etc.)
        protocol_type: Protocol type ('rest', 'stdio', 'stream')
        port: Server port number (default: 8080)
        profile_name: Profile name (defaults to server_name if not provided)
    """
    # Set profile_name to server_name if not provided
    if profile_name is None:
        profile_name = server_name

    # Load editor_config and resolve service paths for derived profiles
    print(f"Loading editor_config.json...")
    editor_config = load_editor_config()
    service_paths = resolve_service_paths(profile_name, editor_config)

    base_profile = service_paths.get('base_profile')
    base_service_paths = service_paths if service_paths.get('is_derived') else None

    if base_profile:
        print(f"  - Derived profile detected: {profile_name} (base: {base_profile})")
        print(f"  - Using service module: {service_paths['module_prefix']}")
    else:
        print(f"  - Base profile: {profile_name}")

    # 자동 스캔 결과 출력
    types_files = service_paths.get('types_files', [])
    service_files = service_paths.get('service_files', [])
    if types_files:
        print(f"  [DIR] Types files ({len(types_files)}):")
        for f in types_files:
            print(f"      - {f}")
    if service_files:
        print(f"  [DIR] Service files ({len(service_files)}):")
        for f in service_files:
            print(f"      - {f}")

    # Load registry and tools
    print(f"Loading registry from: {registry_path}")
    registry = load_registry(registry_path)

    print(f"Loading tool definitions from: {tools_path}")
    tools = load_tool_definitions(tools_path)

    # Extract service factors from mcp_service_factors in tool definitions
    print(f"Extracting service factors from mcp_service_factors...")
    service_factors = extract_service_factors_from_tools(tools)
    internal_args = extract_internal_args_from_tools(tools)  # Legacy format for backward compatibility

    if service_factors:
        print(f"  - Extracted service factors for {len(service_factors)} tools")
        for tool_name, factors in service_factors.items():
            internal_count = len(factors.get('internal', {}))
            defaults_count = len(factors.get('signature_defaults', {}))
            print(f"    - {tool_name}: internal={internal_count}, signature_defaults={defaults_count}")
    else:
        print("  - No service factors found in mcp_service_factors")

    # Prepare context
    context = prepare_context(
        registry, tools, server_name, internal_args, protocol_type, service_factors,
        profile_name=profile_name, port=port,
        base_profile=base_profile, base_service_paths=base_service_paths
    )

    # Setup Jinja2
    template_dir = os.path.dirname(template_path)
    env = Environment(loader=FileSystemLoader(template_dir))

    # Add custom filter to raise errors during template rendering
    def raise_error(message):
        raise ValueError(message)
    env.filters['raise_error'] = raise_error

    template = env.get_template(os.path.basename(template_path))

    # Render template
    rendered = template.render(**context)

    # Create output directory if needed
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Write output
    with open(output_path, 'w') as f:
        f.write(rendered)

    # Print summary
    print(f"\n[OK] Generated {output_path} successfully!")
    print(f"\n[STATS] Summary:")
    print(f"  - Server: {server_name}")
    print(f"  - Protocol: {protocol_type}")
    print(f"  - Services: {len(context['services'])}")
    print(f"  - Tools mapped: {len(context['tools'])}")
    print(f"  - Parameter types: {', '.join(context['param_types'])}")

    print(f"\n[TOOL] Services:")
    for service_name, service_info in context['services'].items():
        print(f"  - {service_info['class_name']} ({service_info['module_path']})")

    print(f"\n[TOOL] Tool mappings:")
    for tool in context['tools']:
        impl = tool.get('implementation', {})
        print(f"  - {tool.get('name', 'unknown')} -> {impl.get('class_name', '?')}.{impl.get('method', '?')}()")


def find_registry_file(server_name: str) -> Optional[str]:
    """Find registry file for a given server"""
    candidates = [
        # Pattern: registry_{server}.json (current convention per docs)
        PROJECT_ROOT / "mcp_editor" / "mcp_service_registry" / f"registry_{server_name}.json",
        # Legacy patterns
        PROJECT_ROOT / "mcp_editor" / "mcp_service_registry" / f"{server_name}_registry.json",
        PROJECT_ROOT / "mcp_editor" / f"mcp_{server_name}" / f"registry_{server_name}.json",
        PROJECT_ROOT / f"mcp_{server_name}" / f"{server_name}_registry.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def find_tools_file(server_name: str) -> Optional[str]:
    """Find tool definitions file for a given server"""
    candidates = [
        # Pattern: mcp_editor/mcp_{server}/tool_definition_templates.py (current convention per docs)
        PROJECT_ROOT / "mcp_editor" / f"mcp_{server_name}" / "tool_definition_templates.py",
        # Legacy patterns
        PROJECT_ROOT / "mcp_editor" / server_name / "tool_definition_templates.py",
        PROJECT_ROOT / "mcp_editor" / "tool_definition_templates.py",
        PROJECT_ROOT / f"mcp_{server_name}" / "tool_definitions.py",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


# =============================================================================
# MCP Server Merge Functions
# =============================================================================

def merge_tool_definitions(source_profiles: List[str], prefix_mode: str = 'auto') -> List[Dict[str, Any]]:
    """Merge tool definitions from multiple profiles into a single list

    Args:
        source_profiles: List of profile names to merge (e.g., ['outlook', 'calendar'])
        prefix_mode: 'auto' = add prefix on conflict, 'always' = always add prefix, 'none' = no prefix

    Returns:
        Merged list of tool definitions with optional prefixes applied
    """
    import yaml
    import importlib.util

    all_tools = []
    tool_names_seen = {}  # track tool_name -> source_profile

    for profile in source_profiles:
        # Find YAML file for this profile
        yaml_path = PROJECT_ROOT / "mcp_editor" / f"mcp_{profile}" / "tool_definition_templates.yaml"
        py_path = PROJECT_ROOT / "mcp_editor" / f"mcp_{profile}" / "tool_definition_templates.py"

        tools = []

        if yaml_path.exists():
            # Load from YAML file
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            tools = data.get('tools', [])
            print(f"    Loaded {len(tools)} tools from {yaml_path.name}")
        elif py_path.exists():
            # Fallback to Python file
            try:
                spec = importlib.util.spec_from_file_location(f"tools_{profile}", py_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                tools = getattr(module, 'MCP_TOOLS', [])
                print(f"    Loaded {len(tools)} tools from {py_path.name}")
            except Exception as e:
                print(f"[WARN] Warning: Failed to load Python tool definitions for profile '{profile}': {e}")
                continue
        else:
            print(f"[WARN] Warning: No tool definitions found for profile '{profile}'")
            print(f"    Tried: {yaml_path}")
            print(f"    Tried: {py_path}")
            continue

        for tool in tools:
            original_name = tool.get('name', '')

            # Determine if prefix is needed
            needs_prefix = False
            if prefix_mode == 'always':
                needs_prefix = True
            elif prefix_mode == 'auto':
                if original_name in tool_names_seen:
                    # Conflict detected - add prefix to both
                    needs_prefix = True
                    # Also update the previously seen tool
                    prev_profile = tool_names_seen[original_name]
                    for prev_tool in all_tools:
                        if prev_tool.get('name') == original_name:
                            prev_tool['name'] = f"{prev_profile}_{original_name}"
                            prev_tool['_original_name'] = original_name
                            prev_tool['_source_profile'] = prev_profile
                            break

            # Apply prefix if needed
            tool_copy = dict(tool)
            if needs_prefix:
                tool_copy['name'] = f"{profile}_{original_name}"
                tool_copy['_original_name'] = original_name
            else:
                tool_copy['_original_name'] = original_name

            tool_copy['_source_profile'] = profile

            # Track tool name
            if original_name not in tool_names_seen:
                tool_names_seen[original_name] = profile

            all_tools.append(tool_copy)

    print(f"[BACKUP] Merged {len(all_tools)} tools from {len(source_profiles)} profiles")
    return all_tools


def normalize_module_path(module_path: str, source_profile: str) -> str:
    """Normalize module_path to include mcp_ prefix

    Converts 'outlook.outlook_service' -> 'mcp_outlook.outlook_service'

    Args:
        module_path: Original module path (e.g., 'calendar.calendar_service')
        source_profile: Source profile name (e.g., 'calendar')

    Returns:
        Normalized module path (e.g., 'mcp_calendar.calendar_service')
    """
    if not module_path:
        return module_path

    # Already has mcp_ prefix
    if module_path.startswith('mcp_'):
        return module_path

    parts = module_path.split('.')
    if len(parts) >= 1:
        # Check if first part matches source_profile
        if parts[0] == source_profile:
            parts[0] = f'mcp_{source_profile}'
        else:
            # Prepend mcp_ to first part
            parts[0] = f'mcp_{parts[0]}'

    return '.'.join(parts)


def merge_registries(source_profiles: List[str], merged_name: str) -> Dict[str, Any]:
    """Merge registries from multiple profiles into a single registry

    Args:
        source_profiles: List of profile names to merge
        merged_name: Name for the merged server

    Returns:
        Merged registry dict with normalized module_paths
    """
    merged_registry = {
        "version": "1.0",
        "generated_at": None,  # Will be set when saving
        "server_name": merged_name,
        "is_merged": True,
        "source_profiles": source_profiles,
        "services": {}
    }

    for profile in source_profiles:
        registry_path = find_registry_file(profile)
        if not registry_path:
            print(f"[WARN] Warning: Registry not found for profile '{profile}'")
            continue

        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)

        for service_name, service_data in registry.get('services', {}).items():
            # Create unique service name if conflict
            unique_name = service_name
            if service_name in merged_registry['services']:
                unique_name = f"{profile}_{service_name}"

            # Normalize module_path
            handler = service_data.get('handler', {})
            original_module_path = handler.get('module_path', '')
            normalized_path = normalize_module_path(original_module_path, profile)

            # Create service entry with normalized path
            service_copy = dict(service_data)
            service_copy['_source_profile'] = profile

            if 'handler' in service_copy:
                service_copy['handler'] = dict(service_copy['handler'])
                service_copy['handler']['module_path'] = normalized_path

            merged_registry['services'][unique_name] = service_copy

    print(f"[INFO] Merged {len(merged_registry['services'])} services from {len(source_profiles)} registries")
    return merged_registry


def find_type_locations_multi(source_profiles: List[str]) -> Dict[str, str]:
    """Find type locations across multiple source profiles

    Unlike find_type_locations which searches single server,
    this searches all source profiles' mcp_* directories.

    Args:
        source_profiles: List of profile names (e.g., ['outlook', 'calendar'])

    Returns:
        Dict mapping type names to their import paths
    """
    import ast
    import glob

    type_locations = {}

    for profile in source_profiles:
        # Search patterns for this profile
        search_paths = [
            PROJECT_ROOT / f"mcp_{profile}" / "*.py",
            PROJECT_ROOT / f"{profile}" / "*.py",
            PROJECT_ROOT / "mcp_editor" / f"mcp_{profile}" / "*.py",
        ]

        for pattern in search_paths:
            for file_path in glob.glob(str(pattern)):
                try:
                    with open(file_path, 'r') as f:
                        tree = ast.parse(f.read())

                    # Extract module name from file path
                    module_parts = Path(file_path).stem
                    if 'mcp_' in str(file_path):
                        if 'mcp_editor' in str(file_path):
                            module_name = f"mcp_editor.mcp_{profile}.{module_parts}"
                        else:
                            module_name = f"mcp_{profile}.{module_parts}"
                    else:
                        module_name = f"{profile}.{module_parts}"

                    # Find class definitions and enums
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            is_enum = any(
                                base.id == 'Enum' if isinstance(base, ast.Name) else
                                (base.attr == 'Enum' if isinstance(base, ast.Attribute) else False)
                                for base in node.bases
                            )

                            if node.name not in type_locations:
                                type_locations[node.name] = {
                                    'module': module_name,
                                    'is_enum': is_enum,
                                    'file': file_path,
                                    'source_profile': profile
                                }
                except:
                    continue

    print(f"[SEARCH] Found {len(type_locations)} types across {len(source_profiles)} profiles")
    return type_locations


def check_tool_name_conflicts(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Check for tool name conflicts and report them

    Args:
        tools: List of tool definitions

    Returns:
        List of conflicts: [{'name': str, 'profiles': [str, ...]}]
    """
    name_to_profiles = {}

    for tool in tools:
        name = tool.get('_original_name', tool.get('name', ''))
        profile = tool.get('_source_profile', 'unknown')

        if name not in name_to_profiles:
            name_to_profiles[name] = []
        name_to_profiles[name].append(profile)

    conflicts = []
    for name, profiles in name_to_profiles.items():
        if len(profiles) > 1:
            conflicts.append({'name': name, 'profiles': profiles})

    return conflicts


def save_merged_yaml(tools: List[Dict[str, Any]], output_path: Path):
    """Save merged tool definitions to YAML file

    Args:
        tools: List of merged tool definitions
        output_path: Path to save the YAML file
    """
    import yaml

    # Clean up internal fields before saving
    clean_tools = []
    for tool in tools:
        tool_copy = dict(tool)
        # Remove internal tracking fields
        tool_copy.pop('_original_name', None)
        tool_copy.pop('_source_profile', None)
        clean_tools.append(tool_copy)

    output_data = {'tools': clean_tools}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(output_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"[SAVE] Saved merged YAML to: {output_path}")


def save_merged_registry(registry: Dict[str, Any], output_path: Path):
    """Save merged registry to JSON file

    Args:
        registry: Merged registry dict
        output_path: Path to save the JSON file
    """
    from datetime import datetime

    # Add generation timestamp
    registry_copy = dict(registry)
    registry_copy['generated_at'] = datetime.now().isoformat()

    # Clean up internal fields in services
    for service_name, service_data in registry_copy.get('services', {}).items():
        if isinstance(service_data, dict):
            service_data.pop('_source_profile', None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(registry_copy, f, indent=2, ensure_ascii=False)

    print(f"[SAVE] Saved merged registry to: {output_path}")


def update_editor_config_for_merge(merged_name: str, source_profiles: List[str], port: int):
    """Update editor_config.json with merged profile entry

    Args:
        merged_name: Name for the merged server
        source_profiles: List of source profile names
        port: Server port number
    """
    config = load_editor_config()

    # Collect types_files and service_files from all source profiles (with auto-scan)
    all_types_files = []
    all_service_files = []

    for profile in source_profiles:
        profile_config = config.get(profile, {})
        source_dir = profile_config.get('source_dir', f'../mcp_{profile}')

        # 자동 스캔으로 타입/서비스 파일 찾기
        scanned_types = scan_types_files(source_dir)
        scanned_services = scan_service_files(source_dir)

        # 설정된 타입 파일도 추가
        config_types = profile_config.get('types_files', [])
        for f in config_types:
            if f not in all_types_files:
                all_types_files.append(f)

        # 스캔된 파일 추가
        for f in scanned_types:
            if f not in all_types_files:
                all_types_files.append(f)

        for f in scanned_services:
            if f not in all_service_files:
                all_service_files.append(f)

    print(f"  [DIR] Auto-scanned types files: {len(all_types_files)}")
    for f in all_types_files:
        print(f"      - {f}")
    print(f"  [DIR] Auto-scanned service files: {len(all_service_files)}")
    for f in all_service_files:
        print(f"      - {f}")

    # Create merged profile entry with all required fields
    merged_config = {
        "source_dir": f"../mcp_{merged_name}",
        "template_definitions_path": f"mcp_{merged_name}/tool_definition_templates.yaml",
        "tool_definitions_path": f"../mcp_{merged_name}/mcp_server/tool_definitions.py",
        "backup_dir": f"mcp_{merged_name}/backups",
        "host": "0.0.0.0",
        "port": port,
        "is_merged": True,
        "source_profiles": source_profiles,
        "types_files": all_types_files,
        "service_files": all_service_files
    }

    config[merged_name] = merged_config

    with open(EDITOR_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"[NOTE] Updated editor_config.json with merged profile: {merged_name}")


def generate_merged_server(
    merged_name: str,
    source_profiles: List[str],
    port: int = 8080,
    protocol: str = 'all',
    prefix_mode: str = 'auto'
):
    """Generate a merged MCP server from multiple source profiles

    Args:
        merged_name: Name for the merged server (e.g., 'ms365')
        source_profiles: List of profile names to merge (e.g., ['outlook', 'calendar'])
        port: Server port number
        protocol: Protocol type ('rest', 'stdio', 'stream', 'all')
        prefix_mode: Tool name prefix mode ('auto', 'always', 'none')
    """
    print(f"\n{'='*60}")
    print(f"[MERGE] MCP Server Merge: {merged_name}")
    print(f"{'='*60}")
    print(f"  Source profiles: {', '.join(source_profiles)}")
    print(f"  Port: {port}")
    print(f"  Protocol: {protocol}")
    print(f"  Prefix mode: {prefix_mode}")
    print()

    # Step 1: Merge tool definitions (YAML)
    print("[INFO] Step 1: Merging tool definitions...")
    merged_tools = merge_tool_definitions(source_profiles, prefix_mode)

    # Check for conflicts
    conflicts = check_tool_name_conflicts(merged_tools)
    if conflicts:
        print(f"[WARN] Tool name conflicts detected (resolved with prefix):")
        for conflict in conflicts:
            print(f"    - {conflict['name']}: {', '.join(conflict['profiles'])}")

    # Step 2: Merge registries
    print("\n[INFO] Step 2: Merging service registries...")
    merged_registry = merge_registries(source_profiles, merged_name)

    # Step 3: Find types across all profiles
    print("\n[INFO] Step 3: Scanning types from source profiles...")
    type_locations = find_type_locations_multi(source_profiles)

    # Step 4: Create output directories and save merged files
    print("\n[INFO] Step 4: Creating merged profile files...")

    merged_editor_dir = PROJECT_ROOT / "mcp_editor" / f"mcp_{merged_name}"
    merged_server_dir = PROJECT_ROOT / f"mcp_{merged_name}" / "mcp_server"
    registry_dir = PROJECT_ROOT / "mcp_editor" / "mcp_service_registry"

    # Create directories
    merged_editor_dir.mkdir(parents=True, exist_ok=True)
    merged_server_dir.mkdir(parents=True, exist_ok=True)

    # Save merged YAML
    merged_yaml_path = merged_editor_dir / "tool_definition_templates.yaml"
    save_merged_yaml(merged_tools, merged_yaml_path)

    # Save merged registry
    merged_registry_path = registry_dir / f"registry_{merged_name}.json"
    save_merged_registry(merged_registry, merged_registry_path)

    # Update editor_config.json
    update_editor_config_for_merge(merged_name, source_profiles, port)

    # Step 5: Generate server files
    print("\n[INFO] Step 5: Generating server files...")

    protocols_to_generate = ['rest', 'stdio', 'stream'] if protocol == 'all' else [protocol]
    template_path = str(SCRIPT_DIR / "python" / "universal_server_template.jinja2")

    success_count = 0
    for proto in protocols_to_generate:
        output_path = str(merged_server_dir / f"server_{proto}.py")

        try:
            # Prepare context for merged server
            service_factors = extract_service_factors_from_tools(merged_tools)
            internal_args = extract_internal_args_from_tools(merged_tools)

            context = prepare_context(
                merged_registry,
                merged_tools,
                merged_name,
                internal_args,
                proto,
                service_factors,
                profile_name=merged_name,
                port=port,
                base_profile=None,
                base_service_paths=None
            )

            # Override type_info with multi-profile types
            context['type_info']['type_locations'] = type_locations

            # Add merged server metadata
            context['is_merged_server'] = True
            context['source_profiles'] = source_profiles

            # Setup Jinja2
            template_dir = os.path.dirname(template_path)
            env = Environment(loader=FileSystemLoader(template_dir))

            def raise_error(message):
                raise ValueError(message)
            env.filters['raise_error'] = raise_error

            template = env.get_template(os.path.basename(template_path))

            # Render template
            rendered = template.render(**context)

            # Write output
            with open(output_path, 'w') as f:
                f.write(rendered)

            print(f"  [OK] Generated: {output_path}")
            success_count += 1

        except Exception as e:
            print(f"  [ERROR] Failed to generate {proto}: {e}")
            import traceback
            traceback.print_exc()

    # Step 6: Print summary
    print(f"\n{'='*60}")
    print(f"[STATS] MERGE SUMMARY")
    print(f"{'='*60}")
    print(f"  Merged server: {merged_name}")
    print(f"  Source profiles: {', '.join(source_profiles)}")
    print(f"  Total tools: {len(merged_tools)}")
    print(f"  Total services: {len(merged_registry['services'])}")
    print(f"  Total types: {len(type_locations)}")
    print(f"  Servers generated: {success_count}/{len(protocols_to_generate)}")
    print()
    print(f"[DIR] Created files:")
    print(f"  - {merged_yaml_path}")
    print(f"  - {merged_registry_path}")
    for proto in protocols_to_generate:
        print(f"  - {merged_server_dir / f'server_{proto}.py'}")
    print()

    if success_count == len(protocols_to_generate):
        print(f"[DONE] Merge completed successfully!")
        return True
    else:
        print(f"[WARN] Merge completed with errors")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate MCP server from universal template or merge multiple servers"
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # =========================================================================
    # Generate command (default behavior)
    # =========================================================================
    generate_parser = subparsers.add_parser('generate', help='Generate single MCP server')
    generate_parser.add_argument("server_name", help="Server name (e.g., 'outlook', 'file_handler')")
    generate_parser.add_argument("--protocol", help="Protocol type",
                                  choices=['rest', 'stdio', 'stream', 'all'], default='rest')
    generate_parser.add_argument("--registry", help="Path to registry JSON file (auto-detected if not specified)")
    generate_parser.add_argument("--tools", help="Path to tool definitions file (auto-detected if not specified)")
    generate_parser.add_argument("--template", help="Path to Jinja2 template",
                                  default=str(SCRIPT_DIR / "python" / "universal_server_template.jinja2"))
    generate_parser.add_argument("--output", help="Output path for generated server.py")

    # =========================================================================
    # Merge command
    # =========================================================================
    merge_parser = subparsers.add_parser('merge', help='Merge multiple MCP servers into one')
    merge_parser.add_argument("--name", required=True, help="Name for merged server (e.g., 'ms365')")
    merge_parser.add_argument("--sources", required=True, help="Comma-separated source profiles (e.g., 'outlook,calendar')")
    merge_parser.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    merge_parser.add_argument("--protocol", choices=['rest', 'stdio', 'stream', 'all'], default='all',
                              help="Protocol type (default: all)")
    merge_parser.add_argument("--prefix", choices=['auto', 'always', 'none'], default='auto',
                              help="Tool name prefix mode: auto=on conflict, always=always add, none=no prefix (default: auto)")

    # For backward compatibility: if no subcommand, treat first arg as server_name
    args, unknown = parser.parse_known_args()

    # If no command specified but there's an argument, use legacy generate mode
    if args.command is None and len(sys.argv) > 1:
        # Check if first argument looks like a server name (not a flag)
        first_arg = sys.argv[1]
        if not first_arg.startswith('-'):
            # Legacy mode: treat as generate command
            legacy_parser = argparse.ArgumentParser(description="Generate MCP server from universal template")
            legacy_parser.add_argument("server_name", help="Server name")
            legacy_parser.add_argument("--protocol", choices=['rest', 'stdio', 'stream', 'all'], default='rest')
            legacy_parser.add_argument("--registry", help="Path to registry JSON file")
            legacy_parser.add_argument("--tools", help="Path to tool definitions file")
            legacy_parser.add_argument("--template", default=str(SCRIPT_DIR / "python" / "universal_server_template.jinja2"))
            legacy_parser.add_argument("--output", help="Output path for generated server.py")
            args = legacy_parser.parse_args()
            args.command = 'generate'
        else:
            parser.print_help()
            sys.exit(1)
    elif args.command is None:
        parser.print_help()
        sys.exit(0)

    # =========================================================================
    # Handle MERGE command
    # =========================================================================
    if args.command == 'merge':
        source_profiles = [p.strip() for p in args.sources.split(',')]

        if len(source_profiles) < 2:
            print("[ERROR] Error: At least 2 source profiles are required for merge")
            sys.exit(1)

        success = generate_merged_server(
            merged_name=args.name,
            source_profiles=source_profiles,
            port=args.port,
            protocol=args.protocol,
            prefix_mode=args.prefix
        )

        sys.exit(0 if success else 1)

    # =========================================================================
    # Handle GENERATE command
    # =========================================================================
    # Find registry file
    registry_path = args.registry or find_registry_file(args.server_name)
    if not registry_path:
        print(f"[ERROR] Could not find registry file for server '{args.server_name}'")
        print(f"   Searched in: mcp_editor/mcp_service_registry/registry_{args.server_name}.json")
        sys.exit(1)

    # Find tools file
    tools_path = args.tools or find_tools_file(args.server_name)
    if not tools_path:
        print(f"[ERROR] Could not find tool definitions file for server '{args.server_name}'")
        print(f"   Searched in: mcp_editor/mcp_{args.server_name}/tool_definition_templates.py")
        sys.exit(1)

    # Generate all protocols or specific one
    if args.protocol == 'all':
        protocols_to_generate = ['rest', 'stdio', 'stream']
    else:
        protocols_to_generate = [args.protocol]

    # Track success/failure
    success_count = 0
    failed_protocols = []

    for protocol in protocols_to_generate:
        # Always use universal template for all protocols
        template_path = args.template or str(SCRIPT_DIR / "python" / "universal_server_template.jinja2")

        # Determine output path
        if args.output:
            output_base = Path(args.output)
            # Check if output is a directory or file
            if output_base.suffix == '' or output_base.is_dir():
                # Output is a directory - generate filename automatically
                if protocol == 'rest':
                    filename = 'server_rest.py'  # Changed for consistency
                else:
                    filename = f'server_{protocol}.py'
                output_path = str(output_base / filename)
            else:
                # Output is a file path
                if len(protocols_to_generate) == 1:
                    output_path = args.output
                else:
                    # Multiple protocols but single file specified - append protocol
                    base = output_base.stem
                    ext = output_base.suffix
                    if protocol == 'rest':
                        filename = f'{base}_rest{ext}'
                    else:
                        filename = f'{base}_{protocol}{ext}'
                    output_path = str(output_base.parent / filename)
        else:
            # Default: mcp_{server}/mcp_server/server_{protocol}.py
            if protocol == 'rest':
                filename = 'server_rest.py'  # Changed for consistency
            else:
                filename = f'server_{protocol}.py'
            output_path = str(PROJECT_ROOT / f"mcp_{args.server_name}" / "mcp_server" / filename)

        # Generate server
        try:
            print(f"\n{'='*60}")
            print(f"[START] Generating {protocol.upper()} server...")
            print(f"{'='*60}")

            generate_server(
                server_name=args.server_name,
                registry_path=registry_path,
                tools_path=tools_path,
                template_path=template_path,
                output_path=output_path,
                protocol_type=protocol
            )
            success_count += 1
        except Exception as e:
            print(f"[ERROR] Error generating {protocol} server: {e}")
            import traceback
            traceback.print_exc()
            failed_protocols.append(protocol)

    # Print final summary
    print(f"\n{'='*60}")
    print(f"[INFO] GENERATION SUMMARY")
    print(f"{'='*60}")
    print(f"[OK] Successfully generated: {success_count}/{len(protocols_to_generate)} servers")

    if failed_protocols:
        print(f"[ERROR] Failed protocols: {', '.join(failed_protocols)}")
        sys.exit(1)
    else:
        print(f"[DONE] All servers generated successfully!")
        sys.exit(0)
