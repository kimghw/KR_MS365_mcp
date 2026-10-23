"""FileHandler 멀티유저 배선 회귀 — 서비스 factory·인증 경로·설정·health·C03.

- mode 1 경로는 AuthManager 를 만들거나 빌리지 않는다 (②-2.2).
- 동기 작업은 작업 스레드에서 호출자 provider·경로를 유지하고, 컨텍스트가 없으면 실패한다 (C03).
- `executor.submit(asyncio.run, …)` 브리지 없이 토큰 코루틴은 요청 이벤트 루프에서 돈다 (②-5.2).
- JSON 저장소·경로 확장 설정은 mode 1 에서 오류다 (②-7.3, ②-7.4, F07).
- health 보안 고지에 절대경로가 없다 (②-2.7).
"""

import base64
import importlib.util
import json
import sys
import threading
import types
from pathlib import Path

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError
from mcp_common.service_context import bind_service
from mcp_common.service_pool import register_service_factory
from mcp_common.testing import FakeTokenProvider, bound, make_principal, multi_user_mode
from mcp_common.user_paths import ensure_user_dirs, paths_for

import mcp_file_handler.file_manager as file_manager_module
from mcp_file_handler.config.settings import Settings, STORAGE_ENV, validate_multi_user_config
from mcp_file_handler.converters.image import ocr_converter as ocr_module
from mcp_file_handler.converters.image.ocr_converter import OCRConverter, ocr_image
from mcp_file_handler.file_manager import FileManager
from mcp_file_handler.mcp_server import handlers
from mcp_file_handler.metadata.manager import MetadataManager
from mcp_file_handler.onedrive import client as client_module
from mcp_file_handler.request_scope import FileRequestScope, bind_scope
from mcp_file_handler.service import FileHandlerService

from .conftest import DOWNLOAD_BASE, FakeGraph, RecordingConverter, install_converter, token_for

SHARE_A = "https://contoso-my.sharepoint.com/:t:/g/personal/alice/AAA"
SHARE_B = "https://contoso-my.sharepoint.com/:t:/g/personal/bob/BBB"


def _within(path, root) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _share_fragment(url: str) -> str:
    return "/shares/u!" + base64.urlsafe_b64encode(url.encode()).rstrip(b"=").decode()


# ----------------------------------------------------------------------
# AuthManager 미생성
# ----------------------------------------------------------------------
async def test_mode1_path_never_constructs_auth_manager(mu, monkeypatch):
    events = []

    class ExplodingAuthManager:
        def __init__(self, *args, **kwargs):
            events.append("AuthManager()")
            raise AssertionError("AuthManager constructed in mode 1")

    def explode(*args, **kwargs):
        events.append("shared")
        raise AssertionError("shared AuthManager requested in mode 1")

    stub = types.ModuleType("session.auth_manager")
    stub.AuthManager = ExplodingAuthManager
    stub.get_default_auth_manager = explode
    monkeypatch.setitem(sys.modules, "session.auth_manager", stub)
    import mcp_common.auth as common_auth

    monkeypatch.setattr(common_auth, "get_shared_auth_manager", explode)

    # 모듈 수준에서 AuthManager 를 끌어오지 않는다
    assert not hasattr(file_manager_module, "AuthManager")
    assert not hasattr(client_module, "AuthManager")

    # handlers.py 를 mode 1 에서 새로 실행해 본다 (모듈 캐시는 건드리지 않음)
    spec = importlib.util.spec_from_file_location(
        "mcp_file_handler.mcp_server._handlers_mode1_probe", handlers.__file__
    )
    probe = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(probe)
        assert probe.file_manager_service is None
        assert probe.lifecycle.services == []

        mu.pool.register(probe.SERVER_NAME, probe.create_service)
        mu.graph.add_file(mu.alice, SHARE_A, "a.txt", b"hello")
        with bound(mu.alice):
            async with mu.pool.lease(probe.SERVER_NAME, mu.alice) as service:
                with bind_service(probe.SERVER_NAME, service):
                    install_converter(service, RecordingConverter())
                    converted = await probe.handle_convert_onedrive_to_text({"url": SHARE_A})
                    saved = await probe.handle_save_file_metadata(
                        {"file_url": SHARE_A, "keywords": ["k"]}
                    )
                    found = await probe.handle_search_metadata({})
                    assert "get_graph_token" in service._tokens.calls
    finally:
        register_service_factory(handlers.SERVER_NAME, handlers.create_service)

    assert converted["success"] and converted["text"].endswith("hello")
    assert saved["success"] and found["count"] == 1
    assert events == []


async def test_create_service_constructs_only(mu):
    paths = ensure_user_dirs(paths_for(mu.alice))
    service = await handlers.create_service(mu.alice, paths, FakeTokenProvider(mu.alice))
    assert isinstance(service, FileHandlerService)
    assert service._manager is None and not paths.metadata_db.exists()
    service.initialize()
    assert paths.metadata_db.exists()
    await service.close()


async def test_service_rejects_mismatched_user_binding(mu):
    paths = paths_for(mu.alice)
    with pytest.raises(SecurityError) as err:
        FileHandlerService(principal=mu.alice, paths=paths, tokens=FakeTokenProvider(mu.bob))
    assert err.value.code == ErrorCode.CONFIG_ERROR
    with pytest.raises(SecurityError):
        FileHandlerService(principal=mu.alice, paths=paths_for(mu.bob), tokens=FakeTokenProvider(mu.alice))
    with pytest.raises(SecurityError):
        FileManager()  # mode 1 에서 경로·공급자 없는 FileManager 금지


async def test_handlers_fail_closed_without_lease(mu):
    with bound(mu.alice):
        with pytest.raises(SecurityError) as err:
            await handlers.handle_search_metadata({})
    assert err.value.code == ErrorCode.MISSING_PRINCIPAL


# ----------------------------------------------------------------------
# 저장소·설정
# ----------------------------------------------------------------------
async def test_json_storage_refused_at_service_creation(mu, monkeypatch):
    monkeypatch.setenv(STORAGE_ENV, "json")
    with pytest.raises(SecurityError) as err:
        async with mu.leased(mu.alice):
            pass
    assert err.value.code == ErrorCode.CONFIG_ERROR
    monkeypatch.delenv(STORAGE_ENV)

    paths = paths_for(mu.alice)
    with pytest.raises(SecurityError) as err:
        FileHandlerService(
            principal=mu.alice, paths=paths, tokens=FakeTokenProvider(mu.alice),
            config={"metadata_storage": "json"},
        )
    assert err.value.code == ErrorCode.CONFIG_ERROR
    with pytest.raises(SecurityError):
        MetadataManager({"metadata_storage": "json", "metadata_path": str(paths.metadata_db)})
    assert not list(mu.root.rglob("*.json"))


def test_settings_mode1_pins_user_paths(tmp_path, clean_config_env):
    alice = make_principal("alice@contoso.com")
    with multi_user_mode(tmp_path / "data"):
        paths = paths_for(alice)
        settings = Settings(paths=paths)
        assert settings["output_dir"] == str(paths.output)
        assert settings["temp_dir"] == str(paths.tmp)
        assert settings["onedrive_temp_dir"] == str(paths.tmp)
        assert settings["download_dir"] == str(paths.downloads_for("file_handler"))
        assert settings["metadata_path"] == str(paths.metadata_db)
        assert settings["metadata_storage"] == "sqlite"
        assert settings["log_file"] is None
        assert not (clean_config_env["cwd"] / "output").exists()  # 공용 ./output 을 만들지 않는다

        with pytest.raises(SecurityError):
            Settings()
        with pytest.raises(SecurityError):
            Settings({"output_dir": str(tmp_path / "elsewhere")}, paths=paths)


def test_f07_env_and_home_cwd_config_block_mode1_startup(tmp_path, monkeypatch, clean_config_env):
    home_cfg = clean_config_env["home"] / ".mcp_file_handler" / "config.json"
    cwd_cfg = clean_config_env["cwd"] / "config.json"
    with multi_user_mode(tmp_path / "data"):
        validate_multi_user_config()  # 깨끗하면 통과

        monkeypatch.setenv("MCP_ATTACHMENT_OUTPUT_DIR", str(tmp_path / "shared-out"))
        with pytest.raises(StartupConfigError):
            validate_multi_user_config()
        monkeypatch.delenv("MCP_ATTACHMENT_OUTPUT_DIR")

        cwd_cfg.write_text(json.dumps({"temp_dir": str(tmp_path / "shared-tmp")}), encoding="utf-8")
        with pytest.raises(StartupConfigError) as err:
            validate_multi_user_config()
        assert str(tmp_path) not in str(err.value)

        cwd_cfg.write_text(json.dumps({"ocr_lang": "kor"}), encoding="utf-8")
        validate_multi_user_config()  # 경로가 아닌 설정은 허용
        assert Settings(paths=paths_for(make_principal())).get("ocr_lang") == "kor"

        home_cfg.parent.mkdir(parents=True)
        home_cfg.write_text(json.dumps({"metadata_path": "metadata.db"}), encoding="utf-8")
        with pytest.raises(StartupConfigError):
            validate_multi_user_config()
        home_cfg.write_text("{not json", encoding="utf-8")
        with pytest.raises(StartupConfigError):
            validate_multi_user_config()

    validate_multi_user_config()  # mode 0 에서는 검사하지 않는다(기존 동작)


def test_health_payload_never_lists_absolute_roots(tmp_path, monkeypatch, clean_config_env):
    monkeypatch.setenv("MCP_ALLOWED_PATHS", str(tmp_path / "allowed"))
    payload = handlers.security_payload()
    assert "allowed_roots" not in payload
    assert payload["allowed_root_count"] == 1
    assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)

    monkeypatch.delenv("MCP_ALLOWED_PATHS")
    with multi_user_mode(tmp_path / "data"):
        payload = handlers.security_payload()
        assert payload["caller_authentication"] == "bearer (per-user)"
        assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)


# ----------------------------------------------------------------------
# C03 — 스레드 작업의 컨텍스트
# ----------------------------------------------------------------------
async def test_c03_thread_work_keeps_callers_provider_and_paths(mu):
    mu.graph.add_file(mu.alice, SHARE_A, "a.txt", b"from-alice")
    mu.graph.add_file(mu.bob, SHARE_B, "b.txt", b"from-bob")
    loop_thread = threading.get_ident()

    async def run(principal, url):
        async with mu.leased(principal) as service:
            conv = install_converter(service, RecordingConverter())
            return await handlers.handle_convert_onedrive_to_text({"url": url}), conv

    import asyncio

    (res_a, conv_a), (res_b, conv_b) = await asyncio.gather(
        run(mu.alice, SHARE_A), run(mu.bob, SHARE_B)
    )
    assert res_a["text"].endswith("from-alice") and res_b["text"].endswith("from-bob")
    for conv, principal in ((conv_a, mu.alice), (conv_b, mu.bob)):
        (call,) = conv.calls
        assert call["user_key"] == principal.user_key
        assert call["thread"] != loop_thread          # 변환은 작업 스레드에서
        assert _within(call["path"], mu.paths(principal).tmp)

    # Graph 호출마다 그 사용자의 토큰 — 사전 서명 URL 에는 bearer 없음 (G02)
    assert mu.graph.tokens_used_for(_share_fragment(SHARE_A)) == {f"Bearer {token_for(mu.alice)}"}
    assert mu.graph.tokens_used_for(_share_fragment(SHARE_B)) == {f"Bearer {token_for(mu.bob)}"}
    assert mu.graph.tokens_used_for(DOWNLOAD_BASE) == {None}


async def test_c03_missing_or_foreign_context_fails(mu):
    async with mu.leased(mu.alice) as service:
        manager = service.manager
        client = manager.onedrive_processor.client
        # 이벤트 루프 스레드에서 동기 토큰 요청 → 오류 (숨은 스레드·새 루프를 만들지 않는다)
        with pytest.raises(RuntimeError):
            client._get_access_token()

    outcomes = []

    def bare():
        for fn in (
            lambda: manager.search_metadata(),
            lambda: manager.process("uploads/x.txt"),
            lambda: manager.process_onedrive(SHARE_A),
            lambda: client._get_access_token(),
            lambda: ocr_image(object()),
        ):
            try:
                fn()
                outcomes.append("ran")
            except SecurityError as exc:
                outcomes.append(exc.code)

    def foreign():
        # B 의 principal 로 A 의 서비스를 쓰려 하면 실패
        with bound(mu.bob), bind_scope(FileRequestScope(owner_key=mu.alice.user_key)):
            try:
                manager.search_metadata()
                outcomes.append("ran")
            except SecurityError as exc:
                outcomes.append(exc.code)

    for target in (bare, foreign):
        thread = threading.Thread(target=target)
        thread.start()
        thread.join(10)
    assert outcomes == [ErrorCode.MISSING_PRINCIPAL] * 6


def _install_fake_ocr_stack(monkeypatch):
    class FakeImage:
        mode = "RGB"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def save(self, fp, format=None):
            if hasattr(fp, "write"):
                fp.write(b"PNG")
            else:
                Path(fp).write_bytes(b"PNG")

        def convert(self, mode):
            return self

        def filter(self, _f):
            return self

    pil = types.ModuleType("PIL")
    image_mod = types.ModuleType("PIL.Image")
    image_mod.open = lambda path: FakeImage()
    enhance = types.ModuleType("PIL.ImageEnhance")

    class Contrast:
        def __init__(self, image):
            self.image = image

        def enhance(self, _factor):
            return self.image

    enhance.Contrast = Contrast
    image_filter = types.ModuleType("PIL.ImageFilter")
    image_filter.SHARPEN = object()
    pil.Image, pil.ImageEnhance, pil.ImageFilter = image_mod, enhance, image_filter

    tess = types.ModuleType("pytesseract")
    tess.pytesseract = types.SimpleNamespace(tesseract_cmd="tesseract-fake")

    def system_temp_path(*args, **kwargs):
        raise AssertionError("pytesseract (system temp) used in mode 1")

    tess.image_to_string = system_temp_path
    for name, module in (("PIL", pil), ("PIL.Image", image_mod), ("PIL.ImageEnhance", enhance),
                         ("PIL.ImageFilter", image_filter), ("pytesseract", tess)):
        monkeypatch.setitem(sys.modules, name, module)

    runs = []

    def fake_run(cmd, capture_output, cwd, env, timeout, check):
        runs.append({"cmd": cmd, "cwd": cwd, "temp": env["TEMP"], "tmp": env["TMP"],
                     "input_exists": Path(cmd[1]).exists()})
        return types.SimpleNamespace(returncode=0, stdout=b"ocr text", stderr=b"")

    monkeypatch.setattr(ocr_module.subprocess, "run", fake_run)
    return runs


async def test_c03_ocr_temp_files_stay_in_request_dir(mu, monkeypatch):
    runs = _install_fake_ocr_stack(monkeypatch)
    paths = mu.paths(mu.alice)
    paths.uploads.mkdir(parents=True, exist_ok=True)
    (paths.uploads / "scan.png").write_bytes(b"fake-image")

    async with mu.leased(mu.alice) as service:
        result = await handlers.handle_convert_file_to_text({"input_path": "uploads/scan.png"})
        preprocessed = await service._run(
            OCRConverter().preprocess_image, str(paths.uploads / "scan.png"), work_dir=True
        )

    assert result["success"], result
    assert result["text"] == "ocr text"
    (run,) = runs
    assert _within(run["cwd"], paths.tmp) and Path(run["cwd"]) != paths.tmp
    assert run["temp"] == run["cwd"] == run["tmp"]
    assert run["input_exists"] and _within(run["cmd"][1], run["cwd"])
    assert preprocessed is not None and _within(preprocessed, paths.tmp)
    assert list(paths.tmp.iterdir()) == []  # 요청이 끝나면 OCR 임시파일까지 정리


# ----------------------------------------------------------------------
# mode 0 — 기존 동작 유지 + 브리지 제거
# ----------------------------------------------------------------------
async def test_mode0_service_uses_loop_bridge_and_legacy_storage(tmp_path, monkeypatch, clean_config_env):
    graph = FakeGraph()
    import ipaddress

    from mcp_common import graph_url_policy

    monkeypatch.setattr(client_module.requests, "get", graph.get)
    monkeypatch.setattr(graph_url_policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("8.8.8.8")])
    owner = make_principal("legacy@contoso.com")
    graph.add_file(owner, SHARE_A, "a.txt", b"legacy-content")
    loop_thread = threading.get_ident()
    token_threads = []

    class LegacyAuth:
        async def validate_and_refresh_token(self, *args, **kwargs):
            token_threads.append(threading.get_ident())
            return token_for(owner)

    config = {
        "temp_dir": str(tmp_path / "t"),
        "output_dir": str(tmp_path / "o"),
        "onedrive_temp_dir": str(tmp_path / "od"),
        "metadata_path": str(tmp_path / "legacy.db"),
    }
    service = FileHandlerService(config=config)
    service._manager = FileManager(config, auth_manager=LegacyAuth())
    install_converter(service, RecordingConverter())

    converted = await service.process_onedrive(SHARE_A)
    assert converted["success"] and converted["text"].endswith("legacy-content")
    # 토큰 코루틴은 요청 이벤트 루프 스레드에서 돈다 (새 루프를 다른 스레드에 만들지 않는다)
    assert token_threads and set(token_threads) == {loop_thread}

    monkeypatch.setenv("MCP_ALLOWED_PATHS", str(tmp_path))
    local = tmp_path / "x.txt"
    local.write_text("local", encoding="utf-8")
    assert (await service.process(str(local)))["text"] == "local"
    assert (await service.save_metadata(str(local), ["k"]))["success"]
    got = await service.get_metadata(str(local))
    assert got["found"] and got["file_url"] == str(local.resolve())  # mode 0 키는 기존처럼 절대경로
    assert got["metadata"]["keywords"] == ["k"]
    outside = await service.process(str(tmp_path.parent / "nope.txt"))
    assert outside["success"] is False and "허용되지 않은 경로" in outside["errors"][0]
