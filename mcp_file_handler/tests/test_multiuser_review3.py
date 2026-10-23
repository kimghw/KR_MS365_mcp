"""astra 3차 보안 리뷰(2026-10-23) FileHandler 항목 회귀 — N01(읽기 경로)·N03·N05.

- N01: `/content` 302 뒤 사전 서명 GET 직전에 호출자 활성 상태를 재확인한다 — 폐기되면 GET 이 나가지 않는다.
- N03: hard cap 뒤에도 converter 가 살아 있으면 `close()` 는 실패(RuntimeError)로 보고한다.
- N05: 사전 서명 URL 정책은 공용 `check_presigned_url` (DNS 실패·단일 라벨 거부) — 회귀는
  `test_multiuser_review.py::test_r08_*` 가 공용 정책 기준으로 갱신됐다.
"""

import threading

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.service_context import bind_service
from mcp_common.testing import FakeTokenProvider, bound
from mcp_common.user_paths import ensure_user_dirs, paths_for

from mcp_file_handler import conversion_workers
from mcp_file_handler.limits import LimitExceeded
from mcp_file_handler.mcp_server import handlers
from mcp_file_handler.onedrive import client as client_module
from mcp_file_handler.service import FileHandlerService

from .conftest import DOWNLOAD_BASE, RecordingConverter, install_converter
from .test_multiuser_review import SHARE_A, _upload
from .test_multiuser_review2 import _wait_until


async def test_n01_presigned_get_is_not_sent_after_revocation(mu, monkeypatch):
    mu.graph.add_file(mu.alice, SHARE_A, "a.txt", b"payload")
    original_get = mu.graph.get
    holder = {}

    def revoking_get(url, headers=None, **kwargs):
        response = original_get(url, headers=headers, **kwargs)
        if url.endswith("/content"):
            holder["provider"].connected = False  # 302 를 받은 직후 호출자가 폐기된다
        return response

    monkeypatch.setattr(client_module.requests, "get", revoking_get)
    async with mu.leased(mu.alice) as service:
        holder["provider"] = service._tokens
        install_converter(service, RecordingConverter())
        with pytest.raises(SecurityError) as err:
            await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
    assert err.value.code == ErrorCode.GRAPH_NOT_CONNECTED
    assert any(url.endswith("/content") for url, _ in mu.graph.calls)          # 302 까지는 갔다
    assert not any(url.startswith(DOWNLOAD_BASE) for url, _ in mu.graph.calls)  # 사전 서명 GET 은 없다
    assert list(mu.paths(mu.alice).tmp.iterdir()) == []


async def test_n01_active_recheck_happens_before_every_presigned_get(mu):
    mu.graph.add_file(mu.alice, SHARE_A, "a.txt", b"payload")
    async with mu.leased(mu.alice) as service:
        install_converter(service, RecordingConverter())
        provider = service._tokens
        before = provider.calls.count("get_graph_token")
        result = await handlers.handle_convert_onedrive_to_text({"url": SHARE_A})
        after = provider.calls.count("get_graph_token")
    assert result["success"]
    # 공유 URL 조회 1 + /content 1 + 사전 서명 GET 직전 재확인 1 = 최소 3회 토큰 획득
    assert after - before >= 3
    assert mu.graph.tokens_used_for(DOWNLOAD_BASE) == {None}


async def test_n03_close_reports_failure_while_converter_alive(mu, monkeypatch):
    monkeypatch.setattr(conversion_workers, "HARD_JOIN_CAP_SECONDS", 0.2)
    paths = ensure_user_dirs(paths_for(mu.alice))
    _upload(mu, mu.alice, "stuck.txt", b"stuck")
    release = threading.Event()

    def hook(path):
        assert release.wait(10)

    service = FileHandlerService(
        principal=mu.alice, paths=paths, tokens=FakeTokenProvider(mu.alice), config={"conversion_timeout": 1}
    )
    service.initialize()
    with bound(mu.alice), bind_service(handlers.SERVER_NAME, service):
        install_converter(service, RecordingConverter(hook))
        result = await handlers.handle_convert_file_to_text({"input_path": "uploads/stuck.txt"})
        assert LimitExceeded("conversion_timeout").message in result["errors"]
        assert service.live_converter_threads == 1

        with pytest.raises(RuntimeError, match="converter threads still alive"):
            await service.close()                      # 풀의 drain 이 실패로 기록할 수 있게 올린다
        assert service._manager is not None            # 실패한 close 는 FileManager 를 놓지 않는다
        assert any(group.cleanup_deferred for group in service._groups)  # 위임 정리는 유지
        assert [p for p in paths.tmp.iterdir() if p.is_dir()]

        release.set()
        assert await _wait_until(lambda: service.live_converter_threads == 0)
        await service.close()                          # 스레드가 끝난 뒤 재시도는 성공
        assert service._manager is None
    assert await _wait_until(lambda: list(paths.tmp.iterdir()) == [])
    assert conversion_workers.live_workers(mu.alice.user_key) == 0
