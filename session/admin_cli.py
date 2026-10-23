"""
멀티유저 관리 CLI — `python -m session.admin_cli` (spec/spec_멀티유저.md ②-4.2, ②-6.5, ②-12.7).

    init                                   데이터 루트·registry·KEK·앱 설정 점검/초기화
    user add --tenant <tid> --oid <oid>    pending_link 사용자 등록 (--reinstate: 삭제 기록 재등록)
    user list [--show-email]               사용자 목록 (이메일은 기본 비표시)
    user disable|enable <user_key>
    user delete <user_key> --yes           키·토큰·데이터·wrapped DEK 삭제 + tombstone
    key issue <user_key> [--domains d1 d2 ...] [--days N]   bearer key 발급 (원문은 한 번만 출력)
    key rotate <kid> [--days N]            새 키 발급 + 기존 키 24시간 후 만료
    key revoke <kid>
    key list <user_key>
    graph disconnect <user_key>            Graph 토큰 삭제·auth_epoch 증가

명령행으로 토큰·client secret·bearer key 를 **받지 않는다**(셸 기록에 남지 않게). 출력에는 발급한
키 원문(1회) 외의 비밀이 없다. 멀티유저 모드(`MS365_MULTI_USER=1` + `MS365_DATA_ROOT`)에서만 동작한다.
"""

import argparse
import json
import os
import sys
from typing import List, Optional

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


def _mask_email(email: Optional[str]) -> str:
    if not email:
        return "-"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _cmd_init(args) -> int:
    from mcp_common.security_policy import ensure_deployment
    from mcp_common.user_paths import ensure_system_dirs

    from . import _registry_db as reg
    from .app_settings import auth_startup_problems

    ensure_system_dirs()
    marker = ensure_deployment()
    reg.ensure_registry()
    problems = auth_startup_problems()
    _print({"status": "ok" if not problems else "incomplete",
            "deployment_id": marker["deployment_id"],
            "registry": "ready",
            "problems": problems})
    return EXIT_OK if not problems else EXIT_ERROR


def _cmd_user(args) -> int:
    from . import identity_registry as ir

    if args.action == "add":
        record = ir.register_user(args.tenant, args.oid, reinstate=args.reinstate)
        _print({"user_key": record.user_key, "status": record.status,
                "next": "key issue <user_key> 로 bearer key 를 발급해 사용자에게 안전하게 전달하세요."})
    elif args.action == "list":
        users = ir.list_users()
        for user in users:
            email = user.pop("graph_email")
            user["graph_email"] = email if args.show_email else _mask_email(email)
        _print(users)
    elif args.action == "disable":
        _print({"user_key": args.user_key, "status": ir.set_status(args.user_key, "disabled").status})
    elif args.action == "enable":
        _print({"user_key": args.user_key, "status": ir.set_status(args.user_key, "enable").status})
    elif args.action == "delete":
        if not args.yes:
            print("삭제는 되돌릴 수 없습니다. 확인하려면 --yes 를 붙이세요.", file=sys.stderr)
            return EXIT_USAGE
        ir.delete_user(args.user_key)
        _print({"user_key": args.user_key, "status": "deleted"})
    return EXIT_OK


def _cmd_key(args) -> int:
    from . import identity_registry as ir

    if args.action in ("issue", "rotate"):
        if args.action == "issue":
            issued = ir.issue_key(args.user_key, args.domains or None, days=args.days)
        else:
            issued = ir.rotate_key(args.kid, days=args.days)
        _print({"kid": issued.kid, "scopes": list(issued.scopes), "expires_at": issued.expires_at})
        # 원문 키는 stdout 마지막 줄에 한 번만. 다시 조회할 방법이 없다.
        print("\n# 아래 키는 다시 표시되지 않습니다. 사용자에게 안전한 경로로 전달하세요.", file=sys.stderr)
        print(issued.key)
    elif args.action == "revoke":
        _print({"kid": args.kid, "revoked": ir.revoke_key(args.kid)})
    elif args.action == "list":
        _print(ir.list_keys(args.user_key))
    return EXIT_OK


def _cmd_graph(args) -> int:
    from . import identity_registry as ir

    ir.disconnect_graph(args.user_key)
    _print({"user_key": args.user_key, "graph": "disconnected"})
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    from mcp_common.principal import DOMAINS

    parser = argparse.ArgumentParser(prog="python -m session.admin_cli", description="MS365 MCP 멀티유저 관리")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="데이터 루트·registry 초기화와 설정 점검").set_defaults(func=_cmd_init)

    user = sub.add_parser("user", help="사용자 관리")
    usub = user.add_subparsers(dest="action", required=True)
    add = usub.add_parser("add")
    add.add_argument("--tenant", required=True, help="tenant ID (UUID)")
    add.add_argument("--oid", required=True, help="사용자 object ID (UUID)")
    add.add_argument("--reinstate", action="store_true", help="삭제 기록(tombstone)이 있는 사용자를 다시 등록")
    lst = usub.add_parser("list")
    lst.add_argument("--show-email", action="store_true")
    for name in ("disable", "enable"):
        usub.add_parser(name).add_argument("user_key")
    delete = usub.add_parser("delete")
    delete.add_argument("user_key")
    delete.add_argument("--yes", action="store_true")
    user.set_defaults(func=_cmd_user)

    key = sub.add_parser("key", help="bearer key 관리")
    ksub = key.add_subparsers(dest="action", required=True)
    issue = ksub.add_parser("issue")
    issue.add_argument("user_key")
    issue.add_argument("--domains", nargs="+", choices=list(DOMAINS), help="허용 도메인 (기본: 전체)")
    issue.add_argument("--days", type=int, default=30)
    rotate = ksub.add_parser("rotate")
    rotate.add_argument("kid")
    rotate.add_argument("--days", type=int, default=30)
    ksub.add_parser("revoke").add_argument("kid")
    ksub.add_parser("list").add_argument("user_key")
    key.set_defaults(func=_cmd_key)

    graph = sub.add_parser("graph", help="Graph 연결 관리")
    gsub = graph.add_subparsers(dest="action", required=True)
    gsub.add_parser("disconnect").add_argument("user_key")
    graph.set_defaults(func=_cmd_graph)
    return parser


def _force_utf8_console() -> None:
    """Windows 콘솔 기본 인코딩(cp949/cp1252)이 한글 도움말·메시지 출력에서 죽지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main(argv: Optional[List[str]] = None, *, load_env: bool = True) -> int:
    _force_utf8_console()
    if load_env:
        from dotenv import load_dotenv

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        load_dotenv(os.path.join(root, ".env"), encoding="utf-8-sig", override=False)

    from mcp_common.security_contracts import StartupConfigError
    from mcp_common.security_policy import multi_user_enabled

    from .registry_admin import AdminError

    args = build_parser().parse_args(argv)
    try:
        if not multi_user_enabled():
            print("관리 CLI 는 멀티유저 모드(MS365_MULTI_USER=1, MS365_DATA_ROOT)에서만 동작합니다.", file=sys.stderr)
            return EXIT_USAGE
        return args.func(args)
    except (AdminError, StartupConfigError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
