"""
명령행 — `python -m tools.migrate_multi_user {plan,apply,verify,activate}`.

출력은 JSON 한 덩어리(stdout), 오류는 stderr 한 줄. 종료 코드 0 성공 / 1 실패·충돌 / 2 사용법.
이 명령은 토큰·client secret·bearer key 를 받는 옵션이 **없다**(셸 기록에 남지 않게).
화면 출력에는 이메일이 없다 — 사용자는 user_key 로만 표시한다.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SOURCE_OPTIONS = (
    ("auth_db", "legacy auth.db (기본 <legacy-root>/database/auth.db)"),
    ("onenote_db", "legacy onenote.db (기본 <legacy-root>/database/onenote.db)"),
    ("metadata_db", "FileHandler metadata.db (기본 <legacy-root>/metadata.db)"),
    ("metadata_json", "FileHandler metadata.json (기본 <legacy-root>/metadata.json)"),
    ("mail_metadata", "Outlook mail_metadata.json (기본 <legacy-root>/downloads/mail_metadata.json)"),
    ("downloads", "다운로드 디렉터리 (기본 <legacy-root>/downloads)"),
    ("output", "출력 디렉터리 (기본 <legacy-root>/output)"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.migrate_multi_user",
        description="MS365 MCP 단일 운영자(mode 0) 데이터 → 멀티유저(mode 1) 사용자별 저장소 이전",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="snapshot·hash·소유자 배정 → manifest")
    plan.add_argument("--mapping", required=True, help="legacy_email → (tenant_id, object_id) 매핑 JSON")
    plan.add_argument("--legacy-root", default=str(_PROJECT_ROOT), help="legacy 저장소 루트 (기본: 이 저장소)")
    for name, text in _SOURCE_OPTIONS:
        plan.add_argument(f"--{name.replace('_', '-')}", dest=name, default=None, help=text)

    apply = sub.add_parser("apply", help="manifest 대로 staging 에 사용자별 저장소 생성")
    apply.add_argument("--manifest", default=None, help="manifest 경로 (기본: 가장 최근)")
    apply.add_argument("--reset-staging", action="store_true", help="다른 run 의 staging 을 지우고 다시 만든다")

    verify = sub.add_parser("verify", help="행 수·owner_key·파일 hash·격리 불변조건 확인")
    verify.add_argument("--manifest", default=None)
    verify.add_argument("--live", action="store_true", help="staging 대신 활성화된 users/<uk>/ 영역을 검증")

    activate = sub.add_parser("activate", help="서버 정지·lock·원본 재검사 후 staging 을 users/ 로 원자적 이동")
    activate.add_argument("--manifest", default=None)
    activate.add_argument("--yes", action="store_true", help="운영 저장소 변경 확인")

    unlock = sub.add_parser("unlock", help="legacy 저장소의 쓰기 정지 lock 해제 (롤백·중단 시)")
    unlock.add_argument("--manifest", default=None)
    unlock.add_argument("--yes", action="store_true", help="legacy 저장소에 mode 0 쓰기를 다시 허용함을 확인")
    return parser


def _force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _run(args) -> int:
    from .common import current_layout, load_manifest

    layout = current_layout()
    if args.command == "plan":
        from .planner import run_plan

        overrides = {name: getattr(args, name) for name, _ in _SOURCE_OPTIONS}
        result = run_plan(layout, Path(args.mapping), Path(args.legacy_root), overrides)
        _print(result)
        return EXIT_OK if result["status"] == "ok" else EXIT_ERROR

    manifest = load_manifest(layout, Path(args.manifest) if args.manifest else None)
    if args.command == "apply":
        from .applier import run_apply

        _print(run_apply(layout, manifest, reset_staging=args.reset_staging))
        return EXIT_OK
    if args.command == "verify":
        from .verifier import run_verify

        report = run_verify(layout, manifest, live=args.live)
        _print({k: v for k, v in report.items() if k != "users"} | {
            "users": {uk: u["ok"] for uk, u in report["users"].items()}})
        return EXIT_OK if report["status"] == "ok" else EXIT_ERROR
    if args.command == "unlock":
        from .common import MigrationError, audit_event
        from .freeze import release_locks
        from .planner import require_no_activation_in_progress

        if not args.yes:
            raise MigrationError("confirm_required", "unlock 은 legacy 저장소에 mode 0 쓰기를 다시 허용합니다 — 확인하려면 --yes.")
        require_no_activation_in_progress(layout)
        removed = release_locks(manifest)
        audit_event("unlock", "success")
        _print({"status": "ok", "run_id": manifest["run_id"], "removed": removed})
        return EXIT_OK
    from .activator import run_activate

    _print(run_activate(layout, manifest, confirm=args.yes))
    return EXIT_OK


def main(argv: Optional[List[str]] = None, *, load_env: bool = True) -> int:
    _force_utf8_console()
    if load_env:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), encoding="utf-8-sig", override=False)
    args = build_parser().parse_args(argv)

    from .common import MigrationError, audit_event

    try:
        return _run(args)
    except MigrationError as exc:
        audit_event(args.command, "failure", error_code=exc.code if exc.code.isidentifier() else "error")
        print(f"오류[{exc.code}]: {exc.message}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
