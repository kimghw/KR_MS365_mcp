# MCP Teams Module

Microsoft Graph API를 사용한 Teams 서비스 모듈입니다.
`mcp_outlook` 모듈과 동일한 구조로 리팩토링되었습니다.

## 구조

```
mcp_teams/
├── __init__.py              # 모듈 초기화
├── teams_types.py           # 타입 정의 (dataclass)
├── graph_teams_client.py    # Graph API 클라이언트
├── teams_service.py         # 서비스 레이어 (Facade 패턴)
├── teams_db_manager.py      # DB 관리 (한글 이름 저장)
├── mcp_server/              # MCP 서버
│   ├── __init__.py
│   ├── handlers.py          # 핸들러 + Server 구성 (두 트랜스포트의 유일한 원본)
│   ├── server_stdio.py      # stdio 트랜스포트 (얇은 구동부)
│   └── server_stream.py     # Streamable HTTP 트랜스포트 (포트 5003)
├── tests/                   # 테스트
│   ├── __init__.py
│   ├── test_teams_service.py
│   └── test_send_chat_file.py   # 채팅에 파일 보내기 (Graph 에 닿지 않음)
└── README.md
```

## 도구 계약 (param_spec)

도구 이름·설명·파라미터·기본값은 **`spec/param_spec/teams.yaml` 한 곳에만** 있다.
`inputSchema` 와 서비스 호출 인자는 기동 시 `mcp_common.param_spec` 가 파생시킨다
(코드 생성 없음, 미리 구워 둔 산출물 없음). 파라미터를 늘리거나 기본값을 바꿀 때는
그 YAML 만 고친다 — `handlers.py` 에 도구 정의를 적으면 사본이 두 벌이 된다.

기본값(`limit` 50, `prefix` `[claude]`, `content_type` `text`)도 전부 YAML 에 있다.
`handler_teams_send_chat_file` 만 `prefix` 가 빈 문자열, `content_type` 이 `html` 이다.
`user_email` 만은 예외로, 값이 비면 `mcp_common.user_resolver` 가 기본 사용자를 고른다.

## 기능

### 채팅 관리
- `list_chats`: 채팅 목록 조회
- `get_chat`: 특정 채팅 정보 조회

### 메시지 관리
- `get_chat_messages`: 채팅 메시지 목록 조회
- `send_chat_message`: 채팅에 메시지 전송
- `send_chat_file`: 채팅에 파일을 붙여 메시지 전송 (아래 "채팅에 파일 보내기" 참조)

### 팀 관리
- `list_teams`: 사용자가 속한 팀 목록 조회

### 채널 관리
- `list_channels`: 팀의 채널 목록 조회
- `get_channel_messages`: 채널 메시지 목록 조회
- `send_channel_message`: 채널에 메시지 전송
- `get_message_replies`: 메시지 답글 목록 조회

### 한글 이름 관리 (DB 연동)
- `save_korean_name`: 채팅방의 한글 이름을 DB에 저장
- `save_korean_names_batch`: 여러 채팅방의 한글 이름을 한 번에 저장
- `find_chat_by_name`: 사용자 이름으로 채팅 검색 (한글/영문 모두 지원)
- `sync_chats`: 채팅 목록을 DB에 동기화
  - Graph 가 돌려준 목록이 **전체일 때만**(다음 페이지 없음) 목록에 없는 기존 채팅을 비활성화하고,
    일부만 받았으면 추가·갱신만 한다.
  - 1:1 채팅의 상대방은 멤버 순서와 무관하게 **이메일이 본인과 다른 멤버**다(못 찾으면 `members[1]`).
- `get_chats_without_korean`: 한글 이름이 없는 채팅 목록 조회

## 사용법

```python
from mcp_teams import TeamsService

async def main():
    service = TeamsService()
    await service.initialize()

    try:
        # 채팅 목록 조회
        chats = await service.list_chats("user@example.com")
        print(chats)

        # 메시지 전송 (Notes 채팅)
        result = await service.send_chat_message(
            user_email="user@example.com",
            content="Hello from Claude!",
            prefix="[Bot]",
        )
        print(result)

        # 파일을 붙여 메시지 전송 (chat_id·recipient_email 이 없으면 Notes 채팅)
        result = await service.send_chat_file(
            user_email="user@example.com",
            content="<p>증빙 파일입니다.</p>",
            file_path="C:/temp/evidence.pdf",  # 또는 file_name + file_base64
            # recipient_email="other@example.com",  # 그 사람과의 1:1 채팅으로 (없으면 만든다)
        )
        print(result)  # {"success": True, "message_id": "...", "chat_id": "48:notes", "file": {...}}

        # 팀 목록 조회
        teams = await service.list_teams("user@example.com")
        print(teams)

        # 한글 이름 저장 (단일)
        result = await service.save_korean_name(
            user_email="user@example.com",
            topic_en="Hangro Kim",
            topic_kr="한그로",
        )
        print(result)

        # 한글 이름 배치 저장
        result = await service.save_korean_names_batch(
            user_email="user@example.com",
            names=[
                {"topic_en": "Hangro Kim", "topic_kr": "한그로"},
                {"topic_en": "John Doe", "topic_kr": "존 도"},
            ]
        )
        print(result)

        # 이름으로 채팅 검색
        result = await service.find_chat_by_name(
            user_email="user@example.com",
            recipient_name="한그로",
        )
        print(result)  # {"success": True, "chat_id": "..."}
    finally:
        await service.close()
```

## 채팅에 파일 보내기 (`handler_teams_send_chat_file`)

2026-10-03 추가. 다른 채팅 도구는 글만 보내고, 이 도구는 파일을 붙여 메시지를 보낸다.
파라미터 이름·필수 여부·기본값의 원본은 `spec/param_spec/teams.yaml` 의 해당 항목이다 —
여기에는 쓰는 법과 동작만 적는다.

- **파일**: `file_base64`(내용) 나 `file_path`(서버가 도는 PC 의 경로) 가운데 하나로 준다.
  `file_path` 를 주면 `file_name` 은 생략할 수 있다(그 파일의 이름을 쓴다). 둘 다 주면
  `file_base64` 를 쓴다. `file_name` 에 경로가 섞여 있으면 이름만 남긴다.
- **보낼 곳**: `chat_id` 가 있으면 그 채팅, 없으면 `recipient_email` 과의 1:1 채팅(없으면 만든다),
  둘 다 없거나 받는 사람이 나 자신이면 나의 Notes(`48:notes`).
- **본문**: `content` 는 필수다. `content_type` 이 `text` 면 줄바꿈을 살려 html 로 바꿔 보낸다
  (첨부 표식 때문에 실제로는 항상 html 로 나간다).
- **필요한 Graph 권한**: `Chat.ReadWrite`, `Files.ReadWrite` (2026-10-03 현재 등록된 계정에는 이미 있다).

잘못된 입력(파일을 주지 않음·틀린 base64·읽을 수 없는 경로·빈 파일·파일 이름 없음)은 Graph 를
부르기 전에 `{"success": False, "error": "..."}` 로 돌려준다.

### 처리 차례

Graph 에는 채팅에 파일을 올리는 한 번의 호출이 없어 차례대로 한다. `TeamsService.send_chat_file`
이 파일 읽기·이름 정리·입력 검증을 하고, `GraphTeamsClient.send_chat_file` 이 아래를 부른다.

| 차례 | Graph 호출 | 하는 일 |
|---|---|---|
| 1 | `POST /chats` (`chatType: oneOnOne`) 또는 `GET /chats/{id}/members` | 보낼 곳과 읽을 사람 정하기 — `chat_id` 가 없으면 받는 사람과의 1:1 채팅 찾기/만들기, `chat_id` 를 줬으면 그 채팅의 구성원 읽기. Notes 로 갈 때는 생략 |
| 2 | `PUT /me/drive/root:/Microsoft Teams Chat Files/<이름>:/content` → `GET /me/drive/items/{id}?$select=…webDavUrl,sharepointIds` | 보내는 사람 OneDrive 에 올리고(같은 이름이 있으면 덮어쓰지 않고 이름을 바꿔 올린다) 첨부에 쓸 값을 읽는다 |
| 3 | `POST /me/drive/items/{id}/invite` (`roles: ["read"]`, `sendInvitation: false`) | 읽기 권한 주기 — `chat_id` 를 줬으면 그 채팅의 구성원 모두(나는 빼고, `recipient_email` 을 같이 줬어도 같다), `chat_id` 없이 `recipient_email` 로 1:1 채팅을 찾았으면 그 사람. Notes 와 구성원이 나뿐인 채팅은 생략 |
| 4 | `POST /me/chats/{chatId}/messages` | 본문 끝에 `<attachment id="GUID">` 를 넣고 `attachments` 에 그 파일을 `reference`(`contentUrl` = `webDavUrl`)로 달아 보낸다 |

- 1 이 실패하면(1:1 채팅을 찾지 못하거나 채팅 구성원을 읽지 못하면) 아무것도 올리지 않고 메시지도 보내지 않는다.
- 3(권한 주기)이 실패하면 메시지는 보내지 않는다. 이때 올린 파일은 OneDrive 에 남는다.
- 성공하면 `{"success": True, "message_id": "...", "chat_id": "...", "file": {"name": "...", "web_url": "..."}}` 를 돌려준다.

### 확인된 것과 확인 안 된 것 (2026-10-03)

- 테스트: `tests/test_send_chat_file.py` 18건 통과. **Graph 에는 닿지 않는다** — 서비스가 파일을
  어떻게 받아 넘기는지, 클라이언트가 어떤 차례로 무엇을 보내는지만 모의 응답으로 본다.
- 실제 전송: 서버를 띄워 본인의 Notes 채팅으로 PDF 한 개를 붙여 보냈고 도착했다.
  실제로 보내 본 것은 이 한 건뿐이다.
- **확인 안 됨**: 다른 사람에게 보내는 길(1:1 채팅 찾기/만들기 `POST /chats`, 그룹 채팅의 구성원
  읽기 `GET /chats/{id}/members`, 읽기 권한 주기 `invite`)은 실제로 보내 본 적이 없다. 위 테스트로 차례와 요청 본문만 확인했다.

### 쓰는 곳

KRS WORKSPACE 확장(`meeting_room` 저장소의 `src/teams.js`)이 `http://localhost:5003/mcp` 에 직접
붙어 이 도구로 여비계산서 증빙 PDF 를 보낸다.

## 특수 채팅

- `48:notes`: 나의 Notes 채팅 (chat_id를 생략하면 자동으로 사용됨)
  - `send_chat_file` 은 `chat_id` 와 `recipient_email` 이 둘 다 없거나 받는 사람이 나 자신일 때 Notes 로 보낸다.

## 인증

`session` 모듈의 `AuthManager`를 사용하여 인증을 처리합니다.
Azure AD OAuth 2.0 플로우를 통해 사용자 인증을 수행합니다.

## 테스트

```bash
cd /home/kimghw/KR_MS365_mcp
pytest mcp_teams/tests/ -v
```

2026-10-03 기준 36건 통과 (`test_send_chat_file.py` 18건 포함 — 이 18건은 Graph 에 닿지 않는다).

## 원본 모듈

이 모듈은 [KR365](https://github.com/kimghw/KR365) 레포지토리의 `modules/teams_mcp`를 기반으로 리팩토링되었습니다.
