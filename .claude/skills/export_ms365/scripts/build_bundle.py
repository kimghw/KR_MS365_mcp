#!/usr/bin/env python3
"""MS365 MCP 서버 번들 스테이징 — 선택한 도메인 서버 + 공용 코드를 한 트리로 모은다.

산출물은 "그 자체로 기동되는 프로젝트"다. 원본 레이아웃(루트 기준 상대경로)을 그대로
유지하므로 `mcp_common.bootstrap` 의 sys.path 삽입, `param_spec` 의 `spec/param_spec`
해석, `session` 의 `database/auth.db` 경로가 손대지 않아도 성립한다.

무엇이 항상 들어가는가 (= 공용):
    mcp_common/  core/  session/  callback_server.py   ← 인증(OAuth/토큰/콜백)
    mcp_time/    spec/param_spec/time.yaml             ← 공용 time 서버
    .claude/skills/setup_ms365/                        ← 설치·운영 스킬
    uv.lock  .python-version  requirements.txt         ← 의존성 재현
    .env.example  .gitignore

무엇이 절대 안 들어가는가:
    .env  *.db  venv/  __pycache__/  *.log  output/  downloads/  .git/
    그리고 원본 `.env` 의 실제 값이 어딘가에 박혀 있으면 **빌드가 실패한다**(비밀 스캔).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 번들 구성 요소
# ---------------------------------------------------------------------------

#: 선택 가능한 도메인 서버. 포트는 spec/param_spec/<name>.yaml 의 server.port 에서 읽는다
#: (여기 적으면 두 벌이 된다).
SERVERS: dict[str, dict[str, str]] = {
    "outlook": {"package": "mcp_outlook", "spec": "outlook.yaml", "desc": "메일 조회·검색·발송·첨부"},
    "calendar": {"package": "mcp_calendar", "spec": "calendar.yaml", "desc": "일정 조회·생성·수정·삭제"},
    "teams": {"package": "mcp_teams", "spec": "teams.yaml", "desc": "채팅·채널 메시지"},
    "onedrive": {"package": "mcp_onedrive", "spec": "onedrive.yaml", "desc": "파일 목록·읽기·쓰기·이동"},
    "onenote": {"package": "mcp_onenote", "spec": "onenote.yaml", "desc": "노트 읽기·쓰기·DB 동기화"},
    "todo": {"package": "mcp_todo", "spec": "todo.yaml", "desc": "할 일 목록·작업"},
    "file_handler": {"package": "mcp_file_handler", "spec": "file_handler.yaml", "desc": "로컬 파일 변환·메타데이터"},
}

#: 사용자가 고르지 않아도 항상 들어가는 패키지. 인증(session)·공용 런타임(mcp_common)·
#: 프로토콜(core)·공용 time 서버(mcp_time).
COMMON_PACKAGES: tuple[str, ...] = ("mcp_common", "core", "session", "mcp_time")

#: 항상 들어가는 루트 단일 파일. callback_server 는 session/auth_manager 가 직접 import 한다.
#:
#: `uv.lock` 이 의존성 재현의 핵심이다 — 이게 빠지면 받은 쪽이 그날의 최신본을 받아 깨진다
#: (2026-09-16 에 mcp 2.x 가 깔려 6개 서버가 전부 기동 실패했다).
#: `requirements.txt` 는 uv 없이 pip 만 쓰는 사람을 위한 안전망이며 `uv export` 산출물이다.
#: `.python-version` 은 `uv sync` 가 받아올 Python 을 정한다.
COMMON_FILES: tuple[str, ...] = (
    "callback_server.py",
    ".env.example",
    ".gitignore",
    "uv.lock",
    "requirements.txt",
    ".python-version",
)

#: 항상 들어가는 도구 계약.
COMMON_SPECS: tuple[str, ...] = ("time.yaml",)

#: 항상 들어가는 스킬 (설치·운영).
COMMON_SKILLS: tuple[str, ...] = ("setup_ms365",)

#: 복사 시 건너뛸 이름/패턴. 디렉터리·파일 양쪽에 적용한다.
EXCLUDE_PATTERNS: tuple[str, ...] = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".git",
    ".mcp_pids",
    ".mcp_logs",
    "venv",
    ".venv",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    "*.bak",
    "*.backup",
    "backups_*",
    "*.pem",
    "*.pfx",
    "*.p12",
    "node_modules",
    ".DS_Store",
    "Thumbs.db",
)

#: 이름이 정확히 이것이면 제외 (`.env.example` 은 살린다).
EXCLUDE_EXACT: tuple[str, ...] = (".env", ".env.local", "auth.db", "metadata.db")

#: 텍스트 파일에서 찾아내면 빌드를 멈추는 패턴. 값 자리에 플레이스홀더가 오면 통과시킨다.
#: 키 뒤의 `['\"]?` 는 JSON(`"refresh_token": "..."`)처럼 키가 따옴표로 닫히는 경우를 위한
#: 것이다 — 이게 없으면 JSON 안의 토큰을 통째로 놓친다.
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    ("AZURE_CLIENT_SECRET", r"AZURE_CLIENT_SECRET['\"]?\s*[=:]\s*['\"]?([^\s'\",#}]{8,})"),
    ("AZURE_CLIENT_ID", r"AZURE_CLIENT_ID['\"]?\s*[=:]\s*['\"]?([0-9a-fA-F-]{30,})"),
    ("refresh_token", r"refresh_token['\"]?\s*[=:]\s*['\"]([A-Za-z0-9._\-]{40,})['\"]"),
    ("access_token", r"access_token['\"]?\s*[=:]\s*['\"]([A-Za-z0-9._\-]{40,})['\"]"),
)

#: 위 패턴에 걸려도 "설명용 자리표시자"면 넘어간다.
PLACEHOLDER_HINTS: tuple[str, ...] = (
    "your_", "_here", "xxxx", "<", "changeme", "placeholder", "example",
    "dummy", "fake", "sample", "...", "${", "{{",
)

TEXT_SUFFIXES: tuple[str, ...] = (
    ".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".cfg", ".ini",
    ".example", ".ps1", ".sh", ".bat", ".in", ".gitignore",
)


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------


def _is_excluded(name: str) -> bool:
    if name in EXCLUDE_EXACT:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_PATTERNS)


def _ignore(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if _is_excluded(n)]


def _copy_tree(src: Path, dst: Path) -> int:
    """제외 규칙을 적용해 디렉터리를 통째로 복사하고 복사한 파일 수를 돌려준다."""
    if not src.is_dir():
        raise FileNotFoundError(f"디렉터리 없음: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)
    return sum(1 for p in dst.rglob("*") if p.is_file())


def _copy_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise FileNotFoundError(f"파일 없음: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _spec_port(spec_path: Path) -> int | None:
    """param_spec YAML 에서 server.port 만 뽑는다 (PyYAML 없이도 동작하도록 정규식)."""
    text = _read_text(spec_path) or ""
    match = re.search(r"^\s{2,}port:\s*(\d+)", text, re.MULTILINE)
    return int(match.group(1)) if match else None


def _git_commit(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _host_env_secrets(root: Path) -> list[tuple[str, str]]:
    """원본 `.env` 의 실제 값들. 번들에 이 값이 섞였는지 대조하는 용도."""
    env_path = root / ".env"
    if not env_path.is_file():
        return []
    secrets: list[tuple[str, str]] = []
    for line in (_read_text(env_path) or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        # 8자 미만이거나 URL/부울 같은 공개값은 대조 대상이 아니다.
        if len(value) >= 12 and not value.startswith(("http://", "https://")):
            secrets.append((key.strip(), value))
    return secrets


# ---------------------------------------------------------------------------
# 비밀 스캔
# ---------------------------------------------------------------------------


def scan_secrets(bundle: Path, host_secrets: list[tuple[str, str]]) -> list[str]:
    """번들에 비밀이 섞였으면 사람이 읽을 수 있는 위반 목록을 돌려준다(값은 안 찍는다)."""
    violations: list[str] = []

    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle).as_posix()

        if path.name in EXCLUDE_EXACT or _is_excluded(path.name):
            violations.append(f"{rel}: 제외 대상 파일이 번들에 남아 있다")
            continue

        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in (".gitignore", ".env.example"):
            continue

        text = _read_text(path)
        if text is None:
            continue

        # 1) 원본 .env 의 실제 값이 그대로 박혀 있는가 — 가장 확실한 신호
        for key, value in host_secrets:
            if value in text:
                violations.append(f"{rel}: 로컬 .env 의 {key} 값이 그대로 들어 있다")

        # 2) 자격증명처럼 생긴 리터럴
        for label, pattern in SECRET_PATTERNS:
            for match in re.finditer(pattern, text):
                captured = match.group(1).lower()
                if any(hint in captured for hint in PLACEHOLDER_HINTS):
                    continue
                line_no = text.count("\n", 0, match.start()) + 1
                violations.append(f"{rel}:{line_no}: {label} 실값으로 보이는 리터럴")

    return violations


# ---------------------------------------------------------------------------
# 생성 파일
# ---------------------------------------------------------------------------


def check_lock(root: Path) -> dict[str, object]:
    """`uv.lock` 이 `pyproject.toml` 과 맞는지 확인하고 잠긴 버전 몇 개를 뽑아 둔다.

    잠금이 곧 재현성이다. 어긋난 잠금을 실어 보내면 받는 쪽의 `uv sync --frozen` 이
    거부하고, 잠금이 아예 없으면 그날의 최신본이 깔려 깨진다 — 2026-09-16 에 `mcp` 가
    2.x 로 깔려 `Server.list_tools` 가 사라지면서 6개 서버가 전부 기동에 실패했다.
    """
    lock = root / "uv.lock"
    if not lock.is_file():
        raise RuntimeError("uv.lock 이 없다 — 먼저 `uv lock` 을 돌릴 것")

    checked = False
    if shutil.which("uv"):
        out = subprocess.run(
            ["uv", "lock", "--check"], cwd=str(root),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        if out.returncode != 0:
            raise RuntimeError(
                "uv.lock 이 pyproject.toml 과 어긋난다 — `uv lock` 으로 갱신한 뒤 다시 빌드할 것:\n"
                + (out.stderr or out.stdout).strip()
            )
        checked = True

    # 사람이 눈으로 확인할 수 있게 핵심 몇 개만 뽑는다 (전체는 uv.lock 에 있다).
    text = lock.read_text(encoding="utf-8")
    pinned: dict[str, str] = {}
    for name in ("mcp", "starlette", "uvicorn", "pydantic", "aiohttp"):
        match = re.search(rf'^name = "{name}"\nversion = "([^"]+)"', text, re.MULTILINE)
        if match:
            pinned[name] = match.group(1)

    return {"verified_by_uv": checked, "key_versions": pinned}


def render_pyproject(source: Path, packages: list[str], testpaths: list[str]) -> str:
    """원본 pyproject 의 의존성·도구 설정을 살린 채 패키지 목록만 번들에 맞게 좁힌다.

    새로 써 버리면 의존성이 두 벌이 되므로 원본을 고쳐 쓴다. 표식이 사라졌으면
    조용히 넘어가지 않고 실패한다.
    """
    text = source.read_text(encoding="utf-8")

    include_block = "\n".join(f'    "{pkg}*",' for pkg in packages)
    new_include = f"include = [\n{include_block}\n]"
    text, n = re.subn(r"include = \[[^\]]*\]", new_include, text, count=1)
    if n != 1:
        raise RuntimeError("pyproject.toml 에서 packages.find 의 include 배열을 찾지 못했다")

    tp_block = "\n".join(f'    "{tp}",' for tp in testpaths) if testpaths else ""
    new_tp = f"testpaths = [\n{tp_block}\n]" if tp_block else "testpaths = []"
    text, n = re.subn(r"testpaths = \[[^\]]*\]", new_tp, text, count=1)
    if n != 1:
        raise RuntimeError("pyproject.toml 에서 testpaths 배열을 찾지 못했다")

    banner = (
        "# ---------------------------------------------------------------------------\n"
        "# 이 파일은 KR_MS365_mcp 원본 pyproject.toml 에서 번들 범위에 맞춰 생성됐다.\n"
        "# 손으로 고치지 말고 export_ms365 스킬로 다시 만들 것.\n"
        "# ---------------------------------------------------------------------------\n"
    )
    return banner + text


def render_readme(name: str, servers: list[dict[str, object]], commit: str, created: str,
                  lock_state: dict[str, object]) -> str:
    rows = "\n".join(
        f"| `{s['name']}` | {s['desc']} | {s['port'] or '-'} | `{s['package']}/mcp_server/server_stream.py` |"
        for s in servers
    )
    server_list = " ".join(str(s["name"]) for s in servers)
    first = str(servers[0]["name"]) if servers else "calendar"
    first_pkg = str(servers[0]["package"]) if servers else "mcp_calendar"

    versions = lock_state.get("key_versions") or {}
    lock_note = ""
    if versions:
        pairs = ", ".join(f"`{k} {v}`" for k, v in versions.items())
        lock_note = f" (핵심: {pairs})"

    return f"""# {name}

KR_MS365_mcp 에서 잘라낸 MS365 MCP 서버 번들. 이 디렉터리 하나로 기동된다.

- 원본 커밋: `{commit}`
- 생성 시각: {created}

## 포함된 서버

| 서버 | 기능 | HTTP 포트 | 진입점 |
|---|---|---|---|
{rows}

공용으로 항상 함께 들어간 것:

| 구성 | 경로 | 역할 |
|---|---|---|
| 인증 | `session/`, `callback_server.py` | Azure OAuth, refresh_token 갱신, `database/auth.db` 저장 |
| 공용 런타임 | `mcp_common/` | 도구 스키마 파생·검증, stdio/HTTP 트랜스포트, 부트스트랩 |
| 프로토콜 | `core/` | 서비스 프로토콜 정의 |
| time 서버 | `mcp_time/` | 시간·타임존 도구 (다른 서버가 날짜 인자를 만들 때 쓴다) |
| 도구 계약 | `spec/param_spec/*.yaml` | **런타임 필수** — 도구 정의의 유일한 원본 |
| 설치 스킬 | `.claude/skills/setup_ms365/` | 환경·.env·MCP 등록·서버 기동/중지 자동화 |
| 의존성 잠금 | `uv.lock`, `.python-version` | 확인된 버전 조합. `requirements.txt` 는 pip 용 안전망 |

## 빠른 시작 (uv)

[uv](https://docs.astral.sh/uv/) 하나만 있으면 된다 — Python 도 uv 가 알아서 받아온다.

```powershell
# 0) uv 가 없다면 (한 줄, 관리자 권한 불필요)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 1) 환경 구성 — .python-version 의 Python 을 받아오고 uv.lock 그대로 설치한다
uv sync --frozen

# 2) Azure 자격증명
copy .env.example .env      # AZURE_CLIENT_ID / SECRET / TENANT_ID 채우기

# 3) 번들 자체 점검 (인증 없이 동작)
uv run verify_bundle.py

# 4) 서버 기동 (HTTP)
uv run {first_pkg}/mcp_server/server_stream.py
```

`--frozen` 은 "잠금 파일을 그대로 쓰고 다시 풀지 말라"는 뜻이다. **이 번들에서는 이걸 쓴다** —
잠금에 적힌 조합이 실제로 기동까지 확인된 것이고, 다시 풀면 그날의 최신본이 들어와 깨질 수
있다{lock_note}.

uv 를 쓸 수 없는 환경이라면 pip 로도 된다 (`requirements.txt` 는 위 잠금에서 뽑은 것이다):

```powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.\\.venv\\Scripts\\python.exe verify_bundle.py
```

Claude Code 에 붙일 때:

```powershell
claude mcp add -s user --transport http {first} http://localhost:{servers[0]['port'] if servers else 5002}/mcp
```

Claude Code 에서 이 디렉터리를 열었다면 `/setup_ms365` 한 줄로 위 1~4 를 대신할 수 있다
(선택 서버: {server_list}).

## 인증 동작

`.env` 에 `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` / `AZURE_TENANT_ID` 만 넣어 두면,
첫 도구 호출 때 MCP 서버가 브라우저 OAuth 를 열고 토큰을 `database/auth.db` 에 저장한다.
콜백 포트는 5000 고정이며 `AZURE_REDIRECT_URI` 와 Azure 앱 등록의 리디렉션 URI 가
같아야 한다. 모든 서버가 `.env` 와 `auth.db` 를 공유하므로 **인증은 1회면 된다**.

## 주의

- `.env` 와 `database/*.db` 는 번들에 들어 있지 않고 `.gitignore` 로 막혀 있다.
  받은 쪽에서 자기 자격증명을 채워 넣는 구조다.
- `spec/param_spec/*.yaml` 은 문서가 아니라 **런타임 입력**이다. 지우면 서버가 뜨지 않는다.
- `uv.lock` 을 지우지 말 것. 이게 "되는 조합"의 유일한 기록이다.
- 소스 트리에서 실행하면 경로가 자동 해석된다. wheel 로 설치해 쓸 때만
  `MCP_PARAM_SPEC_DIR` 로 spec 위치를 알려주면 된다.
- 첨부파일 변환(PDF/DOCX/HWP 등)을 쓰려면 선택 의존성을 더 깔아야 한다:
  `uv sync --frozen --extra converters`.
"""


# ---------------------------------------------------------------------------
# 빌드
# ---------------------------------------------------------------------------


def build(root: Path, servers: list[str], out_dir: Path, bundle_name: str) -> dict[str, object]:
    bundle = out_dir / bundle_name
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)

    copied: dict[str, int] = {}

    # 1) 도메인 서버 패키지 + 도구 계약
    server_meta: list[dict[str, object]] = []
    for name in servers:
        info = SERVERS[name]
        pkg = str(info["package"])
        copied[pkg] = _copy_tree(root / pkg, bundle / pkg)

        spec_src = root / "spec" / "param_spec" / str(info["spec"])
        _copy_file(spec_src, bundle / "spec" / "param_spec" / str(info["spec"]))

        server_meta.append({
            "name": name,
            "package": pkg,
            "desc": info["desc"],
            "port": _spec_port(spec_src),
        })

    # 2) 공용 패키지 (인증·런타임·프로토콜·time)
    for pkg in COMMON_PACKAGES:
        copied[pkg] = _copy_tree(root / pkg, bundle / pkg)

    # 3) 공용 도구 계약
    for spec_name in COMMON_SPECS:
        _copy_file(root / "spec" / "param_spec" / spec_name, bundle / "spec" / "param_spec" / spec_name)

    # 4) 공용 루트 파일
    for fname in COMMON_FILES:
        _copy_file(root / fname, bundle / fname)

    # 4-1) 잠금 무결성 — uv.lock 과 pyproject.toml 이 어긋난 채로 배포하면 받는 쪽에서
    #      `uv sync --frozen` 이 거부한다. 빌드 시점에 확인한다.
    lock_state = check_lock(root)

    # 5) 설치·운영 스킬
    for skill in COMMON_SKILLS:
        copied[f".claude/skills/{skill}"] = _copy_tree(
            root / ".claude" / "skills" / skill, bundle / ".claude" / "skills" / skill
        )

    # 6) 자체 점검 스크립트 (번들 안에서도, 샌드박스에서도 같은 것을 쓴다)
    _copy_file(Path(__file__).parent.parent / "assets" / "verify_bundle.py", bundle / "verify_bundle.py")

    # 7) auth.db 가 생길 자리.
    #    `AuthDatabase` 가 os.makedirs 로 만들긴 하지만, 받는 쪽이 저장소를 clone 했을 때
    #    디렉터리가 보이는 편이 의도가 분명하다. 원본 .gitignore 의 `database/*` 규칙에
    #    막히므로 예외를 덧붙인다 (원본 규칙은 건드리지 않는다).
    (bundle / "database").mkdir(exist_ok=True)
    (bundle / "database" / ".gitkeep").write_text("", encoding="utf-8")
    with (bundle / ".gitignore").open("a", encoding="utf-8") as fh:
        fh.write(
            "\n# --- 번들 전용 (export_ms365 가 덧붙임) ---\n"
            "# auth.db 가 생길 자리는 저장소에 남긴다. DB 파일 자체는 위 규칙이 계속 막는다.\n"
            "!database/.gitkeep\n"
        )

    # 8) 생성 파일
    packages = [str(info["package"]) for name, info in SERVERS.items() if name in servers]
    packages += list(COMMON_PACKAGES)
    testpaths = [f"{pkg}/tests" for pkg in packages if (bundle / pkg / "tests").is_dir()]
    (bundle / "pyproject.toml").write_text(
        render_pyproject(root / "pyproject.toml", packages, testpaths), encoding="utf-8"
    )
    (bundle / "MANIFEST.in").write_text(
        "recursive-include spec/param_spec *.yaml\n", encoding="utf-8"
    )

    commit = _git_commit(root)
    created = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    (bundle / "README.md").write_text(
        render_readme(bundle_name, server_meta, commit, created, lock_state), encoding="utf-8"
    )

    file_list = sorted(p for p in bundle.rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for path in file_list:
        digest.update(path.relative_to(bundle).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())

    manifest = {
        "bundle_name": bundle_name,
        "created_at": created,
        "source_repo": "KR_MS365_mcp",
        "source_commit": commit,
        "servers": server_meta,
        "common": {
            "packages": list(COMMON_PACKAGES),
            "files": list(COMMON_FILES),
            "specs": list(COMMON_SPECS),
            "skills": list(COMMON_SKILLS),
        },
        "lock": lock_state,
        # 매니페스트 자신은 자기 해시에 들어갈 수 없으므로 아래 둘은 "매니페스트를 뺀" 값이다.
        "hashed_file_count": len(file_list),
        "tree_sha256": digest.hexdigest(),
    }
    (bundle / "bundle_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 9) 비밀 스캔 — 여기서 걸리면 번들을 지우고 실패시킨다
    violations = scan_secrets(bundle, _host_env_secrets(root))
    if violations:
        shutil.rmtree(bundle, ignore_errors=True)
        raise RuntimeError("비밀이 섞여 번들을 폐기했다:\n  - " + "\n  - ".join(violations))

    manifest["bundle_path"] = str(bundle)
    manifest["copied"] = copied
    manifest["secret_scan"] = "clean"
    return manifest


def _resolve_servers(raw: str) -> list[str]:
    """`all` 은 도메인 서버 6개를 뜻한다. `all,file_handler` 처럼 섞어 쓸 수 있다."""
    names: list[str] = []
    for token in raw.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token == "all":
            names.extend(n for n in SERVERS if n != "file_handler")
        else:
            names.append(token)

    unknown = [n for n in names if n not in SERVERS]
    if unknown:
        raise SystemExit(f"알 수 없는 서버: {', '.join(unknown)} (가능: {', '.join(SERVERS)}, all)")
    if not names:
        raise SystemExit("서버를 최소 1개 지정해야 한다")
    # 선언 순서 유지 + 중복 제거
    return [n for n in SERVERS if n in names]


def main() -> int:
    parser = argparse.ArgumentParser(description="MS365 MCP 번들 스테이징")
    parser.add_argument("--servers", required=True, help="쉼표 구분 서버 이름 또는 'all'")
    parser.add_argument("--root", default=None, help="원본 프로젝트 루트 (기본: 이 스킬이 속한 프로젝트)")
    parser.add_argument("--out", default=None, help="스테이징 상위 디렉터리 (기본: <root>/output/bundles)")
    parser.add_argument("--name", default=None, help="번들 이름 (기본: ms365-mcp-<서버들>)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로만 출력")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[4]
    if not (root / "mcp_common").is_dir():
        raise SystemExit(f"프로젝트 루트로 보이지 않는다: {root}")

    servers = _resolve_servers(args.servers)
    out_dir = Path(args.out).resolve() if args.out else root / "output" / "bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or ("ms365-mcp-" + "-".join(servers))

    manifest = build(root, servers, out_dir, name)

    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"번들: {manifest['bundle_path']}")
        print(f"서버: {', '.join(s['name'] for s in manifest['servers'])}")  # type: ignore[index]
        print(f"파일: {manifest['hashed_file_count']}개(+매니페스트) | 비밀 스캔: {manifest['secret_scan']}")
        print(f"원본 커밋: {manifest['source_commit']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(main())
