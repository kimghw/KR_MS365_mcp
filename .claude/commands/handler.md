> **공통 지침**: 작업 전 [common.md](common.md) 참조
> **상세 데이터 흐름**: [web_dataflow.md](../preprompts/web_dataflow.md) Section 3-5 참조

# MCP 핸들러 파라미터 체계

> 본 문서는 핸들러 파라미터의 **핵심 개념**을 설명합니다. 런타임 처리 흐름 및 병합 체계 상세는 [web_dataflow.md](../preprompts/web_dataflow.md)를 참조하세요.

## inputSchema 인자 타입

inputSchema의 각 프로퍼티는 다음 3가지 타입 중 하나를 가지며, 모두 `targetParam`을 통해 서비스 메서드 파라미터에 매핑된다.

### Signature
- **역할**: LLM이 제공하는 사용자 입력값
- **targetParam**: 지정됨 → 서비스 메서드 파라미터로 매핑
- **필수 여부**: 단독 사용 가능

### Signature Default (옵션)
- **역할**: 사용자 입력의 기본값 제공
- **targetParam**: 지정됨 → 서비스 메서드 파라미터로 매핑
- **우선순위**: Signature 값 우선, 값이 없는 속성만 default 사용
- **특징**: 템플릿에 의해 핸들러 내부에 하드코딩됨
- **위치**: `mcp_service_factors` (source: "signature_defaults")

### Internal (옵션)
- **역할**: LLM에게 숨겨진 시스템 고정값
- **targetParam**: 지정됨 → 서비스 메서드 파라미터로 매핑
- **특징**: 템플릿에 의해 핸들러 내부에 하드코딩됨
- **위치**: `mcp_service_factors` (source: "internal")

## 매핑 흐름

```
inputSchema 프로퍼티
    ↓ targetParam 지정
서비스 메서드 파라미터
```

**모든 targetParam은 최종적으로 service method의 파라미터로 전달된다.**

## 병합 로직

> **상세 병합 체계**: [web_dataflow.md](../preprompts/web_dataflow.md) Section 5 참조

### 우선순위 (높음 → 낮음)
1. **사용자 입력** (Signature)
2. **Signature Defaults**
3. **Internal 파라미터**
4. 서비스 메서드 기본값

### 핵심 규칙
- Signature 값이 항상 우선
- 같은 targetParam을 가리킬 때만 병합 발생
- null/None 값은 병합에서 제외

## targetParam vs targetServiceFactor

| 필드명 | 역할 | 매핑 대상 |
|--------|------|----------|
| `targetParam` | 서비스 메서드 파라미터명 연결 | `service.method(param_name=...)` |
| `targetServiceFactor` | mcp_service_factors 키와 명시적 연결 | 같은 타입의 파라미터가 여러 개일 때 충돌 방지 |

## 관련 파일

| 파일 | 역할 |
|------|------|
| `tool_definition_templates.yaml` | inputSchema + mcp_service_factors 정의 (**Single Source of Truth**) |
| `{service}_service.py` | 비즈니스 로직 (서비스 메서드) |

> **Note**: `tool_definitions.py`는 더 이상 사용되지 않음. 서버 코드가 런타임에 YAML에서 직접 로드.

---

## 문서 역할

| 문서 | 역할 |
|------|------|
| **handler.md** (본 문서) | 파라미터 체계 **핵심 개념** 요약 |
| [web_dataflow.md](../preprompts/web_dataflow.md) | **런타임 처리 흐름** 및 **병합 체계** 상세 |

---
*Last Updated: 2026-01-11*
*Version: 1.1*
