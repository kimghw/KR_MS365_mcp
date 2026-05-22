# MCP Service Registry 가이드

## 개요

MCP 서비스 레지스트리는 소스 코드에서 `@mcp_service` 데코레이터가 붙은 함수를 AST(Abstract Syntax Tree) 파싱으로 추출하여 JSON 파일로 저장합니다.

```
소스 코드 (.py/.js/.ts)
        ↓ AST 파싱
registry_{server_name}.json  ← 서비스 함수 정보
types_property_{server_name}.json  ← 데이터 모델 정보 (Python만)
        ↓
웹 에디터에서 활용
```

---

## 1. registry_{server_name}.json 생성

### 지원 언어

| 언어 | 파일 확장자 | 파서 | 상태 |
|------|------------|------|------|
| Python | `.py` | `ast` (내장) | 지원 |
| JavaScript | `.js`, `.mjs` | `esprima` | 지원 |
| TypeScript | `.ts`, `.tsx` | `esprima` | 기본 지원 |

### 생성 절차

1. **웹 에디터 요청** → `service_registry.py`의 `load_services_for_server()` 호출
2. **AST 스캔** → `mcp_service_scanner.py`가 소스 디렉토리 순회
3. **데코레이터 추출** → `@mcp_service` 또는 `@McpService` 찾기
4. **메타데이터 파싱** → 함수 시그니처, 파라미터, 데코레이터 옵션 추출
5. **JSON 저장** → `mcp_service_registry/registry_{server_name}.json`

### 출력 파일 구조

```json
{
  "version": "1.0",
  "generated_at": "2024-12-01T10:00:00",
  "server_name": "outlook",
  "services": {
    "send_mail": {
      "signature": "to: str, subject: str, body: str",
      "parameters": [...],
      "metadata": {
        "server_name": "outlook",
        "description": "이메일 발송"
      },
      "handler": {
        "class_name": "MailHandler",
        "module_path": "mcp_outlook.mail_handler",
        "method": "send_mail",
        "is_async": true
      }
    }
  }
}
```

---

## 2. 데코레이터 작성법

### Python

```python
from mcp_service_registry.mcp_service_decorator import mcp_service

class MailHandler:
    @mcp_service(
        server_name="outlook",
        tool_name="send_mail",           # 선택 (기본: 함수명)
        description="이메일을 발송합니다",
        tags=["mail", "communication"]   # 선택
    )
    async def send_mail(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None
    ) -> dict:
        """이메일 발송 서비스"""
        ...
```

**필수 필드:**
- `server_name`: MCP 서버 식별자

**선택 필드:**
- `tool_name`: 툴 이름 (기본값: 함수명)
- `description`: 툴 설명
- `tags`: 태그 목록

### JavaScript / TypeScript

```javascript
// decorators.js - 데코레이터 정의 (프로젝트에 추가 필요)
function McpService(options) {
  return function(target, propertyKey, descriptor) {
    // 메타데이터 저장 로직
    return descriptor;
  };
}

// mail_handler.js
class MailHandler {
  @McpService({
    serverName: "outlook",
    toolName: "send_mail",
    description: "Send an email"
  })
  async sendMail(to, subject, body, cc = null) {
    // ...
  }
}
```

**주의:** JavaScript 데코레이터는 Stage 3 제안이므로 Babel 또는 TypeScript 설정 필요:

```json
// tsconfig.json
{
  "compilerOptions": {
    "experimentalDecorators": true
  }
}
```

### 데코레이터 필드 매핑

| Python | JavaScript | 설명 |
|--------|------------|------|
| `server_name` | `serverName` | 서버 식별자 (필수) |
| `tool_name` | `toolName` | 툴 이름 |
| `description` | `description` | 설명 |
| `tags` | `tags` | 태그 배열 |

스캐너가 JavaScript의 camelCase를 snake_case로 자동 변환합니다.

---

## 3. types_property_{server_name}.json

### 목적

웹 에디터에서 프로퍼티 자동완성, 타입 정보, 설명을 제공하기 위한 데이터 모델 정보.

### 지원 현황

| 언어 | 데이터 모델 | 상태 |
|------|------------|------|
| Python | Pydantic `BaseModel` | 지원 |
| JavaScript | Zod, class-validator | 미지원 (수동 작성 필요) |

### Python - Pydantic 모델 정의

```python
from pydantic import BaseModel, Field
from typing import Optional, List

class DateTime(BaseModel):
    dateTime: str = Field(
        ...,  # 필수 필드
        description="날짜와 시간 (ISO 8601 형식)",
        examples=["2024-12-01T09:00:00"]
    )
    timeZone: str = Field(
        default="Asia/Seoul",
        description="시간대"
    )

class EventInput(BaseModel):
    subject: str = Field(..., description="이벤트 제목")
    start: DateTime = Field(..., description="시작 시간")
    end: DateTime = Field(..., description="종료 시간")
    attendees: Optional[List[str]] = Field(
        default=None,
        description="참석자 이메일 목록",
        examples=[["user@example.com"]]
    )
```

### 추출 명령

```bash
cd mcp_editor/mcp_service_registry
python extract_types.py --server-name calendar /path/to/calendar_types.py
```

### 출력 예시

```json
{
  "classes": [
    {"name": "DateTime", "property_count": 2},
    {"name": "EventInput", "property_count": 4}
  ],
  "properties_by_class": {
    "DateTime": [
      {
        "name": "dateTime",
        "type": "string",
        "description": "날짜와 시간 (ISO 8601 형식)",
        "examples": ["2024-12-01T09:00:00"],
        "default": null
      }
    ]
  },
  "all_properties": [...]
}
```

### JavaScript - 수동 작성

JavaScript 프로젝트는 `types_property_{server_name}.json`을 수동으로 작성해야 합니다:

```json
{
  "classes": [
    {"name": "MailInput", "property_count": 4}
  ],
  "properties_by_class": {
    "MailInput": [
      {
        "name": "to",
        "type": "string",
        "description": "수신자 이메일",
        "examples": ["user@example.com"],
        "default": null
      },
      {
        "name": "subject",
        "type": "string",
        "description": "제목",
        "examples": ["Meeting Request"],
        "default": null
      }
    ]
  },
  "all_properties": [...]
}
```

---

## 4. 설정 파일

### editor_config.json

```json
{
  "outlook": {
    "source_dir": "../mcp_outlook",
    "types_files": ["../mcp_outlook/outlook_types.py"],
    "language": "python"
  },
  "js_server": {
    "source_dir": "../mcp_js_server",
    "types_files": [],
    "language": "javascript"
  }
}
```

---

## 5. 주요 파일

| 파일 | 역할 |
|------|------|
| `mcp_service_scanner.py` | AST 파싱으로 서비스 함수 추출 (Python/JS) |
| `mcp_service_decorator.py` | `@mcp_service` 데코레이터 정의 |
| `extract_types.py` | Pydantic 모델 → JSON 변환 |
| `service_registry.py` | 웹 에디터 API용 서비스 로딩 |
| `meta_registry.py` | 레지스트리 파일 관리 |

---

## 6. 요약

```
┌────────────────────────────────────────────────────────────┐
│                    MCP Service Registry                     │
├────────────────────────────────────────────────────────────┤
│  registry_{server}.json                                     │
│  ├─ Python:     @mcp_service 데코레이터 → AST 파싱          │
│  └─ JavaScript: @McpService 데코레이터 → esprima 파싱       │
├────────────────────────────────────────────────────────────┤
│  types_property_{server}.json                               │
│  ├─ Python:     Pydantic BaseModel → AST 파싱 (자동)        │
│  └─ JavaScript: 수동 작성 필요                              │
└────────────────────────────────────────────────────────────┘
```
