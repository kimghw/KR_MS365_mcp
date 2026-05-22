# MCP Outlook - Microsoft Graph Mail 모듈

Microsoft Graph API를 통한 Outlook 메일 조회, 필터링, 첨부파일 처리를 담당하는 모듈입니다.

## 기본 사용법

### 1단계: 메일 목록 조회

```python
from mcp_outlook.outlook_service import MailService
from mcp_outlook.outlook_types import FilterParams
from mcp_outlook.graph_mail_client import ProcessingMode

mail_service = MailService()
await mail_service.initialize()

result = await mail_service.query_mail_list(
    user_email="user@example.com",
    filter_params=FilterParams(
        received_date_from="2026-02-01T00:00:00Z",
        received_date_to="2026-02-07T00:00:00Z"
    ),
    top=50
)
# result["emails"] → 메일 목록 (id, subject, from, ...)
```

### 2단계: 메일 ID로 첨부파일 처리

조회된 메일 ID를 사용하여 첨부파일을 처리합니다.

```python
message_ids = [email["id"] for email in result["emails"]]

processed = await mail_service.batch_and_process(
    user_email="user@example.com",
    message_ids=message_ids,
    processing_mode=ProcessingMode.FULL_PROCESS,  # 아래 표 참고
    save_directory="downloads"
)
# processed["attachment_result"] → 첨부파일 처리 결과
```

### ProcessingMode 옵션

| 모드 | 로컬 저장 | 텍스트 변환 | 설명 |
|------|:---------:|:-----------:|------|
| `FETCH_ONLY` | - | - | 메일 조회만 (기본값) |
| `FETCH_AND_DOWNLOAD` | O | - | 첨부파일 로컬 저장 |
| `FETCH_AND_CONVERT` | - | O | 텍스트 변환 결과만 반환 |
| `FULL_PROCESS` | O | O | 로컬 저장 + 텍스트 변환 |
| `FETCH_TO_ONEDRIVE` | OneDrive | - | OneDrive 업로드 |
| `FETCH_MEMORY_ONLY` | - | - | 첨부파일 메모리 보관 (저장 없음) |

> 한번에 처리하려면 `fetch_and_process()`로 조회+처리를 동시에 할 수도 있습니다.

## 구조

```
mcp_outlook/
├── outlook_service.py              # 서비스 Facade (MailService)
├── outlook_types.py                # 타입 정의 (FilterParams, ExcludeParams, SelectParams)
├── graph_mail_client.py            # 통합 메일 클라이언트 (GraphMailClient)
├── graph_mail_query.py             # 쿼리 실행 및 페이지네이션
├── graph_mail_url.py               # Graph API URL 빌더
├── graph_mail_id_batch.py          # 배치 처리 ($batch API)
├── mail_attachment.py              # 첨부파일 핸들러 (BatchAttachmentHandler)
├── mail_attachment_storage.py      # 저장 백엔드 (Local / OneDrive)
├── mail_attachment_converter.py    # 파일 변환 (PDF, DOCX, HWP 등 → TXT)
├── mail_attachment_processor.py    # 첨부파일 처리 유틸리티
└── mcp_server/
    ├── server_rest.py              # FastAPI REST 서버 (port 8001)
    ├── server_stdio.py             # STDIO 프로토콜 서버
    ├── server_stream.py            # Streamable HTTP 서버
    ├── server_init.py              # 서버 초기화
    └── run.py                      # 진입점
```

## 인증 연동

`session.AuthManager`를 `TokenProviderProtocol`로 사용합니다.
Graph API 호출마다 `validate_and_refresh_token(email)`을 통해 토큰을 자동 검증/갱신합니다.

## 쿼리 방식 (QueryMethod)

| 방식 | 설명 | 용도 |
|------|------|------|
| `FILTER` | OData `$filter` 쿼리 | 날짜, 발신자, 읽음 상태 등 조건 조합 |
| `SEARCH` | KQL 검색 | 키워드 전문 검색 |
| `URL` | Graph API URL 직접 지정 | 커스텀 쿼리 |
| `BATCH_ID` | `$batch` 엔드포인트 | 메일 ID 목록으로 일괄 조회 (최대 20개/배치) |

## 전처리 필터 (FilterParams)

Graph API `$filter` 파라미터로 변환되어 **서버 측에서** 필터링됩니다.

### 날짜/시간
| 파라미터 | 설명 | 형식 |
|----------|------|------|
| `received_date_from` | 수신일 시작 (>=) | ISO 8601 (`2026-01-01T00:00:00Z`) |
| `received_date_to` | 수신일 끝 (<=) | ISO 8601 |
| `received_date_time` | 수신일 이후 (>=) | ISO 8601 |
| `sent_date_from` / `sent_date_to` | 발신일 범위 | ISO 8601 |
| `created_date_time` | 생성일 이후 | ISO 8601 |
| `last_modified_date_time` | 수정일 이후 | ISO 8601 |

### 발신자
| 파라미터 | 설명 |
|----------|------|
| `from_address` | from 주소 필터 (str 또는 List[str]) |
| `sender_address` | sender 주소 필터 (str 또는 List[str]) |

### 메시지 상태
| 파라미터 | 설명 |
|----------|------|
| `is_read` | 읽음/안읽음 (bool) |
| `is_draft` | 임시보관함 (bool) |
| `has_attachments` | 첨부파일 유무 (bool) |
| `importance` | `low` / `normal` / `high` |
| `sensitivity` | `normal` / `personal` / `private` / `confidential` |
| `inference_classification` | `focused` / `other` |
| `flag_status` | `notFlagged` / `complete` / `flagged` |

### 키워드
| 파라미터 | 설명 |
|----------|------|
| `subject` | 제목 키워드 (str 또는 List[str]) |
| `body_content` | 본문 키워드 |
| `body_preview` | 미리보기 키워드 |
| `subject_operator` | 키워드 조합 (`or` / `and`, 기본: `or`) |
| `body_operator` | 본문 키워드 조합 (`or` / `and`) |

### ID/폴더
| 파라미터 | 설명 |
|----------|------|
| `id` | 특정 메시지 ID |
| `conversation_id` | 대화 스레드 ID |
| `parent_folder_id` | 폴더 ID |
| `categories` | 카테고리 태그 (List[str]) |

## 후처리 필터 (ExcludeParams)

데이터를 가져온 **후 클라이언트 측에서** 제외 필터링합니다.
`exclude_params` 또는 `client_filter` 파라미터로 전달합니다.

| 파라미터 | 설명 |
|----------|------|
| `exclude_from_address` | 특정 발신자 제외 (str 또는 List[str]) |
| `exclude_sender_address` | 특정 sender 제외 |
| `exclude_subject_keywords` | 제목에 포함된 키워드 제외 (List[str]) |
| `exclude_body_keywords` | 본문 키워드 제외 |
| `exclude_preview_keywords` | 미리보기 키워드 제외 |
| `exclude_importance` | 특정 중요도 제외 |
| `exclude_read_status` | 읽음/안읽음 제외 |
| `exclude_draft_status` | 임시보관 제외 |
| `exclude_attachment_status` | 첨부파일 유무 제외 |
| `exclude_categories` | 특정 카테고리 제외 |
| `exclude_flag_status` | 특정 플래그 제외 |
| `exclude_conversation_id` | 특정 대화 제외 |
| `exclude_parent_folder_id` | 특정 폴더 제외 |

## 필드 선택 (SelectParams)

Graph API `$select`로 반환 필드를 지정합니다. 불필요한 필드를 제외하여 응답 크기를 줄입니다.

| 카테고리 | 필드 |
|----------|------|
| 기본 | `id`, `subject`, `body`, `body_preview`, `unique_body` |
| 날짜 | `created_date_time`, `received_date_time`, `sent_date_time`, `last_modified_date_time` |
| 상태 | `is_read`, `is_draft`, `has_attachments`, `importance`, `inference_classification` |
| 수신자 | `from_recipient`, `to_recipients`, `cc_recipients`, `bcc_recipients`, `reply_to` |
| 기타 | `conversation_id`, `parent_folder_id`, `categories`, `flag`, `web_link`, `internet_message_headers` |

## 처리 모드 (ProcessingMode)

| 모드 | 설명 |
|------|------|
| `FETCH_ONLY` | 메일 조회만 (기본값) |
| `FETCH_AND_DOWNLOAD` | 메일 조회 + 첨부파일 로컬 저장 |
| `FETCH_AND_CONVERT` | 메일 조회 + 첨부파일 텍스트 변환 |
| `FULL_PROCESS` | 메일 조회 + 저장 + 변환 |
| `FETCH_TO_ONEDRIVE` | 메일 조회 + OneDrive 업로드 |
| `FETCH_MEMORY_ONLY` | 메일 조회 + 첨부파일 메모리 보관 (파일 저장 없음) |

## 첨부파일 저장

### 로컬 저장 (LocalStorageBackend)
- 폴더 자동 생성: `YYYYMMDD_sender_subject/`
- 파일명 자동 정리 (특수문자 제거, 길이 제한)
- 중복 파일명 자동 넘버링
- 메일 본문 `mail_content.txt`로 저장

### OneDrive 저장 (OneDriveStorageBackend)
- 4MB 이하: Simple PUT 업로드
- 4MB 초과: Upload Session (10MB 청크, 최대 250GB)
- 기본 폴더: `/Attachments`

```python
backend = get_storage_backend(
    storage_type="local",       # 또는 "onedrive"
    base_directory="downloads", # 로컬 전용
    base_folder="/Attachments"  # OneDrive 전용
)
```

## 파일 변환 (mail_attachment_converter)

| 형식 | 라이브러리 |
|------|-----------|
| PDF | pdfplumber |
| DOCX/DOC | python-docx |
| HWP/HWPX | pyhwpx |
| XLSX/XLS | openpyxl |
| PPTX | python-pptx |

토큰 제한: `truncate_to_token_limit(text, max_tokens=50000)` (~4자/토큰)

## 배치 처리 (GraphMailIdBatch)

- Graph API `$batch` 엔드포인트 사용
- 배치당 최대 20개 (자동 분할)
- `batch_fetch_by_ids(user_email, message_ids, select_params)`
- `fetch_single_by_id(user_email, message_id, select_params)`

## 페이지네이션 (GraphMailQuery)

- 페이지 크기: 150건
- 최대 동시 요청: 3페이지
- `top > 150` 이면 자동 페이지네이션
- Filter 최대: 1000건, Search 최대: 250건

## MCP 서버 도구

| 도구 | 설명 |
|------|------|
| `handler_mail_list` | 메일 목록 조회 (필터/검색/URL) |
| `handler_mail_fetch_and_process` | 메일 조회 + 처리 옵션 |
| `handler_mail_fetch_filter` | 필터 기반 조회 |
| `handler_mail_fetch_search` | 검색 기반 조회 |
| `handler_mail_fetch_url` | URL 기반 조회 |
| `handler_mail_batch_fetch` | 메일 ID 배치 조회 |
| `handler_mail_batch_and_process` | 배치 조회 + 처리 |
| `handle_attachments_metadata` | 첨부파일 메타데이터 조회 |
| `handle_download_attachments` | 첨부파일 다운로드 |

## 환경변수 (.env)

> `session/azure_config.py`가 `load_dotenv()`로 `.env`를 자동 로드합니다.

인증 관련 환경변수(`AZURE_CLIENT_ID` 등)는 `session` 모듈에서 관리합니다. [session/README.md](../session/README.md) 참고.

```env
# MCP 서버 설정 (선택, 기본값 있음)
MCP_SERVER_PORT=8091                  # MCP 서버 포트
MCP_SERVER_TYPE=outlook               # 서버 타입 (outlook 설정 시 AZURE_CLIENT_ID, AZURE_TENANT_ID 필수 검증)
MCP_YAML_PATH=<tool definition yaml>  # MCP 도구 정의 YAML 경로

# 서버 운영 설정 (선택, 기본값 있음)
SESSION_TIMEOUT=30                    # 세션 타임아웃 (분)
CLEANUP_INTERVAL=5                    # 세션 정리 주기 (분)
MAX_SESSIONS=100                      # 최대 동시 세션 수
REQUIRE_AUTH=true                     # 인증 필수 여부
DEFAULT_TOP=10                        # 기본 조회 건수
MAX_RESULTS=100                       # 최대 조회 건수

# 인증 DB (선택, 기본값 있음)
DB_PATH=database/auth.db              # SQLite DB 경로
```

## 사용 예시

```python
from mcp_outlook.outlook_service import MailService
from mcp_outlook.outlook_types import FilterParams, ExcludeParams
from mcp_outlook.graph_mail_client import QueryMethod, ProcessingMode

mail_service = MailService()
await mail_service.initialize()

# 7일간 메일 조회 (전처리 필터)
result = await mail_service.query_mail_list(
    user_email="kimghw@krs.co.kr",
    query_method=QueryMethod.FILTER,
    filter_params=FilterParams(
        received_date_from="2026-01-31T00:00:00Z",
        received_date_to="2026-02-07T00:00:00Z"
    ),
    top=50,
    order_by="receivedDateTime desc"
)

# 후처리 필터로 스팸 제외
result = await mail_service.query_mail_list(
    user_email="kimghw@krs.co.kr",
    filter_params=FilterParams(is_read=False),
    client_filter=ExcludeParams(
        exclude_from_address=["noreply@github.com"],
        exclude_subject_keywords=["spam", "newsletter"]
    )
)

# 첨부파일 포함 메일 조회 + 로컬 저장
result = await mail_service.fetch_and_process(
    user_email="kimghw@krs.co.kr",
    filter_params=FilterParams(has_attachments=True),
    processing_mode=ProcessingMode.FETCH_AND_DOWNLOAD,
    save_directory="downloads"
)

# KQL 검색
result = await mail_service.fetch_search(
    user_email="kimghw@krs.co.kr",
    search_term="from:boss@company.com subject:보고서",
    top=20
)

# 메일 ID 배치 조회
result = await mail_service.batch_and_fetch(
    user_email="kimghw@krs.co.kr",
    message_ids=["id1", "id2", "id3"]
)
```

## 응답 형식

```python
{
    "success": True,
    "user": "kimghw@krs.co.kr",
    "method": "filter",
    "total": 50,
    "emails": [
        {
            "id": "AAMkADI...",
            "subject": "회의 안건",
            "from": {"emailAddress": {"address": "...", "name": "..."}},
            "receivedDateTime": "2026-02-05T10:30:00Z",
            "isRead": True,
            "hasAttachments": False,
            ...
        }
    ],
    "request_url": "https://graph.microsoft.com/v1.0/...",
    "fetch_time": 1.5
}
```
