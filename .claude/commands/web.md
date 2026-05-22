
---
description: 웹에디터 설계 원칙 및 작업 가이드 (project)
---

> **공통 지침**: 작업 전 [common.md](common.md) 참조

# 웹에디터 설계 원칙 및 작업 가이드

## 웹에디터 실행
```bash
python mcp_editor/tool_editor_web.py
```

> **자동 스캔**: 웹에디터 시작 시 `@mcp_service` 데코레이터가 있는 함수를 자동 스캔하여 `registry_{server}.json` 업데이트

---

## 1. 목적
MCP 서버의 Tool 인자 및 값을 제어

## 2. 데이터 소스 (서버별 패턴)

| 정보 | 경로 패턴 |
|------|----------|
| 서비스 구현 정보 | `mcp_editor/mcp_service_registry/registry_{server}.json` |
| 도구 정의 (**Single Source of Truth**) | `mcp_editor/mcp_{server}/tool_definition_templates.yaml` |

### 각 파일의 역할

| 파일 | 역할 | 변경 시점 |
|------|------|----------|
| `tool_definition_templates.yaml` | LLM 스키마 + mcp_service_factors (Internal 포함) - **YAML 단일 소스** | 웹에디터에서 저장 시 |
| `registry_{server}.json` | 실제 코드 어디를 호출할지 (implementation) | 소스코드 변경 후 스캔 시 |

> **Note**: `tool_definitions.py`는 더 이상 생성되지 않음. 서버 코드가 런타임에 YAML에서 직접 로드함.

## 3. 네이밍 규칙
→ `docs/terminology.md` 참조

## 4. 생성 대상

### 다중 프로토콜 지원 (v3.0 - YAML Single Source of Truth)
웹에디터에서 "Generate Server" 실행 시 3가지 프로토콜 서버 동시 생성:
- `mcp_{server}/mcp_server/server_rest.py` - REST API 서버 (FastAPI)
- `mcp_{server}/mcp_server/server_stdio.py` - STDIO 프로토콜 서버
- `mcp_{server}/mcp_server/server_stream.py` - Stream 프로토콜 서버 (SSE)

> **삭제됨**: `tool_definitions.py`는 더 이상 생성되지 않음 (v3.0)

### 템플릿 파일
- `jinja/universal_server_template.jinja2` - 통합 서버 템플릿 (모든 프로토콜 지원)

### 수정 원칙
**중요**: 생성 파일 직접 수정 금지. 반드시 아래 파일 수정:
- `jinja/universal_server_template.jinja2` - 서버 템플릿
- `jinja/generate_universal_server.py` - 생성 로직

## 5. 파라미터 분류 원칙

| 분류 | 설명 | LLM 노출 | 저장 위치 |
|------|------|---------|----------|
| **Signature** | LLM이 제공하는 파라미터 | O | `tool_definition_templates.yaml`의 inputSchema |
| **Signature Defaults** | LLM에게 보이지만 기본값 제공 | O | `mcp_service_factors` (source: signature_defaults) |
| **Internal** | 시스템이 고정하는 파라미터 | X | `mcp_service_factors` (source: internal) |

## 6. Generate 흐름

> **상세 데이터 흐름**: [web_dataflow.md](../preprompts/web_dataflow.md) Section 2, 4 참조

### 요약
```
tool_definition_templates.yaml + registry_{server}.json
    → generate_universal_server.py
    → server_rest.py / server_stdio.py / server_stream.py
```

### 프로토콜별 특징
| 프로토콜 | 용도 | 통신 방식 | 포트 |
|---------|------|----------|------|
| REST | HTTP API 클라이언트용 | HTTP/JSON | 지정 포트 |
| STDIO | CLI/터미널 연동 | 표준 입출력 | N/A |
| Stream | 실시간 이벤트 스트림 | SSE | 지정 포트 |

## 7. 작업 흐름
1. `tool_definition_templates.yaml`에서 도구 정의 확인/수정
2. `registry_{server}.json`에서 서비스 구현 정보 확인
3. 필요시 템플릿 수정
4. `generate_universal_server.py`로 최종 파일 생성

---

## 관련 파일 경로

> **전체 파일 목록**: [web_dataflow.md](../preprompts/web_dataflow.md) Section 12 참조

### 핵심 파일
| 구분 | 파일 |
|------|------|
| 웹에디터 | `mcp_editor/tool_editor_web.py` |
| 서버 생성 | `jinja/generate_universal_server.py` |
| 레지스트리 | `mcp_editor/mcp_service_registry/mcp_service_scanner.py` |
| 서버 제어 | `mcp_editor/mcp_server_controller.py` |

---

## 새 MCP 서버 프로젝트 생성

### 사용 방법
1. 웹에디터에서 **"New Project"** 버튼 클릭
2. 서비스 정보 입력 (name, port, description 등)
3. "Create Project" 버튼 클릭

### 생성되는 구조
```
mcp_{service_name}/
├── mcp_server/
│   ├── __init__.py
│   ├── server_rest.py     # REST API 서버
│   ├── server_stdio.py    # STDIO 프로토콜 서버
│   ├── server_stream.py   # Stream 프로토콜 서버
│   └── run.py             # 서버 실행 스크립트
├── {service_name}_service.py  # 비즈니스 로직
├── {service_name}_types.py    # 타입 정의 (선택사항)
└── requirements.txt        # Python 의존성

mcp_editor/mcp_{service_name}/
└── tool_definition_templates.yaml  # 도구 정의 (Single Source of Truth)
```

### 내부 동작
- `jinja/create_mcp_project.py`의 `MCPProjectCreator` 클래스 사용
- 프로젝트 생성 후 `editor_config.json` 자동 업데이트
- 생성 완료 후 3초 뒤 자동 새로고침

---

## MCP 서버 대시보드

> **상세 아키텍처**: [web_dataflow.md](../preprompts/web_dataflow.md) Section 11 참조

### 대시보드 접근
웹에디터 좌측 상단 **MCP 로고**를 클릭하면 서버 대시보드 모달이 열립니다.

### 주요 기능
- **프로필별 상태 조회**: 모든 프로필의 서버 상태 한눈에 확인
- **프로토콜별 독립 제어**: REST, STDIO, Stream 각각 시작/중지/재시작
- **프로필 계층 표시**: Base, Reused, Merged 프로필 구분

### 빠른 참조: API 엔드포인트
| API | 설명 |
|-----|------|
| `GET /api/server/dashboard` | 전체 상태 조회 |
| `POST /api/server/start?profile=X&protocol=Y` | 서버 시작 |
| `POST /api/server/stop?profile=X&protocol=Y` | 서버 중지 |

---

## MCP 프로토콜 서버 실행

### 웹에디터에서 실행 (권장)
대시보드에서 프로토콜 선택 후 **Start** 버튼 클릭

### CLI에서 직접 실행
```bash
# REST API 서버 실행 (FastAPI)
python mcp_outlook/mcp_server/server_rest.py
# 또는
cd mcp_outlook/mcp_server && uvicorn server_rest:app --reload --port 8091

# STDIO 프로토콜 서버 실행
python mcp_outlook/mcp_server/server_stdio.py

# Stream 프로토콜 서버 실행 (SSE)
python mcp_outlook/mcp_server/server_stream.py
```

---

## 디버깅 및 테스트

```bash
# 레지스트리 스캔 및 확인
python mcp_editor/mcp_service_registry/mcp_service_scanner.py

# editor_config.json 재생성
python jinja/generate_editor_config.py

# 서버 코드 재생성 (outlook 예시) - 3가지 프로토콜 동시 생성
python jinja/generate_universal_server.py outlook --protocol all

# 특정 프로토콜만 생성
python jinja/generate_universal_server.py outlook --protocol rest
python jinja/generate_universal_server.py outlook --protocol stdio
python jinja/generate_universal_server.py outlook --protocol stream

# 서버 병합 (outlook + calendar → ms365)
python jinja/generate_universal_server.py merge \
    --name ms365 \
    --sources outlook,calendar \
    --port 8090 \
    --protocol all
```

---

## 서버 병합 기능

> **상세 데이터 흐름**: [web_dataflow.md](../preprompts/web_dataflow.md) Section 10 참조

### 웹 UI에서 병합 (권장)
1. 웹에디터에서 **"Merge"** 버튼 클릭
2. 병합할 서버들 선택 (outlook, calendar 등)
3. 병합 서버 이름 입력 (예: ms365)
4. 포트 및 프로토콜 설정
5. **"Create Merged Server"** 클릭

### CLI에서 병합
```bash
python jinja/generate_universal_server.py merge \
    --name ms365 \
    --sources outlook,calendar \
    --port 8090 \
    --protocol all
```

### 주요 옵션
| 옵션 | 설명 |
|------|------|
| `--name` | 병합 서버 이름 (필수) |
| `--sources` | 병합할 프로필 목록, 콤마 구분 (필수) |
| `--protocol` | 프로토콜 타입 (rest/stdio/stream/all) |

---

## 파생 서버 생성

### 기존 서비스 재사용
기존 MCP 서비스를 재사용하여 도구 세트가 다른 새 프로필 생성:
1. 웹에디터에서 **"New Project"** → **"Reuse existing service"** 선택
2. 기존 서비스 선택 (예: outlook)
3. 새 프로필 이름 입력 (예: outlook_read)
4. 생성 후 YAML에서 필요한 도구만 선택

---

## 체크리스트

웹에디터 작업 시:
- [ ] @mcp_service 데코레이터가 모든 서비스 메서드에 있는지 확인
- [ ] registry_{server}.json이 최신 상태인지 확인
- [ ] tool_definition_templates.yaml이 정확한지 확인
- [ ] Internal 파라미터가 올바르게 설정되었는지 확인
- [ ] Generate Server 실행 시 3가지 프로토콜 파일 생성 확인
  - [ ] server_rest.py 생성 및 동작 확인
  - [ ] server_stdio.py 생성 및 동작 확인
  - [ ] server_stream.py 생성 및 동작 확인
- [ ] 서버가 YAML에서 MCP_TOOLS를 정상 로드하는지 확인

---

## 문서 역할

| 문서 | 역할 |
|------|------|
| **web.md** (본 문서) | 웹에디터 **사용 방법** 및 **실행 지침** |
| [web_dataflow.md](../preprompts/web_dataflow.md) | 웹에디터 **데이터 흐름** 및 **내부 구현** 상세 |

---
*Last Updated: 2026-01-11*
*Version: 3.3*
*변경사항: 역할 분리 - 상세 데이터 흐름은 web_dataflow.md로 참조*
