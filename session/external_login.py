"""
외부 로그인 위임 — **단일 운영자(mode 0) 라이브러리 계약** (spec/spec_멀티유저.md ② '모드 0 외부 로그인 위임 계약(AIP)').

외부 웹 앱(AIP)이 자기 `/auth/callback` 에서 받은 Entra 인가 코드를 넘기면 이 저장소가 토큰 교환·Graph `/me`·
auth.db 저장을 맡고, 호출자에게는 **신원과 연결 상태만** 돌려준다(access/refresh/id token 은 반환·로그 어디에도 싣지 않는다).

- `complete_external_login(service, code, redirect_uri, scopes, save, expect_email)` — 인가 코드 → 신원·연결 상태.
  `expect_email` 을 주면 **저장 전에** `/me` 메일과 대조해 다르면 아무것도 저장하지 않고 ACCOUNT_MISMATCH(2026-10-23 codex 교차 검토).
  저장 실패는 예외가 아니라 정상 반환에 `error="SAVE_FAILED"`(신원은 돌려준다 — 호출자는 로그인을 유지하고 미연결로 표시).
- `connection_state(service, email)` — 4상태(connected·reauth_required·not_connected·unavailable) + 기능별 권한
- `features_from_scopes(scope)` — 저장된 granted scope 문자열 → 기능(mail·teams·onenote·calendar·todo) 판정(결정론)
- `ExternalLoginError` — `code`(EXCHANGE_FAILED·USERINFO_FAILED·ACCOUNT_MISMATCH) 속성, `str()` 은 `"CODE|메시지"`

관문은 `AuthService.complete_external_login/connection_state` 와 `AuthManager` 의 같은 이름 메서드다(이 모듈을 직접
import 하는 외부 코드는 두지 않는다). 멀티유저 모드(`MS365_MULTI_USER=1`)에서는 `refuse_in_multi_user` 로 거부한다 —
그쪽 외부 로그인은 후속 gateway `POST /auth/token`(spec ④ 'AIP 웹 로그인 연동').
"""

import asyncio
import logging
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple, Union

import aiohttp

from .mode_guard import refuse_in_multi_user

logger = logging.getLogger(__name__)

#: Entra 토큰 응답 `scope` 의 Graph 위임 권한 접두(`.default` 로 받아도 실제 부여된 권한이 이 꼴로 나열된다).
GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"

#: 기능 → 필요한 Graph 위임 권한. 바깥 튜플의 각 원소(집합)는 "그중 하나"면 되는 대안 묶음이고, 기능은 **모든 묶음**을
#: 만족해야 True 다. 이 저장소 각 도메인이 실제로 부르는 Graph 경로 기준(2026-10-23 코드 대조):
#:   mail     — Outlook: `/me/messages`·`$batch` 읽기(Mail.Read ⊂ Mail.ReadWrite) + `sendMail`(Mail.Send).
#:              임시저장(`POST /me/messages`)·회신 초안은 Mail.ReadWrite 가 더 필요하다(기능 판정에는 넣지 않음).
#:   teams    — `/me/chats` 읽기(Chat.Read ⊂ Chat.ReadWrite) + `POST /me/chats/{id}/messages`(Chat.ReadWrite 또는 ChatMessage.Send).
#:              첨부 업로드(`/me/drive`)의 Files.ReadWrite 는 선택.
#:   onenote  — `/me/onenote/*` 조회 + 페이지 생성·PATCH: Notes.ReadWrite 또는 Notes.ReadWrite.All(Notes.Create 만으로는 조회 불가).
#:   calendar — `/me/events` 조회·생성·PATCH·DELETE: Calendars.ReadWrite.
#:   todo     — `/me/todo/lists` 조회·생성·PATCH·DELETE: Tasks.ReadWrite(Tasks.ReadWrite.Shared 는 공유 목록용이라 제외).
FEATURE_REQUIREMENTS: Dict[str, Tuple[FrozenSet[str], ...]] = {
    "mail": (frozenset({"Mail.Read", "Mail.ReadWrite"}), frozenset({"Mail.Send"})),
    "teams": (frozenset({"Chat.Read", "Chat.ReadWrite"}), frozenset({"Chat.ReadWrite", "ChatMessage.Send"})),
    "onenote": (frozenset({"Notes.ReadWrite", "Notes.ReadWrite.All"}),),
    "calendar": (frozenset({"Calendars.ReadWrite"}),),
    "todo": (frozenset({"Tasks.ReadWrite"}),),
}

FEATURES: Tuple[str, ...] = tuple(FEATURE_REQUIREMENTS)

#: 연결 상태 문자열(호출자 계약).
STATE_CONNECTED = "connected"
STATE_REAUTH_REQUIRED = "reauth_required"
STATE_NOT_CONNECTED = "not_connected"
STATE_UNAVAILABLE = "unavailable"

#: `azure_token_info.refresh_state` 값 — 마지막 갱신이 `invalid_grant` 류로 거부됐다는 영구 표식.
REFRESH_STATE_OK = "ok"
REFRESH_STATE_REAUTH = "reauth_required"

#: `/me` 응답 중 호출자에게 돌려주는 키(나머지는 auth.db 저장에만 쓴다).
USER_INFO_KEYS = ("id", "displayName", "mail", "userPrincipalName")


class ExternalLoginError(Exception):
    """외부 로그인 위임 실패. `code` 로 단계를 구분하고 `str()` 은 `"CODE|메시지"` 다(워커 오류 규약과 같은 꼴).

    - EXCHANGE_FAILED  : 인가 코드 → 토큰 교환 실패(HTTP 오류·네트워크). `oauth_error` 에 Entra `error` 식별자만.
    - USERINFO_FAILED  : Graph `/me` 실패 또는 메일을 알 수 없음.
    - ACCOUNT_MISMATCH : `expect_email` 과 `/me` 메일이 다름 — **저장 전** 판정이라 아무것도 저장되지 않는다(신규 등록·기존 행 갱신
                         모두 없음). `expected_email`·`actual_email` 속성(소문자)에 두 메일 — 메시지·로그에는 싣지 않는다.
    - SAVE_FAILED      : 코드 상수만 남긴다 — **예외로는 쓰지 않는다**(2026-10-23). auth.db 저장 실패는 `complete_external_login` 이
                         신원과 함께 정상 반환하고 `error` 키에 이 코드를 담는다(호출자가 로그인을 유지하고 미연결로 표시).
    메시지에 토큰·client secret·외부 오류 본문·메일을 넣지 않는다.
    """

    EXCHANGE_FAILED = "EXCHANGE_FAILED"
    USERINFO_FAILED = "USERINFO_FAILED"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    SAVE_FAILED = "SAVE_FAILED"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: Optional[int] = None,
        oauth_error: Optional[str] = None,
        expected_email: Optional[str] = None,
        actual_email: Optional[str] = None,
    ):
        super().__init__(f"{code}|{message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.oauth_error = oauth_error
        self.expected_email = expected_email
        self.actual_email = actual_email


# ----------------------------------------------------------------------
# scope → 기능
# ----------------------------------------------------------------------
def parse_granted_scopes(scope: Union[str, Iterable[str], None]) -> Optional[List[str]]:
    """토큰 응답·DB 의 scope 를 권한 이름 목록으로 정규화한다(Graph 접두 제거, 중복 제거, 입력 순서 유지).

    scope 를 모르는 구형 행(None·빈 문자열)은 None — 호출자가 "판정 불가"로 다룬다.
    """
    if scope is None:
        return None
    tokens = scope.split() if isinstance(scope, str) else [str(s) for s in scope]
    out: List[str] = []
    seen = set()
    for token in tokens:
        name = token.strip()
        if not name:
            continue
        if name.lower().startswith(GRAPH_SCOPE_PREFIX):
            name = name[len(GRAPH_SCOPE_PREFIX):]
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
    return out or None


def features_from_scopes(scope: Union[str, Iterable[str], None]) -> Optional[Dict[str, bool]]:
    """granted scope → 기능별 가능 여부. scope 를 모르면 None(기능별 None 이 아니라 통째로 None)."""
    granted = parse_granted_scopes(scope)
    if granted is None:
        return None
    have = {g.lower() for g in granted}
    return {
        feature: all(any(alt.lower() in have for alt in group) for group in groups)
        for feature, groups in FEATURE_REQUIREMENTS.items()
    }


# ----------------------------------------------------------------------
# 연결 상태
# ----------------------------------------------------------------------
def _normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def connection_state(service: Any, email: str) -> Dict[str, Any]:
    """`email` 계정의 auth.db 연결 상태(mode 0).

    반환 키: email · state · features · granted_scopes · access_token_expires_at · refresh_token_expired.
    - connected        : refresh token 이 있고 만료 전이며 마지막 갱신이 거부되지 않음(access token 만료는 갱신으로 풀리므로 connected)
    - reauth_required  : refresh token 없음 · `refresh_token_expires_at` 경과 · 마지막 갱신이 invalid_grant 류로 거부됨(`refresh_state`)
    - not_connected    : 토큰 행 없음
    - unavailable      : auth.db 를 읽지 못함(잠김·손상 — 연결 여부 미상). `error` 키에 예외 종류 이름만.
    features·granted_scopes 는 저장된 scope 로 결정론 판정, scope 를 모르는 구형 행은 둘 다 None.
    """
    refuse_in_multi_user("connection_state()")
    wanted = _normalize_email(email)
    result: Dict[str, Any] = {
        "email": wanted,
        "state": STATE_NOT_CONNECTED,
        "features": None,
        "granted_scopes": None,
        "access_token_expires_at": None,
        "refresh_token_expired": False,
    }
    if not wanted:
        return result
    try:
        auth_db = service.auth_db
        stored = auth_db.canonical_email(wanted) or wanted
        row = auth_db.get_token(stored, strict=True)
    except Exception as e:  # sqlite 잠김·손상 등 — 연결 여부를 모른다
        logger.error("connection_state unavailable: %s", type(e).__name__)
        result["state"] = STATE_UNAVAILABLE
        result["error"] = type(e).__name__
        return result
    if not row:
        return result

    expires_at = row.get("expires_at")
    result["access_token_expires_at"] = expires_at.isoformat() if hasattr(expires_at, "isoformat") else expires_at
    granted = parse_granted_scopes(row.get("scope"))
    result["granted_scopes"] = granted
    result["features"] = features_from_scopes(granted)

    has_refresh = bool(row.get("refresh_token"))
    refresh_expired = bool(has_refresh and service.is_refresh_expiry_passed(row.get("refresh_token_expires_at")))
    rejected = row.get("refresh_state") == REFRESH_STATE_REAUTH
    result["refresh_token_expired"] = refresh_expired
    if not has_refresh or refresh_expired or rejected:
        result["state"] = STATE_REAUTH_REQUIRED
    else:
        result["state"] = STATE_CONNECTED
    return result


# ----------------------------------------------------------------------
# 외부 로그인 완료
# ----------------------------------------------------------------------
def _scope_string(service: Any, scopes: Union[str, Iterable[str], None]) -> str:
    if scopes is None:
        return " ".join(service.config.default_scopes)
    if isinstance(scopes, str):
        return " ".join(scopes.split())
    return " ".join(str(s).strip() for s in scopes if str(s).strip())


async def complete_external_login(
    service: Any,
    code: str,
    redirect_uri: str,
    scopes: Union[str, Iterable[str], None] = None,
    save: bool = True,
    expect_email: Optional[str] = None,
) -> Dict[str, Any]:
    """외부 앱이 받은 인가 코드를 **주어진 redirect_uri·scope** 로 교환 → Graph `/me` → (expect_email 대조) → (save) auth.db 저장
    → 신원·연결 상태.

    Args:
        service: `AuthService`(mode 0). client_id·client secret·tenant 는 이 저장소 설정(.env → auth.db)만 쓴다.
        code: Entra 인가 코드(외부 앱 콜백이 받은 값).
        redirect_uri: 그 인가 코드를 발급받은 외부 앱의 redirect_uri(토큰 교환 때 같은 값이어야 한다).
        scopes: 교환 때 보낼 scope(None 이면 `config.default_scopes`). 문자열(공백 구분) 또는 목록.
        save: True 면 `complete_auth_flow` 와 같은 순서(`save_user` → `save_token`)로 저장. False 는 신원만(저장 없음 —
              Graph 동의가 막혔을 때의 `openid profile email User.Read` 폴백 로그인. refresh token 없음 허용).
        expect_email: 호출자가 기대하는 계정(로그인 사용자 — 재연결 때). 값이 있으면 `/me` 메일과 **저장 전에** 대조(둘 다 소문자·공백
              제거, `canonical_email` 과 같은 대소문자 무시 규칙)해 다르면 아무것도 저장하지 않고 ACCOUNT_MISMATCH. None = 종전(무검증).

    Returns:
        {"email"(소문자), "display_name", "user_info"(id·displayName·mail·userPrincipalName), "saved", "has_refresh",
         "granted_scopes", "state"(connection_state 의 상태)} — 토큰은 어떤 키에도 없다.
        auth.db 저장에 실패하면(save=True) 예외 대신 같은 꼴로 돌려주되 "saved": False, "state" 는 DB 기준(보통 not_connected
        또는 기존 행 상태), **"error": "SAVE_FAILED"** 키가 더 있다(저장이 안 된 이유 코드만, 메시지 없음 — 2026-10-23 codex 교차 검토:
        저장이 안 돼도 호출자는 신원으로 로그인을 유지한다). 그 밖에는 "error" 키가 없다.

    Raises:
        ExternalLoginError: code = EXCHANGE_FAILED | USERINFO_FAILED | ACCOUNT_MISMATCH. (SAVE_FAILED 는 예외로 쓰지 않는다.)
    """
    refuse_in_multi_user("complete_external_login()")
    if not code or not str(code).strip():
        raise ExternalLoginError(ExternalLoginError.EXCHANGE_FAILED, "인가 코드가 비어 있습니다.")
    if not redirect_uri or not str(redirect_uri).strip():
        raise ExternalLoginError(ExternalLoginError.EXCHANGE_FAILED, "redirect_uri 가 비어 있습니다.")

    config = service.config
    if not getattr(config, "azure_client_id", None):
        config.load_config_from_db()
    if not getattr(config, "azure_client_id", None) or not getattr(config, "azure_client_secret", None):
        raise ExternalLoginError(ExternalLoginError.EXCHANGE_FAILED, "Entra 앱 설정(client_id·client secret)이 없습니다.")
    scope = _scope_string(service, scopes)

    # 1. 토큰 교환 — 이 저장소의 client secret 으로, 외부 앱의 redirect_uri 로
    try:
        token_result = await service._exchange_code_for_tokens(code, redirect_uri=redirect_uri, scope=scope)
    except ExternalLoginError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        logger.error("External login: token exchange transport failure: %s", type(e).__name__)
        raise ExternalLoginError(ExternalLoginError.EXCHANGE_FAILED, f"토큰 교환 통신 실패({type(e).__name__})") from None
    except Exception as e:
        logger.error("External login: token exchange failed: %s", type(e).__name__)
        raise ExternalLoginError(ExternalLoginError.EXCHANGE_FAILED, f"토큰 교환 실패({type(e).__name__})") from None

    # 2. Graph /me — 계정 = mail 또는 userPrincipalName 소문자
    try:
        user_info = await service._get_user_info(token_result["access_token"])
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        logger.error("External login: /me transport failure: %s", type(e).__name__)
        raise ExternalLoginError(ExternalLoginError.USERINFO_FAILED, f"사용자 정보 조회 통신 실패({type(e).__name__})") from None
    except Exception as e:
        logger.error("External login: /me failed: %s", type(e).__name__)
        raise ExternalLoginError(ExternalLoginError.USERINFO_FAILED, f"사용자 정보 조회 실패({type(e).__name__})") from None
    if not isinstance(user_info, dict):
        raise ExternalLoginError(ExternalLoginError.USERINFO_FAILED, "사용자 정보 응답 형식 오류")
    email = _normalize_email(user_info.get("mail") or user_info.get("userPrincipalName"))
    if not email:
        raise ExternalLoginError(ExternalLoginError.USERINFO_FAILED, "사용자 메일을 확인할 수 없습니다.")

    # 3. 예상 계정 대조 — 저장 **전**. 다른 계정(B)의 토큰이 남으면 되돌릴 수 없고(사후 삭제는 B 의 기존 정상 연결까지 지운다),
    #    그래서 여기서 끊는다. 비교 규칙은 canonical_email 과 같은 대소문자 무시(둘 다 소문자·공백 제거).
    wanted = _normalize_email(expect_email)
    if wanted and wanted != email:
        logger.warning("External login: account mismatch — nothing saved")
        raise ExternalLoginError(
            ExternalLoginError.ACCOUNT_MISMATCH,
            "로그인한 계정이 예상 계정과 다릅니다(저장하지 않음).",
            expected_email=wanted,
            actual_email=email,
        )

    granted = parse_granted_scopes(token_result.get("scope")) or []
    has_refresh = bool(token_result.get("refresh_token"))

    # 4. 저장 — complete_auth_flow 와 같은 순서. refresh token 이 없어도 access token 은 저장(기존 refresh 는 COALESCE 로 유지).
    #    저장 실패는 예외가 아니라 반환 `error` 키(신원은 돌려준다 — 호출자는 로그인 유지·미연결 표시).
    saved = False
    save_error: Optional[str] = None
    if save:
        try:
            service.auth_db.ensure_tables()
            ok_user = service.auth_db.save_user(email, user_info)
            ok_token = ok_user and service.auth_db.save_token(email, token_result)
        except Exception as e:
            logger.error("External login: save failed: %s", type(e).__name__)
            ok_token = False
        if ok_token:
            saved = True
            logger.info("External login saved")
        else:
            save_error = ExternalLoginError.SAVE_FAILED
            logger.error("External login: not saved (identity returned with error=%s)", save_error)
    else:
        logger.info("External login identity only (not saved)")

    state = connection_state(service, email)
    result: Dict[str, Any] = {
        "email": email,
        "display_name": user_info.get("displayName"),
        "user_info": {k: user_info.get(k) for k in USER_INFO_KEYS},
        "saved": saved,
        "has_refresh": has_refresh,
        "granted_scopes": granted,
        "state": state["state"],
    }
    if save_error:
        result["error"] = save_error
    return result


__all__ = [
    "ExternalLoginError",
    "FEATURES",
    "FEATURE_REQUIREMENTS",
    "GRAPH_SCOPE_PREFIX",
    "REFRESH_STATE_OK",
    "REFRESH_STATE_REAUTH",
    "STATE_CONNECTED",
    "STATE_NOT_CONNECTED",
    "STATE_REAUTH_REQUIRED",
    "STATE_UNAVAILABLE",
    "USER_INFO_KEYS",
    "complete_external_login",
    "connection_state",
    "features_from_scopes",
    "parse_granted_scopes",
]
