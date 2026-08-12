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
> `Route("/mcp")` 구조를 사용합니다. `server_rest.py` 의 `/mcp/v1/*` 는 MCP transport 가
> 아니라 별도의 단순 REST 래퍼입니다.

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
  - 예외: OneDrive 다운로드용 **임시 폴더는 서버가 직접 만든 것**이라 신뢰 루트로 통과
  - 원격 URL(`http://`, `https://`, `onedrive:`)은 로컬 경로 검증 대상이 아님

- 거부 시 오류 메시지에 허용 루트 목록이 함께 반환됩니다.

## 도구 정의 로딩 구조 (tool_definitions.py)

`mcp_server/tool_definitions.py`는 도구 정의의 SSOT인
`mcp_editor/mcp_file_handler/tool_definition_templates.yaml`을 로드하여 `MCP_TOOLS` 리스트를 제공하는 래퍼입니다.
(`mcp_outlook/mcp_server/server_stream.py`와 동일 패턴)

경로 우선순위:
1. `MCP_YAML_PATH` 환경변수
2. `<project_root>/mcp_editor/mcp_file_handler/tool_definition_templates.yaml`

> 이전에는 이 모듈이 없어 `server.py` / `server_stream.py` / `server_stdio.py` / `server_rest.py`가
> 모두 `ModuleNotFoundError: No module named 'tool_definitions'`로 기동 불가였으며,
> `tool_definitions.py` 추가 후 포트 5008 서버가 정상 기동됩니다.

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

## 구조

```
mcp_file_handler/
├── file_manager.py             # 메인 진입점 (FileManager)
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
    ├── tool_definitions.py     # YAML 로더 래퍼 (MCP_TOOLS)
    ├── handlers.py             # 도구 핸들러 + ToolRuntime/ServiceLifecycle (transport 공통)
    ├── server_stream.py        # 표준 Streamable HTTP 서버 (port 5008, /mcp)
    ├── server_rest.py          # FastAPI REST 래퍼 (/mcp/v1/*)
    ├── server_stdio.py         # STDIO(JSON-RPC) 서버
    └── server.py               # legacy REST + SessionManager 서버
```

## 도구 실행 계약 (handlers.py)

세 transport(stream/stdio/rest)는 모두 `handlers.py` 의 동일한 핸들러와
`mcp_common.runtime.ToolRuntime` 을 공유합니다.

- **동기/비동기 모두 안전**: `FileManager` 의 도구 메서드는 전부 동기 함수입니다.
  이전 transport 들은 반환값을 무조건 `await` 해서 정상 호출조차
  `object dict can't be used in 'await' expression` 으로 실패했습니다.
  `ToolRuntime` 이 내부 `maybe_await` 로 처리하므로 이 버그는 구조적으로 재발하지 않습니다.
- **오류 계약**: 실패는 `ToolExecutionError` 로 올라가 MCP `isError=True` 로 감싸집니다.
  실패가 성공처럼 보이는 TextContent 로 나가지 않습니다.
  REST 는 이를 HTTP 상태코드로 매핑합니다(400 검증/경로거부, 404 미존재, 500 내부오류).
- **lifecycle**: `ServiceLifecycle` 이 `initialize()`/`close()` 를 처리하고,
  초기화 실패 시 `/health` 가 `degraded` + **503** 을 반환합니다.
- **입력 검증**: `inputSchema` 기준으로 기본값 주입 + required/type/enum 검증
  (`MCP_VALIDATE_INPUT=0` 으로 우회 가능).

## 환경변수 (.env)

```env
MCP_YAML_PATH=<tool definition yaml>  # MCP 도구 정의 YAML 경로 (선택, 기본: mcp_editor/mcp_file_handler/tool_definition_templates.yaml)
MCP_SERVER_PORT=5008                  # Streamable HTTP 포트 (선택)
MCP_BIND_HOST=127.0.0.1               # 바인드 호스트 (선택, 기본 loopback)
MCP_ALLOW_PUBLIC_BIND=0               # 1 이어야 0.0.0.0 등 public 바인드 허용
MCP_ALLOWED_PATHS=<path1>;<path2>     # 파일 접근 허용 루트 확장 (선택, 기본: 프로젝트 루트)
MCP_VALIDATE_INPUT=1                  # 0 이면 입력 스키마 검증 비활성 (긴급 우회용)
```
