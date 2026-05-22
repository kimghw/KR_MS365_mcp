> **공통 지침**: 작업 전 [common.md](common.md) 참조

# MCP Protocol 추가 구현 가이드

## 1. 개요
MCP(Model Communication Protocol) 서버에 새로운 프로토콜을 추가하기 위한 실무 가이드입니다.
Jinja2 템플릿 시스템을 활용하여 REST, STDIO, StreamableHTTP 등 다양한 프로토콜을 지원합니다.

## 2. 시스템 구조
```
jinja/
├── generate_universal_server.py      # 메인 생성 스크립트 (이미 구현됨)
├── universal_server_template.jinja2   # 범용 서버 템플릿 (공통 유틸리티 포함)
├── server_rest.jinja2                # REST 프로토콜
├── server_stdio.jinja2               # STDIO 프로토콜
├── server_stream.jinja2              # StreamableHTTP 프로토콜
├── server_[new].jinja2               # 새 프로토콜 추가 위치
├── backup/                           # 백업 디렉토리
├── legacy_backup/                    # 레거시 템플릿 백업
└── __pycache__/                      # Python 캐시
```

## 3. 프로토콜 추가 단계별 가이드

### Step 1: 프로토콜 템플릿 작성 (핵심)
`jinja/server_[protocol_name].jinja2` 파일을 생성합니다.

#### ⚠️ 중요 주의사항
- **템플릿은 프로토콜 핸들러만 포함**: 서버 클래스와 엔트리 포인트 함수만 작성
- **기본 import는 제외**: universal_server_template에서 이미 처리 (json, logging 등)
- **프로토콜 특화 import만 포함**: 예) aiohttp의 web, StreamResponse 등
- **서비스 인스턴스 사용**: 생성하지 말고 globals()에서 참조

#### 필수 구현 요소

##### 1️⃣ **서비스 초기화 (필수!)**
```jinja2
# HTTP 기반 프로토콜 (REST, StreamableHTTP)
async def on_startup(self, app):
    """서버 시작 시 실행 - 서비스 초기화 필수!"""
    logger.info(f"{{ server_title }} Server starting...")

    # ⚠️ 중요: 서비스 초기화 코드 반드시 포함
    {%- for key, service_info in unique_services.items() %}
    if hasattr({{ service_info.instance }}, 'initialize'):
        await {{ service_info.instance }}.initialize()
        logger.info("{{ service_info.class_name }} initialized")
    {%- endfor %}

# STDIO 프로토콜
async def run(self):
    # 서버 시작 전 초기화
    {%- for key, service_info in unique_services.items() %}
    if hasattr({{ service_info.instance }}, 'initialize'):
        await {{ service_info.instance }}.initialize()
    {%- endfor %}
```

##### 2️⃣ **파라미터 파싱 주의사항**
```jinja2
# ⚠️ MCP 표준 요청 형식
# /mcp/v1/tools/call 엔드포인트:
{
    "name": "tool_name",      # ✅ 직접 접근
    "arguments": {...}         # ✅ 직접 접근
}

# ❌ 잘못된 파싱 (params 없음!)
tool_name = data.get("params", {}).get("name")  # 틀림!

# ✅ 올바른 파싱
tool_name = data.get("name")
arguments = data.get("arguments", {})
```

#### 간단한 예시: StreamableHTTP 프로토콜
```jinja2
{# server_stream.jinja2 #}
class StreamableHTTPMCPServer:

    async def handle_tools_call(self, request: web.Request):
        data = await request.json()
        # ✅ 올바른 파라미터 파싱
        tool_name = data.get("name")
        arguments = data.get("arguments", {})

    async def on_startup(self, app):
        # ✅ 필수: 서비스 초기화
        {%- for key, service_info in unique_services.items() %}
        if hasattr({{ service_info.instance }}, 'initialize'):
            await {{ service_info.instance }}.initialize()
            logger.info("{{ service_info.class_name }} initialized")
        {%- endfor %}
```

### Step 2: Universal Template 업데이트 (핵심)
`universal_server_template.jinja2`에 새 프로토콜을 포함시킵니다.

#### 2-1. 프로토콜 include 추가
```jinja2
{#- Include protocol-specific handlers based on protocol_type -#}
{%- if protocol_type == 'rest' %}
{% include 'server_rest.jinja2' %}
{%- elif protocol_type == 'stdio' %}
{% include 'server_stdio.jinja2' %}  {# ✅ 올바른 방법 #}
{%- elif protocol_type == 'stream' %}
{% include 'server_stream.jinja2' %}
{%- elif protocol_type == 'your_new_protocol' %}
{% include 'server_your_new_protocol.jinja2' %}
{%- endif %}
```

**❌ 절대 하지 말아야 할 것**: TODO 코드 직접 작성
```jinja2
{%- elif protocol_type == 'new' %}
# TODO: Implement new protocol
async def handle_new():
    pass  # 이렇게 하면 안됨!
{%- endif %}
```

#### 2-2. 필요한 import 추가
```jinja2
{%- if protocol_type == 'stdio' or protocol_type == 'stream' %}
import asyncio
from typing import AsyncIterator
{%- endif %}
```

#### 2-3. main 실행 부분 수정
```jinja2
if __name__ == "__main__":
{%- if protocol_type == 'rest' %}
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
{%- elif protocol_type == 'stdio' %}
    asyncio.run(handle_stdio())  # 비동기 함수 실행
{%- elif protocol_type == 'stream' %}
    handle_streamablehttp(host="0.0.0.0", port=8001)  # 일반 함수 실행
{%- endif %}
```

### Step 3: 생성 스크립트 옵션 확인
`generate_universal_server.py`는 이미 구현되어 있습니다. 새 프로토콜을 추가할 때 choices에 포함되어야 합니다:

```python
# generate_universal_server.py (이미 구현됨)
parser.add_argument('--protocol',
                   choices=['rest', 'stdio', 'stream', 'all', 'your_new_protocol'],  # 여기에 추가
                   default='rest')
# 'all' 옵션: 모든 프로토콜 서버를 한 번에 생성
```

## 4. 실행 및 테스트

### 코드 생성
```bash
# 개별 프로토콜 서버 생성 (outlook을 예시로)
python jinja/generate_universal_server.py outlook --protocol rest
python jinja/generate_universal_server.py outlook --protocol stdio
python jinja/generate_universal_server.py outlook --protocol stream

# 모든 프로토콜 서버 한 번에 생성
python jinja/generate_universal_server.py outlook --protocol all
```

### 필수 테스트
```bash
# 1. 문법 검증 (필수!)
python -m py_compile mcp_outlook/mcp_server/server_[protocol].py

# 2. 서버 시작 테스트
timeout 3 python mcp_outlook/mcp_server/server_[protocol].py

# 3. 기본 동작 확인 (프로토콜별)
# REST/StreamableHTTP:
curl http://localhost:[PORT]/health

# STDIO:
echo '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}' | python server_stdio.py
```

## 5. 프로토콜별 특징

| 프로토콜 | 통신 방식 | 응답 형식 | 주요 용도 |
|---------|---------|---------|---------|
| **REST** | HTTP/HTTPS | JSON | 웹 API, 동기/비동기 처리 |
| **STDIO** | stdin/stdout | JSON-RPC | CLI 도구, 프로세스 간 통신 |
| **StreamableHTTP** | HTTP + Chunked | NDJSON | 실시간 스트리밍, 점진적 응답 |

## 6. 중요 고려사항

### 이벤트 루프 관리
| 프로토콜 | 실행 방식 | 주의사항 |
|---------|---------|---------|
| STDIO | `asyncio.run(handle_stdio())` | 비동기 함수 |
| StreamableHTTP | `handle_streamablehttp()` | 일반 함수 (aiohttp가 루프 관리) |
| REST | `uvicorn.run(app)` | FastAPI app 실행 |

### 응답 형식 차이
```python
# REST/StreamableHTTP
return web.json_response({"content": [{"type": "text", "text": result}]})

# STDIO (JSON-RPC)
return {"jsonrpc": "2.0", "id": request_id, "result": result}
```

### globals() 사용
프로토콜 템플릿에서 도구 핸들러를 찾을 때 `globals()`를 사용:
```python
handler_name = f"handle_{tool_name.replace('-', '_')}"
if handler_name in globals():
    result = await globals()[handler_name](arguments)
```

## 7. 일반적인 문제와 해결방법

| 문제 | 원인 | 해결 |
|-----|-----|-----|
| **ImportError: asyncio** | universal_server_template에 import 누락 | 조건부 import 추가 |
| **이벤트 루프 충돌** | `asyncio.run()`과 `web.run_app()` 동시 사용 | 프로토콜별 실행 방식 확인 |
| **TODO 코드 생성됨** | `{% include %}` 대신 직접 코드 작성 | 반드시 `{% include %}` 사용 |
| **포트 사용 중** | 이미 실행 중인 서버 | `lsof -i :[PORT]`로 확인 후 종료 |
| **"Unknown tool: None"** | 파라미터를 `params.name`으로 접근 | `data.get("name")` 직접 접근 |
| **"Service not initialized"** | 서비스 초기화 코드 누락 | `on_startup`에 초기화 코드 추가 |

## 8. 체크리스트

### 새 프로토콜 추가 시 필수 작업
- [ ] `server_[protocol].jinja2` 템플릿 작성
- [ ] **서비스 초기화 코드 포함** (`on_startup` 또는 `run` 메서드에)
- [ ] **파라미터 파싱 확인** (`data.get("name")` 직접 접근)
- [ ] `universal_server_template.jinja2`에 `{% include %}` 추가
- [ ] 엔트리 포인트 함수 정의 (`handle_[protocol]()`)
- [ ] `generate_universal_server.py`의 choices에 추가
- [ ] 필요한 import 조건부 추가
- [ ] 문법 검증 (`python -m py_compile`)
- [ ] 기본 동작 테스트
- [ ] **도구 호출 테스트** (파라미터 전달 확인)

## 9. 요약

새로운 MCP 프로토콜 추가는 단 3단계로 완료됩니다:

1. **템플릿 작성**: `jinja/server_[protocol].jinja2` 파일 생성
2. **Include 추가**: `universal_server_template.jinja2`에 `{% include %}` 추가
3. **테스트**: 생성 및 동작 확인

**핵심 원칙**: TODO 코드를 직접 작성하지 말고 반드시 템플릿 파일을 include하세요.

---

## 10. 관련 문서

| 문서 | 설명 |
|------|------|
| [web.md](web.md) | 웹에디터에서 서버 생성/병합 |
| [test.md](test.md) | 프로토콜별 테스트 방법 |
| [terminology.md](terminology.md) | MCP 용어 정의 |

---

**작성일**: 2025-12-26
**최종 수정일**: 2026-01-11
**버전**: 3.3.0
**업데이트**:
- v3.0.0: STDIO 및 StreamableHTTP 프로토콜 추가, 문서 간소화
- v3.1.0: 서비스 초기화 및 파라미터 파싱 주의사항 추가
- v3.2.0: protocol_base.jinja2 제거 반영, 'all' 옵션 추가, 디렉토리 구조 업데이트
- v3.2.1: 날짜 업데이트
- v3.3.0: 관련 문서 섹션 추가, 대시보드/병합 기능 연계