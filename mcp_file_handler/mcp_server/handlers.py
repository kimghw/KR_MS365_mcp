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
    리터럴을 적지 않는다(적으면 계약이 두 벌이 되어 드리프트한다).

보안 주의 (두 transport 공통):
    - 이 서버에는 **호출자 인증이 없다**. 기본 바인드는 loopback(127.0.0.1)이며,
      외부 노출은 `MCP_BIND_HOST` + `MCP_ALLOW_PUBLIC_BIND=1` 옵트인이 필요하다.
    - 파일/디렉터리 접근은 `mcp_common.paths` 의 허용 루트로 제한된다
      (기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장).

await 버그 재발 방지:
    `FileManager` 의 도구 메서드(process/process_directory/save_metadata/...)는 전부
    **동기 함수**다. 예전 transport 들은 반환값을 무조건 `await` 해서 정상 호출조차
    `object dict can't be used in 'await' expression` 으로 실패했다. 여기서는
    `ToolRuntime`(내부 `maybe_await`)이 동기/비동기 핸들러를 모두 처리하므로
    같은 버그가 구조적으로 재발하지 않는다. **핸들러는 계속 동기로 둔다.**

오류 계약:
    핸들러는 실패를 `{"success": False, ...}` 로 돌려주거나 예외를 던진다. 둘 다
    `ToolRuntime` 이 `ToolExecutionError` 로 올려 SDK 가 `isError=True` 로 감싼다.
    즉 실패가 성공처럼 보이는 TextContent 로 새어 나가지 않는다.
"""

import logging
from typing import Any, Dict, List, Optional

from mcp_common.paths import allowed_roots
from mcp_common.runtime import ServiceLifecycle, ToolRuntime

from mcp_file_handler.file_manager import FileManager
from mcp_file_handler.mcp_server.tool_definitions import MCP_TOOLS, SPEC

logger = logging.getLogger(__name__)

SERVER_NAME = SPEC.name
SERVER_VERSION = SPEC.version
DEFAULT_PORT = SPEC.port or 5008

# health 응답/모듈 docstring 에 노출할 보안 고지
SECURITY_NOTICE = (
    "이 서버에는 호출자 인증이 없습니다. 기본 바인드는 loopback 전용이며, "
    "파일 접근은 허용 루트 안으로 제한됩니다."
)


class FileManagerService:
    """`FileManager` 를 감싼 lifecycle 어댑터.

    - 생성 실패를 import 실패(=서버 기동 불가)가 아니라 health degraded 로 노출한다.
    - `initialize()` / `close()` 는 **동기**다. `ServiceLifecycle` 이 `maybe_await`
      으로 처리하므로 async 여부와 무관하게 안전하다.
    """

    def __init__(self) -> None:
        self._manager: Optional[FileManager] = None
        self.init_error: Optional[str] = None
        self._build()

    def _build(self) -> None:
        try:
            self._manager = FileManager()
            self.init_error = None
        except Exception as exc:  # noqa: BLE001 - health 로 보고하고 계속 기동
            self._manager = None
            self.init_error = f"{type(exc).__name__}: {exc}"
            logger.error("FileManager 생성 실패: %s", self.init_error)

    def initialize(self) -> None:
        """ServiceLifecycle.startup() 에서 호출. 실패하면 health 가 degraded 가 된다."""
        if self._manager is None:
            self._build()
        if self._manager is None:
            raise RuntimeError(f"FileManager 초기화 실패: {self.init_error}")

    def close(self) -> None:
        self._manager = None

    @property
    def manager(self) -> FileManager:
        if self._manager is None:
            raise RuntimeError(
                f"FileManager 를 사용할 수 없습니다: {self.init_error or 'not initialized'}"
            )
        return self._manager


file_manager_service = FileManagerService()


def _manager() -> FileManager:
    return file_manager_service.manager


# ----------------------------------------------------------------------
# 도구 핸들러 (전부 동기 — ToolRuntime 이 동기/비동기를 모두 처리한다)
#
# 인자는 전부 `SPEC.call_args()` 가 만든다. `args["x"]` / `args.get("x", 기본값)` 을
# 직접 쓰면 파라미터 이름과 기본값이 param_spec 밖에 또 생긴다.
# ----------------------------------------------------------------------

def handle_convert_file_to_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """로컬 파일 → 텍스트. 경로는 FileManager 가 허용 루트로 검증한다."""
    return _manager().process(**SPEC.call_args("convert_file_to_text", args))


def handle_process_directory(args: Dict[str, Any]) -> Dict[str, Any]:
    """디렉터리 일괄 변환. 허용 루트 밖이면 PathNotAllowedError 가 올라온다."""
    results: List[Dict[str, Any]] = _manager().process_directory(
        **SPEC.call_args("process_directory", args)
    )
    failed = [r for r in results if not r.get("success")]
    return {
        "success": True,
        "processed": len(results),
        "failed": len(failed),
        "results": results,
    }


def handle_save_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    call_args = SPEC.call_args("save_file_metadata", args)
    file_url = call_args["file_url"]
    saved = _manager().save_metadata(**call_args)
    if not saved:
        return {"success": False, "error": "save_failed", "file_url": file_url}
    return {"success": True, "file_url": file_url}


def handle_search_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    # 검색 조건은 param_spec 이 정한 것만 넘어온다(keyword/file_url). 값이 없는 키는
    # `**criteria` 로 넘기면 SQL 조건이 하나 더 붙으므로 제거한다.
    criteria = {
        key: value
        for key, value in SPEC.call_args("search_metadata", args).items()
        if value is not None
    }
    results = _manager().search_metadata(**criteria)
    return {"success": True, "count": len(results), "criteria": criteria, "results": results}


def handle_convert_onedrive_to_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """OneDrive URL → 텍스트. 원격 URL 이므로 로컬 경로 검증 대상이 아니다."""
    return _manager().process_onedrive(**SPEC.call_args("convert_onedrive_to_text", args))


def handle_get_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    call_args = SPEC.call_args("get_file_metadata", args)
    file_url = call_args["file_url"]
    metadata = _manager().get_metadata(**call_args)
    if metadata is None:
        # 저장된 메타데이터가 없는 것은 오류가 아니라 정상적인 "결과 없음"이다.
        # (DB 예외는 manager/storage 에서 그대로 전파되어 isError 로 드러난다.)
        return {"success": True, "found": False, "file_url": file_url}
    return {"success": True, "found": True, "metadata": metadata}


def handle_delete_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    call_args = SPEC.call_args("delete_file_metadata", args)
    file_url = call_args["file_url"]
    deleted = _manager().delete_metadata(**call_args)
    if not deleted:
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
    """health 응답에 붙일 보안 고지."""
    return {
        "caller_authentication": "none",
        "bind_policy": "loopback-only by default (MCP_BIND_HOST + MCP_ALLOW_PUBLIC_BIND to expose)",
        "allowed_roots": [str(root) for root in allowed_roots()],
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
    "FileManagerService",
    "file_manager_service",
    "runtime",
    "lifecycle",
    "build_mcp_server",
    "get_tool_config",
    "security_payload",
]
