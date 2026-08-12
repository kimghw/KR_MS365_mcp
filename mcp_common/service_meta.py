"""
`@mcp_service` — 서비스 함수에 붙는 메타데이터 표식.

원래 이 데코레이터는 `mcp_editor` 의 AST 스캐너가 도구 정의를 **생성**하기 위한 재료였다.
2026-08-12 자로 코드 생성이 폐지되고 도구 계약이 `spec/param_spec/<도메인>.yaml` 로
옮겨가면서(spec/spec_도구정의.md), 이 데코레이터의 소비자는 사라졌다.

그래도 남겨 두는 이유는 두 가지다:

1. 서비스 함수 옆에 "이건 MCP 도구로 노출된다"는 표시가 있는 편이 읽기 좋다.
2. 4개 서비스(outlook/calendar/teams/onedrive)가 이미 이 데코레이터를 쓰고 있어,
   제거하면 무관한 변경이 크게 번진다.

**런타임 동작에는 영향이 없다.** 함수를 감싸지 않고 그대로 돌려주며, 메타데이터는
`func.__mcp_service__` 에 붙여 두기만 한다. 도구 이름·설명·파라미터의 **실제 계약은
param_spec 이며 이 데코레이터의 인자가 아니다** — 둘이 어긋나면 param_spec 이 이긴다.
"""

from typing import Any, Callable, Dict, List, Optional


def mcp_service(
    tool_name: Optional[str] = None,
    description: Optional[str] = None,
    server_name: Optional[str] = None,
    service_name: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    priority: Optional[int] = None,
    related_objects: Optional[List[str]] = None,
    service_signature: Optional[List[Dict[str, Any]]] = None,
    include_in_registry: bool = True,
    **extra: Any,
) -> Callable:
    """서비스 함수에 메타데이터만 붙이고 함수는 그대로 돌려준다.

    인자는 과거 `mcp_editor` 판본과 같은 이름을 받는다 — 호출부를 고치지 않기 위해서다.
    모르는 인자가 와도 `**extra` 로 받아 조용히 보관한다.
    """

    def decorator(func: Callable) -> Callable:
        func.__mcp_service__ = {
            "tool_name": tool_name or getattr(func, "__name__", None),
            "description": description,
            "server_name": server_name,
            "service_name": service_name,
            "category": category,
            "tags": tags or [],
            "priority": priority,
            "related_objects": related_objects or [],
            "service_signature": service_signature,
            "include_in_registry": include_in_registry,
            **extra,
        }
        return func

    return decorator


__all__ = ["mcp_service"]
