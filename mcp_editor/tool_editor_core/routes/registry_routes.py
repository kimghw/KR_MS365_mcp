"""
Registry Routes

레지스트리 및 MCP 서비스 API 엔드포인트:
- GET /api/registry
- GET /api/mcp-services
- GET /api/template-sources
- POST /api/template-sources/load
"""

import os
import json
import importlib.util
from datetime import datetime
from flask import request, jsonify

from . import registry_bp
from ..config import (
    BASE_DIR,
    ROOT_DIR,
    get_profile_config,
    resolve_paths,
    list_profile_names,
)
from tool_editor_web_server_mappings import get_server_name_from_profile


@registry_bp.route("/api/registry", methods=["GET"])
def get_registry():
    """API endpoint to get service registry for current profile"""
    profile = request.args.get("profile")

    # If no profile, use first available profile
    if not profile:
        profiles = list_profile_names()
        profile = profiles[0] if profiles else "mcp_outlook"

    profile_conf = get_profile_config(profile)

    # Get registry path
    registry_path = profile_conf.get("registry_path")
    if not registry_path:
        # Default to mcp_{server}/registry_{server}.json
        server_name = get_server_name_from_profile(profile) or profile.replace("mcp_", "")
        registry_path = os.path.join(BASE_DIR, f"mcp_{server_name}", f"registry_{server_name}.json")

    # Load registry file
    try:
        if os.path.exists(registry_path):
            with open(registry_path, "r", encoding="utf-8") as f:
                registry_data = json.load(f)
            return jsonify(registry_data)
        else:
            return jsonify({"error": "Registry file not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@registry_bp.route("/api/mcp-services", methods=["GET"])
def get_mcp_services():
    """Get available MCP services from registry_{server_name}.json in service_registry"""
    try:
        # Get profile parameter to determine which server
        profiles = list_profile_names()
        profile = request.args.get("profile") or (profiles[0] if profiles else "default")

        # Determine server name from profile using mappings
        server_name = get_server_name_from_profile(profile)

        # Convert server_name to registry format (mcp_outlook -> outlook, mcp_file_handler -> file_handler)
        registry_name = (
            server_name.replace("mcp_", "") if server_name and server_name.startswith("mcp_") else server_name
        )

        # Try multiple paths in order of preference
        mcp_services_path = None
        paths_to_try = []

        if registry_name:
            # Priority 1: New registry format in mcp_{server}/registry_{server}.json
            registry_path = os.path.join(BASE_DIR, f"mcp_{registry_name}", f"registry_{registry_name}.json")
            paths_to_try.append(("registry", registry_path))

            # Priority 2: Old format in server folder (mcp_editor/mcp_outlook/outlook_mcp_services.json)
            old_server_path = os.path.join(BASE_DIR, server_name, f"{registry_name}_mcp_services.json")
            paths_to_try.append(("server_folder", old_server_path))

            # Priority 3: Legacy location (mcp_editor/outlook_mcp_services.json)
            legacy_path = os.path.join(BASE_DIR, f"{registry_name}_mcp_services.json")
            paths_to_try.append(("legacy", legacy_path))

        # Try each path
        for path_type, path in paths_to_try:
            if os.path.exists(path):
                mcp_services_path = path
                print(f"Loading MCP services from {path_type}: {path}")
                break

        # If no registry found, log error
        if not mcp_services_path:
            # Check if expected registry file exists
            expected_registry = os.path.join(BASE_DIR, f"mcp_{registry_name}", f"registry_{registry_name}.json")
            error_msg = f"Registry file not found for server '{registry_name}': {expected_registry}"
            print(f"ERROR: {error_msg}")

            # Return empty services instead of trying fallback
            return jsonify({"services": [], "services_with_signatures": [], "error": error_msg})

        if mcp_services_path and os.path.exists(mcp_services_path):
            with open(mcp_services_path, "r", encoding="utf-8") as f:
                data = json.load(f)

                # Handle new registry format
                if "services" in data and isinstance(data["services"], dict):
                    # New registry format from service_registry
                    decorated = []
                    detailed = []
                    # Groups for merged profiles: class_name -> list of services
                    groups = {}

                    for service_name, service_info in data["services"].items():
                        # Add to decorated services (use service_name, not tool_name)
                        # Service name should match what's selected in the UI
                        decorated.append(service_name)

                        # Get handler info for grouping
                        handler = service_info.get("handler", {})
                        class_name = handler.get("class_name", "Unknown")
                        file_path = handler.get("file", "")

                        # Build detailed info with service_name (not tool_name)
                        service_detail = {
                            "name": service_name,  # Use service_name consistently
                            "parameters": service_info.get("parameters", []),
                            "signature": service_info.get("signature", ""),
                            "class_name": class_name,
                            "file": file_path,  # Use file path instead of module_path
                        }
                        detailed.append(service_detail)

                        # Group by class_name for merged profile dropdown
                        if class_name not in groups:
                            groups[class_name] = []
                        groups[class_name].append(service_name)

                    # Check if this is a merged profile
                    is_merged = data.get("is_merged", False)
                    source_profiles = data.get("source_profiles", [])

                    return jsonify({
                        "services": decorated,
                        "services_with_signatures": detailed,
                        "groups": groups,
                        "is_merged": is_merged,
                        "source_profiles": source_profiles
                    })
                else:
                    # Old format (backward compatibility)
                    decorated = data.get("decorated_services", [])

                    # Build signature strings from parameter metadata
                    detailed = []
                    for service in data.get("services_with_signatures", []):
                        params = service.get("parameters", [])
                        param_strings = []
                        for param in params:
                            if param.get("name") == "self":
                                continue
                            part = param.get("name", "")
                            # Use class_name for display if available (shows original Python class name)
                            display_type = param.get("class_name") or param.get("type")
                            if display_type:
                                part += f": {display_type}"
                            if param.get("default") is not None:
                                part += f" = {param['default']}"
                            param_strings.append(part)

                        detailed.append(
                            {"name": service.get("name"), "parameters": params, "signature": ", ".join(param_strings)}
                        )

                    return jsonify({"services": decorated, "services_with_signatures": detailed})
        return jsonify({"services": [], "services_with_signatures": []})
    except Exception as e:
        return jsonify({"error": str(e), "services": [], "services_with_signatures": []}), 500


@registry_bp.route("/api/template-sources", methods=["GET"])
def get_template_sources():
    """Get available template files (tool_definition_templates.py and backups) for loading"""
    try:
        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        paths = resolve_paths(profile_conf)

        sources = []

        # 1. Current template file (primary)
        template_path = paths.get("template_path")
        if template_path and os.path.exists(template_path):
            try:
                spec = importlib.util.spec_from_file_location("template", template_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                tool_count = len(getattr(module, "MCP_TOOLS", []))
                sources.append(
                    {
                        "name": "Current Template",
                        "path": template_path,
                        "type": "current",
                        "count": tool_count,
                        "modified": datetime.fromtimestamp(os.path.getmtime(template_path)).isoformat(),
                    }
                )
            except Exception as e:
                print(f"Warning: Could not read current template {template_path}: {e}")

        # 2. Backup files
        backup_dir = paths.get("backup_dir")
        if backup_dir and os.path.isdir(backup_dir):
            for filename in os.listdir(backup_dir):
                if filename.startswith("tool_definitions_") and filename.endswith(".py"):
                    filepath = os.path.join(backup_dir, filename)
                    try:
                        spec = importlib.util.spec_from_file_location("backup", filepath)
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        tool_count = len(getattr(module, "MCP_TOOLS", []))
                        sources.append(
                            {
                                "name": filename,
                                "path": filepath,
                                "type": "backup",
                                "count": tool_count,
                                "modified": datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
                            }
                        )
                    except Exception as e:
                        print(f"Warning: Could not read backup {filepath}: {e}")

        # 3. Other profile templates
        all_profiles = list_profile_names()
        current_profile_name = profile or (all_profiles[0] if all_profiles else None)
        for other_profile in all_profiles:
            if other_profile == current_profile_name:
                continue
            other_conf = get_profile_config(other_profile)
            other_paths = resolve_paths(other_conf)
            other_template = other_paths.get("template_path")
            if other_template and os.path.exists(other_template):
                try:
                    spec = importlib.util.spec_from_file_location("other", other_template)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    tool_count = len(getattr(module, "MCP_TOOLS", []))
                    sources.append(
                        {
                            "name": f"{other_profile} template",
                            "path": other_template,
                            "type": "other_profile",
                            "profile": other_profile,
                            "count": tool_count,
                            "modified": datetime.fromtimestamp(os.path.getmtime(other_template)).isoformat(),
                        }
                    )
                except Exception as e:
                    print(f"Warning: Could not read {other_profile} template: {e}")

        # Sort: current first, then by modified date descending
        sources.sort(
            key=lambda x: (0 if x["type"] == "current" else 1, x.get("modified", ""), x["name"]), reverse=False
        )

        return jsonify({"sources": sources})
    except Exception as e:
        return jsonify({"error": str(e), "sources": []}), 500


@registry_bp.route("/api/template-sources/load", methods=["POST"])
def load_from_template_source():
    """Load MCP_TOOLS from a specific template file"""
    try:
        data = request.json or {}
        source_path = data.get("path")

        if not source_path:
            return jsonify({"error": "path is required"}), 400

        if not os.path.exists(source_path):
            return jsonify({"error": f"File not found: {source_path}"}), 404

        # Security check - only allow .py files in expected directories
        abs_source = os.path.abspath(source_path)
        abs_editor = os.path.abspath(BASE_DIR)
        abs_root = os.path.abspath(ROOT_DIR)

        if not (abs_source.startswith(abs_editor) or abs_source.startswith(abs_root)):
            return jsonify({"error": "Access denied: path outside allowed directories"}), 403

        if not source_path.endswith(".py"):
            return jsonify({"error": "Only .py files are allowed"}), 400

        # Load MCP_TOOLS from the file
        spec = importlib.util.spec_from_file_location("source_template", source_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tools = getattr(module, "MCP_TOOLS", [])

        return jsonify({"success": True, "tools": tools, "source": source_path, "count": len(tools)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
