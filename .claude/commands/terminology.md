---
description: MCP Server 용어 정의 (Terminology) (project)
---

> **공통 지침**: 작업 전 [common.md](common.md) 참조

# MCP Server 용어 정의 (Terminology)

## 핵심 구조 (Core Structure)

### 표준 데이터 구조
```python
{
    'tool_name': 'Outlook',           # MCP Tool 이름 (사용자가 호출)
    'server_name': 'outlook',         # MCP 서버 이름 (서버 식별자)
    'profile_key': 'mcp_outlook',     # editor_config.json 프로필 키 (mcp_{server_name} 규칙)

    'implementation': {               # Python 구현 정보
        'method': 'query_filter',     # Python 메서드명
        'class': 'GraphMailQuery',    # 클래스명
        'instance': 'graph_mail_query',   # 인스턴스 변수명
        'module_path': 'graph_mail_query' # import 경로
    },

    'params': {},                     # 파라미터 정보
    'metadata': {}                    # 메타데이터
}
```

## 용어 정의

### MCP 레벨
- **tool_name**: MCP Tool의 이름. 사용자/클라이언트가 호출할 때 사용
- **server_name**: MCP 서버의 이름. 서버를 식별하는 이름
- **profile_key**: editor_config.json에서 사용하는 프로필 키 (`mcp_{server_name}`)

### 프로필 타입
- **Base Profile**: 기본 MCP 서버 프로필 (자체 서비스 코드 보유)
- **Reused Profile**: 기존 Base 서비스를 재사용하는 프로필 (`is_reused: true`, `base_profile` 지정)
- **Merged Profile**: 여러 프로필을 병합한 통합 서버 (`is_merged: true`, `source_profiles` 지정)

### implementation 레벨 (Python 구현)
- **implementation.method**: 실제 Python 클래스의 메서드 이름
- **implementation.class**: Python 클래스 이름
- **implementation.instance**: 클래스 인스턴스를 저장할 변수명
- **implementation.module**: Python import 경로

### 파라미터 레벨
- **Schema Property Name**: inputSchema.properties에 정의되는 이름 (LLM이 인식)
- **params**: 단순 타입 파라미터 정보
- **object_params**: 객체 타입 파라미터 정보
- **targetParam**: Schema Property Name과 실제 서비스 메서드 파라미터를 매핑

### 메타데이터 레벨
- **metadata**: Tool의 부가 정보 (category, tags, priority, description)

## 네이밍 규칙

| 항목 | 규칙 | 예시 |
|------|------|------|
| tool_name | PascalCase 또는 snake_case | "outlook", "keyword_search" |
| server_name | lowercase, 언더스코어 허용 | "outlook", "file_handler" |
| profile_key | `mcp_{server_name}` 형식 | "mcp_outlook" |
| implementation.method | snake_case, 동사로 시작 | "query_filter", "send_mail" |
| implementation.class | PascalCase, 명사형 | "GraphMailQuery" |
| implementation.instance | snake_case | "graph_mail_query" |

## 파일/디렉토리 네이밍 규칙

| 구분 | 규칙 | 예시 |
|------|------|------|
| 모듈 디렉토리 | `mcp_{server_name}/` | `mcp_outlook/` |
| 에디터 프로필 | `mcp_editor/mcp_{server_name}/` | `mcp_editor/mcp_outlook/` |
| 템플릿 정의 (**YAML**) | `tool_definition_templates.yaml` | Single Source of Truth |
| Internal Args | `mcp_service_factors` (YAML 내) | tool_definition_templates.yaml 참조 |
| 레지스트리 | `registry_{server_name}.json` | `registry_outlook.json` |

## 데이터 흐름

### 1. 데코레이터 → Tool 정의
```python
@mcp_service(
    tool_name="handle_query_filter",
    service_name="query_filter",        # → implementation.method
    server_name="outlook",              # → server_name
)
```

### 2. Analyzed 구조 → 생성된 코드
```python
from {{ implementation.module }} import {{ implementation.class }}
{{ implementation.instance }} = {{ implementation.class }}()

async def handle_{{ tool_name }}(args):
    return await {{ implementation.instance }}.{{ implementation.method }}(...)
```

## 예시

### Outlook Tool
```python
{
    'tool_name': 'Outlook',
    'server_name': 'outlook',
    'implementation': {
        'method': 'query_filter',
        'class': 'GraphMailQuery',
        'instance': 'graph_mail_query',
        'module_path': 'graph_mail_query'
    }
}
```

## 관련 파일 경로

### 핵심 스크립트
- `mcp_editor/mcp_service_registry/mcp_service_decorator.py` - @mcp_service 데코레이터
- `mcp_editor/mcp_service_registry/mcp_service_scanner.py` - 데코레이터 스캔
- `mcp_editor/mcp_service_registry/meta_registry.py` - 메타 레지스트리 관리

### 레지스트리 파일
- `mcp_editor/mcp_service_registry/registry_{server_name}.json` - 서비스 구현 정보
- `mcp_editor/mcp_service_registry/types_property_{server_name}.json` - 타입 속성

### 서버별 파일
- `mcp_editor/mcp_{server_name}/tool_definition_templates.yaml` - 도구 정의 (**Single Source of Truth**, mcp_service_factors 포함)
- `mcp_{server_name}/mcp_server/server_rest.py` - REST API 서버 (런타임에 YAML 로드)
- `mcp_{server_name}/mcp_server/server_stdio.py` - STDIO 프로토콜 서버
- `mcp_{server_name}/mcp_server/server_stream.py` - Stream 프로토콜 서버 (SSE)

> **Note**: `tool_definitions.py`는 더 이상 생성되지 않음 (v3.0). 서버가 런타임에 YAML에서 직접 로드.

### 설정 파일
- `mcp_editor/editor_config.json` - 에디터 설정 (프로필별 경로)

---
*Last Updated: 2026-01-11*
*Version: 3.1*
*변경사항: 프로필 타입(Base, Reused, Merged) 용어 추가*