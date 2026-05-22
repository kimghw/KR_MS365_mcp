#!/usr/bin/env python3
"""
Generate MCP server for File Handler from template
Reads service definitions and generates server.py
"""
import os
import sys
import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# Add parent to path for imports
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

def load_tool_definitions():
    """Load tool definitions from mcp_editor"""
    editor_dir = parent_dir / 'mcp_editor'

    # Try to load from template file first (has metadata)
    template_file = editor_dir / 'tool_definition_file_handler_templates.py'
    if template_file.exists():
        print(f"Loading from template file: {template_file}")
        spec = __import__('importlib.util').util.spec_from_file_location(
            "tool_definition_file_handler_templates",
            template_file
        )
        module = __import__('importlib.util').util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.MCP_TOOLS

    # Fallback to clean definitions
    definitions_file = parent_dir / 'mcp_file_handler' / 'mcp_server' / 'tool_definitions.py'
    if definitions_file.exists():
        print(f"Loading from definitions file: {definitions_file}")
        spec = __import__('importlib.util').util.spec_from_file_location(
            "tool_definitions",
            definitions_file
        )
        module = __import__('importlib.util').util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.MCP_TOOLS

    print("ERROR: No tool definitions found!")
    return []


def extract_services_from_tools(tools):
    """Extract service information from tool definitions"""
    services = {}

    for tool in tools:
        mcp_service = tool.get('mcp_service', {})
        service_name = mcp_service.get('name', tool['name'])

        # Determine which class/module provides this service
        if 'file' in tool['name'].lower() or 'directory' in tool['name'].lower() or 'metadata' in tool['name'].lower():
            services['FileManager'] = {
                'module': 'file_manager',
                'instance_name': 'file_manager',
                'class_name': 'FileManager'
            }

        if 'metadata' in tool['name'].lower():
            services['MetadataManager'] = {
                'module': 'metadata.manager',
                'instance_name': 'metadata_manager',
                'class_name': 'MetadataManager'
            }

    return services


def generate_server(replace=False):
    """Generate server.py from template"""

    # Setup Jinja2 environment
    template_dir = Path(__file__).parent
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # Load template
    template = env.get_template('file_handler_server_template.jinja2')

    # Load tool definitions
    tools = load_tool_definitions()
    if not tools:
        print("No tools found, cannot generate server")
        return False

    # Extract service information
    services = extract_services_from_tools(tools)

    print(f"\nFound {len(tools)} tools")
    print(f"Services required: {list(services.keys())}")

    # Render template
    rendered = template.render(
        services=services,
        tools=tools
    )

    # Output path
    output_dir = parent_dir / 'mcp_file_handler' / 'mcp_server'
    output_file = output_dir / 'server.py'

    # Create backup if exists
    if output_file.exists():
        backup_dir = output_dir / 'backups'
        backup_dir.mkdir(exist_ok=True)

        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_dir / f'server_backup_{timestamp}.py'

        import shutil
        shutil.copy2(output_file, backup_file)
        print(f"Backup created: {backup_file}")

    # Check if should replace
    if output_file.exists() and not replace:
        print(f"\nServer file exists: {output_file}")
        print("Use --replace flag to overwrite")
        return False

    # Write output
    output_file.write_text(rendered)
    print(f"\nServer generated: {output_file}")

    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Generate File Handler MCP server from template')
    parser.add_argument('--replace', action='store_true', help='Replace existing server.py')

    args = parser.parse_args()

    success = generate_server(replace=args.replace)

    if success:
        print("\n[OK] Server generation completed successfully")
    else:
        print("\n[FAIL] Server generation failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
