"""
mcp_common — 모든 MS365 MCP 서버가 공유하는 런타임 기반.

리포트에서 지적된 드리프트(바인드 주소, 사용자 선택, 입력 검증, 오류 계약,
lifecycle, 경로 검증)를 도메인별 중복 구현 대신 이 패키지 한 곳으로 수렴시킨다.

사용 예:
    from mcp_common import resolve_bind_host, resolve_user_email
    from mcp_common.errors import normalize_tool_result, ToolExecutionError
    from mcp_common.validation import validate_arguments
    from mcp_common.paths import resolve_safe_path
"""

from mcp_common.net import resolve_bind_host, is_public_bind
from mcp_common.user_resolver import UserResolver, resolve_user_email
from mcp_common.errors import (
    ToolExecutionError,
    ToolValidationError,
    normalize_tool_result,
)
from mcp_common.validation import validate_arguments, apply_schema_defaults
from mcp_common.paths import PathNotAllowedError, resolve_safe_path, allowed_roots
from mcp_common.auth import get_shared_auth_manager

__all__ = [
    "resolve_bind_host",
    "is_public_bind",
    "UserResolver",
    "resolve_user_email",
    "ToolExecutionError",
    "ToolValidationError",
    "normalize_tool_result",
    "validate_arguments",
    "apply_schema_defaults",
    "PathNotAllowedError",
    "resolve_safe_path",
    "allowed_roots",
    "get_shared_auth_manager",
]
