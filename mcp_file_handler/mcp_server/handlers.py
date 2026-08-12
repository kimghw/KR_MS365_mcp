"""
FileHandler MCP 도구 핸들러 — 세 transport(stream/stdio/rest)의 단일 구현.

보안 주의 (모든 transport 공통):
    - 이 서버에는 **호출자 인증이 없다**. 기본 바인드는 loopback(127.0.0.1)이며,
      외부 노출은 `MCP_BIND_HOST` + `MCP_ALLOW_PUBLIC_BIND=1` 옵트인이 필요하다.
    - 파일/디렉터리 접근은 `mcp_common.paths` 의 허용 루트로 제한된다
      (기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장).

await 버그 재발 방지:
    `FileManager` 의 도구 메서드(process/process_directory/save_metadata/...)는 전부
    **동기 함수**다. 예전 transport 들은 반환값을 무조건 `await` 해서 정상 호출조차
    `object dict can't be used in 'await' expression` 으로 실패했다. 여기서는
    `ToolRuntime`(내부 `maybe_await`)이 동기/비동기 핸들러를 모두 처리하므로
    같은 버그가 구조적으로 재발하지 않는다.

오류 계약:
    핸들러는 실패를 `{"success": False, ...}` 로 돌려주거나 예외를 던진다. 둘 다
    `ToolRuntime` 이 `ToolExecutionError` 로 올려 SDK 가 `isError=True` 로 감싼다.
    즉 실패가 성공처럼 보이는 TextContent 로 새어 나가지 않는다.
"""

import logging
import os
import sys
from typing import Any, Dict, List, Optional

# 스크립트로 직접 실행될 때를 위한 경로 보정 (패키지 import 도 그대로 동작)
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_CURRENT_DIR)
_PROJECT_ROOT = os.path.dirname(_PACKAGE_DIR)
for _path in (_PROJECT_ROOT, _PACKAGE_DIR, _CURRENT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from mcp_common.paths import allowed_roots
from mcp_common.runtime import ServiceLifecycle, ToolRuntime

from mcp_file_handler.file_manager import FileManager

try:
    from .tool_definitions import MCP_TOOLS
except ImportError:  # 스크립트 직접 실행
    from tool_definitions import MCP_TOOLS

logger = logging.getLogger(__name__)

SERVER_NAME = "file_handler"
SERVER_VERSION = "1.0.0"
DEFAULT_PORT = 5008

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
# ----------------------------------------------------------------------

def handle_convert_file_to_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """로컬 파일 → 텍스트. 경로는 FileManager 가 허용 루트로 검증한다."""
    return _manager().process(input_path=args["input_path"])


def handle_process_directory(args: Dict[str, Any]) -> Dict[str, Any]:
    """디렉터리 일괄 변환. 허용 루트 밖이면 PathNotAllowedError 가 올라온다."""
    results: List[Dict[str, Any]] = _manager().process_directory(
        directory_path=args["directory_path"]
    )
    failed = [r for r in results if not r.get("success")]
    return {
        "success": True,
        "processed": len(results),
        "failed": len(failed),
        "results": results,
    }


def handle_save_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    file_url = args["file_url"]
    saved = _manager().save_metadata(
        file_url=file_url,
        keywords=args.get("keywords") or [],
        additional_metadata=args.get("additional_metadata"),
    )
    if not saved:
        return {"success": False, "error": "save_failed", "file_url": file_url}
    return {"success": True, "file_url": file_url}


_SEARCH_KEYS = ("keyword", "file_url")


def handle_search_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    criteria = {
        key: value
        for key, value in (args or {}).items()
        if key in _SEARCH_KEYS and value is not None
    }
    results = _manager().search_metadata(**criteria)
    return {"success": True, "count": len(results), "criteria": criteria, "results": results}


def handle_convert_onedrive_to_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """OneDrive URL → 텍스트. 원격 URL 이므로 로컬 경로 검증 대상이 아니다."""
    return _manager().process_onedrive(url=args["url"])


def handle_get_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    file_url = args["file_url"]
    metadata = _manager().get_metadata(file_url=file_url)
    if metadata is None:
        # 저장된 메타데이터가 없는 것은 오류가 아니라 정상적인 "결과 없음"이다.
        # (DB 예외는 manager/storage 에서 그대로 전파되어 isError 로 드러난다.)
        return {"success": True, "found": False, "file_url": file_url}
    return {"success": True, "found": True, "metadata": metadata}


def handle_delete_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    file_url = args["file_url"]
    deleted = _manager().delete_metadata(file_url=file_url)
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


def build_runtime() -> ToolRuntime:
    """도구 등록 + 기본값 주입 + 스키마 검증 + 오류 정규화를 담당하는 런타임."""
    return ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)


def build_lifecycle() -> ServiceLifecycle:
    """initialize/close 를 일관되게 처리하고 실패를 health 에 반영한다."""
    return ServiceLifecycle(SERVER_NAME, [file_manager_service])


def security_payload() -> Dict[str, Any]:
    """health 응답에 붙일 보안 고지."""
    return {
        "caller_authentication": "none",
        "bind_policy": "loopback-only by default (MCP_BIND_HOST + MCP_ALLOW_PUBLIC_BIND to expose)",
        "allowed_roots": [str(root) for root in allowed_roots()],
        "notice": SECURITY_NOTICE,
    }


__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "DEFAULT_PORT",
    "SECURITY_NOTICE",
    "MCP_TOOLS",
    "TOOL_HANDLERS",
    "FileManagerService",
    "file_manager_service",
    "build_runtime",
    "build_lifecycle",
    "security_payload",
]
