---
description: MCP 서비스 구현 가이드 - Facade 패턴 적용
---

> **공통 지침**: 작업 전 [common.md](common.md) 참조

# MCP 서비스 구현 가이드

MCP(Model Communication Protocol) 서버의 서비스 레이어 구현을 위한 범용 가이드

---

## 설계 원칙

### Facade 디자인 패턴 적용
- `{service_name}_service.py`는 실제 비즈니스 로직의 **Facade** 역할
- **인자만 제어**하여 내부 복잡성을 숨김
- 실제 로직은 별도의 클라이언트/핸들러 클래스에 위임
- MCP 도구에서 단순한 인터페이스로 호출 가능

### 3계층 아키텍처 구조

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Server (Handler)                  │
│                   server_rest/stdio/stream.py            │
│         (프로토콜 처리, Tool 호출, 요청/응답 변환)        │
└─────────────────────────┬───────────────────────────────┘
                          │ 호출
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    Service Layer                         │
│                   {service_name}_service.py              │
│  ┌─────────────────────────────────────────────────┐    │
│  │  @mcp_service(tool_name="handler_xxx")          │    │
│  │  async def service_method(...)                  │    │
│  │  - 기본값 설정                                   │    │
│  │  - 응답 형식 변환                                │    │
│  │  - MCP 메타데이터 등록                           │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────┘
                          │ 위임 (Delegation)
                          ▼
┌─────────────────────────────────────────────────────────┐
│                 Implementation Layer                     │
│              (실제 API 호출 및 비즈니스 로직)              │
│         여러 구현체 가능: client, handler, util 등        │
│   (예: GraphMailClient, FileHandler, DatabaseHelper)     │
└─────────────────────────────────────────────────────────┘
```

### 각 계층의 역할

| 계층 | 파일 | 역할 |
|------|------|------|
| **Handler** | `server_*.py` | 프로토콜 처리 (REST/STDIO/Stream), Tool 라우팅 |
| **Service** | `*_service.py` | Facade 역할, 기본값/변환 처리, MCP 메타데이터 |
| **Implementation** | (public 함수) | 실제 비즈니스 로직, 외부 API 호출, 데이터 처리 |

> **실제 구현 예시**: `mcp_outlook/outlook_service.py` 참조

---

## 서비스 구조 템플릿

### 1. 기본 서비스 클래스 구조

```python
# mcp_{service_name}/{service_name}_service.py

from typing import Optional, Dict, Any, List
from mcp_editor.mcp_service_registry.mcp_service_decorator import mcp_service
from .{service_name}_client import {ServiceName}Client  # 실제 로직 클라이언트
from .{service_name}_types import *  # 타입 정의 (선택사항)

class {ServiceName}Service:
    """
    {ServiceName}Client의 Facade - MCP 도구를 위한 단순화된 인터페이스

    이 클래스는 복잡한 내부 로직을 숨기고
    MCP 도구가 쉽게 호출할 수 있는 메서드만 노출합니다.
    """

    def __init__(self):
        self._impl = None  # Implementation Layer 구현체
        self._initialized = False

    async def initialize(self):
        """서비스 초기화 - 서버 시작 시 자동 호출"""
        if not self._initialized:
            # Implementation 초기화
            self._impl = SomeImplementation()
            if hasattr(self._impl, 'initialize'):
                await self._impl.initialize()
            self._initialized = True

    async def close(self):
        """리소스 정리 - 서버 종료 시 호출"""
        if self._impl and hasattr(self._impl, 'close'):
            await self._impl.close()
        self._initialized = False

    # ===== MCP 도구 메서드들 (Facade 메서드) =====

    @mcp_service(
        name="tool_name_1",
        description="도구 설명"
    )
    async def tool_method_1(self,
                           param1: str,
                           param2: Optional[int] = None) -> Dict[str, Any]:
        """
        MCP 도구 1 - 단순화된 인터페이스

        Args:
            param1: 파라미터 1 설명
            param2: 파라미터 2 설명 (선택사항)

        Returns:
            처리 결과
        """
        if not self._initialized:
            await self.initialize()

        # Implementation에 위임
        return await self._impl.complex_method(
            main_param=param1,
            additional_config={'limit': param2} if param2 else {}
        )

    @mcp_service(
        name="tool_name_2",
        description="다른 도구 설명"
    )
    async def tool_method_2(self,
                           keyword: str,
                           max_results: int = 50) -> List[Dict[str, Any]]:
        """
        MCP 도구 2 - 검색 기능

        Args:
            keyword: 검색어
            max_results: 최대 결과 수

        Returns:
            검색 결과 목록
        """
        if not self._initialized:
            await self.initialize()

        # 복잡한 내부 로직을 단순한 인터페이스로 노출
        return await self._client.search(
            query=keyword,
            limit=max_results,
            # 내부적으로 필요한 복잡한 설정은 숨김
            _internal_options={'mode': 'fast', 'cache': True}
        )

# 서비스 인스턴스 생성 (싱글톤)
{service_name}_service = {ServiceName}Service()
```

---

## 2. 타입 정의 (선택사항)

복잡한 타입이 필요한 경우 별도 파일로 분리:

```python
# mcp_{service_name}/{service_name}_types.py

from enum import Enum
from typing import TypedDict, Optional, List

class ProcessingMode(Enum):
    """처리 모드 열거형"""
    BASIC = "basic"
    ADVANCED = "advanced"
    FULL = "full"

class FilterParams(TypedDict, total=False):
    """필터 파라미터 타입"""
    field1: Optional[str]
    field2: Optional[bool]
    field3: Optional[int]

class ResultItem(TypedDict):
    """결과 항목 타입"""
    id: str
    name: str
    data: Dict[str, Any]
```

---

## 3. 클라이언트 구현 (실제 로직)

```python
# mcp_{service_name}/{service_name}_client.py

class {ServiceName}Client:
    """
    실제 비즈니스 로직을 처리하는 클라이언트

    이 클래스는 복잡한 로직, 외부 API 통신,
    데이터 처리 등의 실제 작업을 수행합니다.
    """

    async def initialize(self):
        """클라이언트 초기화"""
        # DB 연결, API 인증, 캐시 초기화 등
        pass

    async def complex_method(self,
                            main_param: str,
                            additional_config: Dict = None) -> Dict[str, Any]:
        """복잡한 내부 로직"""
        # 실제 비즈니스 로직 구현
        pass

    async def search(self,
                    query: str,
                    limit: int,
                    _internal_options: Dict = None) -> List[Dict]:
        """검색 로직"""
        # 복잡한 검색 알고리즘
        pass
```

---

## Facade 패턴 적용 예시

### 간단한 인터페이스 제공

```python
class DatabaseService:
    """데이터베이스 서비스 Facade"""

    @mcp_service(name="query_database")
    async def query_simple(self, table: str, limit: int = 10):
        """단순한 쿼리 인터페이스"""
        # 복잡한 SQL 빌더 로직을 숨김
        query = self._client.query_builder()\
            .select('*')\
            .from_table(table)\
            .limit(limit)\
            .with_joins()\
            .with_indexes()\
            .optimize()

        return await self._client.execute(query)
```

### 파라미터 변환 및 검증

```python
class FileService:
    """파일 처리 서비스 Facade"""

    @mcp_service(name="process_file")
    async def process_file(self,
                          file_path: str,
                          format: str = "json"):
        """파일 처리 - 파라미터를 내부 형식으로 변환"""

        # 외부 파라미터를 내부 옵션으로 변환
        processing_options = {
            'input_path': file_path,
            'output_format': self._map_format(format),
            'compression': 'gzip' if format == 'json' else None,
            'validation': True,
            'error_handling': 'strict'
        }

        return await self._client.process(**processing_options)

    def _map_format(self, external_format: str) -> str:
        """외부 포맷을 내부 포맷으로 매핑"""
        format_map = {
            'json': 'json_newline_delimited',
            'csv': 'csv_with_headers',
            'xml': 'xml_pretty_print'
        }
        return format_map.get(external_format, 'raw')
```

---

## 디렉토리 구조

```
mcp_{service_name}/
├── __init__.py
├── {service_name}_service.py       # Facade 서비스 (MCP 인터페이스)
├── (Implementation 파일들)          # 경로/파일명 자유 - 비즈니스 로직
├── mcp_server/
│   ├── server_rest.py              # REST API 서버 (런타임 YAML 로드)
│   ├── server_stdio.py             # STDIO 서버
│   └── server_stream.py            # Stream 서버
└── tests/
    └── test_{service_name}.py      # 테스트 코드

mcp_editor/mcp_{service_name}/
└── tool_definition_templates.yaml  # 도구 정의 (Single Source of Truth)
```

> **Note**: `tool_definitions.py`는 더 이상 생성되지 않음. 서버가 런타임에 YAML에서 직접 로드.

---

## MCP 데코레이터 사용

### @mcp_service 데코레이터 기본 양식

```python
from mcp_editor.mcp_service_registry.mcp_service_decorator import mcp_service

# 간단한 형식 (최소 필수)
@mcp_service(
    name="tool-name-kebab-case",     # 도구 이름 (kebab-case)
    description="도구 설명"           # 간단한 설명
)
async def my_tool_method(self, param1: str, param2: int = 10):
    """도구 메서드 구현"""
    pass

# 전체 형식 (모든 옵션)
@mcp_service(
    tool_name="handle_query_search",      # MCP Tool 이름 (레거시 형식)
    server_name="{service_name}",         # 서버 식별자
    service_name="query_search",          # 메서드명
    name="query-search",                  # 도구 이름 (신규 형식)
    category="{service_name}_core",       # 카테고리
    tags=["query", "search"],             # 태그
    priority=5,                           # 우선순위 (1-10)
    description="검색 기능",              # 기능 설명
    include_return=True,                  # 반환값 포함 여부
    json_schema_extra={                   # 추가 메타데이터
        "version": "1.0.0"
    }
)
async def query_search(self, keyword: str, max_results: int = 50):
    """검색 기능 구현"""
    pass
```

### 데코레이터 필드 설명

| 필드 | 필수 | 규칙 | 예시 |
|------|------|------|------|
| **name** | O | kebab-case 형식 | `"search-emails"`, `"process-file"` |
| **description** | O | 한 줄 설명 | `"이메일 검색"`, `"파일 처리"` |
| tool_name | - | handle_ + 기능명 (레거시) | `"handle_query_filter"` |
| server_name | - | 서버 식별자 | `"outlook"`, `"file_handler"` |
| service_name | - | 실제 함수명 | `"query_search"` |
| category | - | 기능 카테고리 | `"mail"`, `"data-processing"` |
| tags | - | 검색용 태그 리스트 | `["query", "mail"]` |
| priority | - | 1-10 (높을수록 중요) | `5` |
| include_return | - | 반환값 스키마 포함 | `True`, `False` |
| json_schema_extra | - | 추가 메타데이터 | `{"version": "1.0.0"}` |

### 파라미터 타입 힌트 규칙

```python
@mcp_service(name="example-tool", description="예시 도구")
async def example_method(
    self,
    # 필수 파라미터 (타입 힌트 필수)
    required_param: str,
    another_required: int,

    # 선택 파라미터 (Optional + 기본값)
    optional_param: Optional[str] = None,
    max_items: int = 100,

    # 복잡한 타입
    filter_params: Dict[str, Any] = None,
    items: List[str] = None
) -> Dict[str, Any]:  # 반환 타입
    """메서드 구현"""
    pass
```

---

## 서비스 초기화 패턴

### 1. Lazy Initialization (권장)

```python
class MyService:
    def __init__(self):
        self._client = None
        self._initialized = False

    async def _ensure_initialized(self):
        """필요시 초기화"""
        if not self._initialized:
            await self.initialize()

    @mcp_service(name="my-tool")
    async def tool_method(self, param: str):
        await self._ensure_initialized()
        return await self._client.process(param)
```

### 2. Explicit Initialization

```python
class MyService:
    async def initialize(self):
        """서버 시작 시 명시적 초기화"""
        self._client = await create_client()
        self._cache = await setup_cache()
        self._initialized = True
```

---

## 에러 처리

```python
@mcp_service(name="safe-tool")
async def safe_method(self, param: str):
    """안전한 에러 처리"""
    try:
        await self._ensure_initialized()
        result = await self._client.process(param)
        return {
            "success": True,
            "data": result
        }
    except ValidationError as e:
        return {
            "success": False,
            "error": f"Validation failed: {str(e)}"
        }
    except Exception as e:
        # 로깅
        logger.error(f"Unexpected error: {e}")
        return {
            "success": False,
            "error": "Internal processing error"
        }
```

---

## 데코레이터 파싱 결과 예시

데코레이터가 적용된 메서드는 다음과 같은 JSON으로 파싱됩니다:

```json
{
  "name": "query-search",
  "metadata": {
    "tool_name": "handle_query_search",
    "server_name": "outlook",
    "service_name": "query_search",
    "category": "outlook_core",
    "tags": ["query", "search"],
    "priority": 5,
    "description": "검색 기능"
  },
  "parameters": [
    {
      "name": "keyword",
      "type": "str",
      "required": true,
      "description": "검색어"
    },
    {
      "name": "max_results",
      "type": "int",
      "required": false,
      "default": 50,
      "description": "최대 결과 수"
    }
  ],
  "is_async": true,
  "class": "QueryService",
  "instance": "query_service"
}
```

---

## 체크리스트

### 서비스 구현 시 확인사항

- [ ] `@mcp_service` 데코레이터가 모든 도구 메서드에 적용되었는가?
- [ ] 데코레이터에 최소한 `name`과 `description`이 포함되었는가?
- [ ] 도구 이름이 kebab-case 형식인가? (예: `search-emails`, `process-file`)
- [ ] 서비스 인스턴스가 파일 끝에 생성되었는가? (싱글톤)
- [ ] `initialize()` 메서드가 구현되었는가?
- [ ] 복잡한 로직이 별도 클라이언트로 분리되었는가?
- [ ] 에러 처리가 적절히 구현되었는가?
- [ ] 타입 힌트가 모든 메서드에 추가되었는가?
- [ ] Optional 파라미터에 기본값이 설정되었는가?
- [ ] Lazy initialization이 구현되었는가?

### 파일 구조

- [ ] `{service_name}_service.py` - Facade 서비스
- [ ] `{service_name}_client.py` - 비즈니스 로직 (선택사항)
- [ ] `{service_name}_types.py` - 타입 정의 (선택사항)
- [ ] 서비스가 `mcp_editor/mcp_service_registry/registry_{service_name}.json`에 등록되는가?

---

## 관련 파일 경로

### 데코레이터 및 레지스트리
- `mcp_editor/mcp_service_registry/mcp_service_decorator.py` - @mcp_service 데코레이터
- `mcp_editor/mcp_service_registry/mcp_service_scanner.py` - 서비스 스캐너
- `mcp_editor/mcp_service_registry/registry_{service_name}.json` - 서비스 레지스트리

### 템플릿 및 정의
- `mcp_editor/mcp_{service_name}/tool_definition_templates.py` - 도구 템플릿 (mcp_service_factors 포함)

### 서버 코드
- `mcp_{service_name}/mcp_server/server_rest.py` - REST API 서버
- `mcp_{service_name}/mcp_server/server_stdio.py` - STDIO 서버
- `mcp_{service_name}/mcp_server/server_stream.py` - Stream 서버

---

**작성일**: 2025-01-05
**최종 수정일**: 2026-01-11
**버전**: 1.3.0
**용도**: 범용 MCP 서비스 구현 가이드
**업데이트**:
- v1.0.0: 초기 버전 - Facade 패턴 기반 서비스 구현 가이드
- v1.1.0: decorator.md 내용 통합 - 데코레이터 상세 가이드 추가
- v1.2.0: tool_internal_args.json 삭제 반영 (mcp_service_factors로 통합)
- v1.3.0: 서버 병합, 대시보드, 프로토콜별 제어 기능 연계 반영

**관련 문서**:
- `.claude/commands/terminology.md` - MCP 용어 정의 (프로필 타입 포함)
- `.claude/commands/web.md` - 웹에디터 사용 가이드 (대시보드, 병합 포함)
- `.claude/commands/test.md` - 테스트 가이드