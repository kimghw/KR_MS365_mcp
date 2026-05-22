#!/usr/bin/env python3
"""
Generate server.py from tool definitions using Jinja2 template
"""
import os
import sys
import re
import ast
import argparse
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from jinja2 import Environment, FileSystemLoader

# Import system paths
sys.path.insert(0, str(Path(__file__).parent.parent))

# Try to import MCPMetaRegistry (may be in different locations)
try:
    from mcp_service_registry import MCPMetaRegistry
    from mcp_service_registry.collectors import CollectorContext
except ImportError:
    try:
        from mcp_editor.mcp_service_registry import MCPMetaRegistry
        from mcp_editor.mcp_service_registry.collectors import CollectorContext
    except ImportError:
        # Fallback - registry not available
        MCPMetaRegistry = None
        CollectorContext = None


def to_python_literal(value: Any) -> str:
    """
    Convert a Python value to a string that is valid Python code.
    Unlike json.dumps which produces true/false/null,
    this produces True/False/None.
    """
    if value is None:
        return 'None'
    elif isinstance(value, bool):
        return 'True' if value else 'False'
    elif isinstance(value, str):
        return repr(value)
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, dict):
        items = ', '.join(f'{to_python_literal(k)}: {to_python_literal(v)}' for k, v in value.items())
        return '{' + items + '}'
    elif isinstance(value, (list, tuple)):
        items = ', '.join(to_python_literal(item) for item in value)
        return '[' + items + ']'
    else:
        # Fallback to repr for other types
        return repr(value)


def copy_mcp_decorators(output_dir: str) -> Path:
    """Generate mcp_decorators.py file"""
    decorators_content = '''"""
MCP Tool Decorator
Decorator for marking functions as MCP tools
"""
from functools import wraps
from typing import Any, Callable, Dict, Optional

# Registry to store MCP tool metadata
MCP_TOOL_REGISTRY = {}

def mcp_tool(
    tool_name: str,
    description: str = "",
    category: str = "",
    tags: list = None,
    priority: int = 0
) -> Callable:
    """
    Decorator to mark a function as an MCP tool

    Args:
        tool_name: Name of the tool in MCP
        description: Tool description
        category: Tool category
        tags: List of tags
        priority: Tool priority
    """
    def decorator(func: Callable) -> Callable:
        # Store metadata in registry
        MCP_TOOL_REGISTRY[tool_name] = {
            "function": func,
            "tool_name": tool_name,
            "description": description,
            "category": category,
            "tags": tags or [],
            "priority": priority,
            "module": func.__module__,
            "function_name": func.__name__
        }

        # Add metadata to function
        func._mcp_tool = True
        func._mcp_metadata = {
            "tool_name": tool_name,
            "description": description,
            "category": category,
            "tags": tags or [],
            "priority": priority
        }

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator

def get_mcp_tools() -> Dict[str, Any]:
    """Get all registered MCP tools"""
    return MCP_TOOL_REGISTRY

def get_mcp_tool(tool_name: str) -> Optional[Dict[str, Any]]:
    """Get a specific MCP tool by name"""
    return MCP_TOOL_REGISTRY.get(tool_name)
'''

    decorators_path = Path(output_dir) / 'mcp_decorators.py'
    decorators_path.parent.mkdir(parents=True, exist_ok=True)
    with open(decorators_path, 'w') as f:
        f.write(decorators_content)
    return decorators_path


def find_internal_args_file(tools_path: str) -> Optional[str]:
    """
    Find tool_internal_args.json based on tools_path location.
    Searches in the same directory or common editor directories.
    """
    tools_path = Path(tools_path).resolve()  # Convert to absolute path

    # Extract server name from path (e.g., mcp_outlook -> outlook)
    # Try to infer from parent directory name
    parent_name = tools_path.parent.name  # e.g., "mcp_server"
    grandparent_name = tools_path.parent.parent.name  # e.g., "mcp_outlook"

    # Derive server name from grandparent (mcp_outlook -> outlook)
    server_name = None
    if grandparent_name.startswith("mcp_"):
        server_name = grandparent_name[4:]  # "outlook"

    # Search patterns (in order of priority)
    search_paths = [
        # Same directory as tools file
        tools_path.parent / "tool_internal_args.json",
        # mcp_editor/{server_name}/ pattern (relative to tools file)
        tools_path.parent.parent / tools_path.parent.name / "tool_internal_args.json",
    ]

    # Try to find the file
    for candidate in search_paths:
        if candidate.exists():
            return str(candidate)

    # Fallback: search in mcp_editor directories at project root
    # Find project root by looking for mcp_editor directory
    project_root = tools_path.parent
    while project_root.parent != project_root:
        mcp_editor_dir = project_root / "mcp_editor"
        if mcp_editor_dir.exists():
            # First, try specific server name directory if we know it
            if server_name:
                specific_path = mcp_editor_dir / server_name / "tool_internal_args.json"
                if specific_path.exists():
                    return str(specific_path)

            # Look for tool_internal_args.json in subdirectories
            for subdir in mcp_editor_dir.iterdir():
                if subdir.is_dir():
                    candidate = subdir / "tool_internal_args.json"
                    if candidate.exists():
                        return str(candidate)
            break
        project_root = project_root.parent

    return None


def load_internal_args(internal_args_path: Optional[str]) -> Dict[str, Any]:
    """
    Load internal args from JSON file.
    Returns empty dict if file doesn't exist.
    """
    if not internal_args_path or not Path(internal_args_path).exists():
        return {}

    try:
        with open(internal_args_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load internal_args from {internal_args_path}: {e}")
        return {}


def extract_defaults_from_schema(original_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract default values from original_schema.properties.
    Returns a dict with property names and their default values.
    Only includes properties that have a 'default' key.
    """
    defaults = {}
    properties = original_schema.get('properties', {})
    for prop_name, prop_info in properties.items():
        if 'default' in prop_info:
            defaults[prop_name] = prop_info['default']
    return defaults


def enrich_internal_args_with_defaults(internal_args: Dict[str, Any]) -> Dict[str, Any]:
    """
    For internal args with empty value {}, extract defaults from original_schema.properties
    and use them as the effective value.
    """
    enriched = {}
    for tool_name, tool_args in internal_args.items():
        enriched[tool_name] = {}
        for arg_name, arg_info in tool_args.items():
            enriched_arg = dict(arg_info)  # Copy original

            # If value is empty dict and original_schema has properties with defaults
            if arg_info.get('value') == {} and 'original_schema' in arg_info:
                defaults = extract_defaults_from_schema(arg_info['original_schema'])
                if defaults:
                    enriched_arg['value'] = defaults

            enriched[tool_name][arg_name] = enriched_arg

    return enriched


def collect_all_param_types(tools: List[Dict[str, Any]], internal_args: Dict[str, Any]) -> set:
    """
    Collect all parameter types from both Signature (inputSchema) and Internal args.
    This ensures all necessary types are imported in the generated server.
    """
    types = set()

    # JSON schema types that should NOT be imported (they are Python built-ins or schema keywords)
    EXCLUDED_TYPES = {'object', 'array', 'string', 'number', 'integer', 'boolean', 'null'}

    # Collect from Signature parameters (inputSchema)
    for tool in tools:
        schema = tool.get('inputSchema', {})
        properties = schema.get('properties', {})
        for prop_name, prop_schema in properties.items():
            if prop_schema.get('type') == 'object':
                base_model = prop_schema.get('baseModel')
                if base_model and base_model not in EXCLUDED_TYPES:
                    types.add(base_model)

    # Collect from Internal args
    for tool_name, params in internal_args.items():
        for param_name, param_info in params.items():
            param_type = param_info.get('type')
            # Only add actual class names, not JSON schema types
            if param_type and param_type not in EXCLUDED_TYPES:
                types.add(param_type)

    return types


def parse_signature(signature: str) -> Dict[str, Any]:
    """Parse function signature to extract parameters and their types"""
    params = {}

    # Remove spaces around equals for easier parsing
    signature = signature.replace(" = ", "=")

    # Split by comma, but be careful with nested brackets
    param_strings = []
    current = []
    bracket_count = 0

    for char in signature:
        if char == '[':
            bracket_count += 1
        elif char == ']':
            bracket_count -= 1
        elif char == ',' and bracket_count == 0:
            param_strings.append(''.join(current).strip())
            current = []
            continue
        current.append(char)

    if current:
        param_strings.append(''.join(current).strip())

    for param_str in param_strings:
        # Parse each parameter
        if ':' in param_str:
            name, type_and_default = param_str.split(':', 1)
            name = name.strip()
            type_and_default = type_and_default.strip()

            # Check for default value
            if '=' in type_and_default:
                type_str, default = type_and_default.split('=', 1)
                type_str = type_str.strip()
                default = default.strip()
                params[name] = {
                    'type': type_str,
                    'has_default': True,
                    'default': default,
                    'is_required': False
                }
            else:
                params[name] = {
                    'type': type_and_default,
                    'has_default': False,
                    'default': None,
                    'is_required': 'Optional' not in type_and_default
                }
        else:
            # No type annotation
            name = param_str.strip()
            if '=' in name:
                name, default = name.split('=', 1)
                params[name.strip()] = {
                    'type': 'Any',
                    'has_default': True,
                    'default': default.strip(),
                    'is_required': False
                }
            else:
                params[name] = {
                    'type': 'Any',
                    'has_default': False,
                    'default': None,
                    'is_required': True
                }

    return params


def params_from_service_info(service_info: Dict[str, Any]) -> Dict[str, Any]:
    """Prefer structured parameters over re-parsing signature strings."""
    signature_params: Dict[str, Any] = {}

    if not service_info:
        return signature_params

    structured = service_info.get("parameters")
    if isinstance(structured, list):
        for param in structured:
            name = param.get("name")
            if not name or name == "self":
                continue

            param_type = param.get("type") or "Any"
            has_default = param.get("has_default", False)
            default_val = param.get("default")

            # If has_default not explicitly provided, infer from presence of default value
            if not has_default and default_val is not None:
                has_default = True

            signature_params[name] = {
                "type": param_type,
                "has_default": has_default,
                "default": default_val,
                "is_required": param.get(
                    "is_required",
                    not has_default and "Optional" not in str(param_type),
                ),
            }
        return signature_params

    signature = service_info.get("signature")
    if signature:
        return parse_signature(signature)

    return signature_params


def analyze_tool_schema(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze tool schema to understand parameter types and requirements"""

    # Determine service based on tool name
    tool_name = tool['name']
    tool_name_lower = tool_name.lower()

    # Determine handler info based on tool type
    # Attachment server tools
    if 'file' in tool_name_lower or 'convert' in tool_name_lower or 'onedrive' in tool_name_lower or 'directory' in tool_name_lower:
        handler_class = 'FileManager'
        handler_instance = 'file_manager'
        handler_module = 'file_manager'
        handler_method = tool_name
    elif 'metadata' in tool_name_lower:
        handler_class = 'MetadataManager'
        handler_instance = 'metadata_manager'
        handler_module = 'metadata.manager'
        handler_method = tool_name
    # Outlook server tools
    else:
        # Only use GraphMailQuery (GraphMailClient removed based on AST analysis)
        handler_class = 'GraphMailQuery'
        handler_instance = 'graph_mail_query'
        handler_module = 'graph_mail_query'
        handler_method = tool_name

    # Create improved structure
    analyzed = {
        # MCP/Tool naming
        'tool_name': tool_name,
        'server_name': 'outlook',  # Will be determined from context

        # Handler info (grouped in dictionary)
        'handler': {
            'method': handler_method,
            'class': handler_class,
            'instance': handler_instance,
            'module': handler_module,
        },

        # Parameters (will be filled below)
        'params': {},
        'object_params': {},
        'call_params': {},

        # Legacy fields for compatibility (will be removed later)
        'name': tool_name,
        'service_class': handler_class,
        'service_object': handler_instance,
        'service_method': handler_method,
    }

    # Check if tool has mcp_service metadata
    if 'mcp_service' in tool:
        service_info = tool['mcp_service']
        # If mcp_service is a string, use it directly as the handler method
        if isinstance(service_info, str):
            analyzed['handler']['method'] = service_info
            analyzed['service_method'] = service_info  # Legacy compatibility
            analyzed['mcp_service'] = service_info
            signature_params = {}
        else:
            # mcp_service is a dict with 'name' key - this is the actual Python method name
            method_name = service_info.get('name', tool['name'])
            analyzed['handler']['method'] = method_name
            analyzed['service_method'] = method_name  # Legacy compatibility
            analyzed['mcp_service'] = method_name  # Always set as string for template

            # Extract server name if available
            if 'server_name' in service_info:
                analyzed['server_name'] = service_info['server_name']

            signature_params = params_from_service_info(service_info)
    else:
        signature_params = {}

    # Analyze input schema
    schema = tool.get('inputSchema', {})
    properties = schema.get('properties', {})
    required = schema.get('required', [])

    for param_name, param_schema in properties.items():
        param_type = param_schema.get('type', 'string')

        # Check if this is an object parameter that needs conversion
        # Check for default value - use 'default' in param_schema to detect explicit null defaults
        has_default = 'default' in param_schema
        param_default = param_schema.get('default')

        if param_type == 'object':
            # This is an object that needs to be converted to a class
            base_model = param_schema.get('baseModel')
            if not base_model:
                # Try to infer from description or name
                if 'filter' in param_name.lower():
                    base_model = 'FilterParams'
                elif 'exclude' in param_name.lower():
                    base_model = 'ExcludeParams'
                elif 'select' in param_name.lower():
                    base_model = 'SelectParams'

            if base_model:
                analyzed['object_params'][param_name] = {
                    'class_name': base_model,
                    'is_optional': param_name not in required,
                    'is_dict': True,  # Most are dict-based
                    'has_default': has_default,
                    'default': param_default,
                    # Use to_python_literal for valid Python code (True/False/None instead of true/false/null)
                    'default_json': to_python_literal(param_default) if has_default and param_default is not None else None
                }

                # Add to call_params with the converted name
                param_info = signature_params.get(param_name, {})
                analyzed['call_params'][param_name] = {
                    'value': f"{param_name}_params" if base_model else param_name
                }
        elif param_type == 'array':
            # Arrays typically pass through directly
            analyzed['params'][param_name] = {
                'is_required': param_name in required,
                'has_default': has_default,
                'default': param_default,
                # Use to_python_literal for valid Python code (True/False/None instead of true/false/null)
                'default_json': to_python_literal(param_default) if has_default else None
            }
            analyzed['call_params'][param_name] = {
                'value': param_name
            }
        else:
            # Regular parameters
            # Priority: inputSchema.default > signature_params.default
            param_info = signature_params.get(param_name, {})
            final_has_default = has_default or 'default' in param_info
            final_default = param_default if has_default else param_info.get('default')
            analyzed['params'][param_name] = {
                'is_required': param_name in required,
                'has_default': final_has_default,
                'default': final_default,
                # Use to_python_literal for valid Python code (True/False/None instead of true/false/null)
                'default_json': to_python_literal(final_default) if final_has_default else None
            }

            # Add to call_params if not an object param
            if param_name not in analyzed['object_params']:
                analyzed['call_params'][param_name] = {
                    'value': param_name
                }

    # Special handling for specific tools based on existing server.py patterns
    if tool['name'] == 'query_emails':
        analyzed['handler']['method'] = 'query_filter'  # Actual method name in GraphMailQuery
        analyzed['service_method'] = 'query_filter'  # Legacy compatibility
        analyzed['object_params'] = {
            'filter': {'class_name': 'FilterParams', 'is_optional': True, 'is_dict': True},
            'exclude': {'class_name': 'ExcludeParams', 'is_optional': True, 'is_dict': True},
            'select': {'class_name': 'SelectParams', 'is_optional': True, 'is_dict': True},
        }
        analyzed['params'] = {
            'user_email': {'is_required': True, 'has_default': False},
            'top': {'is_required': False, 'has_default': True, 'default': '10'},
            'orderby': {'is_required': False, 'has_default': True, 'default': '"receivedDateTime desc"'},
        }
        analyzed['call_params'] = {
            'user_email': {'value': 'user_email'},
            'filter': {'value': 'filter_params'},
            'exclude': {'value': 'exclude_params'},
            'select': {'value': 'select_params'},
            'top': {'value': 'args.get("top", 10)'},
            'orderby': {'value': 'args.get("orderby", "receivedDateTime desc")'},
        }
    elif tool['name'] == 'mail_search':
        # Handle mail_search which maps to query_search
        if 'mcp_service' in tool:
            analyzed['handler']['method'] = tool['mcp_service']['name']
            analyzed['service_method'] = tool['mcp_service']['name']  # Legacy compatibility
        else:
            analyzed['handler']['method'] = 'query_search'  # Default mapping for mail_search
            analyzed['service_method'] = 'query_search'  # Legacy compatibility

        analyzed['object_params'] = {
            'client_filter': {'class_name': 'ExcludeParams', 'is_optional': True, 'is_dict': True},
            'select': {'class_name': 'SelectParams', 'is_optional': True, 'is_dict': True},
        }
        analyzed['params'] = {
            'user_email': {'is_required': True, 'has_default': False},
            'search': {'is_required': True, 'has_default': False},
            'top': {'is_required': False, 'has_default': True, 'default': '250'},
            'orderby': {'is_required': False, 'has_default': False},
        }
        analyzed['call_params'] = {
            'user_email': {'value': 'user_email'},
            'search': {'value': 'search'},
            'client_filter': {'value': 'client_filter_params'},
            'select': {'value': 'select_params'},
            'top': {'value': 'args.get("top", 250)'},
            'orderby': {'value': 'orderby'},
        }
    elif tool['name'] == 'mail_list':
        # Ensure mail_list maps to the underlying query_filter service
        analyzed['handler']['class'] = 'GraphMailQuery'
        analyzed['handler']['instance'] = 'graph_mail_query'
        analyzed['handler']['module'] = 'graph_mail_query'

        # Legacy compatibility
        analyzed['service_class'] = 'GraphMailQuery'
        analyzed['service_object'] = 'graph_mail_query'

        service_override = tool.get('mcp_service')
        if isinstance(service_override, dict):
            service_override = service_override.get('name')

        method_name = service_override or 'query_filter'
        analyzed['handler']['method'] = method_name
        analyzed['service_method'] = method_name  # Legacy compatibility

    # Derive getter name for the handler instance (used in template)
    analyzed['handler']['getter'] = f"get_{analyzed['handler']['instance']}_instance"

    return analyzed


def analyze_decorated_methods(server_dir: Path) -> Dict[str, Any]:
    """
    Analyze Python files to find @mcp_tool decorated methods and extract service info

    Returns:
        Dict with 'services' containing class info and 'methods' with decorated methods
    """
    result = {
        'services': {},  # class_name -> {'module': module_name, 'instance_name': instance_name}
        'methods': {},   # method_name -> {'class': class_name, 'module': module_name}
        'param_types': set()
    }

    # Common directories to check for service files
    search_dirs = [
        server_dir,
        server_dir.parent,  # Check parent directory
        server_dir / 'mcp_server'
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue

        # Find all Python files
        py_files = list(search_dir.glob('*.py'))

        for py_file in py_files:
            # Skip __pycache__, tests, and generated files
            if any(skip in str(py_file) for skip in ['__pycache__', 'test_', 'server.py', 'tool_definitions.py']):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Parse the AST
                tree = ast.parse(content)

                # Find classes and their decorated methods
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        class_name = node.name
                        module_name = py_file.stem  # Use filename as module name

                        # Look for @mcp_tool decorated methods
                        for item in node.body:
                            if isinstance(item, ast.AsyncFunctionDef) or isinstance(item, ast.FunctionDef):
                                # Check decorators
                                for decorator in item.decorator_list:
                                    decorator_name = None

                                    # Handle different decorator patterns
                                    if isinstance(decorator, ast.Name):
                                        decorator_name = decorator.id
                                    elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                                        decorator_name = decorator.func.id

                                    if decorator_name in ['mcp_tool', 'mcp_service']:
                                        # Found an MCP service/tool method
                                        method_name = item.name

                                        # Add service info if not already present
                                        if class_name not in result['services']:
                                            # Convert ClassName to instance_name
                                            instance_name = class_name[0].lower() + class_name[1:] if class_name else 'service'
                                            # Convert instance_name from camelCase to snake_case
                                            instance_name = re.sub(r'(?<!^)(?=[A-Z])', '_', instance_name).lower()

                                            result['services'][class_name] = {
                                                'module': module_name,
                                                'instance_name': instance_name
                                            }

                                        # Add method info
                                        result['methods'][method_name] = {
                                            'class': class_name,
                                            'module': module_name
                                        }

                                        # Extract parameter types from method signature
                                        if isinstance(item, (ast.AsyncFunctionDef, ast.FunctionDef)):
                                            for arg in item.args.args:
                                                if arg.annotation:
                                                    # Extract type names from annotations
                                                    if isinstance(arg.annotation, ast.Name):
                                                        type_name = arg.annotation.id
                                                        if type_name not in ['str', 'int', 'bool', 'float', 'list', 'dict', 'Any', 'Optional']:
                                                            result['param_types'].add(type_name)

            except Exception as e:
                # Skip files that can't be parsed
                continue

    return result


def extract_service_metadata(tools: List[Dict[str, Any]], server_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Extract metadata about services and imports from tools"""
    metadata = {
        'services': {},
        'param_types': set(),
        'modules': set()
    }

    # First, try to extract from mcp_service annotations in tools
    for tool in tools:
        # Check for service information
        if 'mcp_service' in tool:
            service_info = tool['mcp_service']
            # Extract service class info if available
            if 'class' in service_info:
                class_name = service_info['class']
                module = service_info.get('module', 'graph_mail_query')
                metadata['services'][class_name] = {
                    'module': module,
                    'instance_name': class_name[0].lower() + class_name[1:] if class_name else 'service'
                }
                metadata['modules'].add(module)

        # Extract parameter types
        schema = tool.get('inputSchema', {})
        properties = schema.get('properties', {})

        for prop_name, prop_schema in properties.items():
            if prop_schema.get('type') == 'object':
                base_model = prop_schema.get('baseModel')
                if base_model:
                    metadata['param_types'].add(base_model)

    # If no services found from mcp_service, use AST analysis
    if not metadata['services'] and server_dir:
        ast_result = analyze_decorated_methods(server_dir)

        if ast_result['services']:
            metadata['services'] = ast_result['services']
            metadata['modules'] = {info['module'] for info in ast_result['services'].values()}
            metadata['param_types'].update(ast_result['param_types'])

    # Only add default services if still no services found
    if not metadata['services']:
        # Check if it's attachment or file handler server
        has_attachment_tools = any('file' in tool['name'].lower() or 'metadata' in tool['name'].lower()
                                  or 'convert' in tool['name'].lower() or 'onedrive' in tool['name'].lower()
                                  for tool in tools)

        if has_attachment_tools:
            metadata['services'] = {
                'FileManager': {
                    'module': 'file_manager',
                    'instance_name': 'file_manager'
                }
            }
            metadata['modules'] = {'file_manager'}
        else:
            # Only add GraphMailQuery as default for outlook server
            metadata['services'] = {
                'GraphMailQuery': {
                    'module': 'graph_mail_query',
                    'instance_name': 'graph_mail_query'
                }
            }
            metadata['modules'] = {'graph_mail_query'}

    # Add parameter types based on services being used
    if 'GraphMailQuery' in metadata['services']:
        metadata['param_types'].update(['FilterParams', 'ExcludeParams', 'SelectParams'])

    return metadata


def generate_server_with_registry(template_path: str, output_path: str,
                                 tools_path: str, internal_args_path: str = None,
                                 server_name: str = "outlook", use_registry: bool = True):
    """
    Generate server.py using MCPMetaRegistry system.

    Args:
        template_path: Path to Jinja2 template file
        output_path: Path for generated server.py
        tools_path: Path to tools definition file
        internal_args_path: Explicit path to tool_internal_args.json (optional)
        server_name: Server name for context (default: "outlook")
        use_registry: Whether to use the new registry system (default: True)
    """
    if not use_registry or MCPMetaRegistry is None or CollectorContext is None:
        # Fall back to old method if registry is disabled or not available
        tools = load_tool_definitions(tools_path)
        return generate_server(template_path, output_path, tools, tools_path, internal_args_path, server_name)

    # Create collector context
    tools_path = Path(tools_path)

    # Determine scan directory
    scan_dir = None
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root / f"mcp_{server_name}",
        repo_root / f"mcp_{server_name}" / "mcp_server",
    ]
    for candidate in candidates:
        if candidate.exists():
            scan_dir = candidate
            break

    # Determine types files
    types_files = []
    if scan_dir:
        # Look for types files in the scan directory
        for pattern in ["*_types.py", "types.py"]:
            types_files.extend(scan_dir.glob(pattern))

    # Create context
    ctx = CollectorContext(
        server_name=server_name,
        tools_path=tools_path,
        internal_args_path=Path(internal_args_path) if internal_args_path else None,
        scan_dir=scan_dir,
        types_files=types_files
    )

    # Initialize registry
    registry = MCPMetaRegistry()

    # Get Jinja context
    context = registry.to_jinja_context(ctx)

    # Set up Jinja2 environment
    template_dir = os.path.dirname(template_path)
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template(os.path.basename(template_path))

    # Render template
    rendered = template.render(**context)

    # Write output
    with open(output_path, 'w') as f:
        f.write(rendered)

    # Print summary
    print(f"Generated {output_path} successfully!")
    print(f"\nRegistry Summary:")
    print(registry.get_summary(ctx))
    print(f"\nProcessed {len(context['tools'])} tools:")
    for tool in context['tools']:
        internal_count = len(tool.get('internal_args', {}))
        internal_info = f" (+ {internal_count} internal args)" if internal_count else ""
        print(f"  - {tool['name']} -> {tool['service_method']}(){internal_info}")
    print(f"\nServices detected:")
    for service, info in context['services'].items():
        print(f"  - {service} from {info['module']}")
    print(f"\nParameter types: {', '.join(context['param_types'])}")

def generate_server(template_path: str, output_path: str, tools: List[Dict[str, Any]] = None,
                    tools_path: str = None, internal_args_path: str = None, server_name: str = None):
    """Generate server.py from template and tool definitions (legacy method)

    Args:
        template_path: Path to Jinja2 template file
        output_path: Path for generated server.py
        tools: List of tool definitions (optional, falls back to global MCP_TOOLS)
        tools_path: Path to tools definition file (used for finding internal_args)
        internal_args_path: Explicit path to tool_internal_args.json (optional)
        server_name: Server name for context (optional)
    """
    # Use provided tools or fall back to global MCP_TOOLS
    if tools is None:
        tools = MCP_TOOLS

    # Load internal args
    if not internal_args_path and tools_path:
        internal_args_path = find_internal_args_file(tools_path)
    internal_args_raw = load_internal_args(internal_args_path)

    # Enrich internal args: extract defaults from original_schema.properties
    internal_args = enrich_internal_args_with_defaults(internal_args_raw)

    if internal_args:
        print(f"Loaded internal args for {len(internal_args)} tools from: {internal_args_path}")
        # Show enriched defaults
        for tool_name, tool_args in internal_args.items():
            for arg_name, arg_info in tool_args.items():
                if arg_info.get('value') and arg_info['value'] != internal_args_raw.get(tool_name, {}).get(arg_name, {}).get('value'):
                    print(f"  - {tool_name}.{arg_name}: extracted defaults from schema -> {arg_info['value']}")

    # Set up Jinja2 environment
    template_dir = os.path.dirname(template_path)
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template(os.path.basename(template_path))

    # Determine server directory for AST analysis
    server_dir = None
    if output_path:
        server_dir = Path(output_path).parent
    elif tools_path:
        server_dir = Path(tools_path).parent

    # Extract service metadata
    service_metadata = extract_service_metadata(tools, server_dir)

    # Collect all param types (Signature + Internal)
    all_param_types = collect_all_param_types(tools, internal_args)
    service_metadata['param_types'].update(all_param_types)

    # Analyze all tools
    analyzed_tools = []
    for tool in tools:
        analyzed = analyze_tool_schema(tool)

        # Add service info from metadata if available
        if 'mcp_service' in tool and 'class' in tool['mcp_service']:
            class_name = tool['mcp_service']['class']
            if class_name in service_metadata['services']:
                analyzed['service_class'] = class_name
                analyzed['service_object'] = service_metadata['services'][class_name]['instance_name']
                analyzed['service_module'] = service_metadata['services'][class_name]['module']

        # Add internal args for this tool (if any)
        tool_internal_args = internal_args.get(analyzed['name'], {})
        analyzed['internal_args'] = tool_internal_args

        # CRITICAL: Merge internal_args into call_params so they are passed to service methods
        # Internal args use {arg_name}_params naming convention in the template
        for arg_name, arg_info in tool_internal_args.items():
            # Only add to call_params if not already present (internal args should not override schema params)
            if arg_name not in analyzed['call_params']:
                analyzed['call_params'][arg_name] = {
                    'value': f"{arg_name}_params"
                }

        analyzed_tools.append(analyzed)

    # Collect unique handler instances for helper generation in template
    handler_instances = []
    seen_instances = set()
    for tool in analyzed_tools:
        instance_name = tool['handler'].get('instance') or tool.get('service_object')
        class_name = tool['handler'].get('class') or tool.get('service_class')

        if instance_name and instance_name not in seen_instances:
            handler_instances.append({
                'name': instance_name,
                'class': class_name
            })
            seen_instances.add(instance_name)

    # Prepare context for template
    context = {
        'tools': analyzed_tools,
        'services': service_metadata['services'],
        'param_types': sorted(service_metadata['param_types']),
        'modules': sorted(service_metadata['modules']),
        'internal_args': internal_args,  # Full internal args dict for reference
        'server_name': server_name,
        'handler_instances': handler_instances
    }

    # Render template
    rendered = template.render(**context)

    # Write output
    with open(output_path, 'w') as f:
        f.write(rendered)

    print(f"Generated {output_path} successfully!")
    print(f"Processed {len(analyzed_tools)} tools:")
    for tool in analyzed_tools:
        internal_count = len(tool.get('internal_args', {}))
        internal_info = f" (+ {internal_count} internal args)" if internal_count else ""
        print(f"  - {tool['name']} -> {tool['service_method']}(){internal_info}")
    print(f"\nServices detected:")
    for service, info in service_metadata['services'].items():
        print(f"  - {service} from {info['module']}")
    print(f"\nParameter types: {', '.join(sorted(service_metadata['param_types']))}")


def load_tool_definitions(tool_def_path: str) -> List[Dict[str, Any]]:
    """Load tool definitions from a Python module or JSON file"""
    path = Path(tool_def_path)

    if path.suffix == '.json':
        # Load from JSON file
        with open(path, 'r') as f:
            data = json.load(f)
            return data.get('MCP_TOOLS', data)
    elif path.suffix == '.py':
        # Use AST to parse the file without importing
        import ast

        def _eval_mcp_tools(node_value):
            """
            Evaluate the MCP_TOOLS assignment node.
            Supports both literal lists/dicts and json.loads(\"\"\"...\"\"\") patterns
            produced by the web editor.
            """
            # Handle json.loads(\"\"\"...\"\"\") style (Call node)
            if isinstance(node_value, ast.Call):
                func = node_value.func
                func_name = None
                if isinstance(func, ast.Attribute):
                    # e.g., json.loads(...)
                    func_name = f"{getattr(func.value, 'id', None)}.{func.attr}"
                elif isinstance(func, ast.Name):
                    # e.g., loads(...)
                    func_name = func.id

                if func_name in ('json.loads', 'loads') and node_value.args:
                    first_arg = node_value.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        return json.loads(first_arg.value)
            # Fallback to literal eval for plain list/dict constants
            return ast.literal_eval(node_value)

        with open(path, 'r') as f:
            tree = ast.parse(f.read())

        for node in tree.body:
            # Handle regular assignment (MCP_TOOLS = [...])
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == 'MCP_TOOLS':
                        return _eval_mcp_tools(node.value)

            # Handle type-annotated assignment (MCP_TOOLS: List[Dict[str, Any]] = [...])
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == 'MCP_TOOLS':
                    return _eval_mcp_tools(node.value)

        raise ValueError("Could not find MCP_TOOLS in the Python file")
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}. Use .py or .json")


def main():
    parser = argparse.ArgumentParser(description='Generate MCP server from tool definitions')
    parser.add_argument(
        '--tools', '-t',
        default='/home/kimghw/Connector_auth/mcp_editor/outlook/tool_definition_templates.py',
        help='Path to tool definition templates file (default: mcp_editor/outlook/tool_definition_templates.py)'
    )
    parser.add_argument(
        '--template', '-p',
        default=None,
        help='Path to Jinja2 template file (default: outlook_server_template.jinja2 in same directory as this script)'
    )
    parser.add_argument(
        '--output', '-o',
        default=None,
        help='Output path for generated server.py (default: temp file, or server.py location with --replace)'
    )
    parser.add_argument(
        '--replace', '-r',
        action='store_true',
        help='Replace existing server.py in place (creates backup first)'
    )
    parser.add_argument(
        '--backup-dir',
        help='Directory for backups when using --replace (default: ./backups)'
    )
    parser.add_argument(
        '--config', '-c',
        help='Path to configuration file with service metadata (JSON)'
    )
    parser.add_argument(
        '--include-decorators',
        action='store_true',
        default=True,
        help='Also generate mcp_decorators.py file (default: True)'
    )
    parser.add_argument(
        '--use-registry',
        action='store_true',
        default=False,
        help='Use the new MCPMetaRegistry system for generation'
    )
    parser.add_argument(
        '--server-name',
        default='outlook',
        help='Server name for context (default: outlook)'
    )

    args = parser.parse_args()

    # Set default template path if not provided
    if args.template is None:
        script_dir = Path(__file__).parent
        template_path = script_dir / "outlook_server_template.jinja2"
    else:
        template_path = Path(args.template)

    # Load tool definitions
    print(f"Loading tool definitions from: {args.tools}")
    global MCP_TOOLS
    MCP_TOOLS = load_tool_definitions(args.tools)
    print(f"  Loaded {len(MCP_TOOLS)} tool definitions")

    # Load additional config if provided
    if args.config:
        with open(args.config, 'r') as f:
            config = json.load(f)
            # You can use this config to override service metadata
            print(f"  Loaded configuration from: {args.config}")

    # Handle output path
    if args.replace:
        # Replace mode - output to the CORRECT server.py location
        # The server.py should be in mcp_outlook/mcp_server/, NOT in mcp_editor/outlook/
        server_path = Path("/home/kimghw/Connector_auth/mcp_outlook/mcp_server/server.py")

        # Create backup if file exists
        if server_path.exists():
            from datetime import datetime
            backup_dir = Path(args.backup_dir) if args.backup_dir else server_path.parent / "backups"
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"server_backup_{timestamp}.py"
            backup_path = backup_dir / backup_name

            import shutil
            shutil.copy2(server_path, backup_path)
            print(f"[OK] Created backup: {backup_path}")

        output_path = server_path
        use_temp = False
    elif args.output:
        output_path = Path(args.output)
        use_temp = False
    else:
        import tempfile
        temp_fd, temp_path = tempfile.mkstemp(prefix='mcp_server_', suffix='.py')
        os.close(temp_fd)  # Close the file descriptor
        output_path = Path(temp_path)
        use_temp = True
        print(f"Using temporary file: {output_path}")

    # Generate server using the appropriate method
    if args.use_registry:
        # Use new registry system
        generate_server_with_registry(
            str(template_path),
            str(output_path),
            tools_path=args.tools,
            server_name=args.server_name,
            use_registry=True
        )
    else:
        # Use legacy method (with tools_path for internal_args discovery)
        generate_server(str(template_path), str(output_path), MCP_TOOLS, tools_path=args.tools)

    print(f"\n[OK] Generated server successfully!")
    print(f"   Output: {output_path}")

    # Generate mcp_decorators.py if requested
    decorators_path = None
    if args.include_decorators:
        # Put decorators in mcp_editor/outlook/ directory, NOT with server.py
        decorators_dir = Path("/home/kimghw/Connector_auth/mcp_editor/outlook")
        decorators_path = copy_mcp_decorators(str(decorators_dir))
        print(f"[OK] Generated mcp_decorators.py")
        print(f"   Output: {decorators_path}")

    if use_temp:
        print(f"\n[INFO] Next steps:")
        print(f"1. Review the generated files:")
        print(f"   cat {output_path}")
        if decorators_path:
            print(f"   cat {decorators_path}")
        print(f"\n2. If satisfied, copy to your project:")
        print(f"   cp {output_path} mcp_outlook/mcp_server/server.py")
        if decorators_path:
            print(f"   cp {decorators_path} mcp_outlook/mcp_server/")
        print(f"\n3. Clean up temp files when done:")
        print(f"   rm {output_path}")
        if decorators_path:
            print(f"   rm {decorators_path}")
    else:
        print(f"\nTo use the generated server:")
        print(f"1. Review the generated files")
        print(f"2. Copy to mcp_outlook/mcp_server/ directory")
        print(f"3. Test with: python -m mcp_outlook.mcp_server.server")


if __name__ == "__main__":
    main()
