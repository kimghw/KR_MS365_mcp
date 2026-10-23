"""WP3 경로 경계 — `mcp_common.paths` mode 1 (spec/spec_멀티유저.md ②-7.4, 테스트 F01·F06·F07).

mode 0 동작이 그대로인지도 함께 확인한다 (기존 FileHandler 호출자 회귀 방지).
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from mcp_common import paths
from mcp_common.audit import FIELDS
from mcp_common.paths import PathNotAllowedError, UserPathNotAllowedError
from mcp_common.secure_files import UnsafePathError, open_for_read
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import bound, make_principal, multi_user_mode, single_user_mode
from mcp_common.user_paths import ensure_user_dirs, paths_for, system_paths

BS = "\\"


def _make_dir_link(link: Path, target: Path) -> bool:
    """디렉터리 링크 생성 (Windows: junction, POSIX: symlink). 못 만들면 False."""
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True
        )
        return result.returncode == 0 and link.exists()
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


@pytest.fixture
def alice(tmp_path):
    root = tmp_path / "data"
    with multi_user_mode(root) as data_root:
        principal = make_principal("alice@contoso.com")
        up = ensure_user_dirs(paths_for(principal))
        with bound(principal, request_id="req-alice-0001"):
            yield {"root": data_root, "principal": principal, "paths": up}


def _assert_no_abs_path(exc: BaseException, *paths_: Path) -> None:
    text = str(exc) + json.dumps(getattr(exc, "payload", ""), ensure_ascii=False)
    for p in paths_:
        assert str(p) not in text
        assert str(p).replace("\\", "/") not in text


# ----------------------------------------------------------------------
# allowed_roots / 상대·절대
# ----------------------------------------------------------------------
def test_allowed_roots_is_only_current_users_files(alice):
    assert paths.allowed_roots() == [alice["paths"].files]


def test_mode1_ignores_allowed_paths_env_set_after_startup(alice, monkeypatch, tmp_path):
    """F07 — 기동 검사 뒤에 MCP_ALLOWED_PATHS/MCP_DATA_DIR 이 생겨도 범위가 넓어지지 않는다."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("MCP_ALLOWED_PATHS", str(outside))
    monkeypatch.setenv("MCP_DATA_DIR", str(outside))
    assert paths.allowed_roots() == [alice["paths"].files]
    with pytest.raises(UserPathNotAllowedError) as info:
        paths.resolve_safe_path(str(outside / "x.txt"))
    assert info.value.reason == "outside_root"
    assert not paths.is_allowed(str(outside / "x.txt"))


def test_relative_path_resolves_under_user_files(alice):
    resolved = paths.resolve_safe_path("uploads/report.pdf")
    assert resolved == Path(os.path.realpath(alice["paths"].uploads / "report.pdf"))
    assert paths.is_allowed("uploads/report.pdf")


def test_absolute_path_inside_files_is_allowed(alice):
    target = alice["paths"].output / "a.txt"
    target.write_text("ok", encoding="utf-8")
    assert paths.resolve_safe_path(str(target), must_exist=True) == Path(os.path.realpath(target))


def test_files_root_itself_is_allowed(alice):
    assert paths.resolve_safe_path(".") == Path(os.path.realpath(alice["paths"].files))


# ----------------------------------------------------------------------
# F01 — 특수 경로 거부
# ----------------------------------------------------------------------
_WINDOWS_ONLY = [
    ("C:foo.txt", "drive_relative"),
    ("C:", "drive_relative"),
    (BS + "Windows" + BS + "win.ini", "drive_relative"),
    ("/etc/passwd", "drive_relative"),
]

_REJECTED = [
    ("../auth/auth.db", "traversal"),
    ("uploads/../../db/onenote.db", "traversal"),
    ("..", "traversal"),
    (BS * 2 + "server" + BS + "share" + BS + "x.txt", "unc"),
    ("//server/share/x.txt", "unc"),
    (BS * 2 + "?" + BS + "C:" + BS + "x.txt", "device_path"),
    (BS * 2 + "." + BS + "PhysicalDrive0", "device_path"),
    ("//./pipe/x", "device_path"),
    (BS + "??" + BS + "C:" + BS + "x", "device_path"),
    ("report.txt:secret", "ads"),
    ("uploads/a.txt::$DATA", "ads"),
    ("CON", "reserved_name"),
    ("uploads/nul.txt", "reserved_name"),
    ("COM1.log", "reserved_name"),
    ("lpt9", "reserved_name"),
    ("CONOUT$", "reserved_name"),
    ("a\x00b.txt", "nul"),
    ("a\x07b.txt", "control_char"),
    ("uploads/name.", "trailing_dot_space"),
    ("uploads/name ", "trailing_dot_space"),
    ("uploads/a*.txt", "invalid_char"),
    ("uploads/a?.txt", "invalid_char"),
    ("", "empty"),
    ("   ", "empty"),
]


@pytest.mark.parametrize("raw,reason", _REJECTED + (_WINDOWS_ONLY if os.name == "nt" else []))
def test_special_paths_are_rejected_for_read_and_write(alice, raw, reason):
    for must_exist in (False, True):  # 쓰기(새 파일)·읽기(기존 파일) 경계 모두
        with pytest.raises(UserPathNotAllowedError) as info:
            paths.resolve_safe_path(raw, must_exist=must_exist)
        exc = info.value
        assert exc.reason == reason
        assert isinstance(exc, PathNotAllowedError) and isinstance(exc, SecurityError)
        assert exc.code == ErrorCode.PATH_NOT_ALLOWED
        assert exc.payload["error"] == "path_not_allowed" and exc.payload["reason"] == reason
        _assert_no_abs_path(exc, alice["root"], alice["paths"].files)
    assert not paths.is_allowed(raw)


def test_non_string_path_is_rejected(alice):
    with pytest.raises(UserPathNotAllowedError) as info:
        paths.resolve_safe_path(b"uploads/x.txt")
    assert info.value.reason == "invalid_type"
    with pytest.raises(UserPathNotAllowedError):
        paths.resolve_safe_path(None)


def test_must_exist_error_has_no_absolute_path(alice):
    with pytest.raises(FileNotFoundError) as info:
        paths.resolve_safe_path("uploads/missing.pdf", must_exist=True)
    assert "uploads/missing.pdf" in str(info.value)
    _assert_no_abs_path(info.value, alice["root"])


def test_directory_link_inside_files_is_rejected(alice, tmp_path):
    """F01 — junction/symlink 로 파일 루트 밖(자기 auth/)을 가리키는 경로."""
    up = alice["paths"]
    (up.auth_dir / "auth.db").write_bytes(b"SQLite format 3\x00")
    link = up.uploads / "shortcut"
    if not _make_dir_link(link, up.auth_dir):
        pytest.skip("이 OS/권한에서는 디렉터리 링크를 만들 수 없다")
    for raw in ("uploads/shortcut/auth.db", str(link / "auth.db"), "uploads/shortcut"):
        with pytest.raises(UserPathNotAllowedError) as info:
            paths.resolve_safe_path(raw)
        assert info.value.reason in {"link", "outside_root", "protected"}
        _assert_no_abs_path(info.value, alice["root"])


def test_directory_link_pointing_inside_files_is_also_rejected(alice):
    up = alice["paths"]
    link = up.uploads / "to_output"
    if not _make_dir_link(link, up.output):
        pytest.skip("이 OS/권한에서는 디렉터리 링크를 만들 수 없다")
    with pytest.raises(UserPathNotAllowedError) as info:
        paths.resolve_safe_path("uploads/to_output/x.txt")
    assert info.value.reason == "link"


def test_file_symlink_is_rejected(alice):
    up = alice["paths"]
    real = up.output / "real.txt"
    real.write_text("x", encoding="utf-8")
    link = up.uploads / "alias.txt"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("이 OS/권한에서는 symlink 를 만들 수 없다")
    with pytest.raises(UserPathNotAllowedError) as info:
        paths.resolve_safe_path("uploads/alias.txt")
    assert info.value.reason == "link"


def test_user_files_root_replaced_by_link_is_rejected(tmp_path):
    with multi_user_mode(tmp_path / "data"):
        principal = make_principal("carol@contoso.com")
        up = paths_for(principal)
        up.root.mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        if not _make_dir_link(up.files, elsewhere):
            pytest.skip("이 OS/권한에서는 디렉터리 링크를 만들 수 없다")
        with bound(principal):
            with pytest.raises(UserPathNotAllowedError) as info:
                paths.resolve_safe_path("x.txt")
        assert info.value.reason == "link"


# ----------------------------------------------------------------------
# F06 — 자기 auth.db·업무 DB·system 트리
# ----------------------------------------------------------------------
def test_own_auth_and_business_dbs_are_unreachable(alice):
    up = alice["paths"]
    up.auth_db.write_bytes(b"auth")
    up.onenote_db.write_bytes(b"db")
    sysp = system_paths()
    sysp.root.mkdir(parents=True, exist_ok=True)
    sysp.registry_db.write_bytes(b"reg")
    targets = [
        str(up.auth_db), str(up.wrapped_dek), str(up.onenote_db), str(up.metadata_db),
        str(up.teams_db), str(up.outlook_db), str(up.manifest), str(sysp.registry_db),
        str(sysp.deployment_json), "../auth/auth.db", "../db/metadata.db", "../manifest.json",
    ]
    for raw in targets:
        with pytest.raises(UserPathNotAllowedError):
            paths.resolve_safe_path(raw, must_exist=False)
    # 안전 열기 관문도 파일 루트 밖이면 거부한다
    with pytest.raises(UnsafePathError):
        open_for_read(up.auth_db, up.files)


def test_hardlink_to_auth_db_inside_files_cannot_be_read(alice):
    """경로 검사는 통과해도(일반 파일) 안전 열기가 하드링크를 거부한다 — 계층 방어."""
    up = alice["paths"]
    up.auth_db.write_bytes(b"SECRET-TOKEN-DB")
    alias = up.uploads / "innocent.db"
    try:
        os.link(up.auth_db, alias)
    except (OSError, NotImplementedError):
        pytest.skip("이 파일시스템에서는 하드링크를 만들 수 없다")
    resolved = paths.resolve_safe_path("uploads/innocent.db", must_exist=True)
    with pytest.raises(UnsafePathError) as info:
        open_for_read(resolved, up.files)
    assert info.value.reason == "hardlink"


def test_protected_trees_rejected_even_if_files_root_were_misconfigured(alice, monkeypatch):
    """루트 계산이 잘못돼 데이터 루트 전체가 허용되더라도 auth/·db/·system/ 은 거부."""
    up = alice["paths"]
    real_user_paths = paths._user_paths

    def widened():
        p = real_user_paths()
        return type(p)(**{**p.__dict__, "files": alice["root"]})

    monkeypatch.setattr(paths, "_user_paths", widened)
    for raw in (str(up.auth_db), str(up.onenote_db), str(system_paths().registry_db)):
        with pytest.raises(UserPathNotAllowedError) as info:
            paths.resolve_safe_path(raw)
        assert info.value.reason == "protected"


# ----------------------------------------------------------------------
# A vs B
# ----------------------------------------------------------------------
def test_alice_cannot_resolve_bobs_files(tmp_path):
    with multi_user_mode(tmp_path / "data"):
        alice_p = make_principal("alice@contoso.com")
        bob_p = make_principal("bob@contoso.com")
        a = ensure_user_dirs(paths_for(alice_p))
        b = ensure_user_dirs(paths_for(bob_p))
        (b.uploads / "bob.txt").write_text("bob secret", encoding="utf-8")
        with bound(alice_p):
            assert paths.allowed_roots() == [a.files]
            for raw in (str(b.uploads / "bob.txt"), str(b.files), "../../" + bob_p.user_key + "/files/uploads/bob.txt"):
                with pytest.raises(UserPathNotAllowedError):
                    paths.resolve_safe_path(raw)
        with bound(bob_p):
            assert paths.resolve_safe_path("uploads/bob.txt", must_exist=True).read_text(encoding="utf-8") == "bob secret"


def test_missing_principal_is_not_a_path_error(tmp_path):
    with multi_user_mode(tmp_path / "data"):
        with pytest.raises(SecurityError) as info:
            paths.resolve_safe_path("uploads/x.txt")
        assert info.value.code == ErrorCode.MISSING_PRINCIPAL
        assert not isinstance(info.value, PathNotAllowedError)
        with pytest.raises(SecurityError):
            paths.allowed_roots()


# ----------------------------------------------------------------------
# 감사
# ----------------------------------------------------------------------
def test_denial_is_audited_without_path(alice):
    from mcp_common.security_policy import ensure_deployment

    ensure_deployment()
    with pytest.raises(UserPathNotAllowedError):
        paths.resolve_safe_path("../auth/auth.db")
    audit_dir = system_paths().audit
    lines = [
        json.loads(line)
        for f in sorted(audit_dir.glob("audit-*.jsonl"))
        for line in f.read_text(encoding="utf-8").splitlines()
    ]
    denied = [r for r in lines if r["event"] == "path.denied"]
    assert len(denied) == 1
    record = denied[0]
    assert set(record) <= set(FIELDS)
    assert record["outcome"] == "denied"
    assert record["error_code"] == "path_not_allowed"
    assert record["user_key"] == alice["principal"].user_key
    assert record["request_id"] == "req-alice-0001"
    raw = json.dumps(record)
    assert "auth" not in raw.replace("auth_epoch", "") and str(alice["root"]) not in raw
    assert "alice@" not in raw


def test_is_allowed_does_not_audit(alice):
    assert not paths.is_allowed("../auth/auth.db")
    assert not list(system_paths().audit.glob("audit-*.jsonl"))


# ----------------------------------------------------------------------
# mode 0 — 기존 동작 그대로
# ----------------------------------------------------------------------
def test_mode0_behaviour_unchanged(tmp_path, monkeypatch):
    with single_user_mode():
        monkeypatch.delenv("MCP_ALLOWED_PATHS", raising=False)
        monkeypatch.delenv("MCP_DATA_DIR", raising=False)
        assert paths.allowed_roots() == [paths._PROJECT_ROOT]

        monkeypatch.setenv("MCP_ALLOWED_PATHS", str(tmp_path))
        assert paths.allowed_roots() == [tmp_path.resolve()]
        inside = tmp_path / "a.txt"
        assert paths.resolve_safe_path(str(inside)) == inside.resolve()
        assert paths.is_allowed(str(inside))

        with pytest.raises(PathNotAllowedError) as info:
            paths.resolve_safe_path(str(tmp_path.parent / "elsewhere.txt"))
        exc = info.value
        assert type(exc) is PathNotAllowedError and not isinstance(exc, SecurityError)
        assert "path outside allowed roots" in str(exc) and "MCP_ALLOWED_PATHS" in str(exc)

        with pytest.raises(PathNotAllowedError, match="empty path"):
            paths.resolve_safe_path("")


def test_mode0_error_converts_to_security_error_without_path(tmp_path, monkeypatch):
    with single_user_mode():
        monkeypatch.setenv("MCP_ALLOWED_PATHS", str(tmp_path / "root"))
        with pytest.raises(PathNotAllowedError) as info:
            paths.resolve_safe_path(str(tmp_path / "other.txt"))
        converted = info.value.to_security_error()
        assert converted.code == ErrorCode.PATH_NOT_ALLOWED
        assert str(tmp_path) not in str(converted)


def test_mode1_error_to_security_error_is_itself(alice):
    with pytest.raises(UserPathNotAllowedError) as info:
        paths.resolve_safe_path("CON")
    assert info.value.to_security_error() is info.value
