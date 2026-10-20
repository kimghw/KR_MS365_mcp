#!/usr/bin/env python3
"""번들 배포 — zip 으로 묶거나 GitHub 저장소를 새로 만들어 올린다.

`build_bundle.py` 가 만든 스테이징 디렉터리를 입력으로 받는다. 이 스크립트는
번들 내용을 다시 손대지 않는다 — 비밀 스캔은 빌드 단계에서 이미 끝났고, 여기서는
"스캔을 통과한 트리인가"(bundle_manifest.json 존재)만 확인한다.

GitHub 공개 저장소는 `--confirm-public` 없이는 만들지 않는다. 인증 코드와 사내 도구
계약이 들어 있어 실수로 공개되면 되돌릴 수 없기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

COMMIT_MESSAGE = "MS365 MCP 번들 초기 커밋"


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def _require_bundle(bundle: Path) -> dict[str, Any]:
    manifest_path = bundle / "bundle_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"번들이 아니다 (bundle_manifest.json 없음): {bundle}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# zip
# ---------------------------------------------------------------------------


def make_zip(bundle: Path, zip_path: Path) -> dict[str, Any]:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    files = sorted(p for p in bundle.rglob("*") if p.is_file())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, arcname=f"{bundle.name}/{path.relative_to(bundle).as_posix()}")

    return {
        "mode": "zip",
        "path": str(zip_path),
        "file_count": len(files),
        "size_bytes": zip_path.stat().st_size,
        "size_mb": round(zip_path.stat().st_size / (1024 * 1024), 2),
    }


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


def _gh_ready() -> str | None:
    if shutil.which("gh") is None:
        return "gh CLI 가 PATH 에 없다 (https://cli.github.com)"
    status = _run(["gh", "auth", "status"], timeout=30)
    if status.returncode != 0:
        return "gh 인증이 안 돼 있다 — `gh auth login` 먼저"
    return None


def push_github(
    bundle: Path,
    repo: str,
    visibility: str,
    owner: str | None,
    description: str,
) -> dict[str, Any]:
    problem = _gh_ready()
    if problem:
        raise SystemExit(problem)

    target = f"{owner}/{repo}" if owner else repo

    exists = _run(["gh", "repo", "view", target], timeout=60)
    if exists.returncode == 0:
        raise SystemExit(f"이미 있는 저장소다: {target} (다른 이름을 쓰거나 먼저 지울 것)")

    # 번들 디렉터리 자체를 작업 트리로 삼는다. .git 은 여기서 처음 생긴다.
    if (bundle / ".git").exists():
        shutil.rmtree(bundle / ".git")

    for cmd in (
        ["git", "init", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", COMMIT_MESSAGE],
    ):
        result = _run(cmd, cwd=bundle)
        if result.returncode != 0:
            raise SystemExit(f"{' '.join(cmd)} 실패:\n{result.stderr or result.stdout}")

    create = _run(
        [
            "gh", "repo", "create", target,
            f"--{visibility}",
            "--source", str(bundle),
            "--remote", "origin",
            "--push",
            "--description", description,
        ],
        cwd=bundle,
        timeout=300,
    )
    if create.returncode != 0:
        raise SystemExit(f"gh repo create 실패:\n{create.stderr or create.stdout}")

    url = _run(["gh", "repo", "view", target, "--json", "url", "-q", ".url"], timeout=60)
    return {
        "mode": "github",
        "repo": target,
        "visibility": visibility,
        "url": url.stdout.strip() if url.returncode == 0 else f"https://github.com/{target}",
    }


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="MS365 MCP 번들 배포")
    parser.add_argument("--bundle", required=True, help="build_bundle.py 가 만든 디렉터리")
    parser.add_argument("--mode", required=True, choices=("zip", "github", "both"))
    parser.add_argument("--zip-out", default=None, help="zip 경로 (기본: <번들 상위>/<이름>.zip)")
    parser.add_argument("--repo", default=None, help="GitHub 저장소 이름")
    parser.add_argument("--owner", default=None, help="GitHub 소유자 (기본: 인증된 계정)")
    parser.add_argument("--visibility", default="private", choices=("private", "public"))
    parser.add_argument("--confirm-public", action="store_true", help="public 저장소 생성 확인")
    parser.add_argument("--description", default=None, help="저장소 설명")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    bundle = Path(args.bundle).resolve()
    manifest = _require_bundle(bundle)
    server_names = ", ".join(s["name"] for s in manifest.get("servers", []))

    if args.mode in ("github", "both"):
        if not args.repo:
            raise SystemExit("--mode github 에는 --repo 가 필요하다")
        if args.visibility == "public" and not args.confirm_public:
            raise SystemExit(
                "public 저장소는 --confirm-public 없이 만들지 않는다 "
                "(인증 코드·도구 계약 포함 — 사용자에게 먼저 확인할 것)"
            )

    outputs: list[dict[str, Any]] = []

    if args.mode in ("zip", "both"):
        zip_path = Path(args.zip_out).resolve() if args.zip_out else bundle.parent / f"{bundle.name}.zip"
        outputs.append(make_zip(bundle, zip_path))

    if args.mode in ("github", "both"):
        description = args.description or f"MS365 MCP 서버 번들 ({server_names})"
        outputs.append(push_github(bundle, args.repo, args.visibility, args.owner, description))

    report = {"bundle": bundle.name, "servers": server_names, "outputs": outputs}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in outputs:
            if item["mode"] == "zip":
                print(f"zip: {item['path']} ({item['size_mb']} MB, {item['file_count']}개 파일)")
            else:
                print(f"github: {item['url']} ({item['visibility']})")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
