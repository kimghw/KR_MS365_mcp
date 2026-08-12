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
│   └── test_teams_service.py
└── README.md
```

## 도구 계약 (param_spec)

도구 이름·설명·파라미터·기본값은 **`spec/param_spec/teams.yaml` 한 곳에만** 있다.
`inputSchema` 와 서비스 호출 인자는 기동 시 `mcp_common.param_spec` 가 파생시킨다
(코드 생성 없음, 미리 구워 둔 산출물 없음). 파라미터를 늘리거나 기본값을 바꿀 때는
그 YAML 만 고친다 — `handlers.py` 에 도구 정의를 적으면 사본이 두 벌이 된다.

기본값(`limit` 50, `prefix` `[claude]`, `content_type` `text`)도 전부 YAML 에 있다.
`user_email` 만은 예외로, 값이 비면 `mcp_common.user_resolver` 가 기본 사용자를 고른다.

## 기능

### 채팅 관리
- `list_chats`: 채팅 목록 조회
- `get_chat`: 특정 채팅 정보 조회

### 메시지 관리
- `get_chat_messages`: 채팅 메시지 목록 조회
- `send_chat_message`: 채팅에 메시지 전송

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

## 특수 채팅

- `48:notes`: 나의 Notes 채팅 (chat_id를 생략하면 자동으로 사용됨)

## 인증

`session` 모듈의 `AuthManager`를 사용하여 인증을 처리합니다.
Azure AD OAuth 2.0 플로우를 통해 사용자 인증을 수행합니다.

## 테스트

```bash
cd /home/kimghw/KR_MS365_mcp
pytest mcp_teams/tests/ -v
```

## 원본 모듈

이 모듈은 [KR365](https://github.com/kimghw/KR365) 레포지토리의 `modules/teams_mcp`를 기반으로 리팩토링되었습니다.
