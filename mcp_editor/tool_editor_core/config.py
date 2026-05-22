"""
Configuration Management Module

설정 관리 함수들:
- 경로 해석 및 프로필 로딩
- 모듈 탐색 및 제너레이터 로딩
"""

import json
import os
import sys
import importlib.util

# Import server name mappings
from tool_editor_web_server_mappings import get_server_name_from_profile, get_server_name_from_path

# === Constants ===

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.environ.get("MCP_EDITOR_ROOT", os.path.dirname(BASE_DIR))
CONFIG_PATH = os.path.join(BASE_DIR, "editor_config.json")

DEFAULT_PROFILE = {
    "template_definitions_path": "tool_definition_templates.py",
    "tool_definitions_path": "../mcp_outlook/mcp_server/tool_definitions.py",
    "backup_dir": "backups",
    "types_files": ["../mcp_outlook/outlook_types.py"],
    "host": "127.0.0.1",
    "port": 8091,
}

# Extended Profile Schema (Phase 1: 파생 서버 지원)
PROFILE_SCHEMA = {
    # 기본 필드
    "source_dir": str,              # 서비스 소스 경로
    "template_definitions_path": str,
    "tool_definitions_path": str,
    "backup_dir": str,
    "types_files": list,
    "host": str,
    "port": int,
    # 파생 서버 관련 필드 (신규)
    "is_base": bool,                # base 서버 여부 (기본: True)
    "base_profile": str,            # 파생 시 base 프로필명 (선택)
    "derived_profiles": list,       # 파생 프로필 목록 (선택)
    "is_reused": bool,              # 기존 필드 유지 (호환성)
}

# Jinja templates directory (moved to mcp_editor/jinja/)
JINJA_DIR = os.path.join(BASE_DIR, "jinja")
JINJA_PYTHON_DIR = os.path.join(JINJA_DIR, "python")
JINJA_JS_DIR = os.path.join(JINJA_DIR, "javascript")
JINJA_COMMON_DIR = os.path.join(JINJA_DIR, "common")

SERVER_TEMPLATES = {
    "outlook": os.path.join(JINJA_PYTHON_DIR, "universal_server_template.jinja2"),
    "file_handler": os.path.join(JINJA_PYTHON_DIR, "universal_server_template.jinja2"),
    "scaffold": os.path.join(JINJA_PYTHON_DIR, "mcp_server_scaffold_template.jinja2"),
    "universal": os.path.join(JINJA_PYTHON_DIR, "universal_server_template.jinja2"),
}
DEFAULT_SERVER_TEMPLATE = SERVER_TEMPLATES["outlook"]
GENERATOR_SCRIPT_PATH = os.path.join(JINJA_DIR, "generate_universal_server.py")
EDITOR_CONFIG_TEMPLATE = os.path.join(JINJA_COMMON_DIR, "editor_config_template.jinja2")
EDITOR_CONFIG_GENERATOR = os.path.join(JINJA_DIR, "generate_editor_config.py")


# === Path Resolution Functions ===

def _resolve_path(path: str) -> str:
    """Resolve relative paths against the editor directory"""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(BASE_DIR, path))


def get_source_path_for_profile(profile_name: str, profile_config: dict | None = None) -> str:
    """
    profile_name에서 소스 경로 유추 (컨벤션 기반, 하위 호환성 지원)

    Args:
        profile_name: 프로필 이름 (e.g., "outlook", "calendar")
        profile_config: 프로필 설정 (선택, 하위 호환성용)

    Returns:
        소스 디렉토리 절대 경로

    컨벤션:
        profile_name → "../mcp_{profile_name}" (BASE_DIR 기준)

    하위 호환:
        profile_config에 source_dir가 있으면 우선 사용
    """
    # 하위 호환: 기존 source_dir 필드 존재 시 우선 사용
    if profile_config and profile_config.get("source_dir"):
        return os.path.normpath(os.path.join(BASE_DIR, profile_config["source_dir"]))

    # 컨벤션 기반 유추
    return os.path.normpath(os.path.join(BASE_DIR, f"../mcp_{profile_name}"))


def _get_config_path() -> str:
    """Allow overriding config path via MCP_EDITOR_CONFIG env"""
    env_path = os.environ.get("MCP_EDITOR_CONFIG")
    if env_path:
        return _resolve_path(env_path)
    return CONFIG_PATH


def _get_template_for_server(server_name: str | None) -> str:
    """Return the best template path for a given server name."""
    if server_name and server_name in SERVER_TEMPLATES:
        candidate = SERVER_TEMPLATES[server_name]
        if os.path.exists(candidate):
            return candidate

    for candidate in SERVER_TEMPLATES.values():
        if os.path.exists(candidate):
            return candidate

    return ""


def _guess_server_name(profile_conf: dict | None, profile_name: str | None = None) -> str | None:
    """Attempt to infer the server name from profile info or config keys."""
    if profile_name:
        guessed = get_server_name_from_profile(profile_name)
        if guessed:
            return guessed

    profile_conf = profile_conf or {}
    for key in ("template_definitions_path", "tool_definitions_path"):
        value = profile_conf.get(key)
        if isinstance(value, str):
            guessed = get_server_name_from_path(value)
            if guessed:
                return guessed

    return None


def _generate_config_from_template(config_path: str) -> dict | None:
    """
    Try to render editor_config.json using the Jinja template and generator utility.
    Falls back silently if the template or generator script is missing.
    """
    if not (os.path.exists(EDITOR_CONFIG_TEMPLATE) and os.path.exists(EDITOR_CONFIG_GENERATOR)):
        return None

    try:
        spec = importlib.util.spec_from_file_location("editor_config_generator", EDITOR_CONFIG_GENERATOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        server_names = module.scan_codebase_for_servers(ROOT_DIR)
        if not server_names:
            fallback = _guess_server_name(None, "_default") or "outlook"
            server_names = {fallback}

        module.generate_editor_config(server_names, ROOT_DIR, config_path, EDITOR_CONFIG_TEMPLATE)
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # pragma: no cover - best effort
        print(f"Warning: Could not generate editor_config.json from template: {e}")
    return None


def _load_config_file():
    config_path = _get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load editor_config.json: {e}")
        generated = _generate_config_from_template(config_path)
        if generated:
            return generated
    else:
        generated = _generate_config_from_template(config_path)
        if generated:
            return generated
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"_default": DEFAULT_PROFILE}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not write default editor_config.json: {e}")
    return {"_default": DEFAULT_PROFILE}


def _merge_profile(default_profile: dict, override_profile: dict) -> dict:
    merged = DEFAULT_PROFILE.copy()
    merged.update(default_profile or {})
    if override_profile:
        for k, v in override_profile.items():
            # Allow all string, list, int, dict values (including new keys like source_dir)
            if isinstance(v, (str, list, int, dict)):
                merged[k] = v
    return merged


# === Public Functions ===

def list_profile_names() -> list:
    data = _load_config_file()
    if isinstance(data, dict):
        # legacy single-profile dict (values not dict) -> single pseudo profile
        if all(not isinstance(v, dict) for v in data.values()):
            return ["_default"]
        return list(data.keys())
    return []


def get_profile_config(profile_name: str | None = None) -> dict:
    data = _load_config_file()
    # legacy single-profile dict
    if isinstance(data, dict) and all(not isinstance(v, dict) for v in data.values()):
        return _merge_profile({}, data)

    if isinstance(data, dict) and data:
        # If no profile specified, use first available profile
        if not profile_name:
            first_profile_name = next(iter(data.keys()))
            return _merge_profile({}, data[first_profile_name])
        # Use specified profile if exists
        if profile_name in data:
            return _merge_profile({}, data[profile_name])

    return DEFAULT_PROFILE.copy()


def resolve_paths(profile_conf: dict) -> dict:
    # 단순화: 중간 JSON 파일 제거, mcp_service_factors에 직접 저장
    return {
        "template_path": _resolve_path(profile_conf["template_definitions_path"]),
        "tool_path": _resolve_path(profile_conf["tool_definitions_path"]),
        "backup_dir": _resolve_path(profile_conf["backup_dir"]),
        "types_files": profile_conf.get(
            "types_files", profile_conf.get("graph_types_files", ["../mcp_outlook/outlook_types.py"])
        ),
        "host": profile_conf.get("host", "127.0.0.1"),
        "port": profile_conf.get("port", 8091),
    }


def _default_generator_paths(profile_conf: dict, profile_name: str | None = None) -> dict:
    """Return default generator paths for the active profile"""
    resolved = resolve_paths(profile_conf)
    output_dir = os.path.dirname(resolved["tool_path"])
    output_path = output_dir
    server_name = _guess_server_name(profile_conf, profile_name)
    template_path = _get_template_for_server(server_name)

    return {"tools_path": resolved["template_path"], "template_path": template_path, "output_path": output_path}


def discover_mcp_modules(profile_conf: dict | None = None, profile_name: str | None = None) -> list:
    """
    Detect modules that contain an MCP server folder.
    Assumes each module has the same mcp/mcp_server structure.

    For reused profiles (e.g., outlook_read), this function uses the profile name
    to determine the correct YAML path in mcp_editor/mcp_{profile_name}/.

    Args:
        profile_conf: Profile configuration dict
        profile_name: Profile name for path resolution (e.g., 'outlook_read')
    """
    modules = []
    profile_conf = profile_conf or DEFAULT_PROFILE
    fallback = _default_generator_paths(profile_conf)

    if not os.path.isdir(ROOT_DIR):
        return modules

    for entry in os.listdir(ROOT_DIR):
        module_dir = os.path.join(ROOT_DIR, entry)
        if not os.path.isdir(module_dir):
            continue

        # Look for either mcp_server or a generic mcp folder
        for candidate in ("mcp_server", "mcp"):
            mcp_dir = os.path.join(module_dir, candidate)
            if not os.path.isdir(mcp_dir):
                continue

            server_name = get_server_name_from_path(module_dir) or get_server_name_from_profile(entry)
            template_path = _get_template_for_server(server_name) or fallback["template_path"]

            # Determine the profile-specific template path
            # For reused profiles, use profile_name; otherwise use server_name
            effective_profile = profile_name or server_name
            editor_template_defs = (
                os.path.join(ROOT_DIR, "mcp_editor", f"mcp_{effective_profile}", "tool_definition_templates.py")
                if effective_profile
                else ""
            )

            # Fallback to server_name based path if profile-specific doesn't exist
            if not os.path.exists(editor_template_defs) and profile_name and server_name != profile_name:
                editor_template_defs = (
                    os.path.join(ROOT_DIR, "mcp_editor", f"mcp_{server_name}", "tool_definition_templates.py")
                    if server_name
                    else ""
                )

            tools_candidates = [
                editor_template_defs,
                os.path.join(mcp_dir, "tool_definition_templates.py"),
                os.path.join(mcp_dir, "tool_definitions.py"),
                fallback["tools_path"],
            ]
            tools_path = next((p for p in tools_candidates if p and os.path.exists(p)), fallback["tools_path"])

            modules.append(
                {
                    "name": entry,
                    "server_name": server_name,
                    "mcp_dir": mcp_dir,
                    "tools_path": tools_path,
                    "template_path": template_path,
                    "output_path": mcp_dir,
                }
            )
            break

    modules.sort(key=lambda x: x["name"].lower())
    return modules


def load_generator_module():
    """Load the Jinja2 generator module dynamically"""
    if not os.path.exists(GENERATOR_SCRIPT_PATH):
        raise FileNotFoundError(f"Generator script not found at {GENERATOR_SCRIPT_PATH}")

    spec = importlib.util.spec_from_file_location("mcp_jinja_generator", GENERATOR_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_dirs(paths: dict):
    os.makedirs(paths["backup_dir"], exist_ok=True)


# === Phase 1: 파생 서버 관련 헬퍼 함수들 ===

def get_base_profile(profile_name: str) -> str | None:
    """
    프로필의 base 프로필 반환 (없으면 None)

    Args:
        profile_name: 프로필 이름

    Returns:
        base 프로필명 또는 None (자신이 base인 경우)
    """
    config = _load_config_file()
    profile = config.get(profile_name, {})
    return profile.get("base_profile")


def get_derived_profiles(profile_name: str) -> list:
    """
    프로필의 파생 프로필 목록 반환

    Args:
        profile_name: 프로필 이름

    Returns:
        파생 프로필 목록 (없으면 빈 리스트)
    """
    config = _load_config_file()
    profile = config.get(profile_name, {})
    return profile.get("derived_profiles", [])


def get_sibling_profiles(profile_name: str) -> list:
    """
    동일 base를 공유하는 형제 프로필 목록 반환

    Args:
        profile_name: 프로필 이름

    Returns:
        형제 프로필 목록 (자신 포함, base도 포함)
    """
    config = _load_config_file()

    # 자신의 base_profile 확인
    profile = config.get(profile_name, {})
    base = profile.get("base_profile")

    # base가 없으면 자신이 base
    if not base:
        base = profile_name

    # 동일 base를 공유하는 모든 프로필 찾기
    siblings = []
    for pname, pconf in config.items():
        pbase = pconf.get("base_profile")
        # base 프로필이거나 같은 base를 공유
        if pname == base or pbase == base:
            siblings.append(pname)

    return siblings


def is_base_profile(profile_name: str) -> bool:
    """
    base 프로필 여부 확인

    Args:
        profile_name: 프로필 이름

    Returns:
        base 프로필이면 True
    """
    config = _load_config_file()
    profile = config.get(profile_name, {})

    # 명시적으로 is_base가 설정되어 있으면 그 값 사용
    if "is_base" in profile:
        return profile["is_base"]

    # base_profile이 없으면 base로 간주
    return profile.get("base_profile") is None


def get_profile_family(profile_name: str) -> dict:
    """
    프로필의 전체 가족 관계 조회

    Args:
        profile_name: 프로필 이름

    Returns:
        {
            "base": base 프로필명,
            "derived": 파생 프로필 목록,
            "current": 현재 프로필명,
            "is_base": 현재 프로필이 base인지
        }
    """
    config = _load_config_file()
    profile = config.get(profile_name, {})

    base = profile.get("base_profile") or profile_name
    is_base = is_base_profile(profile_name)

    # base의 derived_profiles 가져오기
    base_profile = config.get(base, {})
    derived = base_profile.get("derived_profiles", [])

    # derived_profiles가 없으면 동적으로 계산
    if not derived:
        for pname, pconf in config.items():
            if pconf.get("base_profile") == base and pname != base:
                derived.append(pname)

    return {
        "base": base,
        "derived": derived,
        "current": profile_name,
        "is_base": is_base
    }


def migrate_config_schema(config: dict) -> dict:
    """
    기존 설정을 새 스키마로 마이그레이션

    - is_reused=True인 프로필에 base_profile 추출
    - base 프로필에 is_base=True, derived_profiles 추가

    Args:
        config: 기존 설정 딕셔너리

    Returns:
        마이그레이션된 설정 딕셔너리
    """
    migrated = config.copy()
    derived_map = {}  # base_profile -> [derived_profiles]

    # 1단계: is_reused 프로필에서 base_profile 추론
    for profile_name, profile_conf in migrated.items():
        if not isinstance(profile_conf, dict):
            continue

        # is_reused 플래그가 있는 프로필
        if profile_conf.get("is_reused"):
            # base_profile이 이미 있으면 스킵
            if "base_profile" in profile_conf:
                base = profile_conf["base_profile"]
            else:
                # source_dir에서 base 추론
                source_dir = profile_conf.get("source_dir", "")
                if source_dir:
                    # ../mcp_outlook -> outlook
                    base = source_dir.replace("../mcp_", "").replace("./mcp_", "").strip("/")
                    profile_conf["base_profile"] = base
                else:
                    continue

            # derived_map에 추가
            if base not in derived_map:
                derived_map[base] = []
            derived_map[base].append(profile_name)

    # 2단계: base 프로필에 is_base와 derived_profiles 추가
    for base_profile, derived_list in derived_map.items():
        if base_profile in migrated:
            migrated[base_profile]["is_base"] = True
            existing_derived = migrated[base_profile].get("derived_profiles", [])
            # 중복 제거하여 병합
            all_derived = list(set(existing_derived + derived_list))
            migrated[base_profile]["derived_profiles"] = all_derived

    return migrated


def save_config_file(config: dict) -> bool:
    """
    editor_config.json에 설정 저장

    Args:
        config: 저장할 설정 딕셔너리

    Returns:
        성공 여부
    """
    try:
        config_path = _get_config_path()
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Warning: Could not save editor_config.json: {e}")
        return False


def update_derived_profiles_list(base_profile: str, derived_profile: str, add: bool = True) -> bool:
    """
    base 프로필의 derived_profiles 목록 업데이트

    Args:
        base_profile: base 프로필명
        derived_profile: 추가/제거할 파생 프로필명
        add: True=추가, False=제거

    Returns:
        성공 여부
    """
    config = _load_config_file()

    if base_profile not in config:
        return False

    derived_list = config[base_profile].get("derived_profiles", [])

    if add:
        if derived_profile not in derived_list:
            derived_list.append(derived_profile)
        config[base_profile]["is_base"] = True
    else:
        if derived_profile in derived_list:
            derived_list.remove(derived_profile)

    config[base_profile]["derived_profiles"] = derived_list
    return save_config_file(config)
