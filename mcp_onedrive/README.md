# MCP OneDrive Module

Microsoft Graph API를 사용한 OneDrive 서비스 모듈입니다.
`mcp_outlook` 모듈과 동일한 구조로 리팩토링되었습니다.

## 구조

```
mcp_onedrive/
├── __init__.py              # 모듈 초기화
├── onedrive_types.py        # 타입 정의 (dataclass)
├── graph_onedrive_client.py # Graph API 클라이언트
├── onedrive_service.py      # 서비스 레이어 (Facade 패턴)
├── mcp_server/              # MCP 서버
│   ├── __init__.py
│   ├── handlers.py          # 도구 계약 로드 + 핸들러 (두 트랜스포트의 유일한 원본)
│   ├── server_stdio.py      # stdio 트랜스포트 (얇음)
│   └── server_stream.py     # Streamable HTTP 트랜스포트 (포트 5004, 얇음)
├── tests/                   # 테스트
│   ├── __init__.py
│   └── test_onedrive_service.py
└── README.md
```

## 도구 계약 (param_spec)

도구 이름·설명·파라미터·필수여부·기본값은 **`spec/param_spec/onedrive.yaml` 한 곳**에만
적는다. `inputSchema` 와 서비스 호출 인자는 기동 시 `mcp_common.param_spec` 이 여기서
파생시킨다 — 코드 생성물도, 서버 파일 안의 도구 정의 리터럴도 없다.

- 파라미터를 늘리거나 필수/선택·기본값을 바꾸려면 YAML 만 고치고 서버를 재기동한다.
- `boolean` 은 YAML 에 boolean 으로 적는다. 노출 스키마의 `enabled`/`disabled` 문자열
  enum 변환과 역변환은 `mcp_common/schema_normalize.py` 가 담당한다
  (`as_text`, `overwrite`).
- `user_email` 은 스키마상 선택이며, 실제 값은 `mcp_common.user_resolver` 정책으로
  정해진다(명시값 → `MS365_DEFAULT_USER_EMAIL` → auth.db, 없으면 오류).
  멀티유저 모드(`MS365_MULTI_USER=1`)에서는 인증된 호출자의 연결 계정만 허용한다 —
  생략하면 본인 계정, 다른 계정이면 `identity_mismatch`.

## 기능

### 드라이브 정보
- `get_drive_info`: 드라이브 정보 조회 (용량, 사용량 등)

### 파일/폴더 조회
- `list_files`: 파일/폴더 목록 조회
- `get_item`: 파일/폴더 정보 조회

### 파일 읽기/쓰기
- `read_file`: 파일 내용 읽기 (텍스트/바이너리)
- `write_file`: 파일 쓰기/업로드
- `delete_file`: 파일/폴더 삭제

### 폴더 관리
- `create_folder`: 폴더 생성

### 파일 복사/이동
- `copy_file`: 파일 복사
- `move_file`: 파일 이동

## 사용법

```python
from mcp_onedrive import OneDriveService

async def main():
    service = OneDriveService()
    await service.initialize()

    try:
        # 드라이브 정보 조회
        drive = await service.get_drive_info("user@example.com")
        print(drive)

        # 파일 목록 조회
        files = await service.list_files("user@example.com", folder_path="Documents")
        print(files)

        # 파일 쓰기
        result = await service.write_file(
            user_email="user@example.com",
            file_path="Documents/test.txt",
            content="Hello World",
        )
        print(result)

        # 파일 읽기
        content = await service.read_file("user@example.com", "Documents/test.txt")
        print(content)
    finally:
        await service.close()
```

## 충돌 처리

- `overwrite=True` (기본값): 기존 파일 덮어쓰기
- `overwrite=False`: 파일이 존재하면 실패

## 경로·검색어 인코딩

- `folder_path`/`file_path` 는 Graph 에 보내기 전에 URL 인코딩한다(`/` 만 보존). `#`, `%`, `?`,
  공백이 든 이름도 그대로 쓰면 된다 — 예전에는 `report#v2.txt` 가 `report` 로 잘려 나갔다.
- 검색어의 작은따옴표는 OData 문자열 규칙대로 `''` 로 이스케이프한 뒤 인코딩한다.

## 인증

`session` 모듈의 `AuthManager`를 사용하여 인증을 처리합니다.
Azure AD OAuth 2.0 플로우를 통해 사용자 인증을 수행합니다.

멀티유저 모드에서는 서비스 풀이 사용자별 `OneDriveService(token_provider=..., paths=...)` 를
만들고(`handlers.create_service`), 핸들러는 요청에 lease 된 서비스를 쓴다. GraphClient 는
주입된 사용자 고정 토큰 공급자만 쓰며 공용 AuthManager 로 대체하지 않는다. `close()` 는
자기 HTTP 세션만 닫고 토큰 공급자는 닫지 않는다. OneDrive 도구는 로컬 파일을 쓰지 않는다
(사양: `spec/spec_멀티유저.md` ②-7.3·②-7.6).

## 입력 상한 (R02)

`list_files.limit` 은 1~1000 — `spec/param_spec/onedrive.yaml` 의 `minimum`/`maximum` 이 MCP 입력을
막고, 서비스 함수(`OneDriveService.list_files`)도 Graph 요청 전에 `input_bounds.check_top()` 으로
한 번 더 막는다(`invalid_argument` 오류). `input_bounds.py` 는 calendar·todo 와 같은 사본이다.

## redirect·사전 서명 URL 정책 (두 모드 공통, ②-7.5)

- bearer 를 단 Graph 요청은 redirect 를 따라가지 않는다(`allow_redirects=False`). 3xx 는
  상태 코드만 담은 오류로 돌려준다.
- `read_file` 의 `/content` 302 는 사전 서명 URL 로 **bearer 없이** 한 번만 간다 — https·
  userinfo 없음·기본 포트·공개 호스트(사설·loopback·link-local IP, `localhost`, 단일 라벨
  호스트 거부). 그 URL 이 다시 redirect 하면 따라가지 않는다. 302 와 이 GET 사이에서 호출자가
  폐기·연결 해제되면 GET 을 보내지 않는다(직전에 bound provider 로 활성 상태 재검사, N01).
- `@odata.nextLink` 이어 조회는 `GraphOneDriveClient.fetch_next_link()` 로만 한다 — 본인
  `/v1.0/me/drive/...` 또는 본인 `/users/{id}/drive/...`, dot-segment 없음. 그 밖은
  `path_not_allowed`.
- 정책 구현은 `graph_url_policy.py` — calendar·todo 와 바이트 단위로 같은 사본이다(공용 모듈로
  올리기 전까지 세 벌을 함께 고친다).

## 테스트

```bash
cd /home/kimghw/KR_MS365_mcp
pytest mcp_onedrive/tests/ -v
```

## 원본 모듈

이 모듈은 [KR365](https://github.com/kimghw/KR365) 레포지토리의 `modules/onedrive_mcp`를 기반으로 리팩토링되었습니다.
