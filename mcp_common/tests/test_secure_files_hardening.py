"""WP3 안전 파일 관문 — `mcp_common.secure_files` (spec/spec_멀티유저.md ②-7.4, 테스트 F01·F05).

공개 시그니처는 WP0 계약이다. 여기서는 강화된 동작(정화·링크 거부·handle 재검증·요청별 temp)을 본다.
"""

import os
import subprocess
import threading
import unicodedata
from pathlib import Path

import pytest

from mcp_common import secure_files
from mcp_common.secure_files import (
    UnsafePathError,
    atomic_write_bytes,
    create_exclusive,
    ensure_within,
    is_reserved_name,
    open_for_read,
    public_path,
    request_temp_dir,
    safe_filename,
    safe_join,
    write_new_file,
)
from mcp_common.security_contracts import ErrorCode
from mcp_common.testing import make_principal, multi_user_mode
from mcp_common.user_paths import ensure_user_dirs, paths_for


def _make_dir_link(link: Path, target: Path) -> bool:
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


def _make_file_symlink(link: Path, target: Path) -> bool:
    try:
        os.symlink(target, link)
        return True
    except (OSError, NotImplementedError):
        return False


@pytest.fixture
def user(tmp_path):
    with multi_user_mode(tmp_path / "data"):
        yield ensure_user_dirs(paths_for(make_principal("alice@contoso.com")))


# ----------------------------------------------------------------------
# safe_filename
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Windows\\system32\\cmd.exe", "cmd.exe"),
        ("report.pdf", "report.pdf"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("NUL .txt", "_NUL .txt"),
        ("COM¹.log", "_COM¹.log"),
        ("conout$", "_conout$"),
        ("a.txt:secret", "a.txt_secret"),
        ("a.txt::$DATA", "a.txt__$DATA"),
        ("name. . ", "name"),
        ("  spaced  ", "spaced"),
        ("a<b>c|d?e*f\"g", "a_b_c_d_e_f_g"),
        ("tab\there", "tab_here"),
        ("a\uff0fb\uff3cc", "a_b_c"),  # 전각 구분자 (WorstFit)
        ("evil\u202etxt.exe", "eviltxt.exe"),
    ],
)
def test_safe_filename_examples(raw, expected):
    assert safe_filename(raw) == expected


@pytest.mark.parametrize("raw", [None, "", ".", "..", "...", "/", "\\", "dir/", " . "])
def test_safe_filename_falls_back_to_default(raw):
    assert safe_filename(raw) == "file"
    assert safe_filename(raw, default="첨부") == "첨부"


def test_safe_filename_sanitizes_default_too():
    assert safe_filename(None, default="../CON") == "_CON"
    assert safe_filename("", default="..") == "file"


def test_safe_filename_normalizes_to_nfc():
    decomposed = "e\u0301te\u0301.txt"
    assert safe_filename(decomposed) == unicodedata.normalize("NFC", decomposed)


def test_safe_filename_caps_utf8_bytes_and_keeps_extension():
    name = "가" * 300 + ".pdf"
    cleaned = safe_filename(name)
    assert len(cleaned.encode("utf-8")) <= 200
    assert cleaned.endswith(".pdf")
    cleaned.encode("utf-8").decode("utf-8")  # 멀티바이트를 반으로 자르지 않음
    long_ext = "x" * 10 + "." + "y" * 300
    assert len(safe_filename(long_ext).encode("utf-8")) <= 200


_NASTY = [
    "../" * 50 + "x", "\\\\server\\share\\f", "\\\\?\\C:\\x", "C:x", "a:b:c", "\x00\x01\x02",
    "CON.tar.gz", "lpt¹", "prn .txt", "....", "a" * 1000, "😀" * 100 + ".png", "x \u202e y.",
    "\u2215etc\u2215passwd", "₩₩server₩share", "<script>", "  \t\n ",
]


@pytest.mark.parametrize("raw", _NASTY)
def test_safe_filename_invariants(raw):
    cleaned = safe_filename(raw)
    assert cleaned and cleaned not in (".", "..")
    assert "/" not in cleaned and "\\" not in cleaned and ":" not in cleaned
    assert not any(ord(c) < 32 for c in cleaned)
    assert cleaned == cleaned.rstrip(". ")
    assert not is_reserved_name(cleaned)
    assert len(cleaned.encode("utf-8")) <= 200
    assert cleaned == unicodedata.normalize("NFC", cleaned)
    assert secure_files._component_problem(cleaned) is None


def test_is_reserved_name():
    for name in ("CON", "con", "Nul.txt", "COM9", "LPT1.tar.gz", "AUX ", "COM²", "CONIN$"):
        assert is_reserved_name(name), name
    for name in ("CONSOLE", "COM0", "COM10", "nul_", "_CON", "report.con"):
        assert not is_reserved_name(name), name


# ----------------------------------------------------------------------
# ensure_within / safe_join
# ----------------------------------------------------------------------
def test_ensure_within_rejects_escape_and_special_components(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert ensure_within(root / "a" / "b.txt", root) == root / "a" / "b.txt"
    cases = {
        root / ".." / "x": "outside_root",
        tmp_path / "other": "outside_root",
        root / "CON": None,  # Windows 가 장치로 바꾸면 outside_root, 아니면 reserved_name
        root / "nul.txt": "reserved_name",
        root / "x.txt:stream": None,
    }
    for path, reason in cases.items():
        with pytest.raises(UnsafePathError) as info:
            ensure_within(path, root)
        if reason:
            assert info.value.reason == reason
        assert str(tmp_path) not in str(info.value)


def test_ensure_within_rejects_link_components(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    if not _make_dir_link(root / "j", outside):
        pytest.skip("디렉터리 링크를 만들 수 없다")
    with pytest.raises(UnsafePathError) as info:
        ensure_within(root / "j" / "x.txt", root)
    assert info.value.reason == "link"


def test_safe_join_keeps_remote_names_single(tmp_path):
    base = tmp_path / "dl"
    base.mkdir()
    for raw in ("../../evil.txt", "C:\\evil.txt", "/etc/passwd", "..", "CON"):
        joined = safe_join(base, raw)
        assert joined.parent == Path(os.path.abspath(base))


def test_unsafe_path_error_converts_to_security_error():
    exc = UnsafePathError("path outside root", "outside_root").to_security_error()
    assert exc.code == ErrorCode.PATH_NOT_ALLOWED


# ----------------------------------------------------------------------
# 생성·저장
# ----------------------------------------------------------------------
def test_create_exclusive_adds_suffix_and_never_overwrites(user):
    first = write_new_file(user.downloads, "a.txt", b"1", root=user.files)
    second = write_new_file(user.downloads, "a.txt", b"2", root=user.files)
    assert first.name == "a.txt" and second.name == "a (1).txt"
    assert first.read_bytes() == b"1" and second.read_bytes() == b"2"
    assert first.is_absolute()


def test_create_exclusive_root_rejects_directory_outside_root(user, tmp_path):
    outside = tmp_path / "outside"
    with pytest.raises(UnsafePathError):
        create_exclusive(outside, "x.txt", root=user.files)
    assert not outside.exists()  # 탈출 경로에 디렉터리를 만들지도 않는다
    with pytest.raises(UnsafePathError):
        write_new_file(user.auth_dir, "x.txt", b"x", root=user.files)


def test_write_new_file_remote_name_cannot_escape(user):
    path = write_new_file(user.downloads_for("outlook"), "../../../auth/auth.db", b"x", root=user.files)
    assert path.parent == Path(os.path.abspath(user.downloads_for("outlook")))
    assert path.name == "auth.db"
    assert not user.auth_db.exists()


def test_create_exclusive_in_linked_directory_is_rejected_in_mode1(user, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = user.files / "linked"
    if not _make_dir_link(link, outside):
        pytest.skip("디렉터리 링크를 만들 수 없다")
    with pytest.raises(UnsafePathError):
        write_new_file(link, "x.txt", b"x", root=user.files)
    with pytest.raises(UnsafePathError):
        write_new_file(link, "x.txt", b"x")  # root 없이도 mode 1 은 링크 디렉터리 거부
    assert not (outside / "x.txt").exists()


def test_atomic_write_replaces_and_leaves_no_temp(user):
    target = user.output / "state.json"
    atomic_write_bytes(target, b"one", root=user.files)
    atomic_write_bytes(target, b"two", root=user.files)
    assert target.read_bytes() == b"two"
    assert [p.name for p in user.output.iterdir()] == ["state.json"]


def test_atomic_write_refuses_link_target(user, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"keep")
    link = user.output / "link.txt"
    if not _make_file_symlink(link, victim):
        pytest.skip("symlink 를 만들 수 없다")
    with pytest.raises(UnsafePathError):
        atomic_write_bytes(link, b"pwned", root=user.files)
    assert victim.read_bytes() == b"keep"


def test_atomic_write_rejects_outside_root(user, tmp_path):
    with pytest.raises(UnsafePathError):
        atomic_write_bytes(user.db_dir / "x.json", b"x", root=user.files)


# ----------------------------------------------------------------------
# open_for_read
# ----------------------------------------------------------------------
def test_open_for_read_returns_binary_file(user):
    path = write_new_file(user.uploads, "doc.bin", b"\x00\x01data", root=user.files)
    with open_for_read(path, user.files) as fh:
        assert fh.read() == b"\x00\x01data"
        assert "b" in fh.mode


def test_open_for_read_rejects_directory_missing_and_outside(user, tmp_path):
    with pytest.raises(IsADirectoryError):
        open_for_read(user.uploads, user.files)
    with pytest.raises(FileNotFoundError) as info:
        open_for_read(user.uploads / "missing.txt", user.files)
    assert str(tmp_path) not in str(info.value)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"x")
    with pytest.raises(UnsafePathError):
        open_for_read(outside, user.files)
    with pytest.raises((IsADirectoryError, UnsafePathError)):
        open_for_read(user.files, user.files)


def test_open_for_read_rejects_hardlink(user):
    original = write_new_file(user.uploads, "a.txt", b"x", root=user.files)
    try:
        os.link(original, user.uploads / "b.txt")
    except (OSError, NotImplementedError):
        pytest.skip("하드링크를 만들 수 없다")
    with pytest.raises(UnsafePathError) as info:
        open_for_read(user.uploads / "b.txt", user.files)
    assert info.value.reason == "hardlink"


def test_open_for_read_through_junction_is_rejected(user, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    if not _make_dir_link(user.uploads / "j", outside):
        pytest.skip("디렉터리 링크를 만들 수 없다")
    with pytest.raises(UnsafePathError):
        open_for_read(user.uploads / "j" / "secret.txt", user.files)


def test_open_handle_is_reverified_when_precheck_is_bypassed(user, tmp_path, monkeypatch):
    """TOCTOU — 사전 검사가 통과한 뒤 경로가 바뀐 상황을 사전 검사 무력화로 흉내 낸다.

    연 handle 의 실제 경로(Windows) / 성분별 O_NOFOLLOW(POSIX) 가 마지막 방어선이다.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    if not _make_dir_link(user.uploads / "swapped", outside):
        pytest.skip("디렉터리 링크를 만들 수 없다")
    monkeypatch.setattr(secure_files, "ensure_within", lambda p, r: Path(os.path.abspath(p)))
    with pytest.raises(UnsafePathError):
        open_for_read(user.uploads / "swapped" / "secret.txt", user.files)
    with pytest.raises(UnsafePathError):
        write_new_file(user.uploads / "swapped", "new.txt", b"x", root=user.files)


# ----------------------------------------------------------------------
# request_temp_dir (F05)
# ----------------------------------------------------------------------
def test_request_temp_dir_cleans_only_its_own_directory(user):
    with request_temp_dir(user, "req-bbbbbbbb") as b_dir:
        (b_dir / "b.txt").write_bytes(b"b")
        with request_temp_dir(user, "req-aaaaaaaa") as a_dir:
            (a_dir / "a.txt").write_bytes(b"a")
            (a_dir / "sub").mkdir()
            (a_dir / "sub" / "deep.txt").write_bytes(b"d")
        assert not a_dir.exists()
        assert (b_dir / "b.txt").read_bytes() == b"b"
    assert not b_dir.exists()
    assert user.tmp.is_dir()


def test_request_temp_dir_concurrent_cleanup_keeps_other_request(user):
    stop = threading.Event()
    errors = []

    def request_b():
        try:
            with request_temp_dir(user, "req-long-running") as b_dir:
                for i in range(200):
                    (b_dir / f"{i}.txt").write_bytes(b"x")
                    if not b_dir.is_dir():
                        errors.append("B temp removed")
                        return
                stop.wait(5)
                if len(list(b_dir.iterdir())) != 200:
                    errors.append("B temp changed")
        except Exception as exc:  # pragma: no cover - 실패 진단용
            errors.append(repr(exc))

    thread = threading.Thread(target=request_b)
    thread.start()
    for i in range(30):
        with request_temp_dir(user, f"req-short-{i:04d}") as a_dir:
            (a_dir / "a.txt").write_bytes(b"a")
    stop.set()
    thread.join(10)
    assert not errors
    assert list(user.tmp.iterdir()) == []


def test_request_temp_dir_users_are_independent(tmp_path):
    with multi_user_mode(tmp_path / "data"):
        a = ensure_user_dirs(paths_for(make_principal("alice@contoso.com")))
        b = ensure_user_dirs(paths_for(make_principal("bob@contoso.com")))
        with request_temp_dir(b, "same-request-id") as b_dir:
            (b_dir / "keep.txt").write_bytes(b"b")
            with request_temp_dir(a, "same-request-id") as a_dir:
                assert a_dir != b_dir
            assert (b_dir / "keep.txt").exists()


def test_request_temp_dir_refuses_existing_directory(user):
    existing = user.request_tmp("req-existing1")
    existing.mkdir(parents=True)
    (existing / "other.txt").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        with request_temp_dir(user, "req-existing1"):
            pass
    assert (existing / "other.txt").read_bytes() == b"keep"


def test_request_temp_dir_rejects_bad_request_id(user):
    for rid in ("../x", "a/b", "short", "x" * 65):
        with pytest.raises(ValueError):
            with request_temp_dir(user, rid):
                pass


def test_request_temp_dir_does_not_follow_swapped_link(user, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_bytes(b"keep")
    with request_temp_dir(user, "req-swapped01") as directory:
        os.rmdir(directory)
        if not _make_dir_link(directory, victim):
            pytest.skip("디렉터리 링크를 만들 수 없다")
    assert (victim / "precious.txt").read_bytes() == b"keep"


def test_request_temp_dir_refuses_linked_tmp(tmp_path):
    with multi_user_mode(tmp_path / "data"):
        up = paths_for(make_principal("dave@contoso.com"))
        up.files.mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        if not _make_dir_link(up.tmp, elsewhere):
            pytest.skip("디렉터리 링크를 만들 수 없다")
        with pytest.raises(UnsafePathError):
            with request_temp_dir(up, "req-linkedtmp"):
                pass
        assert list(elsewhere.iterdir()) == []


# ----------------------------------------------------------------------
# public_path
# ----------------------------------------------------------------------
def test_public_path_is_relative_and_never_absolute(user, tmp_path):
    path = write_new_file(user.downloads_for("onedrive"), "x.txt", b"x", root=user.files)
    assert public_path(user, path) == "downloads/onedrive/x.txt"
    with pytest.raises(UnsafePathError) as info:
        public_path(user, user.auth_db)
    assert str(tmp_path) not in str(info.value)
