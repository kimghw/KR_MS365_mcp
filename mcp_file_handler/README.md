# MCP File Handler - 파일 변환/메타데이터 모듈

다양한 파일 형식(PDF, DOCX, HWP, Excel, 이미지)의 텍스트 변환, OneDrive 연동, 파일 메타데이터 관리를 담당하는 모듈입니다.

## MCP 서버 실행

```bash
venv/Scripts/python.exe mcp_file_handler/mcp_server/server_stream.py
```

- 포트: **5008** (Streamable HTTP)
- 엔드포인트:

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /mcp/v1/initialize` | MCP 세션 초기화 |
| `POST /mcp/v1/tools/list` | 도구 목록 조회 |
| `POST /mcp/v1/tools/call` | 도구 호출 |
| `GET /health` | 헬스 체크 |

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
    ├── server_stream.py        # Streamable HTTP 서버 (port 5008)
    ├── server_rest.py          # FastAPI REST 서버
    ├── server_stdio.py         # STDIO 프로토콜 서버
    └── server.py               # MCP 서버
```

## 환경변수 (.env)

```env
MCP_YAML_PATH=<tool definition yaml>  # MCP 도구 정의 YAML 경로 (선택, 기본: mcp_editor/mcp_file_handler/tool_definition_templates.yaml)
```
