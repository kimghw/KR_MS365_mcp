"""
프로세스 부트스트랩 — 모든 MCP 서버가 기동 직후 거치는 준비 절차 한 벌.

각 도메인 서버(`server_stdio.py` / `server_stream.py`)는 `.env` 로드, env 값의 BOM 제거,
`sys.path` 조작, stdout 보호, 로깅 설정을 파일마다 복붙해 갖고 있었고 판본이 갈렸다
(spec/spec_MCP트랜스포트.md ③-6). 그 20여 줄을 여기로 모은다.

**순서가 계약이다.** 아래 순서를 바꾸면 조용히 깨진다:

1. 원본 stdout 보관 → `sys.stdout = sys.stderr` (stdio 만) — 서비스 모듈의 `print()` 가
   JSON-RPC 스트림을 오염시키지 않도록 **가장 먼저** 해야 한다.
2. `.env` 로드 (`encoding="utf-8-sig"`)
3. **전체 env 값의 BOM 제거** — `AZURE_*` 몇 개만 훑는 방식은 금지(②-5)
4. `sys.path` 삽입 (패키지 디렉터리 → 프로젝트 루트)
5. 로깅 설정 — **stderr 로만**
6. 그 다음에야 서비스 모듈을 import 한다

## 사용 패턴

`mcp_common` 자체를 import 하려면 프로젝트 루트가 먼저 `sys.path` 에 있어야 하므로,
서버 파일 선두에 최소 전문(preamble) 3줄이 필요하다.

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from mcp_common.bootstrap import bootstrap_stdio   # 또는 bootstrap_http

    BOOT = bootstrap_stdio(__file__, package_name="mcp_onedrive")

    # ↓ 서비스 모듈 import 는 반드시 bootstrap 호출 뒤에
    from mcp_onedrive.onedrive_service import OneDriveService

`mcp_common` 패키지는 import 시점에 stdout 으로 아무것도 쓰지 않으므로 전문 단계에서
읽어도 안전하다.

## 자격증명

`.env` 로드 결과를 로그로 남기되 **값은 남기지 않는다.** 기존 서버들이
`repr(os.getenv('AZURE_CLIENT_ID'))` 를 stderr 로 찍던 디버그 print 는 여기서
존재 여부(bool)로 대체한다(②-5).
"""

import logging
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, TextIO

logger = logging.getLogger(__name__)

# UTF-8 BOM. utf-8-sig 로 읽어도 값 안쪽에 남는 경우가 있어 별도로 훑는다.
_BOM = "﻿"

# 존재 여부만 로그로 남길 키 (값은 절대 남기지 않는다).
_CREDENTIAL_KEYS = (
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_TENANT_ID",
)


@dataclass(frozen=True)
class Bootstrap:
    """부트스트랩 결과. 서버 파일이 이후 단계에서 쓸 값만 담는다."""

    project_root: str
    package_dir: str
    server_dir: str
    env_path: str
    env_loaded: bool
    #: stdio 에서 JSON-RPC 를 실제로 내보낼 원본 stdout. http 에서는 None.
    original_stdout: Optional[TextIO] = None

    def original_stdout_buffer(self):
        """SDK `stdio_server(stdout=...)` 에 넘길 바이너리 버퍼.

        SDK 는 `sys.stdout.buffer` 를 직접 감싸는데(`mcp/server/stdio.py`), 우리는 이미
        `sys.stdout` 을 stderr 로 돌려놨으므로 그대로 두면 JSON-RPC 가 stderr 로 나간다.
        반드시 이 버퍼를 명시 주입해야 한다(spec ④-1-1).
        """
        if self.original_stdout is None:
            raise RuntimeError("bootstrap_stdio() 로 초기화한 경우에만 쓸 수 있다")
        return self.original_stdout.buffer


def _reconfigure(stream: Optional[TextIO]) -> None:
    """Windows 콘솔 기본 인코딩(cp949)이 한글 도구 설명을 깨뜨리는 것을 막는다."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        # 파이프로 묶인 경우 등 재설정이 불가능한 스트림은 그대로 둔다.
        pass


def _strip_env_bom() -> List[str]:
    """모든 환경변수 값 앞의 BOM 을 제거하고, 손본 키 목록을 돌려준다."""
    touched: List[str] = []
    for key, value in list(os.environ.items()):
        if value and value.startswith(_BOM):
            os.environ[key] = value.lstrip(_BOM)
            touched.append(key)
    return touched


def _load_env(project_root: str) -> tuple:
    """프로젝트 루트의 `.env` 를 읽는다. 파일이 없어도 실패로 보지 않는다."""
    from dotenv import load_dotenv

    env_path = os.path.join(project_root, ".env")
    loaded = load_dotenv(env_path, encoding="utf-8-sig")
    return env_path, bool(loaded)


def _insert_paths(project_root: str, package_dir: str) -> None:
    """절대 import(`mcp_onedrive.x`)와 상대 import(`onedrive_service`)를 모두 성립시킨다.

    스크립트 실행 시 `sys.path[0]` 은 서버 파일 디렉터리이므로 그대로 둔다.
    최종 순서: [package_dir, project_root, server_dir, ...]
    """
    for path in (project_root, package_dir):
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)


def _configure_logging(level: int) -> None:
    """로그는 stderr 로만 나간다. stdio 에서 stdout 은 JSON-RPC 전용이다."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )


def _log_env_summary(env_path: str, env_loaded: bool, bom_keys: List[str]) -> None:
    present = [key for key in _CREDENTIAL_KEYS if os.environ.get(key)]
    missing = [key for key in _CREDENTIAL_KEYS if not os.environ.get(key)]
    logger.info(
        ".env %s (exists=%s, loaded=%s)",
        env_path,
        os.path.exists(env_path),
        env_loaded,
    )
    # 값이 아니라 존재 여부만 남긴다.
    logger.info("credentials present=%s missing=%s", present, missing)
    if bom_keys:
        logger.info("BOM stripped from env keys: %s", bom_keys)


def _common(
    server_file: str,
    package_name: str,
    log_level: int,
    original_stdout: Optional[TextIO],
) -> Bootstrap:
    server_dir = os.path.dirname(os.path.abspath(server_file))
    package_dir = os.path.dirname(server_dir)
    project_root = os.path.dirname(package_dir)

    if package_name and os.path.basename(package_dir) != package_name:
        # 파일을 옮겼는데 인자를 안 고친 경우를 조용히 넘기지 않는다.
        raise ValueError(
            f"package_name={package_name!r} 이 실제 디렉터리 "
            f"{os.path.basename(package_dir)!r} 와 다르다 ({server_file})"
        )

    env_path, env_loaded = _load_env(project_root)
    bom_keys = _strip_env_bom()
    _insert_paths(project_root, package_dir)
    _configure_logging(log_level)
    _log_env_summary(env_path, env_loaded, bom_keys)

    return Bootstrap(
        project_root=project_root,
        package_dir=package_dir,
        server_dir=server_dir,
        env_path=env_path,
        env_loaded=env_loaded,
        original_stdout=original_stdout,
    )


def bootstrap_stdio(
    server_file: str,
    *,
    package_name: str = "",
    log_level: int = logging.INFO,
) -> Bootstrap:
    """stdio 서버용 부트스트랩. **서비스 모듈 import 보다 먼저 호출해야 한다.**

    stdout 을 stderr 로 돌려 임포트된 모듈의 `print()` 가 JSON-RPC 스트림을 오염시키지
    못하게 하고, 원본 stdout 은 `Bootstrap.original_stdout` 으로 돌려준다.
    """
    original_stdout = sys.stdout
    _reconfigure(original_stdout)
    _reconfigure(sys.stdin)
    _reconfigure(sys.stderr)
    # 여기서부터 print() 는 전부 stderr 로 간다.
    sys.stdout = sys.stderr

    return _common(server_file, package_name, log_level, original_stdout)


def bootstrap_http(
    server_file: str,
    *,
    package_name: str = "",
    log_level: int = logging.INFO,
) -> Bootstrap:
    """Streamable HTTP 서버용 부트스트랩.

    stdout 이 프로토콜 채널이 아니므로 리다이렉트하지 않는다. 나머지 순서는 stdio 와 같다.
    """
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)

    return _common(server_file, package_name, log_level, None)


__all__ = ["Bootstrap", "bootstrap_stdio", "bootstrap_http"]
