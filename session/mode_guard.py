"""
legacy(mode 0) 인증 경로 차단 가드 (spec/spec_멀티유저.md ②-5.5, ②-10 정적 검증).

멀티유저 모드(`MS365_MULTI_USER=1`)에서 다음 legacy 경로는 **실행 자체를 거부**한다.

- 인자 없는 `AuthDatabase()` / 공용 `database/auth.db`
- `AuthManager()` · `get_default_auth_manager()` · `_auto_reauth()` (서버 브라우저 실행)
- `AuthService()` · `AzureConfig()` 기본 생성 (공용 DB 의 client secret)
- `session.session_manager` 의 이메일 키 세션
- `CallbackServer` (도메인별 콜백 서버 — 멀티유저는 `session.auth_gateway` 하나)
- 이메일 기반 기본 사용자 선택(`get_default_user_email`)

거부는 `LegacyAuthDisabledError`(= `StartupConfigError` 하위)로 한다. 도구 실행 중에
올라오면 런타임이 내부 오류로 감싸 원문을 노출하지 않는다.
"""

from mcp_common.security_contracts import StartupConfigError


class LegacyAuthDisabledError(StartupConfigError):
    """멀티유저 모드에서 legacy 단일 운영자 인증 경로를 호출했다."""


def multi_user_active() -> bool:
    from mcp_common.security_policy import multi_user_enabled

    return multi_user_enabled()


def refuse_in_multi_user(what: str) -> None:
    """멀티유저 모드면 `LegacyAuthDisabledError`. mode 0 에서는 아무 일도 하지 않는다."""
    if multi_user_active():
        raise LegacyAuthDisabledError(
            f"{what} 는 단일 운영자(mode 0) 전용입니다. 멀티유저 모드에서는 "
            "session.identity_registry / session.token_store / session.auth_gateway 를 사용하세요."
        )


__all__ = ["LegacyAuthDisabledError", "multi_user_active", "refuse_in_multi_user"]
