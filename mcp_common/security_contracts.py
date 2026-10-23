"""
멀티유저 보안 계약 — 오류 코드·토큰 값 객체·Protocol (spec/spec_멀티유저.md ②-11.1, WP0).

이 모듈은 **타입과 계약만** 담는다. 구현은 각 WP 가 소유한다:

- `BoundTokenProvider` 구현 → session (WP2), `mcp_common.auth.get_bound_token_provider()`
- `ManagedService` 구현 → 각 도메인 서비스 (WP4~WP9)

공용 계약을 바꿀 때는 `CONTRACT_VERSION` 을 올리고 사양서 ②-12 를 함께 고친다.
각 WP 가 임의로 이름·시그니처를 바꾸지 않는다.

## 오류

보안 실패는 전부 `SecurityError` 로 올린다. `ToolExecutionError` 의 하위 클래스라
`ToolRuntime.call()` 의 `except ToolExecutionError: raise` 경로를 그대로 타고
SDK 가 `CallToolResult(isError=True)` 로 감싼다. 페이로드에는 **고정 코드와 공개용
메시지만** 싣는다 — 다른 사용자의 존재 여부, 절대경로, 토큰, 외부 오류 원문을 넣지 않는다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from mcp_common.errors import ToolExecutionError

CONTRACT_VERSION = 1


class ErrorCode:
    """공개 오류 코드. 문자열 값이 곧 클라이언트 계약이다."""

    UNAUTHENTICATED = "unauthenticated"          # bearer 없음·형식 오류·만료·폐기·미지 키 (HTTP 401)
    FORBIDDEN_SCOPE = "forbidden_scope"          # 유효 키지만 도메인 scope 부족 (HTTP 403)
    MISSING_PRINCIPAL = "missing_principal"      # 멀티유저인데 요청에 principal 이 묶이지 않음
    IDENTITY_MISMATCH = "identity_mismatch"      # user_email 이 호출자 연결 계정과 다름
    INVALID_USER_EMAIL = "invalid_user_email"    # user_email 이 null·빈 문자열·비문자열
    ACCOUNT_INACTIVE = "account_inactive"        # 계정 비활성·삭제 중·auth_epoch 변경
    GRAPH_NOT_CONNECTED = "graph_not_connected"  # Graph 연결(토큰) 없음
    GRAPH_REAUTH_REQUIRED = "graph_reauth_required"  # refresh 실패(invalid_grant 등)
    NOT_FOUND = "not_found"                      # 다른 사용자 소유 리소스 포함
    PATH_NOT_ALLOWED = "path_not_allowed"        # 사용자 파일 루트 밖
    UNEXPECTED_ARGUMENT = "unexpected_argument"  # 스키마에 없는 최상위 인자 (멀티유저)
    OVERLOADED = "overloaded"                    # 서비스 풀·동시 실행 상한 초과 (재시도 가능)
    CONFIG_ERROR = "config_error"                # 기동 시 보안 설정 위반
    INTERNAL_ERROR = "internal_error"            # 그 밖의 내부 오류 (원문 비노출)


#: HTTP 계층에서 응답할 때의 상태 코드. 도구 오류로 나갈 때는 쓰지 않는다.
HTTP_STATUS: Dict[str, int] = {
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN_SCOPE: 403,
    ErrorCode.ACCOUNT_INACTIVE: 403,
    ErrorCode.OVERLOADED: 503,
}

#: 코드별 기본 공개 메시지 (한국어). 호출자가 `public_message` 를 따로 주면 그것을 쓴다.
DEFAULT_MESSAGES: Dict[str, str] = {
    ErrorCode.UNAUTHENTICATED: "인증이 필요합니다. 유효한 Bearer 키를 Authorization 헤더로 보내세요.",
    ErrorCode.FORBIDDEN_SCOPE: "이 키로는 해당 MCP 서버를 사용할 수 없습니다.",
    ErrorCode.MISSING_PRINCIPAL: "요청 사용자 컨텍스트가 없습니다.",
    ErrorCode.IDENTITY_MISMATCH: "user_email 이 인증된 사용자와 일치하지 않습니다. 다른 계정은 선택할 수 없습니다.",
    ErrorCode.INVALID_USER_EMAIL: "user_email 은 비어 있지 않은 문자열이어야 합니다. 생략하면 본인 계정을 씁니다.",
    ErrorCode.ACCOUNT_INACTIVE: "계정이 비활성 상태이거나 인증 상태가 바뀌었습니다.",
    ErrorCode.GRAPH_NOT_CONNECTED: "Microsoft 365 계정이 아직 연결되지 않았습니다.",
    ErrorCode.GRAPH_REAUTH_REQUIRED: "Microsoft 365 재연결이 필요합니다.",
    ErrorCode.NOT_FOUND: "대상을 찾을 수 없습니다.",
    ErrorCode.PATH_NOT_ALLOWED: "허용되지 않은 경로입니다.",
    ErrorCode.UNEXPECTED_ARGUMENT: "허용되지 않은 인자가 포함되어 있습니다.",
    ErrorCode.OVERLOADED: "요청이 많아 잠시 처리할 수 없습니다. 다시 시도하세요.",
    ErrorCode.CONFIG_ERROR: "서버 보안 설정 오류입니다.",
    ErrorCode.INTERNAL_ERROR: "내부 오류가 발생했습니다.",
}


class SecurityError(ToolExecutionError):
    """보안 실패. 페이로드는 `{"status":"error","error":<code>,"message":...}` 고정형.

    Args:
        code: `ErrorCode` 값
        public_message: 클라이언트에 보여도 되는 메시지 (없으면 코드 기본 메시지)
        details: 공개해도 되는 부가 정보만 (예: 연결 URL, 거부된 인자 **이름**)
        tool: 도구 이름 (있으면)
    """

    def __init__(
        self,
        code: str,
        public_message: Optional[str] = None,
        *,
        details: Optional[Dict[str, Any]] = None,
        tool: Optional[str] = None,
    ):
        self.code = code
        self.public_message = public_message or DEFAULT_MESSAGES.get(code, code)
        self.details = dict(details or {})
        payload: Dict[str, Any] = {
            "status": "error",
            "error": code,
            "message": self.public_message,
        }
        if self.details:
            payload.update(self.details)
        super().__init__(payload, tool=tool)

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 400)


class StartupConfigError(RuntimeError):
    """멀티유저 기동 시 보안 설정 위반. 서버를 띄우지 않는다."""


@dataclass(frozen=True)
class AccessToken:
    """Graph access token 값 객체. `repr` 에 값이 나오지 않는다."""

    value: str = field(repr=False)
    expires_at: Optional[datetime] = None
    token_version: int = 0

    def __str__(self) -> str:  # 실수로 문자열 포맷에 넣어도 값이 새지 않게
        return "AccessToken(***)"


@runtime_checkable
class BoundTokenProvider(Protocol):
    """한 사용자에 **고정된** 토큰 공급자. 생성 후 사용자를 바꾸지 않는다.

    `validate_and_refresh_token()` 은 기존 GraphClient 들이 쓰던 email 기반 시그니처의
    **과도기 어댑터**다. email 이 주어지면 자신의 principal 과 일치하는지만 확인하고
    (불일치 → `SecurityError(IDENTITY_MISMATCH)`), 계정을 **선택하지 않는다.**
    `auto_reauth` 는 무시한다 — 멀티유저에서 서버가 브라우저를 열지 않는다.
    """

    @property
    def user_key(self) -> str: ...

    async def get_graph_token(self, *, minimum_ttl_seconds: int = 120) -> AccessToken: ...

    async def validate_and_refresh_token(
        self, email: Optional[str] = None, auto_reauth: bool = False
    ) -> Optional[str]: ...

    async def close(self) -> None:
        """차용 해제 또는 no-op. 공용 인증 자원(세션·DB·다른 사용자)을 닫지 않는다."""
        ...


@runtime_checkable
class ManagedService(Protocol):
    """서비스 풀이 수명을 관리하는 사용자별 서비스.

    `initialize()` 는 선택이다. 반환값 의미는 `ServiceLifecycle` 과 같다 —
    None·truthy 는 성공, 명시적 falsy(False 등)는 실패.
    """

    async def close(self) -> None: ...


__all__ = [
    "CONTRACT_VERSION",
    "ErrorCode",
    "HTTP_STATUS",
    "DEFAULT_MESSAGES",
    "SecurityError",
    "StartupConfigError",
    "AccessToken",
    "BoundTokenProvider",
    "ManagedService",
]
