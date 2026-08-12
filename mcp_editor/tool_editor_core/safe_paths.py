"""
경로 안전성 헬퍼

웹 에디터의 여러 API 는 요청 본문으로 받은 경로에 디렉터리를 만들고 파일을 쓴다.
검증 없이 쓰면 임의 위치 파일 생성/덮어쓰기가 되므로, 공통 기반인
`mcp_common.paths.resolve_safe_path()` 로 허용 루트(기본: 프로젝트 루트) 안인지 검사한다.

허용 루트는 `MCP_ALLOWED_PATHS` 환경변수로 넓힐 수 있다 (os.pathsep 구분).
"""

import os
import sys
from pathlib import Path
from typing import Optional

# mcp_common 은 프로젝트 루트에 있다.
# 에디터는 mcp_editor/ 만 sys.path 에 올려두는 경로로도 기동되므로 여기서 보강한다.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mcp_common.paths import PathNotAllowedError, allowed_roots, resolve_safe_path  # noqa: E402

# 상대 경로의 기본 기준 디렉터리 (mcp_editor/)
_EDITOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

__all__ = [
    "PathNotAllowedError",
    "allowed_roots",
    "resolve_safe_path",
    "resolve_request_path",
    "path_error_payload",
]


def resolve_request_path(
    raw_path,
    *,
    base: Optional[str] = None,
    must_exist: bool = False,
) -> Path:
    """
    요청으로 받은 경로를 허용 루트 안의 절대 경로로 정규화한다.

    Args:
        raw_path: 요청에서 받은 경로 문자열 (절대/상대 모두 허용)
        base: 상대 경로의 기준 디렉터리 (기본: mcp_editor/)
        must_exist: True 면 대상이 실제로 존재해야 함

    Raises:
        PathNotAllowedError: 비었거나 허용 루트 밖인 경로
        FileNotFoundError: must_exist=True 인데 대상이 없음
    """
    if raw_path is None or str(raw_path).strip() == "":
        raise PathNotAllowedError("empty path")

    candidate = str(raw_path).strip()
    if not os.path.isabs(candidate):
        candidate = os.path.join(base or _EDITOR_DIR, candidate)

    return resolve_safe_path(candidate, must_exist=must_exist)


def path_error_payload(exc: Exception, field: str = "") -> dict:
    """거부된 경로에 대한 400 응답 본문을 만든다."""
    label = f" ({field})" if field else ""
    return {
        "error": f"허용되지 않은 경로{label}: {exc}",
        "allowed_roots": [str(root) for root in allowed_roots()],
        "hint": "허용 루트를 넓히려면 MCP_ALLOWED_PATHS 환경변수를 설정하세요.",
    }
