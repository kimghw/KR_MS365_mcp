# MCP Attachment Server Generator

## 개요
Jinja2 템플릿을 사용하여 MCP 서버 파일을 자동 생성하는 시스템입니다.

## 생성되는 파일
1. **server.py** - MCP 서버 구현
2. **mcp_decorators.py** - MCP 툴 데코레이터

## 사용 방법

### 1. 기본 사용법
```bash
# tool_definitions.py에서 서버 생성
python jinja/generate_attachment_server.py \
    --tools mcp_attachment/mcp_server/tool_definitions.py \
    --output-dir generated/

# JSON 파일에서 서버 생성
python jinja/generate_attachment_server.py \
    --tools tools.json \
    --output-dir generated/
```

### 2. 커스텀 템플릿 사용
```bash
python jinja/generate_attachment_server.py \
    --tools mcp_attachment/mcp_server/tool_definitions.py \
    --template custom_template.jinja2 \
    --output-dir generated/
```

### 3. 데코레이터 없이 생성
```bash
python jinja/generate_attachment_server.py \
    --tools mcp_attachment/mcp_server/tool_definitions.py \
    --output-dir generated/ \
    --no-include-decorators
```

## 템플릿 구조
템플릿(`attachment_server_template.jinja2`)은 다음을 포함합니다:
- MCP 서버 클래스
- 각 툴에 대한 핸들러 메서드
- `@mcp_tool` 데코레이터 적용
- 비동기 처리 지원

## 툴 정의 형식

### Python 파일 (tool_definitions.py)
```python
TOOL_DEFINITIONS = [
    {
        "name": "convert_file_to_text",
        "description": "Convert a file to text format",
        "category": "file_processing",
        "tags": ["conversion", "text"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                }
            },
            "required": ["file_path"]
        }
    }
]
```

### JSON 파일
```json
{
    "TOOL_DEFINITIONS": [
        {
            "name": "convert_file_to_text",
            "description": "Convert a file to text format",
            "inputSchema": {
                ...
            }
        }
    ]
}
```

## 생성된 파일 사용

### 1. 파일 복사
```bash
# 생성된 파일을 프로젝트로 복사
cp generated/server.py mcp_attachment/mcp_server/
cp generated/mcp_decorators.py mcp_attachment/mcp_server/
```

### 2. 서버 실행
```bash
# MCP 서버 실행
python -m mcp_attachment.mcp_server.server
```

## 데코레이터 활용

생성된 `mcp_decorators.py`는 다음 기능을 제공합니다:

```python
from mcp_decorators import mcp_tool, get_mcp_tools

@mcp_tool(
    tool_name="my_tool",
    description="My custom tool",
    category="custom",
    tags=["example"]
)
async def my_tool_handler(self, arguments: dict):
    # 툴 구현
    pass

# 등록된 모든 툴 조회
tools = get_mcp_tools()
```

## 템플릿 커스터마이징

템플릿을 수정하여 추가 기능을 구현할 수 있습니다:

1. **로깅 추가**
2. **에러 처리 개선**
3. **캐싱 메커니즘**
4. **성능 모니터링**

## 주의사항

- 생성된 파일을 수동으로 수정한 경우, 재생성 시 변경사항이 손실됩니다
- 툴 정의가 변경되면 서버를 재생성해야 합니다
- 템플릿 수정 시 Jinja2 문법을 준수해야 합니다