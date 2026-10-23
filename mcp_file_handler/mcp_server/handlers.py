"""
FileHandler MCP — 도구 정의와 핸들러. **두 트랜스포트가 공유하는 유일한 원본이다.**

`server_stdio.py` 와 `server_stream.py` 는 이 모듈을 import 해 `build_mcp_server()` 가
만든 같은 `Server` 객체를 받아 구동만 한다. 도구 정의나 핸들러가 트랜스포트 파일에
다시 나타나면 사양 위반이다(spec/spec_MCP트랜스포트.md ②-3-1).

이 모듈은 트랜스포트를 import 하지 않고(단방향 의존) 프로세스 부트스트랩도 하지 않는다 —
호출자가 `mcp_common.bootstrap` 을 먼저 돌린 뒤 import 해야 한다.

도구 계약:
    `spec/param_spec/file_handler.yaml` 한 곳에만 적는다. `inputSchema`·기본값·호출 인자는
    `tool_definitions.SPEC` 이 기동 시 파생시킨다. 이 파일에는 파라미터 이름이나 기본값
    리터럴을 적지 않는다(적으면 계약이 두 벌이 되어 드리프트한다). 바인딩(`service:`)은
    전부 `FileHandlerService.<메서드>` 다.

서비스 배선 (spec/spec_멀티유저.md ②-12 항목 2, `mcp_common.service_context` 패턴):
    - mode 1 (`MS365_MULTI_USER=1`): `create_service(principal, paths, tokens)` 가 사용자별
      `FileHandlerService` 를 **생성만** 하고, 서비스 풀이 `initialize()`/`close()` 를 부른다.
      전역 인스턴스를 만들지 않는다(AuthManager 도 만들지 않는다). 핸들러는
      `service_for()` 로 이 요청에 lease 된 사용자 서비스를 꺼낸다.
    - mode 0: 전역 `file_manager_service` 1개 (`FileHandlerService.legacy()`).
    - mode 1 기동 시 홈/CWD config·환경변수 경로 설정이 있으면 `StartupConfigError` 로
      서버를 띄우지 않는다(F07 — 조용히 무시하지 않는다).

핸들러는 async 다. 동기 `FileManager` 작업은 `FileHandlerService` 가 작업 스레드로 넘긴다
(principal·요청 scope 는 `contextvars.copy_context()` 로 명시 전달). 예전에는 핸들러가
동기라 이벤트 루프 스레드에서 돌았고, OneDrive 토큰을 얻으려고 새 이벤트 루프를 다른
스레드에 만드는 브리지(`executor.submit(asyncio.run, …)`)가 필요했다 — 그 브리지는 없다.

오류 계약:
    핸들러는 실패를 `{"success": False, ...}` 로 돌려주거나 예외를 던진다. 둘 다
    `ToolRuntime` 이 `ToolExecutionError` 로 올려 SDK 가 `isError=True` 로 감싼다.
    mode 1 의 경로 위반은 `SecurityError(path_not_allowed)`, 요청 컨텍스트 누락은
    `missing_principal` 이다. 응답에 절대경로를 싣지 않는다.
"""

import logging
from typing import Any, Dict, List, Optional

from mcp_common.paths import allowed_roots
from mcp_common.runtime import ServiceLifecycle, ToolRuntime
from mcp_common.security_policy import multi_user_enabled
from mcp_common.service_context import service_for
from mcp_common.service_pool import register_service_factory

from mcp_file_handler.config.settings import validate_multi_user_config
from mcp_file_handler.mcp_server.tool_definitions import MCP_TOOLS, SPEC
from mcp_file_handler.service import FileHandlerService

logger = logging.getLogger(__name__)

SERVER_NAME = SPEC.name
SERVER_VERSION = SPEC.version
DEFAULT_PORT = SPEC.port or 5008

# health 응답/모듈 docstring 에 노출할 보안 고지
SECURITY_NOTICE = (
    "이 서버에는 호출자 인증이 없습니다. 기본 바인드는 loopback 전용이며, "
    "파일 접근은 허용 루트 안으로 제한됩니다."
)
SECURITY_NOTICE_MULTI_USER = (
    "멀티유저 모드: 호출자는 bearer 로 인증되고, 파일 접근은 호출자 자신의 files/ 루트로 "
    "제한됩니다. 응답과 health 에 절대경로를 싣지 않습니다."
)

#: 하위 호환 이름 (예전 lifecycle 어댑터 클래스)
FileManagerService = FileHandlerService


# ----------------------------------------------------------------------
# 서비스 배선
# ----------------------------------------------------------------------
async def create_service(principal, paths, tokens) -> FileHandlerService:
    """사용자별 서비스 factory — 생성만 한다. initialize()/close() 는 서비스 풀이 부른다."""
    return FileHandlerService(principal=principal, paths=paths, tokens=tokens)


register_service_factory(SERVER_NAME, create_service)

if multi_user_enabled():
    validate_multi_user_config()

# mode 0 전용 전역 인스턴스. mode 1 에서는 만들지 않는다.
file_manager_service: Optional[FileHandlerService] = (
    None if multi_user_enabled() else FileHandlerService.legacy()
)


def _service() -> FileHandlerService:
    return service_for(SERVER_NAME, legacy=file_manager_service)


# ----------------------------------------------------------------------
# 도구 핸들러
#
# 인자는 전부 `SPEC.call_args()` 가 만든다. `args["x"]` / `args.get("x", 기본값)` 을
# 직접 쓰면 파라미터 이름과 기본값이 param_spec 밖에 또 생긴다.
# ----------------------------------------------------------------------

async def handle_convert_file_to_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """로컬 파일 → 텍스트. 경로는 FileManager 가 허용 범위로 검증한다."""
    return await _service().process(**SPEC.call_args("convert_file_to_text", args))


async def handle_process_directory(args: Dict[str, Any]) -> Dict[str, Any]:
    """디렉터리 일괄 변환. 허용 범위 밖이면 경로 오류가 올라온다."""
    results: List[Dict[str, Any]] = await _service().process_directory(
        **SPEC.call_args("process_directory", args)
    )
    failed = [r for r in results if not r.get("success")]
    return {
        "success": True,
        "processed": len(results),
        "failed": len(failed),
        "results": results,
    }


# 메타데이터 응답의 `file_url` 은 호출자 입력이 아니라 서비스가 정규화한 참조다 — 자기
# files/ 안의 절대경로를 넣어도 상대 참조로 돌아간다 (astra 리뷰 R14).
async def handle_save_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    outcome = await _service().save_metadata(**SPEC.call_args("save_file_metadata", args))
    if not outcome["success"]:
        return {"success": False, "error": "save_failed", "file_url": outcome["file_url"]}
    return {"success": True, "file_url": outcome["file_url"]}


async def handle_search_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    # 검색 조건은 param_spec 이 정한 것만 넘어온다(keyword/file_url). 값이 없는 키는
    # `**criteria` 로 넘기면 SQL 조건이 하나 더 붙으므로 제거한다.
    criteria = {
        key: value
        for key, value in SPEC.call_args("search_metadata", args).items()
        if value is not None
    }
    outcome = await _service().search_metadata(**criteria)
    results = outcome["results"]
    # 반사하는 criteria 는 서비스가 정리한 것 — 정규화 전 경로를 되돌려주지 않는다 (N10)
    return {"success": True, "count": len(results), "criteria": outcome["criteria"], "results": results}


async def handle_convert_onedrive_to_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """OneDrive URL → 텍스트. 원격 URL 이므로 로컬 경로 검증 대상이 아니다."""
    return await _service().process_onedrive(**SPEC.call_args("convert_onedrive_to_text", args))


async def handle_get_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    outcome = await _service().get_metadata(**SPEC.call_args("get_file_metadata", args))
    if not outcome["found"]:
        # 저장된 메타데이터가 없는 것은 오류가 아니라 정상적인 "결과 없음"이다.
        # (DB 예외는 manager/storage 에서 그대로 전파되어 isError 로 드러난다.)
        return {"success": True, "found": False, "file_url": outcome["file_url"]}
    return {"success": True, "found": True, "metadata": outcome["metadata"]}


async def handle_delete_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    outcome = await _service().delete_metadata(**SPEC.call_args("delete_file_metadata", args))
    file_url = outcome["file_url"]
    if not outcome["deleted"]:
        # 이미 없는 항목의 재삭제는 멱등적 정상 동작이다.
        # (DB 예외는 manager/storage 에서 그대로 전파되어 isError 로 드러난다.)
        return {"success": True, "deleted": False, "already_absent": True, "file_url": file_url}
    return {"success": True, "deleted": True, "file_url": file_url}


TOOL_HANDLERS = {
    "convert_file_to_text": handle_convert_file_to_text,
    "process_directory": handle_process_directory,
    "save_file_metadata": handle_save_file_metadata,
    "search_metadata": handle_search_metadata,
    "convert_onedrive_to_text": handle_convert_onedrive_to_text,
    "get_file_metadata": handle_get_file_metadata,
    "delete_file_metadata": handle_delete_file_metadata,
}


# 기본값 주입 + 스키마 검증 + 오류 정규화는 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [file_manager_service])


def get_tool_config(tool_name: str) -> Optional[dict]:
    """하위 호환용 조회 헬퍼."""
    return runtime.tool_config(tool_name)


def build_mcp_server():
    """stdio·stream 이 공유하는 `Server` 를 만든다. 도구 등록은 여기서 1회만 한다."""
    from mcp.server.lowlevel import Server as MCPServer

    server = MCPServer(name=SERVER_NAME, version=SERVER_VERSION)
    tool_objects = runtime.build_tool_objects()

    @server.list_tools()
    async def _list_tools():
        return tool_objects

    # SDK 검증은 끄고(validate_input=False) ToolRuntime 이 검증한다.
    # 실패는 예외로 올라가 SDK 가 CallToolResult(isError=True) 로 감싼다.
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        return await runtime.dispatch(name, arguments or {})

    return server


def security_payload() -> Dict[str, Any]:
    """health 응답에 붙일 보안 고지. **허용 루트 절대경로를 싣지 않는다** (②-2.7)."""
    bind_policy = "loopback-only by default (MCP_BIND_HOST + MCP_ALLOW_PUBLIC_BIND to expose)"
    if multi_user_enabled():
        return {
            "caller_authentication": "bearer (per-user)",
            "bind_policy": bind_policy,
            "file_access": "caller's own files/ root only",
            "notice": SECURITY_NOTICE_MULTI_USER,
        }
    return {
        "caller_authentication": "none",
        "bind_policy": bind_policy,
        "file_access": "mcp_common.paths allowed roots (MCP_ALLOWED_PATHS to widen)",
        "allowed_root_count": len(allowed_roots()),
        "notice": SECURITY_NOTICE,
    }


__all__ = [
    "SPEC",
    "SERVER_NAME",
    "SERVER_VERSION",
    "DEFAULT_PORT",
    "SECURITY_NOTICE",
    "MCP_TOOLS",
    "TOOL_HANDLERS",
    "FileHandlerService",
    "FileManagerService",
    "create_service",
    "file_manager_service",
    "runtime",
    "lifecycle",
    "build_mcp_server",
    "get_tool_config",
    "security_payload",
]
