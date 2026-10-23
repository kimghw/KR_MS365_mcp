"""FileHandler 멀티유저 테스트 공용 fixture (네트워크 없음).

- `mu`: `MS365_MULTI_USER=1` + tmp 데이터 루트 + 서비스 풀(FakeTokenProvider) + 가짜 Graph.
  경로 관문은 실제 `mcp_common.paths`(mode 1 = 현재 principal 의 files/)를 그대로 쓴다.
- `FakeGraph`: 토큰(=사용자)별 OneDrive. 다른 사용자 토큰으로 항목을 열면 404,
  사전 서명 다운로드 URL 에 bearer 가 붙으면 400 (G02).
- `RecordingConverter`: `.txt` 변환기. 읽은 경로·내용·스레드 안의 principal/scope 를 기록한다.
"""

import base64
import ipaddress
import re
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import unquote

import pytest
import requests

from mcp_common import graph_url_policy
from mcp_common.principal import Principal, current_principal
from mcp_common.service_context import bind_service
from mcp_common.service_pool import UserServicePool
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode
from mcp_common.user_paths import UserPaths, paths_for

from mcp_file_handler.base_converter import BaseConverter
from mcp_file_handler.config.settings import PATH_ENV, STORAGE_ENV
from mcp_file_handler.mcp_server import handlers
from mcp_file_handler.onedrive import client as client_module
from mcp_file_handler.request_scope import current_scope

DOWNLOAD_BASE = "https://download.example.invalid/presigned/"


def token_for(principal: Principal) -> str:
    """FakeTokenProvider 의 기본 토큰 값."""
    return f"fake-token-{principal.user_key[:8]}"


# ----------------------------------------------------------------------
# fake Graph
# ----------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status_code=200, *, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}
        self.ok = status_code < 400
        self.chunks_served = 0   # 스트림이 상한에서 실제로 끊겼는지 확인용 (R09)
        self.closed = False

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), max(1, chunk_size)):
            self.chunks_served += 1
            yield self.content[i:i + chunk_size]

    def close(self):
        self.closed = True


class FakeGraph:
    def __init__(self):
        self._lock = threading.Lock()
        self._n = 0
        self.items: Dict[str, Dict[str, Any]] = {}
        self.shares: Dict[tuple, str] = {}
        self.calls: List[tuple] = []
        # R08 시나리오용: /content 의 Location 을 바꾸거나, 사전 서명 URL 이 다시 redirect 하게 한다
        self.location_override: Optional[str] = None
        self.presigned_redirect_to: Optional[str] = None
        self.declared_length: Dict[str, int] = {}   # item_id → Content-Length 헤더 값 (R09)
        self.download_responses: List[FakeResponse] = []

    def _new(self, token: str, name: str, **extra) -> str:
        with self._lock:
            self._n += 1
            item_id = f"item{self._n}!{token[-8:]}"
        self.items[item_id] = {"token": token, "name": name, **extra}
        return item_id

    def add_file(self, principal: Principal, share_url: str, name: str, content: bytes) -> str:
        token = token_for(principal)
        item_id = self._new(token, name, content=content)
        self.shares[(token, share_url)] = item_id
        return item_id

    def _build(self, token: str, entry) -> str:
        kind, name, payload = entry
        if kind == "file":
            return self._new(token, name, content=payload)
        children = [self._build(token, child) for child in payload]
        return self._new(token, name, children=children)

    def add_folder(self, principal: Principal, share_url: str, name: str, children: list) -> str:
        token = token_for(principal)
        item_id = self._build(token, ("folder", name, children))
        self.shares[(token, share_url)] = item_id
        return item_id

    def _meta(self, item_id: str) -> Dict[str, Any]:
        item = self.items[item_id]
        meta = {"id": item_id, "name": item["name"]}
        if "children" in item:
            meta["folder"] = {"childCount": len(item["children"])}
        else:
            meta["size"] = len(item["content"])
        return meta

    def get(self, url, headers=None, allow_redirects=True, stream=False, timeout=None, **_kw):
        auth = (headers or {}).get("Authorization")
        with self._lock:
            self.calls.append((url, auth))
        if url.startswith(DOWNLOAD_BASE):
            if auth is not None:
                return FakeResponse(400)  # 사전 서명 URL 에 Graph bearer 금지
            if self.presigned_redirect_to:
                return FakeResponse(302, headers={"Location": self.presigned_redirect_to})
            item_id = url[len(DOWNLOAD_BASE):]
            headers = {}
            if item_id in self.declared_length:
                headers["Content-Length"] = str(self.declared_length[item_id])
            response = FakeResponse(200, content=self.items[item_id]["content"], headers=headers)
            self.download_responses.append(response)
            return response
        token = auth.split(" ", 1)[1] if auth and auth.startswith("Bearer ") else None
        if "/shares/u!" in url:
            encoded = url.split("/shares/u!", 1)[1].split("/", 1)[0]
            share_url = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
            item_id = self.shares.get((token, share_url))
            if item_id is None:
                return FakeResponse(404)
            return FakeResponse(200, json_data=self._meta(item_id))
        match = re.search(r"/me/drive/items/([^/]+)(/children|/content)?$", url)
        if not match:
            return FakeResponse(404)
        item_id = unquote(match.group(1))
        item = self.items.get(item_id)
        if item is None or item["token"] != token:
            return FakeResponse(404)
        if match.group(2) == "/children":
            return FakeResponse(200, json_data={"value": [self._meta(c) for c in item["children"]]})
        if match.group(2) == "/content":
            location = self.location_override or (DOWNLOAD_BASE + item_id)
            return FakeResponse(302, headers={"Location": location})
        return FakeResponse(200, json_data=self._meta(item_id))

    def tokens_used_for(self, fragment: str) -> set:
        return {auth for url, auth in self.calls if fragment in url}


# ----------------------------------------------------------------------
# recording converter
# ----------------------------------------------------------------------
class RecordingConverter(BaseConverter):
    def __init__(self, hook: Optional[Callable[[str], None]] = None):
        super().__init__()
        self.hook = hook
        self.calls: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def supports(self, file_path: str) -> bool:
        return str(file_path).lower().endswith(".txt")

    def convert(self, file_path: str) -> str:
        if self.hook is not None:
            self.hook(file_path)
        data = Path(file_path).read_bytes()
        principal = current_principal()
        scope = current_scope()
        with self._lock:
            self.calls.append({
                "path": Path(file_path),
                "content": data,
                "user_key": principal.user_key if principal else None,
                "work_dir": scope.work_dir if scope else None,
                "thread": threading.get_ident(),
            })
        return data.decode("utf-8")


def install_converter(service, converter: RecordingConverter) -> RecordingConverter:
    service.manager.file_detector.converters.insert(0, converter)
    return converter


# ----------------------------------------------------------------------
# multi-user environment
# ----------------------------------------------------------------------
@dataclass
class MultiUserEnv:
    root: Path
    pool: UserServicePool
    graph: FakeGraph
    alice: Principal
    bob: Principal

    def paths(self, principal: Principal) -> UserPaths:
        return paths_for(principal)

    @asynccontextmanager
    async def leased(self, principal: Principal, request_id: Optional[str] = None):
        """WP1 런타임이 하는 일 — identity bind → 풀 lease → 서비스 bind."""
        with bound(principal, request_id):
            async with self.pool.lease(handlers.SERVER_NAME, principal) as service:
                with bind_service(handlers.SERVER_NAME, service):
                    yield service


@pytest.fixture(autouse=True)
def _fresh_worker_registry():
    """프로세스 전역 사용자별 변환 슬롯을 테스트마다 비운다 (살아 있는 스레드는 자기 슬롯 객체를 쥔다)."""
    from mcp_file_handler.conversion_workers import reset_registry_for_tests

    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


@pytest.fixture
def clean_config_env(tmp_path, monkeypatch):
    """FileHandler 경로 환경변수·홈/CWD config 의 영향을 없앤다."""
    for name in PATH_ENV + (STORAGE_ENV,):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return {"home": home, "cwd": cwd}


@pytest.fixture
async def mu(tmp_path, monkeypatch, clean_config_env):
    data_root = tmp_path / "data"
    data_root.mkdir()
    graph = FakeGraph()
    monkeypatch.setattr(client_module.requests, "get", graph.get)
    # 가짜 다운로드 호스트는 DNS 에 없다 — 공인 주소로 해석되는 것으로 고정 (공용 사전 서명 정책은 그대로 돈다)
    monkeypatch.setattr(graph_url_policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("8.8.8.8")])
    with multi_user_mode(data_root) as root:
        pool = UserServicePool(token_provider_factory=FakeTokenProvider)
        pool.register(handlers.SERVER_NAME, handlers.create_service)
        env = MultiUserEnv(
            root=root,
            pool=pool,
            graph=graph,
            alice=make_principal("alice@contoso.com"),
            bob=make_principal("bob@contoso.com"),
        )
        try:
            yield env
        finally:
            await pool.close()
