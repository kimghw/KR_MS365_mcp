"""
Generator Routes

서버 생성 API 엔드포인트:
- GET /api/server-generator/defaults
- POST /api/server-generator
- POST /api/create-mcp-project
- POST /api/scaffold/create
- POST /api/scaffold/check
"""

import os
import sys
from pathlib import Path
from flask import request, jsonify

from . import generator_bp
from ..config import (
    BASE_DIR,
    ROOT_DIR,
    JINJA_DIR,
    get_profile_config,
    resolve_paths,
    list_profile_names,
    discover_mcp_modules,
    load_generator_module,
    _default_generator_paths,
    _guess_server_name,
    _get_template_for_server,
    _resolve_path,
)
from tool_editor_web_server_mappings import get_server_name_from_profile, get_server_name_from_path


@generator_bp.route("/api/server-generator/defaults", methods=["GET"])
def get_server_generator_defaults():
    """Expose detected modules and default paths for the Jinja2 server generator"""
    try:
        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        modules = discover_mcp_modules(profile_conf)
        fallback = _default_generator_paths(profile_conf, profile)
        preferred_server = _guess_server_name(profile_conf, profile)
        active_module = None

        if preferred_server:
            for mod in modules:
                mod_server = (
                    mod.get("server_name")
                    or get_server_name_from_path(mod.get("mcp_dir", ""))
                    or get_server_name_from_profile(mod.get("name", ""))
                )
                if mod_server == preferred_server:
                    active_module = mod.get("name")
                    break

        if not active_module and modules:
            active_module = modules[0]["name"]

        return jsonify(
            {"modules": modules, "fallback": fallback, "active_module": active_module, "server_name": preferred_server}
        )
    except Exception as e:
        return jsonify({"error": str(e), "modules": [], "fallback": {}}), 500


@generator_bp.route("/api/create-mcp-project", methods=["POST"])
def create_new_mcp_project():
    """Create a new MCP server project using create_mcp_project.py"""
    try:
        data = request.json or {}
        service_name = data.get("service_name", "").lower()
        description = data.get("description", "")
        port = data.get("port", 8080)
        author = data.get("author", "")
        include_types = data.get("include_types", True)

        if not service_name:
            return jsonify({"error": "service_name is required"}), 400

        # Validate service name
        if not service_name.replace("_", "").isalnum():
            return jsonify({"error": "Service name should only contain letters, numbers, and underscores"}), 400

        # Check if project already exists
        project_dir = os.path.join(ROOT_DIR, f"mcp_{service_name}")
        if os.path.exists(project_dir):
            return jsonify({"error": f"Project mcp_{service_name} already exists"}), 400

        # Import and use create_mcp_project module
        sys.path.insert(0, JINJA_DIR)
        from create_mcp_project import MCPProjectCreator

        creator = MCPProjectCreator(base_dir=ROOT_DIR)
        result = creator.create_project(
            service_name=service_name, description=description, port=port, author=author, include_types=include_types
        )

        if result.get("errors"):
            return jsonify({"error": f"Project creation failed: {', '.join(result['errors'])}"}), 500

        # Reload profiles after creating new project
        from ..config import list_profile_names
        profiles = list_profile_names()

        return jsonify(
            {
                "success": True,
                "service_name": service_name,
                "project_dir": f"mcp_{service_name}",
                "created_files": len(result.get("created_files", [])),
                "message": f"Successfully created MCP project: {service_name}",
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/api/server-generator", methods=["POST"])
def generate_server_from_web():
    """Run the Jinja2 server generator with paths provided by the web editor"""
    try:
        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        modules = discover_mcp_modules(profile_conf)
        defaults = _default_generator_paths(profile_conf, profile)

        data = request.json or {}
        module_name = data.get("module")
        selected_module = next((m for m in modules if m.get("name") == module_name), None)
        server_name = data.get("server_name") or get_server_name_from_profile(profile)
        if not server_name and selected_module:
            server_name = get_server_name_from_path(selected_module.get("mcp_dir", ""))

        tools_path = data.get("tools_path") or (
            selected_module["tools_path"] if selected_module else defaults["tools_path"]
        )
        template_path = data.get("template_path") or (
            selected_module["template_path"] if selected_module else defaults["template_path"]
        )
        output_path = data.get("output_path") or (
            selected_module["output_path"] if selected_module else defaults["output_path"]
        )

        if not server_name:
            for candidate_path in (tools_path, template_path, output_path):
                if candidate_path:
                    server_name = get_server_name_from_path(str(candidate_path))
                    if server_name:
                        break

        if not template_path:
            template_path = _get_template_for_server(server_name)

        if not tools_path:
            return jsonify({"error": "tools_path is required"}), 400
        if not template_path:
            return jsonify({"error": "template_path is required"}), 400
        if not output_path:
            return jsonify({"error": "output_path is required"}), 400

        def resolve_for_generator(path_value: str) -> str:
            """Resolve a provided path against both editor and repo roots"""
            if os.path.isabs(path_value):
                return path_value
            editor_path = _resolve_path(path_value)
            if os.path.exists(editor_path):
                return editor_path
            return os.path.normpath(os.path.join(ROOT_DIR, path_value))

        tools_path = resolve_for_generator(tools_path)
        template_path = resolve_for_generator(template_path)
        output_path = resolve_for_generator(output_path)

        if not os.path.exists(tools_path):
            return jsonify({"error": f"Tools file not found: {tools_path}"}), 400
        if not os.path.exists(template_path):
            return jsonify({"error": f"Template file not found: {template_path}"}), 400

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        generator_module = load_generator_module()

        # Find registry file for the server
        registry_path = generator_module.find_registry_file(server_name)
        if not registry_path:
            return jsonify({"error": f"Registry file not found for server: {server_name}"}), 400

        # Generate ALL server types by default
        protocols_to_generate = ["rest", "stdio", "stream"]
        generated_files = []

        for protocol in protocols_to_generate:
            # Always use universal template for all protocols
            protocol_template_path = template_path

            # Determine output file for this protocol
            output_base = Path(output_path)
            if output_base.suffix == "" or output_base.is_dir():
                # Output is a directory
                if protocol == "rest":
                    filename = "server_rest.py"
                else:
                    filename = f"server_{protocol}.py"
                protocol_output_path = str(output_base / filename)
            else:
                # Output is a file - generate protocol-specific files
                base = output_base.stem
                ext = output_base.suffix
                if protocol == "rest":
                    filename = f"{base}_rest{ext}"
                else:
                    filename = f"{base}_{protocol}{ext}"
                protocol_output_path = str(output_base.parent / filename)

            # Generate this protocol's server
            # Get port from profile config
            server_port = profile_conf.get("port", 8080)
            generator_module.generate_server(
                template_path=protocol_template_path,
                output_path=protocol_output_path,
                registry_path=registry_path,
                tools_path=tools_path,
                server_name=server_name,
                protocol_type=protocol,
                port=server_port,
            )
            generated_files.append(protocol_output_path)

        # Count tools for response
        loaded_tools = generator_module.load_tool_definitions(tools_path)

        return jsonify(
            {
                "success": True,
                "module": module_name,
                "tools_path": tools_path,
                "template_path": template_path,
                "output_path": output_path,
                "registry_path": registry_path,
                "tool_count": len(loaded_tools),
                "generated_files": generated_files,
                "protocols": protocols_to_generate,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/api/scaffold/create", methods=["POST"])
def create_new_server():
    """Create a new MCP server project from scratch"""
    try:
        data = request.json
        server_name = data.get("server_name", "").strip()
        description = data.get("description", "").strip()
        port = data.get("port", 8080)

        # Validation
        if not server_name:
            return jsonify({"error": "Server name is required"}), 400

        # Check if server already exists
        server_dir = os.path.join(ROOT_DIR, f"mcp_{server_name}")
        if os.path.exists(server_dir):
            return jsonify({"error": f"Server 'mcp_{server_name}' already exists"}), 409

        # Import scaffold generator
        scaffold_path = os.path.join(JINJA_DIR, "scaffold_generator.py")
        if not os.path.exists(scaffold_path):
            return jsonify({"error": f"scaffold_generator.py not found at {scaffold_path}"}), 500
        sys.path.insert(0, JINJA_DIR)
        from scaffold_generator import MCPServerScaffold

        # Create the server
        generator = MCPServerScaffold(ROOT_DIR)
        result = generator.create_server_project(
            server_name=server_name,
            description=description,
            port=port,
            create_venv=False,  # Don't create venv in web context
        )

        if result.get("errors"):
            return jsonify({"error": "Server created with errors", "details": result}), 500

        return jsonify(
            {
                "success": True,
                "message": f"Successfully created MCP server: {server_name}",
                "server_name": server_name,
                "created_files": result["created_files"],
                "created_dirs": result["created_dirs"],
                "next_steps": [
                    f"cd mcp_{server_name}/mcp_server",
                    "python -m venv venv && source venv/bin/activate",
                    "pip install fastapi uvicorn pydantic",
                    f"Select '{server_name}' profile in web editor",
                ],
            }
        )

    except Exception as e:
        import traceback

        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@generator_bp.route("/api/scaffold/check", methods=["POST"])
def check_server_exists():
    """Check if a server name is available"""
    try:
        data = request.json
        server_name = data.get("server_name", "").strip()

        if not server_name:
            return jsonify({"valid": False, "error": "Server name is required"}), 400

        # Check naming rules
        if not server_name.replace("_", "").isalnum():
            return (
                jsonify({"valid": False, "error": "Server name must contain only letters, numbers, and underscores"}),
                400,
            )

        # Check if exists
        server_dir = os.path.join(ROOT_DIR, f"mcp_{server_name}")
        exists = os.path.exists(server_dir)

        return jsonify({"valid": not exists, "exists": exists, "server_name": server_name, "path": server_dir})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
