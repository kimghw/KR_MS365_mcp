"""시나리오 4 보강 — 파일 경로로 다른 사용자 영역·자기 비밀 저장소에 닿을 수 없다 (②-7.4, ②-10 F01·F06).

경로를 받는 도구(FileHandler 변환, Outlook 발송 첨부, Teams 파일 전송)에 B 의 `files/` 절대경로,
`..` 상대 탈출, 자기 `auth/`·`db/` 를 넣어도 `path_not_allowed` 로 끝나고 내용·절대경로가
응답에 실리지 않으며 Graph 로 아무것도 나가지 않는다.
"""

import pytest

from mcp_common.user_paths import ensure_user_dirs, paths_for

SECRET = "BOB-SECRET-FILE-CONTENT"


@pytest.fixture
def bob_secret(mu, bob):
    paths = ensure_user_dirs(paths_for(bob.user_key))
    target = paths.files / "uploads" / "secret.txt"
    target.write_text(SECRET, encoding="utf-8")
    return target


def _targets(mu, alice, bob, bob_secret):
    a = paths_for(alice.user_key)
    return {
        "b_absolute": str(bob_secret),
        "b_relative_escape": f"../../{bob.user_key}/files/uploads/secret.txt",
        "b_relative_escape_backslash": f"..\\..\\{bob.user_key}\\files\\uploads\\secret.txt",
        "own_auth_db": str(a.auth_db),
        "own_db_dir": str(a.metadata_db),
        "system_registry": str(mu.root / "system" / "registry.db"),
    }


def _assert_denied(result, mu):
    assert result.is_error, result.text[:300]
    assert result.error_code in ("path_not_allowed", "not_found"), result.text[:300]
    assert SECRET not in result.text
    assert str(mu.root) not in result.text and str(mu.root).replace("\\", "/") not in result.text


@pytest.mark.parametrize("which", ["b_absolute", "b_relative_escape", "b_relative_escape_backslash",
                                   "own_auth_db", "own_db_dir", "system_registry"])
def test_file_handler_convert_cannot_leave_callers_files(mu, alice, bob, bob_secret, which):
    target = _targets(mu, alice, bob, bob_secret)[which]
    with mu.client("file_handler") as c:
        result = c.call(alice.key, "convert_file_to_text", {"input_path": target})
    _assert_denied(result, mu)
    assert mu.graph.calls == []


def test_file_handler_convert_accepts_own_relative_file(mu, alice):
    """자기 `files/` 안 상대경로는 경로 관문을 통과한다(변환기 라이브러리가 없는 환경이라 내용 변환은 보지 않는다)."""
    paths = ensure_user_dirs(paths_for(alice.user_key))
    (paths.files / "uploads" / "mine.txt").write_text("alice own text", encoding="utf-8")
    with mu.client("file_handler") as c:
        result = c.call(alice.key, "convert_file_to_text", {"input_path": "uploads/mine.txt"})
    assert result.error_code not in ("path_not_allowed", "not_found", "missing_principal"), result.text[:300]
    assert "No converter" in result.text or not result.is_error
    assert str(mu.root) not in result.text


@pytest.mark.parametrize("which", ["b_absolute", "b_relative_escape", "own_auth_db"])
def test_outlook_send_attachment_cannot_read_other_users_file(mu, alice, bob, bob_secret, which):
    target = _targets(mu, alice, bob, bob_secret)[which]
    with mu.client("outlook") as c:
        result = c.call(alice.key, "mail_send", {"to_recipients": ["x@fabrikam.com"], "subject": "s", "body": "b",
                                                 "attachments": [target]})
    _assert_denied(result, mu)
    assert [c for c in mu.graph.calls if c.method != "GET"] == []
    for call in mu.graph.calls:
        assert SECRET not in str(call.kwargs)


@pytest.mark.parametrize("which", ["b_absolute", "b_relative_escape", "own_auth_db"])
def test_teams_send_file_cannot_read_other_users_file(mu, alice, bob, bob_secret, which):
    target = _targets(mu, alice, bob, bob_secret)[which]
    with mu.client("teams") as c:
        result = c.call(alice.key, "handler_teams_send_chat_file", {"content": "hi", "file_path": target})
    _assert_denied(result, mu)
    for call in mu.graph.calls:
        assert call.method == "GET" or SECRET not in str(call.kwargs)
