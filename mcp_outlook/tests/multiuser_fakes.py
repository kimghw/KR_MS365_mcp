"""
Outlook 멀티유저 테스트 공용 도구 (네트워크 없음).

`aiohttp.ClientSession` 을 기록용 가짜로 바꾸고, 요청은 라우터 함수가 응답한다.
테스트 파일은 `from mcp_outlook.tests.multiuser_fakes import *` 로 fixture 까지 가져간다.
"""

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiohttp
import pytest

from mcp_common.testing import FakeTokenProvider, make_principal, multi_user_mode
from mcp_common.user_paths import ensure_user_dirs, paths_for

ALICE_EMAIL = "alice@contoso.com"
BOB_EMAIL = "bob@contoso.com"


@dataclass
class Call:
    method: str
    url: str
    headers: Dict[str, str]
    kwargs: Dict[str, Any] = field(default_factory=dict)

    @property
    def authorization(self) -> Optional[str]:
        for key, value in self.headers.items():
            if key.lower() == "authorization":
                return value
        return None


class FakeResponse:
    def __init__(self, status: int = 200, json_data: Any = None, text: str = ""):
        self.status = status
        self._json = json_data if json_data is not None else {}
        self._text = text
        self.headers: Dict[str, str] = {}

    async def json(self):
        return self._json

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def __await__(self):  # `await session.delete(url)` 형태 지원
        async def _self():
            return self

        return _self().__await__()


Router = Callable[[Call], FakeResponse]


class FakeSession:
    def __init__(self, router: Router, log: List[Call]):
        self._router = router
        self._log = log

    def _request(self, method: str, url: Any, headers: Optional[Dict[str, str]] = None, **kwargs):
        call = Call(method, str(url), dict(headers or {}), kwargs)
        self._log.append(call)
        return self._router(call)

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._request("DELETE", url, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class HttpRecorder:
    """설치된 가짜 세션의 기록. `sessions` 는 ClientSession 생성 횟수."""

    def __init__(self):
        self.calls: List[Call] = []
        self.sessions = 0


def install_http(monkeypatch, router: Router) -> HttpRecorder:
    recorder = HttpRecorder()

    def _factory(*_args, **_kwargs):
        recorder.sessions += 1
        return FakeSession(router, recorder.calls)

    monkeypatch.setattr(aiohttp, "ClientSession", _factory)
    return recorder


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def mail_with_attachments(message_id: str, attachments: List[Dict[str, Any]], subject: str = "Quarterly report") -> Dict[str, Any]:
    return {
        "id": message_id,
        "subject": subject,
        "receivedDateTime": "2026-10-01T09:00:00Z",
        "from": {"emailAddress": {"name": "Sender", "address": "sender@fabrikam.com"}},
        "body": {"contentType": "text", "content": "body text"},
        "hasAttachments": True,
        "attachments": [
            {
                "id": f"att{i}",
                "name": att["name"],
                "contentType": "application/octet-stream",
                "@odata.type": "#microsoft.graph.fileAttachment",
                "contentBytes": b64(att["data"]),
            }
            for i, att in enumerate(attachments)
        ],
    }


def batch_router(mails_by_token: Dict[str, Dict[str, Any]]) -> Router:
    """$batch POST 에 Authorization 토큰별 메일을 돌려준다(토큰 → 사용자)."""

    def _route(call: Call) -> FakeResponse:
        if call.method == "POST" and call.url.endswith("/$batch"):
            token = (call.authorization or "").replace("Bearer ", "")
            mail = mails_by_token.get(token)
            if mail is None:
                return FakeResponse(401, text='{"error":{"code":"InvalidAuthenticationToken"}}')
            return FakeResponse(200, {"responses": [{"id": "1", "status": 200, "body": mail}]})
        return FakeResponse(404, text='{"error":{"code":"ResourceNotFound"}}')

    return _route


def user_files(paths) -> List[Path]:
    return sorted(p for p in Path(paths.files).rglob("*") if p.is_file())


@pytest.fixture
def mu(tmp_path):
    """멀티유저 모드 + 임시 데이터 루트."""
    with multi_user_mode(tmp_path) as root:
        yield root


@pytest.fixture
def alice():
    return make_principal(ALICE_EMAIL)


@pytest.fixture
def bob():
    return make_principal(BOB_EMAIL)


@pytest.fixture
def alice_paths(mu, alice):
    return ensure_user_dirs(paths_for(alice))


@pytest.fixture
def bob_paths(mu, bob):
    return ensure_user_dirs(paths_for(bob))


@pytest.fixture
def alice_tokens(alice):
    return FakeTokenProvider(alice)


@pytest.fixture
def bob_tokens(bob):
    return FakeTokenProvider(bob)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """`check_presigned_url` 의 DNS 해석을 공개 주소로 고정한다 — 테스트는 네트워크를 타지 않는다."""
    import ipaddress

    from mcp_common import graph_url_policy

    monkeypatch.setattr(
        graph_url_policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("13.107.136.10")]
    )


@pytest.fixture
def no_shared_auth(monkeypatch):
    """mode 1 경로에서 공유 AuthManager 를 얻으려 하면 즉시 실패시킨다."""
    calls: List[str] = []

    def _forbidden():
        calls.append("get_shared_auth_manager")
        raise AssertionError("get_shared_auth_manager() must not be called in multi-user mode")

    monkeypatch.setattr("mcp_common.auth.get_shared_auth_manager", _forbidden)
    return calls


__all__ = [
    "ALICE_EMAIL",
    "BOB_EMAIL",
    "Call",
    "FakeResponse",
    "FakeSession",
    "HttpRecorder",
    "install_http",
    "b64",
    "mail_with_attachments",
    "batch_router",
    "user_files",
    "mu",
    "alice",
    "bob",
    "alice_paths",
    "bob_paths",
    "alice_tokens",
    "bob_tokens",
    "public_dns",
    "no_shared_auth",
]
