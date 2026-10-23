# mcp_todo — Microsoft To Do MCP Server

Microsoft Graph **To Do (Tasks)** API를 MCP 서버로 노출합니다. `mcp_calendar` / `mcp_outlook` 의 패턴(Streamable HTTP, 공식 MCP SDK)을 그대로 따라갑니다.

## 구조

```
mcp_todo/
├── todo_types.py          # Pydantic 모델 (TaskList, TodoTask)
├── graph_todo_query.py    # Graph API 호출 (GET/POST/PATCH/DELETE)
├── graph_todo_client.py   # Facade (인증/초기화/위임)
├── todo_service.py        # MCP 도구 레이어 (기본값 처리, list 이름 해석)
└── mcp_server/
    ├── handlers.py        # 도구 계약 로드 + 핸들러 (두 트랜스포트의 유일한 원본)
    ├── server_stdio.py    # STDIO 트랜스포트 (mcp_common.stdio_transport)
    └── server_stream.py   # Streamable HTTP 트랜스포트 (mcp_common.http_transport)
```

도구 계약(이름·설명·파라미터·enum·기본값)의 **단일 원본은 `spec/param_spec/todo.yaml`** 입니다.
`inputSchema`·기본값·서비스 호출 인자는 기동 시 `mcp_common.param_spec` 가 여기서 파생시킵니다
(코드 생성물 없음). 도구를 고치려면 그 YAML 만 고치면 됩니다 —
`mcp_editor` 의 `tool_definition_templates.yaml` 은 더 이상 참조하지 않습니다.

## 노출되는 MCP 도구

| 도구 | 설명 |
|------|------|
| `todo_lists_view` | 모든 태스크 리스트 조회 |
| `todo_list_create` | 새 태스크 리스트 생성 (`display_name`) |
| `todo_list_delete` | 태스크 리스트 삭제 (list_id 또는 displayName/wellknownListName) |
| `todo_tasks_view` | 리스트 내 태스크 조회 (status 필터, top, orderby) |
| `todo_task_get` | 단일 태스크 조회 |
| `todo_task_create` | 새 태스크 생성 (title, body, importance, due/reminder, categories) |
| `todo_task_update` | 태스크 수정 — `status="completed"`로 완료 처리 |
| `todo_task_delete` | 태스크 삭제 |

> `list_id_or_name` 파라미터는 list_id, `displayName`, 또는 `wellknownListName`(예: `defaultList`)을 받아 자동 해석합니다. 비워두면 기본 리스트(`defaultList`)를 사용합니다.

## Graph API 엔드포인트

베이스: `https://graph.microsoft.com/v1.0/users/{user_email}/todo`
(멀티유저 모드 `MS365_MULTI_USER=1` 에서는 `https://graph.microsoft.com/v1.0/me/todo` —
토큰 주인에 고정. `user_email` 은 인증된 호출자의 연결 계정만 허용하고, 서비스는 사용자별로
서비스 풀이 만든다: `handlers.create_service`)

- bearer 를 단 요청은 redirect 를 따라가지 않는다(`allow_redirects=False`, 두 모드 공통). 3xx 는
  상태 코드만 담은 오류로 돌려준다.
- `@odata.nextLink` 이어 조회는 `GraphTodoQuery.fetch_next_link()` 로만 한다 — 본인
  `/v1.0/me/todo/...` 또는 본인 `/users/{id}/todo/...`, dot-segment 없음. 그 밖은 `path_not_allowed`.
  정책 구현 `graph_url_policy.py` 는 calendar·onedrive 와 같은 사본이다.
- 기존 Python 연동용 `from mcp_todo.todo_service import todo_service` 는 유지된다 — mode 0 에서는
  handlers 의 legacy 인스턴스(지연 속성, `import *` 에도 포함), 멀티유저 모드에서는
  `LegacyAuthDisabledError`(`import *` 에는 포함되지 않아 아무것도 만들지 않는다).
- 입력 상한(R02): `top` 1~1000, `categories` 최대 50개 — YAML `minimum`/`maximum`/`maxItems` 가 MCP
  입력을 막고, 서비스 함수도 Graph 요청 전에 `input_bounds` 로 한 번 더 막는다(`invalid_argument`).

- `GET /lists` — 리스트 조회
- `POST /lists` — 리스트 생성
- `DELETE /lists/{listId}` — 리스트 삭제
- `GET /lists/{listId}/tasks` — 태스크 조회 (`$filter`, `$orderby`, `$top`)
- `GET /lists/{listId}/tasks/{taskId}` — 단일 태스크
- `POST /lists/{listId}/tasks` — 태스크 생성
- `PATCH /lists/{listId}/tasks/{taskId}` — 태스크 수정
- `DELETE /lists/{listId}/tasks/{taskId}` — 태스크 삭제

## 필수 Azure 권한

`AZURE_SCOPES` 환경변수에 **`Tasks.ReadWrite`** 가 포함되어야 합니다. (공유 리스트까지 다루려면 `Tasks.ReadWrite.Shared`도 필요)

현재 프로젝트 `.env` 예시:

```
AZURE_SCOPES=User.Read Mail.Read Mail.Send Mail.ReadWrite Calendars.ReadWrite Tasks.ReadWrite offline_access openid
```

스코프 변경 후에는 재인증(`ms365_setup_oauth`)이 필요합니다.

## 실행

```bash
# 기본 포트: 5006
python -m mcp_todo.mcp_server.server_stream

# 포트 변경
MCP_SERVER_PORT=9000 python -m mcp_todo.mcp_server.server_stream
```

엔드포인트:
- MCP: `POST/GET/DELETE http://localhost:5006/mcp` (Streamable HTTP, `Mcp-Session-Id` 헤더)
- Health: `GET http://localhost:5006/health`

## 클라이언트 등록

`setup-mcp` 스킬로 Claude Code / VSCode Copilot 에 자동 등록할 수 있습니다.
