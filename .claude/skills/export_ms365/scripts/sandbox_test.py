#!/usr/bin/env python3
"""Windows Sandbox 에서 번들을 백지 상태로 검증한다.

호스트에는 venv·Python·이미 깔린 패키지가 있어서 "여기선 되는데"가 쉽게 나온다.
샌드박스는 매번 새 Windows 라 그게 통하지 않는다 — 번들이 자기 발로 서는지 본다.

흐름
    1. 작업 폴더 준비: in/<번들>(읽기 전용으로 매핑), out/(결과가 나오는 통로)
    2. .wsb 생성 → WindowsSandbox.exe 실행
    3. 게스트에서 sandbox_runner.ps1 이 uv 설치 → uv sync --frozen → verify_bundle.py --http
    4. out/done.json 이 생길 때까지 대기하며 progress.json 을 따라 출력
    5. result.json 을 읽어 판정

샌드박스는 한 번에 하나만 뜬다. 이미 실행 중이면 여기서 멈춘다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SANDBOX_EXE = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsSandbox.exe"
GUEST_DESKTOP = r"C:\Users\WDAGUtilityAccount\Desktop"
GUEST_SRC = rf"{GUEST_DESKTOP}\bundle_src"
GUEST_OUT = rf"{GUEST_DESKTOP}\out"

WSB_TEMPLATE = """<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Default</Networking>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <PrinterRedirection>Disable</PrinterRedirection>
  <MemoryInMB>{memory}</MemoryInMB>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{host_in}</HostFolder>
      <SandboxFolder>{guest_src}</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>{host_out}</HostFolder>
      <SandboxFolder>{guest_out}</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{guest_src}\\_runner\\sandbox_runner.ps1" -BundleName "{bundle_name}"{extra_args}</Command>
  </LogonCommand>
</Configuration>
"""


def _preflight() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows Sandbox 는 Windows 에서만 돈다")
    if not SANDBOX_EXE.is_file():
        raise SystemExit(
            "WindowsSandbox.exe 가 없다. 기능을 켤 것:\n"
            "  Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All"
        )
    # 빌드마다 프로세스 이름이 다르다 (WindowsSandboxClient / WindowsSandboxRemoteSession).
    # 어느 빌드에서든 확실히 도는 것은 컨테이너 메모리 프로세스다.
    running = subprocess.run(
        ["tasklist", "/NH"], capture_output=True, text=True, errors="replace", timeout=30,
    )
    stdout = running.stdout or ""
    if any(name in stdout for name in ("vmmemWindowsSandbox", "WindowsSandboxClient.exe")):
        raise SystemExit("Windows Sandbox 가 이미 실행 중이다 — 닫고 다시 시도할 것 (동시에 하나만 뜬다)")


def _copy_runner(runner: Path, dest: Path) -> None:
    """러너를 **UTF-8 BOM 으로** 복사한다.

    게스트의 Windows PowerShell 5.1 은 BOM 이 없는 .ps1 을 ANSI 코드페이지(한국어
    Windows 는 cp949)로 읽는다. 한글 주석 한 줄이면 곧바로 파싱 오류가 나고, LogonCommand 는
    조용히 죽어 `out/` 에 아무것도 남기지 않는다 — 8분을 태우고 나서야 알게 된다.
    실제로 그렇게 한 번 태웠다(2026-09-16).
    """
    text = runner.read_text(encoding="utf-8-sig")
    dest.write_text(text, encoding="utf-8-sig")


def prepare(bundle: Path, work: Path, runner: Path) -> dict[str, Path]:
    host_in = work / "in"
    host_out = work / "out"
    for path in (host_in, host_out):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)

    shutil.copytree(bundle, host_in / bundle.name)
    (host_in / "_runner").mkdir()
    _copy_runner(runner, host_in / "_runner" / "sandbox_runner.ps1")
    return {"in": host_in, "out": host_out}


def parse_check(ps1: Path) -> None:
    """게스트에 보내기 전에 호스트의 PowerShell 로 파싱만 해 본다.

    러너가 파싱 단계에서 죽으면 게스트는 아무 흔적도 남기지 않는다. 여기서 1초에 잡는다.
    """
    script = (
        "$e = $null; "
        f"$null = [System.Management.Automation.Language.Parser]::ParseFile('{ps1}', [ref]$null, [ref]$e); "
        "if ($e -and $e.Count -gt 0) { "
        "$e | ForEach-Object { Write-Output (\"line \" + $_.Extent.StartLineNumber + \": \" + $_.Message) }; exit 1 } "
        "else { exit 0 }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True, text=True, errors="replace", timeout=60,
    )
    if result.returncode != 0:
        raise SystemExit(f"러너 스크립트에 파싱 오류가 있다 ({ps1}):\n{result.stdout.strip()}")


def write_wsb(work: Path, host_in: Path, host_out: Path, bundle_name: str,
              memory: int, no_shutdown: bool) -> Path:
    wsb = work / "bundle_test.wsb"
    wsb.write_text(
        WSB_TEMPLATE.format(
            memory=memory,
            host_in=host_in,
            host_out=host_out,
            guest_src=GUEST_SRC,
            guest_out=GUEST_OUT,
            bundle_name=bundle_name,
            extra_args=" -NoShutdown" if no_shutdown else "",
        ),
        encoding="utf-8",
    )
    return wsb


def wait_for_result(host_out: Path, timeout: int, quiet: bool) -> dict[str, Any] | None:
    done = host_out / "done.json"
    progress = host_out / "progress.json"
    deadline = time.time() + timeout
    last_stage = ""

    while time.time() < deadline:
        if done.is_file():
            time.sleep(1)  # 쓰기 완료 대기
            try:
                # utf-8-sig 여야 한다. 게스트의 `Set-Content -Encoding utf8` 은 Windows
                # PowerShell 5.1 에서 **BOM 을 붙여** 쓰고, 그러면 json.loads 가 매번
                # JSONDecodeError 를 낸다 — 검사는 다 통과했는데 호스트만 시간 초과로
                # 끝나는 유령 실패가 된다(2026-09-16 실제로 겪었다).
                return json.loads(done.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                time.sleep(1)
                continue

        if not quiet and progress.is_file():
            try:
                data = json.loads(progress.read_text(encoding="utf-8-sig"))
                stage = f"{data.get('current')}/{data.get('state')}"
                if stage != last_stage:
                    elapsed = int(timeout - (deadline - time.time()))
                    print(f"  [{elapsed:>4}s] {data.get('current')} — {data.get('state')}")
                    last_stage = stage
            except (json.JSONDecodeError, OSError):
                pass

        time.sleep(3)

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows Sandbox 번들 검증")
    parser.add_argument("--bundle", required=True, help="build_bundle.py 가 만든 디렉터리")
    parser.add_argument("--work", default=None, help="작업 폴더 (기본: %TEMP%\\ms365_sandbox_<시각>)")
    parser.add_argument("--timeout", type=int, default=900, help="대기 한도(초), 기본 900")
    parser.add_argument("--memory", type=int, default=6144, help="샌드박스 메모리 MB")
    # Python 버전은 번들의 `.python-version` 이 정한다 — uv 가 그걸 보고 받아온다.
    # 여기서 따로 고르게 두면 잠금과 어긋난 환경을 검증하게 된다.
    parser.add_argument("--no-shutdown", action="store_true", help="검증 후 샌드박스를 닫지 않는다 (디버깅)")
    parser.add_argument("--keep", action="store_true", help="작업 폴더를 지우지 않는다")
    parser.add_argument("--quiet", action="store_true", help="진행 상황 출력 생략")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    _preflight()

    bundle = Path(args.bundle).resolve()
    if not (bundle / "bundle_manifest.json").is_file():
        raise SystemExit(f"번들이 아니다 (bundle_manifest.json 없음): {bundle}")

    runner = Path(__file__).resolve().parent.parent / "assets" / "sandbox_runner.ps1"
    if not runner.is_file():
        raise SystemExit(f"러너 스크립트가 없다: {runner}")

    work = Path(args.work).resolve() if args.work else (
        Path(os.environ.get("TEMP", r"C:\Temp")) / f"ms365_sandbox_{datetime.now():%Y%m%d_%H%M%S}"
    )
    work.mkdir(parents=True, exist_ok=True)

    folders = prepare(bundle, work, runner)
    parse_check(folders["in"] / "_runner" / "sandbox_runner.ps1")
    wsb = write_wsb(work, folders["in"], folders["out"], bundle.name,
                    args.memory, args.no_shutdown)

    python_version = (bundle / ".python-version").read_text(encoding="utf-8").strip() \
        if (bundle / ".python-version").is_file() else "(번들에 .python-version 없음)"

    if not args.quiet:
        print(f"번들      : {bundle}")
        print(f"작업 폴더 : {work}")
        print(f"설정      : {wsb}")
        print(f"Python    : {python_version} (uv 가 받아온다)")
        # 실측(2026-09-16, 6개 서버 번들 2회): 전체 약 63초. 회선이 느리면 늘어난다.
        print("샌드박스 기동 — uv 설치·uv sync·검증까지 보통 1~2분\n")

    # 분리해서 띄운다. 그러지 않으면 이 프로세스가 죽을 때(시간 초과·Ctrl+C) 샌드박스가
    # 같이 끌려 내려가 게스트 상태를 들여다볼 수 없다 — 실제로 그렇게 증거를 날린 적이 있다.
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(SANDBOX_EXE), str(wsb)], creationflags=creationflags, close_fds=True)

    done = wait_for_result(folders["out"], args.timeout, args.quiet)

    result_path = folders["out"] / "result.json"
    result: dict[str, Any] | None = None
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            result = None

    report: dict[str, Any] = {
        "bundle": bundle.name,
        "work_dir": str(work),
        "wsb": str(wsb),
        "timed_out": done is None,
        "runner": done,
        "verify": result,
        "ok": bool(done and done.get("ok") and result and result.get("ok")),
        "artifacts": {
            name: str(folders["out"] / name)
            for name in ("result.json", "runner.log", "uv-install.log", "uv-sync.log",
                         "verify.log", "pip-freeze.txt", "progress.json")
            if (folders["out"] / name).is_file()
        },
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print()
        if report["timed_out"]:
            print(f"시간 초과 ({args.timeout}s) — 샌드박스가 아직 돌고 있을 수 있다")
        elif done:
            print(f"러너: {'성공' if done.get('ok') else '실패'} — {done.get('stage')}: {done.get('detail')}")
        if result:
            for item in result.get("results", []):
                mark = "PASS" if item["ok"] else "FAIL"
                print(f"  [{mark}] {item['check']}: {item['detail']}")
            print(f"\n{result.get('passed')} passed / {result.get('failed')} failed "
                  f"(Python {result.get('python')})")
        print(f"\n산출물: {work / 'out'}")

    if not args.keep and report["ok"]:
        # 실패했을 때는 로그를 남긴다. 성공했으면 매핑 폴더만 정리.
        shutil.rmtree(folders["in"], ignore_errors=True)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
