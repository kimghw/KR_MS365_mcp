"""
Flask Application Factory

MCP Tool Editor Web 인터페이스의 Flask 애플리케이션을 생성합니다.
"""

import os
import sys

from flask import Flask
from flask_cors import CORS

# Add mcp_editor to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def create_app():
    """Create and configure the Flask application"""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates'),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'),
    )
    CORS(app)

    # Register all blueprints
    from .routes import register_routes
    register_routes(app)

    return app


def run_app():
    """Run the Flask application"""
    import subprocess
    from .config import get_profile_config, resolve_paths, ensure_dirs
    from .service_registry import scan_all_registries

    print("Starting MCP Tool Editor Web Interface...")

    # Auto-generate editor_config.json with types/service files scan
    print("Generating editor_config.json from @mcp_service decorators...")
    # jinja is now inside mcp_editor (not ROOT_DIR)
    jinja_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "jinja")
    generate_config_script = os.path.join(jinja_dir, "generate_editor_config.py")
    if os.path.exists(generate_config_script):
        try:
            result = subprocess.run(
                [sys.executable, generate_config_script],
                capture_output=True,
                text=True,
                cwd=jinja_dir
            )
            if result.returncode == 0:
                print("[OK] editor_config.json updated successfully")
            else:
                print(f"[WARN] Config generation warning: {result.stderr[:200] if result.stderr else 'Unknown'}")
        except Exception as e:
            print(f"[WARN] Could not auto-generate config: {e}")
    else:
        print(f"[WARN] generate_editor_config.py not found at {generate_config_script}")

    # Scan all registries on startup
    print("Scanning MCP service registries...")
    scan_all_registries()

    profile_name = os.environ.get("MCP_EDITOR_MODULE")
    profile_conf = get_profile_config(profile_name)
    paths = resolve_paths(profile_conf)
    ensure_dirs(paths)
    host = paths.get("host", "127.0.0.1")
    port = paths.get("port", 8091)
    print(f"Active profile: {profile_name or '_default'}")
    print(f"Access the editor at: http://{host}:{port}")
    print("Press Ctrl+C to stop the server")

    app = create_app()
    app.run(debug=True, host=host, port=port)


if __name__ == "__main__":
    run_app()
