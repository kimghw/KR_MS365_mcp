"""
stdio 트랜스포트 구동부 — 공식 MCP SDK 기반, 한 벌.

기존 도메인 서버들은 `StdioMCPServer` 라는 자체 JSON-RPC 루프를 7개 파일에 복제해 갖고
있었고, 그 과정에서 실제 결함이 누적됐다(spec/spec_MCP트랜스포트.md ③-5):

- 깨진 JSON 한 줄에 서버가 종료됨(파싱 실패를 EOF 로 오인)
- `protocolVersion` 하드코딩 — 클라이언트와 협상하지 않음
- 취소 알림을 `"cancelled"` 로 비교(스펙명은 `notifications/cancelled`)
- 요청 순차 처리 — 느린 도구 하나가 이후 전부를 블록
- `ping` 이 비표준 `{"pong": true}` 를 반환
- `-32700` parse error 미응답

이 모듈은 그 루프를 폐기하고 SDK 의 `stdio_server()` 를 쓴다. 위 항목은 전부 SDK 가
스펙대로 처리하므로 별도 코드가 필요 없다.

**stream 과 같은 `Server` 객체를 그대로 받는다.** 도구 등록은 도메인의 `handlers.py`
에서 한 번만 하고, 이 모듈은 구동만 담당한다(②-3).
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def serve_stdio(mcp_server: Any, lifecycle: Any, boot: Any) -> None:
    """`Server` 를 stdio 로 구동한다. stdin EOF 가 정상 종료다.

    Args:
        mcp_server: `handlers.build_mcp_server()` 가 만든 `mcp.server.lowlevel.Server`
        lifecycle: `mcp_common.runtime.ServiceLifecycle`
        boot: `mcp_common.bootstrap.bootstrap_stdio()` 의 반환값

    `boot.original_stdout_buffer()` 를 SDK 에 **명시 주입**하는 것이 핵심이다. 부트스트랩이
    `sys.stdout` 을 stderr 로 돌려놨기 때문에, SDK 기본값(`sys.stdout.buffer`)을 그대로
    두면 JSON-RPC 응답이 통째로 stderr 로 나가 클라이언트가 아무 응답도 받지 못한다
    (spec ④-1-1).
    """
    from io import TextIOWrapper

    import anyio
    from mcp.server.stdio import stdio_server

    # 원본 stdout 만이 프로토콜 채널이다.
    stdout = anyio.wrap_file(TextIOWrapper(boot.original_stdout_buffer(), encoding="utf-8"))

    await lifecycle.startup()
    if lifecycle.errors:
        # 서버는 계속 뜨되(도구 목록 조회는 가능해야 한다) 실패를 분명히 남긴다.
        for message in lifecycle.errors:
            logger.error("[%s] startup degraded: %s", lifecycle.server_name, message)

    logger.info("[%s] stdio server ready", lifecycle.server_name)
    try:
        async with stdio_server(stdout=stdout) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )
    finally:
        await lifecycle.shutdown()
        logger.info("[%s] stdio server stopped", lifecycle.server_name)


def run_stdio(mcp_server: Any, lifecycle: Any, boot: Any) -> None:
    """`serve_stdio` 를 asyncio 백엔드로 돌린다.

    SDK 는 anyio 기반이지만 도메인 서비스가 순수 asyncio(aiohttp)라 백엔드를 asyncio 로
    고정한다(spec ④-1-4).
    """
    import anyio

    try:
        anyio.run(serve_stdio, mcp_server, lifecycle, boot, backend="asyncio")
    except KeyboardInterrupt:
        logger.info("[%s] interrupted", lifecycle.server_name)


__all__ = ["serve_stdio", "run_stdio"]
