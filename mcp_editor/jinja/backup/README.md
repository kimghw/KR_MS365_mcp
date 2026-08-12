# backup/ — 생성에 쓰이지 않는 참고용 보관본

이 디렉터리의 파일들은 **더 이상 코드 생성에 사용되지 않는다.** 과거 구현을
참고할 목적으로만 남겨 둔 보관본이다.

## 중요

- 활성 생성기/템플릿은 이 디렉터리가 아니라 상위 경로에 있다.
  - 템플릿: `mcp_editor/jinja/python/`, `mcp_editor/jinja/javascript/`,
    `mcp_editor/jinja/common/`
  - 생성기: `mcp_editor/jinja/generate_universal_server.py`,
    `mcp_editor/jinja/scaffold_generator.py`,
    `mcp_editor/jinja/create_mcp_project.py`,
    `mcp_editor/jinja/generate_editor_config.py`
- **여기 있는 파일을 수정해도 생성 결과는 바뀌지 않는다.** 실제 산출물을
  바꾸려면 위의 활성 경로를 고쳐야 한다.
- 여기 있는 코드는 보안 수정이 반영되어 있지 **않다.** 특히
  `host="0.0.0.0"` 같은 옛 기본값이 그대로 남아 있으므로,
  이 파일을 복사해 새 서버를 만들지 마라. 현재 바인드 정책은
  `mcp_common/net.py` 의 `resolve_bind_host()` 가 단일 기준(SSOT)이며
  기본값은 `127.0.0.1` 이다.

## 보관 경위

기존에 `mcp_editor/jinja/backup/` 과 `mcp_editor/jinja/legacy_backup/` 두
디렉터리에 동일한 파일이 중복 존재했다. 아래 4개 파일이 바이트 단위로 완전히
동일함을 확인했고, `backup/` 쪽이 `generate_server_legacy.py` 를 추가로
갖고 있는 상위집합이라 `backup/` 만 남기고 `legacy_backup/` 을 제거했다.

- `outlook_server_template.jinja2`
- `file_handler_server_template.jinja2`
- `generate_outlook_server.py`
- `generate_file_handler_server.py`

제거된 `legacy_backup/` 은 git 이력에 남아 있으므로 필요하면 복구할 수 있다.
