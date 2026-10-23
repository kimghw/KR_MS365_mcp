# MCP File Handler - 파일 변환/메타데이터 모듈

다양한 파일 형식(PDF, DOCX, HWP, Excel, 이미지)의 텍스트 변환, OneDrive 연동, 파일 메타데이터 관리를 담당하는 모듈입니다.

## MCP 서버 실행

```bash
venv/Scripts/python.exe mcp_file_handler/mcp_server/server_stream.py
```

- 포트: **5008** (Streamable HTTP, `MCP_SERVER_PORT` 로 변경 가능)
- 바인드: 기본 **127.0.0.1 (loopback 전용)**
- 엔드포인트 (표준 MCP SDK transport):

| 엔드포인트 | 설명 |
|-----------|------|
| `/mcp` | 표준 Streamable HTTP 단일 엔드포인트 (SDK 가 프로토콜 버전 협상) |
| `GET /health` | 헬스 체크. 초기화 실패 시 `degraded` + HTTP **503** |

> 구버전의 `/mcp/v1/initialize|tools/list|tools/call` 독자 경로, 자체 NDJSON 스트리밍,
> `protocolVersion: 0.1.0` 하드코딩은 **제거**되었습니다. 다른 서버(onenote/outlook 등)와
> 동일하게 `mcp.server.streamable_http_manager.StreamableHTTPSessionManager` + Starlette
> `Route("/mcp")` 구조를 사용합니다.
>
> 지원 트랜스포트는 **stdio 와 Streamable HTTP 2종**입니다. REST 계열(`/mcp/v1/*` 래퍼)은
> 폐지되었습니다 — 근거와 상세는 [spec/spec_MCP트랜스포트.md](../spec/spec_MCP트랜스포트.md) 참조.

## 보안 (중요)

- 이 서버에는 **호출자 인증이 없습니다.** 기본 바인드는 loopback 전용이며,
  외부 노출은 명시적 옵트인이 필요합니다.

  ```env
  MCP_BIND_HOST=0.0.0.0        # 노출할 인터페이스
  MCP_ALLOW_PUBLIC_BIND=1      # 함께 있어야 public 바인드가 허용됨
  ```

  옵트인 없이 public 주소를 요청하면 loopback 으로 강등되고 경고 로그가 남습니다
  (`mcp_common.net.resolve_bind_host`).

- 도구가 여는 **모든 파일/디렉터리 경로는 허용 루트 안으로 제한**됩니다
  (`mcp_common.paths.resolve_safe_path`). 기본 허용 루트는 프로젝트 루트이며
  `MCP_ALLOWED_PATHS` (`;` 구분) 로 확장합니다. `..`/심볼릭 링크는 realpath 로
  해소한 뒤 비교하므로 traversal 로 우회할 수 없습니다.
  - 적용 지점: `convert_file_to_text`, `process_directory`(패턴 매칭 결과 포함),
    `save/get/delete_file_metadata` 의 로컬 `file_url`, OneDrive `output_dir`
  - OneDrive 다운로드는 **요청마다 새로 만든 전용 디렉터리**에만 쓰고, 끝나면 그 디렉터리만
    지웁니다. 다운로드한 파일은 그 디렉터리 안인지 다시 확인합니다 — 허용 루트를 넓히던
    `trusted_roots` 예외는 없어졌습니다. 원격 파일명은 `secure_files.safe_join` 으로
    단일 이름으로 정화하고, 파일은 배타 생성(같은 이름이면 ` (n)` 접미사)합니다.
  - 원격 URL(`http://`, `https://`, `onedrive:`)은 로컬 경로 검증 대상이 아님

- mode 0 에서는 거부 시 오류 메시지에 허용 루트 목록이 함께 반환됩니다. `/health` 의 보안
  고지에는 허용 루트 **개수만** 싣고 절대경로는 싣지 않습니다.

### 멀티유저 모드 (`MS365_MULTI_USER=1`)

근거: [spec/spec_멀티유저.md](../spec/spec_멀티유저.md) ②-2.2·②-2.5·②-5.2·②-7.3·②-7.4.

| 항목 | 동작 |
|------|------|
| 서비스 | `handlers.create_service(principal, paths, tokens)` 가 사용자별 `FileHandlerService` 를 만들고 서비스 풀이 수명을 관리. 전역 인스턴스·`AuthManager` 를 만들지 않음 |
| 인증 | OneDrive 토큰은 주입된 사용자 고정 `BoundTokenProvider` 에서만. 동기 작업은 작업 스레드에서 돌고 토큰 코루틴은 요청 이벤트 루프에서 실행(`token_bridge.py`) — `executor.submit(asyncio.run, …)` 브리지 제거(mode 0 도 동일) |
| 파일 범위 | 호출자 자신의 `files/` 만. 상대경로는 `files/` 기준. 자기 `auth/`·`db/`·다른 사용자 영역·UNC·ADS·장치 경로·드라이브 상대경로는 `path_not_allowed` |
| 응답 | 절대경로 대신 `files/` 기준 상대경로(`uploads/a.pdf`). 오류 문구에 예외 원문(경로·URL·외부 응답 본문)을 싣지 않음 |
| 메타데이터 | 사용자별 `db/metadata.db` 의 `file_metadata` (PK `(owner_key, file_url)`, 모든 SQL 에 owner 조건). JSON 저장소는 서비스 생성 시 `config_error` |
| 임시파일 | 요청별 `files/tmp/<request_id>/` (OneDrive 다운로드·OCR 입력/전처리·PDF 페이지 이미지 포함). 끝나면 그 디렉터리만 정리. OCR 은 tesseract 를 직접 실행해 TEMP/TMP 도 요청 디렉터리로 고정 |
| 경로 설정 | output → `files/output/`, 다운로드(`output_dir` 상대경로 기준) → `files/downloads/file_handler/`. `MCP_ATTACHMENT_{TEMP_DIR,OUTPUT_DIR,METADATA_PATH,LOG_FILE}`·`MCP_ATTACHMENT_METADATA_STORAGE≠sqlite`·홈/CWD config 의 경로 키는 **기동 실패**(`StartupConfigError`) |
| 컨텍스트 | 작업 스레드는 `contextvars.copy_context()` 로 principal·요청 scope 를 받음. 없거나 다른 사용자면 `missing_principal` |
| 기타 | stdio 기동 거부, health 에 경로 없음, 로그에 파일명·경로·공유 URL·예외 원문 없음 |

사용자 저장소 초기화는 `mcp_file_handler.storage_schema.ensure_storage(principal, paths)`
(마이그레이션 도구와 서비스 `initialize()` 공용).

### 자원 상한과 보안 리뷰 반영 (astra 2026-10-23: R05·R08·R09·R12·R14)

| 설정 키 (`MCP_ATTACHMENT_*` 환경변수·config) | 기본값 | 적용 |
|------|-------:|------|
| `max_file_size` (MB) | 100 | 파일 하나 — OneDrive 스트림 누적·로컬 입력 복사. 초과 순간 스트림 중단·부분 파일 삭제 |
| `max_total_size` (MB) | 500 | 요청 전체 바이트 예산 (다운로드 + 입력 복사) |
| `max_download_files` | 200 | 요청 하나가 받는 OneDrive 파일 수 |
| `max_folder_depth` | 10 | 폴더 재귀 깊이 |
| `max_output_chars` | 2,000,000 | 변환 결과 텍스트(파일별·요청 합계, 초과분 절단 + `metadata.truncated`) |
| `conversion_timeout` (초) | 300 | 요청 하나의 변환 시간. 넘기면 결과 폐기(`limit_exceeded/conversion_timeout`) |
| `max_workers` | 4 | 서비스(사용자)당 동시 변환 스레드. 시간 초과로 버려진 스레드도 끝날 때까지 슬롯을 쥔다 → 넘치면 `overloaded` |

- mode 0 은 위 키로 조정, **mode 1 은 기본값이 천장**(낮추기만 가능). 구현은 `limits.py`.
- 초과는 고정 페이로드 `{"error":"limit_exceeded","limit":<코드>}` 또는 결과 `errors` 문구로 나간다.
- 변환 스레드는 강제 종료할 수 없다 — 시간 초과 시 결과만 버리고 슬롯 상한으로 누적을 막는다
  (프로세스 격리 worker 는 변환기 직렬화가 필요해 후속 과제).
- **N03 (2차 리뷰)** 수명 기준은 **실제 converter 스레드**다(`conversion_workers.py`). 요청이 끝날 때
  살아 있는 스레드가 있으면 `HARD_JOIN_CAP_SECONDS`(30초)까지 기다린 뒤에야 응답·lease 해제가 일어나고,
  그래도 남으면 요청 디렉터리 정리를 마지막 스레드에 위임한다(그때까지 디렉터리 유지). `close()` 도
  같은 상한으로 스레드를 기다린다. 슬롯은 **프로세스 전역 user_key 별**(`slots_for`)이라 서비스가
  퇴거·재생성돼도 사용자당 `max_workers` 를 넘지 못한다(mode 0 은 `legacy` 키 하나).
- **N03 (3차)** hard cap 뒤에도 살아 있는 converter 가 있으면 `close()` 는 **`RuntimeError` 를 올린다**
  (성공으로 보고하지 않음 → 풀의 drain 실패). 위임된 temp 정리는 유지되고, 다시 `close()` 하면 재검사한다.
- **N05 (3차)** 사전 서명 URL 정책은 공용 `mcp_common.graph_url_policy.check_presigned_url` 하나다
  (DNS 해석 실패·단일 라벨 호스트도 거부). **N01 (3차)** 사전 서명 GET 직전에 토큰 공급자에서
  토큰을 다시 얻어 호출자 활성 상태를 재확인한다(폐기됐으면 GET 이 나가지 않음).
- **N06** mode 0 의 legacy `SQLiteStorage`/`JSONStorage` 는 생성 시점과 **쓰기마다**
  `mcp_common.security_policy.assert_legacy_store_not_frozen()` 으로 `.migration_lock` 을 확인한다
  (읽기는 허용, 메모리 상태도 검사 전에는 바꾸지 않음). mode 1 에서는 no-op.
- **N08** `max_download_files`·`max_total_size` 는 로컬 디렉터리 순회에도 적용된다
  (초과는 `limit_exceeded/too_many_files`·파일별 `request_too_large`).
- **N10** `search_metadata` 응답의 `criteria.file_url` 은 공개 참조로 바꿔 반사하거나(자기 files/
  안 절대경로 → 상대 참조, 검색에도 그 값을 씀) 바꿀 수 없으면 생략한다.
- **R02** `save_file_metadata.keywords` 는 스키마 `maxItems: 100`·항목 `maxLength: 200` 이고,
  서비스 경계에서도 같은 값으로 잘라 저장한다(`limits.KEYWORDS_MAX_ITEMS`/`KEYWORD_MAX_LENGTH`).
- **R05** 요청 temp 는 작업 스레드가 열고 닫는다. 호출이 취소돼도(반복 취소·종료 포함) worker 가
  끝날 때까지 `conversion_timeout + 30초` 안에서 기다린 뒤 취소를 올리고, `close()` 도 진행 중
  worker 를 기다린다.
- **R08** 사전 서명 다운로드 URL: https·표준 포트·자격증명 없음·사설/루프백/링크로컬/예약 주소
  아님(리터럴 IP 와 DNS 해석 결과 모두)·추가 redirect 금지 (`onedrive/client.py:validate_download_url`).
- **R12** mode 1 로컬 입력은 `open_for_read` handle 에서 요청 디렉터리 `input/` 로 배타 복사한
  복사본만 변환기에 준다.
- **R14** 메타데이터 응답의 `file_url` 은 서비스가 정규화한 참조(mode 1: `files/` 기준 상대경로)다.

## 도구 정의 로딩 구조 (param_spec)

도구 계약의 **단일 원본은 `spec/param_spec/file_handler.yaml`** 입니다. 도구 이름·설명·
파라미터·필수여부·기본값을 여기 한 곳에만 적고, `inputSchema` 와 서비스 호출 인자는
기동 시 `mcp_common.param_spec` 이 파생시킵니다 (미리 구워 둔 산출물 없음).

- `mcp_server/tool_definitions.py` — `load_param_spec("file_handler")` 결과(`SPEC`,
  `MCP_TOOLS`)를 재수출하는 얇은 관문. `mcp_server/__init__.py` 의
  `from .tool_definitions import MCP_TOOLS` 를 위해 남겨 두었고, `FileManager` 를
  만들지 않아 패키지 import 가 가볍습니다.
- `mcp_server/handlers.py` — `SPEC.call_args("<도구명>", args)` 로 서비스 호출 인자를
  만듭니다. 핸들러에 파라미터 이름·기본값 리터럴을 적지 않습니다.

> 2026-08-12 코드 생성(jinja 템플릿 + 생성기) 폐지 이전에는 에디터 쪽 AST 추출 산출물
> `tool_definition_templates.yaml` 을 `MCP_YAML_PATH` 로 읽었습니다. 그 경로와
> 환경변수는 더 이상 쓰이지 않습니다.

## MCP 서버 도구

| 도구 | 설명 |
|------|------|
| `convert_file_to_text` | 로컬 파일을 텍스트로 변환 |
| `process_directory` | 디렉토리 내 파일 일괄 처리 |
| `save_file_metadata` | 파일 메타데이터 저장 |
| `search_metadata` | 메타데이터 검색 |
| `convert_onedrive_to_text` | OneDrive 파일 다운로드 + 텍스트 변환 |
| `get_file_metadata` | 파일 메타데이터 조회 |
| `delete_file_metadata` | 파일 메타데이터 삭제 |

OneDrive 연동(`onedrive/client.py`, `onedrive/downloader.py`) 동작 메모:

- 공유 URL 조회는 Graph 가 요구하는 `u!` 접두사 토큰(`/shares/u!{base64url}/driveItem`)을 쓴다.
- 폴더 재귀 다운로드는 하위 폴더 구조를 그대로 보존한다 — `A/same.txt` 와 `B/same.txt` 가
  더 이상 한 파일로 겹쳐 쓰이지 않는다.

## 구조

```
mcp_file_handler/
├── file_manager.py             # 메인 진입점 (FileManager, 동기)
├── service.py                  # FileHandlerService — FileManager 의 async 어댑터 (요청 temp·작업 스레드)
├── request_scope.py            # 요청 범위 상태(ContextVar): 작업 디렉터리·이벤트 루프·소유자
├── token_bridge.py             # 동기 코드 → 비동기 토큰 공급자 다리 (요청 루프에 위임)
├── path_policy.py              # mode 1 경로 정책 (files/ 루트·공개 경로·공개 오류 문구)
├── storage_schema.py           # ensure_storage() — 사용자 db/metadata.db 초기화
├── base_converter.py           # 변환기 베이스 클래스
├── attachment_converter.py     # 첨부파일 변환
├── converters/
│   ├── pdf/pdf_converter.py    # PDF → TXT
│   ├── docx/docx_converter.py  # DOCX → TXT
│   ├── hwp/hwp_converter.py    # HWP/HWPX → TXT
│   ├── excel/excel_converter.py# XLSX/XLS → TXT
│   └── image/ocr_converter.py  # 이미지 OCR
├── metadata/
│   ├── manager.py              # 메타데이터 관리 (MetadataManager)
│   └── storage.py              # 메타데이터 저장소
├── onedrive/
│   ├── client.py               # OneDrive 클라이언트
│   ├── downloader.py           # 파일 다운로드
│   └── processor.py            # 다운로드 + 변환 파이프라인
├── utils/
│   ├── file_detector.py        # 파일 형식 감지
│   └── logger.py               # 로거 설정
├── config/settings.py          # 설정
└── mcp_server/
    ├── tool_definitions.py     # param_spec 재수출 관문 (SPEC, MCP_TOOLS)
    ├── handlers.py             # 도구 핸들러 + build_mcp_server() (transport 공통)
    ├── server_stream.py        # Streamable HTTP 서버 (port 5008, /mcp, /health)
    └── server_stdio.py         # STDIO 서버 (공식 SDK stdio_server)
```

## 도구 실행 계약 (handlers.py)

두 transport(stream/stdio)는 모두 `handlers.py` 의 동일한 핸들러와
`mcp_common.runtime.ToolRuntime` 을 공유합니다.

- **핸들러는 async**: 핸들러는 `FileHandlerService` 의 async 메서드를 부르고, 서비스가
  동기 `FileManager` 작업을 작업 스레드로 넘깁니다(이벤트 루프를 막지 않음).
  param_spec 의 `service:` 는 전부 `FileHandlerService.<메서드>` 입니다.
  `ToolRuntime` 은 내부 `maybe_await` 로 동기/비동기 핸들러를 모두 처리합니다.
- **오류 계약**: 실패는 `ToolExecutionError` 로 올라가 MCP `isError=True` 로 감싸집니다.
  실패가 성공처럼 보이는 TextContent 로 나가지 않습니다.
- **lifecycle**: `ServiceLifecycle` 이 `initialize()`/`close()` 를 처리하고,
  초기화 실패 시 `/health` 가 `degraded` + **503** 을 반환합니다.
- **입력 검증**: `inputSchema` 기준으로 기본값 주입 + required/type/enum 검증
  (`MCP_VALIDATE_INPUT=0` 으로 우회 가능).

## 환경변수 (.env)

```env
MCP_PARAM_SPEC_DIR=<dir>              # param_spec 디렉터리 (선택, 기본: <project_root>/spec/param_spec)
MCP_SERVER_PORT=5008                  # Streamable HTTP 포트 (선택)
MCP_BIND_HOST=127.0.0.1               # 바인드 호스트 (선택, 기본 loopback)
MCP_ALLOW_PUBLIC_BIND=0               # 1 이어야 0.0.0.0 등 public 바인드 허용
MCP_ALLOWED_PATHS=<path1>;<path2>     # 파일 접근 허용 루트 확장 (선택, 기본: 프로젝트 루트)
MCP_VALIDATE_INPUT=1                  # 0 이면 입력 스키마 검증 비활성 (긴급 우회용)
```
