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

## 인증

`session` 모듈의 `AuthManager`를 사용하여 인증을 처리합니다.
Azure AD OAuth 2.0 플로우를 통해 사용자 인증을 수행합니다.

## 테스트

```bash
cd /home/kimghw/KR_MS365_mcp
pytest mcp_onedrive/tests/ -v
```

## 원본 모듈

이 모듈은 [KR365](https://github.com/kimghw/KR365) 레포지토리의 `modules/onedrive_mcp`를 기반으로 리팩토링되었습니다.
