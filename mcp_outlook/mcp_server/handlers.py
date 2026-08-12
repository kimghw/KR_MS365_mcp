"""
Outlook MCP — 핸들러. **두 트랜스포트가 공유하는 유일한 원본이다.**

도구 계약(이름·설명·파라미터·기본값)은 `spec/param_spec/outlook.yaml` 한 곳에만 있고,
`inputSchema` 와 서비스 호출 인자는 기동 시 `mcp_common.param_spec` 이 파생시킨다.
**이 파일에는 도구 정의를 적지 않는다** — 전에는 `MCP_TOOLS` 를 YAML 에서 읽어
`INTERNAL_ARG_TYPES`·`merge_param_data`·boolean 변환 사본이 stdio/stream 양쪽에
중복돼 있었고 실제로 드리프트했다(spec/spec_MCP트랜스포트.md ②-3-1).

`server_stdio.py` 와 `server_stream.py` 는 이 모듈을 import 해 `build_mcp_server()` 가
만든 같은 `Server` 객체를 구동만 한다. 이 모듈은 트랜스포트를 import 하지 않고(단방향
의존), 프로세스 부트스트랩도 하지 않는다 — 호출자가 `mcp_common.bootstrap` 을 먼저
돌린 뒤 import 해야 한다.

## outlook 고유 사항

- 도구 이름과 서비스 함수가 1:1 이 아니다(`mail_list_keyword` → `fetch_search`,
  `test_handler` → `fetch_filter` 등). 매핑은 아래 각 핸들러에 있다.
- `type: object` 파라미터는 `SPEC.call_args()` 가 **dict** 로 넘겨 준다. 핸들러는
  그 dict 로 Pydantic 모델(`FilterParams`/`ExcludeParams`/`SelectParams`)을 만든다.
  값이 없으면(None/빈 dict) 모델을 만들지 않고 None 을 넘긴다 — 기존
  `merge_param_data(...) if ... is not None else None` 과 같은 동작이다.
- `user_email` 은 spec 이 아니라 정책이 정한다. 10개 도구 모두 기존
  `resolve_request_user(args)`(= `required=True`)와 동등하게 처리한다.
"""

from typing import Any, Dict, List, Optional, Type

from mcp_common.param_spec import load_param_spec
from mcp_common.runtime import ServiceLifecycle, ToolRuntime
from mcp_common.user_resolver import resolve_user_email

from mcp_outlook.outlook_service import MailService
from mcp_outlook.outlook_types import ExcludeParams, FilterParams, SelectParams

# 도구 계약의 단일 원본. 이 파일에는 도구 정의를 적지 않는다.
SPEC = load_param_spec("outlook")

SERVER_NAME = SPEC.name
SERVER_VERSION = SPEC.version
DEFAULT_PORT = SPEC.port or 5001

MCP_TOOLS: List[Dict[str, Any]] = SPEC.mcp_tools()


mail_service = MailService()


def _call_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """spec 에서 호출 인자를 파생시키고 user_email 만 정책(SSOT)으로 해석한다.

    Outlook 도구 10개는 모두 사용자 컨텍스트가 필요하다. 스키마상 `user_email` 은
    선택이고(`test_handler` 는 아예 없다), 실제 값 결정은 `mcp_common.user_resolver`
    가 한다(명시값 → 환경변수 → auth.db). 끝내 없으면 `ToolExecutionError` 를 올린다.
    """
    call = SPEC.call_args(tool_name, args)
    call["user_email"] = resolve_user_email(call.get("user_email"), required=True)
    return call


def _model(model: Type[Any], value: Any) -> Optional[Any]:
    """`type: object` 파라미터의 dict 를 Pydantic 모델로. 값이 없으면 None.

    빈 dict 도 None 으로 본다 — 기존 `merge_param_data` 가 `result if result else None`
    이었으므로 `{}` 는 모델을 만들지 않았다.
    """
    if value is None or isinstance(value, model):
        return value
    if not value:
        return None
    return model(**value)


# ============================================================
# 도구 핸들러 — 도구 이름 → 서비스 함수 매핑
# ============================================================


async def handle_mail_list_period(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_list_period → MailService.query_mail_list

    `DatePeriodFilter`(targetParam filter_params)는 에이전트가 채우고,
    `client_filter`/`select`(31개 필드)/`top` 은 spec 의 internal 값이 주입된다.
    """
    call = _call_args("mail_list_period", args)
    call["filter_params"] = _model(FilterParams, call.get("filter_params"))
    call["client_filter"] = _model(ExcludeParams, call.get("client_filter"))
    call["select_params"] = _model(SelectParams, call.get("select_params"))
    return await mail_service.query_mail_list(**call)


async def handle_mail_list_keyword(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_list_keyword → MailService.fetch_search (search_keywords → search_term)"""
    return await mail_service.fetch_search(**_call_args("mail_list_keyword", args))


async def handle_mail_query_if_emaidID(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_query_if_emaidID → MailService.batch_and_fetch"""
    return await mail_service.batch_and_fetch(**_call_args("mail_query_if_emaidID", args))


async def handle_mail_attachment_meta(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_attachment_meta → MailService.fetch_attachments_metadata"""
    call = _call_args("mail_attachment_meta", args)
    call["select_params"] = _model(SelectParams, call.get("select_params"))
    return await mail_service.fetch_attachments_metadata(**call)


async def handle_mail_attachment_download(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_attachment_download → MailService.download_attachments

    boolean 파라미터의 enabled/disabled → bool 복원은 `SPEC.call_args()` 가 한다.
    """
    return await mail_service.download_attachments(**_call_args("mail_attachment_download", args))


async def handle_mail_fetch_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_fetch_filter → MailService.fetch_filter"""
    call = _call_args("mail_fetch_filter", args)
    call["filter_params"] = _model(FilterParams, call.get("filter_params"))
    call["exclude_params"] = _model(ExcludeParams, call.get("exclude_params"))
    return await mail_service.fetch_filter(**call)


async def handle_mail_fetch_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_fetch_search → MailService.fetch_search"""
    call = _call_args("mail_fetch_search", args)
    call["select_params"] = _model(SelectParams, call.get("select_params"))
    return await mail_service.fetch_search(**call)


async def handle_mail_process_with_download(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_process_with_download → MailService.process_with_download"""
    call = _call_args("mail_process_with_download", args)
    call["filter_params"] = _model(FilterParams, call.get("filter_params"))
    return await mail_service.process_with_download(**call)


async def handle_mail_query_url(args: Dict[str, Any]) -> Dict[str, Any]:
    """mail_query_url → MailService.fetch_url

    구 핸들러는 `fetch_url(select=...)` 로 호출했는데 시그니처 인자는 `select_params`
    라, 이 도구는 호출될 때마다 TypeError 로 죽고 있었다. spec 의 targetParam 을
    `select_params` 로 바로잡아 해소했다 (2026-08-12).
    """
    call = _call_args("mail_query_url", args)
    call["filter_params"] = _model(FilterParams, call.get("filter_params"))
    call["select_params"] = _model(SelectParams, call.get("select_params"))
    return await mail_service.fetch_url(**call)


async def handle_test_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """test_handler → MailService.fetch_filter"""
    call = _call_args("test_handler", args)
    call["filter_params"] = _model(FilterParams, call.get("filter_params"))
    call["exclude_params"] = _model(ExcludeParams, call.get("exclude_params"))
    call["select_params"] = _model(SelectParams, call.get("select_params"))
    call["client_filter"] = _model(ExcludeParams, call.get("client_filter"))
    return await mail_service.fetch_filter(**call)


TOOL_HANDLERS = {
    "mail_list_period": handle_mail_list_period,
    "mail_list_keyword": handle_mail_list_keyword,
    "mail_query_if_emaidID": handle_mail_query_if_emaidID,
    "mail_attachment_meta": handle_mail_attachment_meta,
    "mail_attachment_download": handle_mail_attachment_download,
    "mail_fetch_filter": handle_mail_fetch_filter,
    "mail_fetch_search": handle_mail_fetch_search,
    "mail_process_with_download": handle_mail_process_with_download,
    "mail_query_url": handle_mail_query_url,
    "test_handler": handle_test_handler,
}


# 기본값 주입 + 스키마 검증 + 오류 정규화는 ToolRuntime 이 담당한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [mail_service])


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
        # 진짜 bool -> enabled/disabled 보정은 ToolRuntime 이 검증 전에 처리한다.
        return await runtime.dispatch(name, arguments)

    return server


__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "DEFAULT_PORT",
    "MCP_TOOLS",
    "TOOL_HANDLERS",
    "runtime",
    "lifecycle",
    "build_mcp_server",
    "get_tool_config",
]
