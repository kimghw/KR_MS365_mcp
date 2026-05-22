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
    └── server_stream.py   # 공식 MCP SDK Streamable HTTP 서버
```

도구 정의(YAML)는 `mcp_editor/mcp_todo/tool_definition_templates.yaml` 입니다.

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
# 기본 포트: 8093
python -m mcp_todo.mcp_server.server_stream

# 포트 변경
MCP_SERVER_PORT=9000 python -m mcp_todo.mcp_server.server_stream
```

엔드포인트:
- MCP: `POST/GET/DELETE http://localhost:8093/mcp` (Streamable HTTP, `Mcp-Session-Id` 헤더)
- Health: `GET http://localhost:8093/health`

## 클라이언트 등록

`setup-mcp` 스킬로 Claude Code / VSCode Copilot 에 자동 등록할 수 있습니다.
