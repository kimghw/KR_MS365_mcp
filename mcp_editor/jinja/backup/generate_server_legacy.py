#!/usr/bin/env python3
"""
Universal MCP server generator
- Uses registry JSON files for service metadata
- Single template for all servers
- Automatic registry and tool definition discovery
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# Ensure project paths are in sys.path
sys.path.insert(0, str(PROJECT_ROOT))


def load_registry(registry_path: str) -> Dict[str, Any]:
    """Load service registry JSON file"""
    with open(registry_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_tool_definitions(tool_def_path: str) -> List[Dict[str, Any]]:
    """Load tool definitions from Python module or JSON file"""
    path = Path(tool_def_path)

    if path.suffix == '.json':
        with open(path, 'r') as f:
            data = json.load(f)
            return data.get('MCP_TOOLS', data)
    elif path.suffix == '.py':
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
                        # Handle literal list/dict
                        return ast.literal_eval(node.value)

            # Handle type-annotated assignment
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == 'MCP_TOOLS':
                    if isinstance(node.value, ast.Call):
                        func = node.value.func
                        if hasattr(func, 'attr') and func.attr == 'loads':
                            if node.value.args and isinstance(node.value.args[0], ast.Constant):
                                return json.loads(node.value.args[0].value)
                    return ast.literal_eval(node.value)

        raise ValueError("Could not find MCP_TOOLS in the Python file")
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")


def extract_param_types(registry: Dict[str, Any]) -> List[str]:
    """Extract unique parameter types from registry"""
    param_types = set()

    for service_name, service_data in registry.get('services', {}).items():
        for param in service_data.get('parameters', []):
            param_type = param.get('type', '')
            # Extract custom types (not built-ins)
            if 'Params' in param_type:
                # Handle Optional[XXXParams] -> XXXParams
                if 'Optional[' in param_type:
                    param_type = param_type.replace('Optional[', '').replace(']', '')
                param_types.add(param_type)

    return sorted(list(param_types))


def prepare_context(registry: Dict[str, Any], tools: List[Dict[str, Any]], server_name: str) -> Dict[str, Any]:
    """Prepare Jinja2 context from registry and tools"""

    # Extract services with proper structure
    services = {}
    for service_name, service_data in registry.get('services', {}).items():
        # Support both 'implementation' (new) and 'handler' (legacy) keys
        impl = service_data.get('implementation', service_data.get('handler', {}))
        services[service_name] = {
            'class_name': impl.get('class_name', impl.get('class', '')),
            'module_path': impl.get('module_path', impl.get('module', '')),
            'instance': impl.get('instance', impl.get('instance_name', '')),
            'method': impl.get('method', service_name)
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

    # Extract parameter types
    param_types = extract_param_types(registry)

    # Prepare context
    context = {
        'server_name': server_name,
        'server_title': f"{server_name.replace('_', ' ').title()} MCP Server",
        'services': services,
        'tools': tools_map,
        'param_types': param_types,
        'MCP_TOOLS': tools  # Original tool definitions
    }

    return context


def generate_server(
    template_path: str,
    output_path: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    server_name: str = None,
    tools_path: str = None,
    registry_path: str = None
):
    """Generate server.py from registry and template

    Args:
        template_path: Path to Jinja2 template file (optional)
        output_path: Path for generated server.py
        tools: List of tool definitions (optional, loaded from tools_path if not provided)
        server_name: Name of the server (outlook, file_handler, etc.)
        tools_path: Path to tool definitions file
        registry_path: Path to service registry JSON
    """

    # Determine server name from output path if not provided
    if not server_name:
        output_parts = Path(output_path).parts
        for part in output_parts:
            if part.startswith('mcp_'):
                server_name = part[4:]  # Remove 'mcp_' prefix
                break
        if not server_name:
            server_name = 'server'

    # Find registry file if not provided
    if not registry_path:
        registry_path = find_registry_file(server_name)
        if not registry_path:
            raise ValueError(f"Could not find registry file for server: {server_name}")

    # Find tools file if not provided and tools not passed
    if not tools:
        if not tools_path:
            tools_path = find_tools_file(server_name)
            if not tools_path:
                raise ValueError(f"Could not find tool definitions for server: {server_name}")
        tools = load_tool_definitions(tools_path)

    # Load registry
    print(f"Loading registry from: {registry_path}")
    registry = load_registry(registry_path)

    # Use universal template if not specified
    if not template_path or not Path(template_path).exists():
        template_path = str(SCRIPT_DIR / "universal_server_template.jinja2")

    # Prepare context
    context = prepare_context(registry, tools, server_name)

    # Setup Jinja2
    template_dir = os.path.dirname(template_path)
    env = Environment(loader=FileSystemLoader(template_dir))
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
    print(f"  - Services: {len(context['services'])}")
    print(f"  - Tools mapped: {len(context['tools'])}")
    if context['param_types']:
        print(f"  - Parameter types: {', '.join(context['param_types'])}")


def find_registry_file(server_name: str) -> Optional[str]:
    """Find registry file for a given server"""
    registry_path = PROJECT_ROOT / "mcp_editor" / "mcp_service_registry" / f"registry_{server_name}.json"

    if registry_path.exists():
        return str(registry_path)

    return None


def find_tools_file(server_name: str) -> Optional[str]:
    """Find tool definitions file for a given server"""
    candidates = [
        PROJECT_ROOT / "mcp_editor" / server_name / "tool_definition_templates.py",
        PROJECT_ROOT / "mcp_editor" / "tool_definition_templates.py",
        PROJECT_ROOT / f"mcp_{server_name}" / "tool_definitions.py",
        PROJECT_ROOT / f"mcp_{server_name}" / "mcp_server" / "tool_definitions.py",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


# Compatibility functions for web editor
def load_tool_definitions(tool_def_path: str) -> List[Dict[str, Any]]:
    """Compatibility wrapper for loading tool definitions"""
    path = Path(tool_def_path)

    if path.suffix == '.json':
        with open(path, 'r') as f:
            data = json.load(f)
            return data.get('MCP_TOOLS', data)
    elif path.suffix == '.py':
        import ast

        with open(path, 'r') as f:
            tree = ast.parse(f.read())

        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == 'MCP_TOOLS':
                        if isinstance(node.value, ast.Call):
                            func = node.value.func
                            if hasattr(func, 'attr') and func.attr == 'loads':
                                if node.value.args and isinstance(node.value.args[0], ast.Constant):
                                    return json.loads(node.value.args[0].value)
                        return ast.literal_eval(node.value)

            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == 'MCP_TOOLS':
                    if isinstance(node.value, ast.Call):
                        func = node.value.func
                        if hasattr(func, 'attr') and func.attr == 'loads':
                            if node.value.args and isinstance(node.value.args[0], ast.Constant):
                                return json.loads(node.value.args[0].value)
                    return ast.literal_eval(node.value)

        raise ValueError("Could not find MCP_TOOLS in the Python file")
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")


def main():
    parser = argparse.ArgumentParser(
        description='Universal MCP server generator using registry data'
    )

    parser.add_argument(
        '--server', '-s',
        help='Server name (outlook, file_handler, etc.)'
    )

    parser.add_argument(
        '--registry', '-r',
        help='Path to service registry JSON (auto-detected if not provided)'
    )

    parser.add_argument(
        '--tools', '-t',
        help='Path to tool definitions file (auto-detected if not provided)'
    )

    parser.add_argument(
        '--template', '-p',
        help='Path to Jinja2 template (default: universal_server_template.jinja2)'
    )

    parser.add_argument(
        '--output', '-o',
        required=True,
        help='Output path for generated server.py'
    )

    parser.add_argument(
        '--backup', '-b',
        action='store_true',
        help='Create backup if output file exists'
    )

    args = parser.parse_args()

    # Determine server name
    server_name = args.server
    if not server_name:
        # Try to infer from output path
        output_parts = Path(args.output).parts
        for part in output_parts:
            if part.startswith('mcp_'):
                server_name = part[4:]
                break
        if not server_name:
            print("[ERROR] Could not determine server name. Please specify with --server")
            sys.exit(1)

    # Find registry file
    registry_path = args.registry
    if not registry_path:
        registry_path = find_registry_file(server_name)
        if not registry_path:
            print(f"[ERROR] Could not find registry file for server: {server_name}")
            print(f"   Please specify with --registry option")
            print(f"   Or generate it using: python -m mcp_editor.mcp_service_registry.scanner --server {server_name}")
            sys.exit(1)

    # Find tools file
    tools_path = args.tools
    if not tools_path:
        tools_path = find_tools_file(server_name)
        if not tools_path:
            print(f"[ERROR] Could not find tool definitions for server: {server_name}")
            print(f"   Please specify with --tools option")
            sys.exit(1)

    # Get template path
    template_path = args.template
    if not template_path:
        template_path = str(SCRIPT_DIR / "universal_server_template.jinja2")

    # Check if template exists
    if not Path(template_path).exists():
        print(f"[ERROR] Template file not found: {template_path}")
        sys.exit(1)

    # Create backup if requested
    output_path = Path(args.output)
    if args.backup and output_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = output_path.parent / f"{output_path.stem}_backup_{timestamp}{output_path.suffix}"
        import shutil
        shutil.copy2(output_path, backup_path)
        print(f"[BACKUP] Created backup: {backup_path}")

    # Generate server
    try:
        generate_server(
            template_path=template_path,
            output_path=str(output_path),
            server_name=server_name,
            tools_path=tools_path,
            registry_path=registry_path
        )
    except Exception as e:
        print(f"[ERROR] Error generating server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()