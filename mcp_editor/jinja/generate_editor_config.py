#!/usr/bin/env python3
"""
Generate editor_config.json automatically from @mcp_service decorators

This script scans the codebase for @mcp_service decorators, extracts server_name values,
and automatically generates an editor_config.json file with appropriate profiles using Jinja2 templates.
"""

import ast
import os
import json
from pathlib import Path
from typing import List, Dict, Any, Set
from jinja2 import Environment, FileSystemLoader

# Import scan functions from generate_universal_server
try:
    from generate_universal_server import scan_types_files, scan_service_files
except ImportError:
    # Fallback if running from different directory
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from generate_universal_server import scan_types_files, scan_service_files


def extract_server_name_from_file(file_path: str) -> Set[str]:
    """Extract all server_name values from @mcp_service decorators in a Python file"""
    server_names = set()

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Check if function has @mcp_service decorator
                for decorator in node.decorator_list:
                    decorator_name = None

                    # Handle simple decorator: @mcp_service
                    if isinstance(decorator, ast.Name):
                        decorator_name = decorator.id
                    # Handle decorator with args: @mcp_service(...)
                    elif isinstance(decorator, ast.Call):
                        if isinstance(decorator.func, ast.Name):
                            decorator_name = decorator.func.id

                    if decorator_name == 'mcp_service':
                        # Extract server_name from decorator arguments
                        if isinstance(decorator, ast.Call):
                            for keyword in decorator.keywords:
                                if keyword.arg == 'server_name' and isinstance(keyword.value, ast.Constant):
                                    server_name = keyword.value.value
                                    if server_name:
                                        server_names.add(server_name)
                                        print(f"  Found server_name='{server_name}' in {file_path}")

    except Exception as e:
        print(f"Error processing {file_path}: {e}")

    return server_names


def scan_codebase_for_servers(base_dir: str) -> Set[str]:
    """Scan entire codebase for @mcp_service decorators and extract server names"""
    all_server_names = set()

    print(f"Scanning codebase in: {base_dir}")

    for py_file in Path(base_dir).rglob("*.py"):
        # Skip venv, __pycache__, and other non-source directories
        if any(part in str(py_file) for part in ['venv', '__pycache__', '.git', '.claude', 'node_modules', 'backups']):
            continue

        server_names = extract_server_name_from_file(str(py_file))
        all_server_names.update(server_names)

    return all_server_names


def detect_module_paths(server_name: str, base_dir: str) -> Dict[str, Any]:
    """
    Detect appropriate file paths for a server based on naming conventions

    Looks for patterns like:
    - mcp_{server_name}/
    - {server_name}_mcp/
    - mcp{server_name}/
    """
    possible_patterns = [
        f"mcp_{server_name}",
        f"{server_name}_mcp",
        f"mcp{server_name}",
        server_name
    ]

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

    # Auto-scan for types and service files using recursive glob
    source_dir = f"../{module_dir}"
    types_files = scan_types_files(source_dir)
    service_files = scan_service_files(source_dir)

    if types_files:
        print(f"    [DIR] Types files ({len(types_files)}):")
        for f in types_files:
            print(f"        - {f}")
    else:
        print(f"    No types file found for {server_name}")

    if service_files:
        print(f"    [DIR] Service files ({len(service_files)}):")
        for f in service_files:
            print(f"        - {f}")

    return {
        "template_definitions_path": f"mcp_{server_name}/tool_definition_templates.yaml",
        "tool_definitions_path": f"../{mcp_server_dir}/tool_definitions.py",
        "backup_dir": f"mcp_{server_name}/backups",
        "types_files": types_files,
        "service_files": service_files,
        "host": "0.0.0.0",
        "port": 8091
    }


def load_existing_config(config_path: str) -> Dict[str, Any]:
    """Load existing editor_config.json if it exists"""
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: Could not load existing config: {e}")
            return {}
    return {}


def merge_configs(existing_config: Dict[str, Any], new_config: Dict[str, Any],
                  discovered_servers: Set[str]) -> Dict[str, Any]:
    """
    Merge new auto-generated config with existing one.

    Merge Strategy:
    1. Include all newly discovered server profiles
    2. Preserve existing profiles that are NOT in the discovered set (reused profiles)
    3. Preserve custom values (port, host) for discovered servers if they exist

    Args:
        existing_config: Current editor_config.json content
        new_config: Newly generated config dict
        discovered_servers: Set of server names from @mcp_service decorators

    Returns:
        Merged configuration dict
    """
    merged = {}

    # 1. Add all newly discovered servers (from auto-generation)
    merged.update(new_config)

    # 2. Preserve existing profiles not in discovered set (these are reused profiles)
    preserved_count = 0
    for profile_name, profile_config in existing_config.items():
        if profile_name not in discovered_servers:
            # This is a reused or manually added profile - preserve it
            merged[profile_name] = profile_config
            preserved_count += 1
            print(f"    [KEEP] Preserved reused profile: {profile_name}")

    # 3. For discovered servers, preserve custom values (port, host) if they differ
    for server_name in discovered_servers:
        if server_name in existing_config and server_name in merged:
            existing_profile = existing_config[server_name]
            # Preserve custom port if it was changed from default
            if 'port' in existing_profile and existing_profile['port'] != 8091:
                merged[server_name]['port'] = existing_profile['port']
                print(f"    [KEEP] Preserved custom port for {server_name}: {existing_profile['port']}")
            # Preserve custom host if it was changed
            if 'host' in existing_profile and existing_profile['host'] != "0.0.0.0":
                merged[server_name]['host'] = existing_profile['host']
                print(f"    [KEEP] Preserved custom host for {server_name}: {existing_profile['host']}")

    if preserved_count > 0:
        print(f"    Total preserved profiles: {preserved_count}")

    return merged


def generate_editor_config(server_names: Set[str], base_dir: str, output_path: str, template_path: str):
    """
    Generate editor_config.json with profiles for each discovered server using Jinja2 template.

    Uses merge strategy to preserve existing reused profiles and custom values.

    Args:
        server_names: Set of server names discovered from @mcp_service decorators
        base_dir: Base directory of the project
        output_path: Path where editor_config.json will be saved
        template_path: Path to the Jinja2 template file
    """
    # Load existing config for merging
    existing_config = load_existing_config(output_path)

    # Prepare data for template
    default_server_name = sorted(server_names)[0] if server_names else "outlook"
    default_server_config = detect_module_paths(default_server_name, base_dir)
    default_server_config['name'] = default_server_name

    print(f"\nGenerating profiles for {len(server_names)} server(s):")

    # Prepare server configurations
    servers = []
    for server_name in sorted(server_names):
        print(f"  - {server_name}")
        server_config = detect_module_paths(server_name, base_dir)
        server_config['name'] = server_name
        servers.append(server_config)

    # Load Jinja2 template
    template_dir = os.path.dirname(template_path)
    template_file = os.path.basename(template_path)

    env = Environment(
        loader=FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True
    )
    template = env.get_template(template_file)

    # Render template
    rendered_content = template.render(
        default_server=default_server_config,
        servers=servers
    )

    # Parse rendered content as JSON for merging
    try:
        new_config = json.loads(rendered_content)
    except json.JSONDecodeError as e:
        print(f"  Error: Failed to parse generated config: {e}")
        # Fallback: write rendered content directly (no merge)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(rendered_content)
        print(f"\n[OK] Generated {output_path} (without merge)")
        return

    # Merge with existing config to preserve reused profiles
    if existing_config:
        print(f"\n  Merging with existing config ({len(existing_config)} profiles)...")
        merged_config = merge_configs(existing_config, new_config, server_names)
    else:
        merged_config = new_config

    # Write merged config file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(merged_config, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Generated {output_path}")
    print(f"  Total profiles: {len(merged_config)}")
    print(f"  Profiles: {', '.join(sorted(merged_config.keys()))}")


def main():
    """Main entry point"""
    # Determine project root (parent of jinja directory)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    print("=" * 60)
    print("Generate editor_config.json from @mcp_service decorators")
    print("=" * 60)
    print()

    # Scan codebase for server names
    server_names = scan_codebase_for_servers(project_root)

    if not server_names:
        print("\n[WARN] No server_name values found in @mcp_service decorators")
        print("  Creating default config with 'outlook' server")
        server_names = {"outlook"}

    print(f"\nDiscovered {len(server_names)} unique server name(s):")
    for name in sorted(server_names):
        print(f"  - {name}")

    # Generate config in mcp_editor directory
    config_output_path = os.path.join(project_root, "mcp_editor", "editor_config.json")

    # Template path
    template_path = os.path.join(script_dir, "editor_config_template.jinja2")

    if not os.path.exists(template_path):
        print(f"\n[ERROR] Error: Template file not found: {template_path}")
        return

    # Backup existing config if it exists
    if os.path.exists(config_output_path):
        backup_path = config_output_path + ".backup"
        import shutil
        shutil.copy2(config_output_path, backup_path)
        print(f"\n[BACKUP] Backed up existing config to: {backup_path}")

    # Generate new config using template
    generate_editor_config(server_names, project_root, config_output_path, template_path)

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
