"""
Flask Application Factory

MCP Tool Editor Web 인터페이스의 Flask 애플리케이션을 생성합니다.
"""

import os
import sys

from flask import Flask

# Add mcp_editor to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# mcp_common(공통 기반)은 프로젝트 루트에 있으므로 함께 올린다
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_TRUTHY = {"1", "true", "yes", "on"}

# 에디터 UI 기본 포트.
# port SSOT(.claude/skills/port_manager/port_list.md)의 "MCP Tool Editor = 8091" 과 일치.
# 프로필 포트(editor_config.json 의 port, 5001~5008)는 "관리 대상 자식 서버"의 포트이고,
# 에디터 UI 는 반드시 그와 분리된 자체 포트로 떠야 한다.
DEFAULT_EDITOR_PORT = 8091


def _is_truthy(value) -> bool:
    """환경변수 옵트인 판정"""
    return bool(value) and str(value).strip().lower() in _TRUTHY


def _editor_port() -> int:
    """
    에디터 UI 바인드 포트 결정: MCP_EDITOR_PORT 환경변수 > 기본 8091.

    (구버전은 활성 프로필의 port 로 바인드했다. 예: Outlook 프로필이면 5001.
     그러면 에디터가 관리 대상 서버의 포트를 선점해 버려서, 대시보드에서
     그 프로필 서버를 기동하면 address-in-use 로 실패했다. 에디터 UI 포트와
     관리 대상 서버 포트를 분리하기 위해 프로필 포트 바인드를 제거했다.)
    """
    raw = str(os.environ.get("MCP_EDITOR_PORT", "")).strip()
    if not raw:
        return DEFAULT_EDITOR_PORT
    try:
        return int(raw)
    except ValueError:
        print(
            f"[WARN] MCP_EDITOR_PORT={raw!r} 는 정수가 아닙니다. "
            f"기본 포트 {DEFAULT_EDITOR_PORT} 를 사용합니다."
        )
        return DEFAULT_EDITOR_PORT


def _configure_cors(app):
    """
    CORS 설정 (기본: 비활성화).

    에디터 UI 는 서버와 같은 오리진에서 동작하므로 CORS 가 필요 없다.
    반면 전역 허용(`CORS(app)`)은 사용자가 방문한 아무 웹페이지나
    로컬 에디터 API(프로필 생성/삭제, 서버 기동, 파일 쓰기)를 호출할 수 있게 만든다.

    별도 오리진에서 호출해야 하면 MCP_EDITOR_CORS_ORIGINS 에 오리진을
    콤마로 나열해 명시적으로 옵트인한다.
        예) MCP_EDITOR_CORS_ORIGINS=http://127.0.0.1:3000
    """
    origins_raw = os.environ.get("MCP_EDITOR_CORS_ORIGINS", "").strip()
    if not origins_raw:
        return

    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    if not origins:
        return

    if "*" in origins:
        print("[WARN] MCP_EDITOR_CORS_ORIGINS='*' 는 허용하지 않습니다. CORS 를 비활성화합니다.")
        return

    try:
        from flask_cors import CORS
    except ImportError:
        print("[WARN] flask_cors 미설치 - MCP_EDITOR_CORS_ORIGINS 를 무시합니다")
        return

    CORS(app, origins=origins, supports_credentials=False)
    print(f"[WARN] CORS 활성화됨 (허용 오리진: {', '.join(origins)})")


def create_app():
    """Create and configure the Flask application"""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates'),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'),
    )
    _configure_cors(app)

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

    from mcp_common.net import resolve_bind_host

    profile_name = os.environ.get("MCP_EDITOR_MODULE")
    profile_conf = get_profile_config(profile_name)
    paths = resolve_paths(profile_conf)
    ensure_dirs(paths)

    # 바인드 호스트: MCP_BIND_HOST > 프로필 host > 127.0.0.1.
    # 에디터는 호출자 인증이 없으므로 public 주소는 MCP_ALLOW_PUBLIC_BIND=1 옵트인이 없으면
    # resolve_bind_host() 가 loopback 으로 강등한다.
    host = resolve_bind_host(
        os.environ.get("MCP_BIND_HOST") or paths.get("host"),
        server_name="editor",
    )
    # 에디터 UI 포트는 프로필 포트(관리 대상 서버 포트)와 분리한다.
    # 자식 서버 기동 시에는 mcp_server_controller 가 editor_config.json 의
    # 프로필 포트(5001~5008)를 MCP_SERVER_PORT 로 계속 전달한다.
    port = _editor_port()

    # 디버거는 임의 코드 실행 콘솔을 노출하므로 기본 비활성화, MCP_EDITOR_DEBUG 로만 옵트인
    debug = _is_truthy(os.environ.get("MCP_EDITOR_DEBUG"))

    print(f"Active profile: {profile_name or '_default'}")
    if paths.get("port"):
        print(f"Managed server port for active profile: {paths['port']} (child servers only)")
    print(f"Access the editor at: http://{host}:{port}")
    if debug:
        print("[WARN] MCP_EDITOR_DEBUG 활성화 - Werkzeug 디버거가 열립니다 (로컬 개발 전용)")
    print("Press Ctrl+C to stop the server")

    app = create_app()
    app.run(debug=debug, host=host, port=port)


if __name__ == "__main__":
    run_app()
