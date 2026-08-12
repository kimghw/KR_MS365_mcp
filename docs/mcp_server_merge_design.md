# MCP 서버 병합(Merge) 기능 설계서

> ⚠️ **2026-08-12 자로 REST 트랜스포트가 폐지되었습니다.** 본 문서의 REST 관련 서술
> (`server_rest.py`, `--protocol rest`, REST 선택지 등)은 작성 시점의 **이력으로만
> 유효**하며 현행 구조가 아닙니다. 지원 트랜스포트는 stdio 와 Streamable HTTP 2종이고,
> 현행 사양은 [spec/spec_MCP트랜스포트.md](../spec/spec_MCP트랜스포트.md) 입니다.

> **작성일**: 2026-01-10
> **상태**: 작성 완료
> **관련 파일**: `jinja/universal_server_template.jinja2`, `jinja/generate_universal_server.py`

---

## 1. 개요

### 1.1 목적
2개 이상의 MCP 서비스(예: outlook + calendar)를 하나의 통합 MCP 서버로 병합

### 1.2 기대 효과
- 단일 포트로 여러 서비스 제공
- 리소스(포트, 프로세스) 절약
- LLM 관점에서 통합된 도구 세트 제공

### 1.3 대상 서비스
- **outlook**: MailService (11개 서비스, mcp_server 존재)
- **calendar**: CalendarService (7개 서비스, **mcp_server 미존재**)

---

## 2. 현재 구조 분석

### 2.1 서비스 레이어 (`*_service.py`)

```
mcp_outlook/outlook_service.py          mcp_calendar/calendar_service.py
├─ MailService                          ├─ CalendarService
├─ @mcp_service 데코레이터               ├─ @mcp_service 데코레이터
└─ GraphMailClient 위임                  └─ GraphCalendarClient 위임
```

**특징:**
- 동일한 Facade 패턴 적용
- `@mcp_service` 데코레이터로 메타데이터 정의
- 독립적인 초기화/종료 라이프사이클

### 2.2 서버 레이어 (`server_*.py`)

```
mcp_outlook/mcp_server/
├─ server_rest.py      # REST API (FastAPI)
├─ server_stdio.py     # STDIO 프로토콜
└─ server_stream.py    # Streamable HTTP
```

**특징:**
- 단일 서비스만 import
- `tool_definition_templates.yaml`에서 도구 정의 로드
- `SERVICE_INSTANCES` 딕셔너리로 서비스 관리

### 2.3 Jinja 템플릿 구조 (다중 서비스 지원 확인)

`jinja/universal_server_template.jinja2:174-236`:

```jinja2
{# 이미 여러 서비스를 처리하는 반복문 구조 #}
{%- set unique_services = {} %}
{%- for service_name, service_info in services.items() %}
  ...
{%- endfor %}

# Import service classes (unique)
{%- for key, service_info in unique_services.items() %}
from {{ service_info.module_path }} import {{ service_info.class_name }}
{%- endfor %}

# Create service instances
{%- for key, service_info in unique_services.items() %}
{{ service_info.instance }} = {{ service_info.class_name }}()
{%- endfor %}

SERVICE_INSTANCES = {
{%- for key, service_info in unique_services.items() %}
    "{{ service_info.class_name }}": {{ service_info.instance }},
{%- endfor %}
}
```

**결론**: 템플릿은 이미 다중 서비스를 지원하는 구조

---

## 3. 핵심 병목 지점 분석

> 템플릿은 다중 서비스를 지원하지만, **입력 데이터 준비 파이프라인**에 단일 서버 전제가 있음

### 3.1 YAML 로딩 (단일 파일 전제)

**위치**: `universal_server_template.jinja2:101-132`

```python
def _load_mcp_tools() -> List[Dict[str, Any]]:
    yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_{{ profile_name }}" / "tool_definition_templates.yaml"
```

| 문제 | 서버는 YAML **1개만** 로드 |
|------|---------------------------|
| 영향 | 런타임 merge 시 `handle_<tool>` 핸들러 누락으로 `tools/call` 실패 |
| **해결** | 통합 서버용 **merged YAML 1개 생성** (빌드 타임 병합) |

### 3.2 레지스트리 (단일 서버 전제)

**위치**: `generate_universal_server.py:1014-1029`

```python
def find_registry_file(server_name: str) -> Optional[str]:
    candidates = [
        PROJECT_ROOT / "mcp_editor" / "mcp_service_registry" / f"registry_{server_name}.json",
    ]
```

| 문제 | `server_name` 1개에 대한 registry만 탐색 |
|------|----------------------------------------|
| **해결** | 통합 서버용 `registry_merged_server.json` 같은 **merge registry 생성** |

### 3.3 module_path 정규화 문제

**현재 레지스트리 값**:

| 서버 | module_path |
|------|-------------|
| outlook | `outlook.outlook_service` |
| calendar | `calendar.calendar_service` |

**템플릿 처리** (`universal_server_template.jinja2:199-203`):

```jinja2
{%- if not service_info.module_path.startswith('mcp_') %}
from mcp_{{ server_name }}.{{ module_name }} import {{ service_info.class_name }}
```

| 문제 | 통합 서버명이 `merged_server`면 `from mcp_merged_server.outlook_service`가 되어 **import 실패** |
|------|--------------------------------------------------------------------------------|
| **해결** | 통합 registry 생성 시 module_path 정규화: `mcp_outlook.outlook_service` |

### 3.4 타입 import 스캔 (단일 서버만 탐색)

**위치**: `generate_universal_server.py:399-414`

```python
def find_type_locations(server_name: str) -> Dict[str, str]:
    search_paths = [
        PROJECT_ROOT / f"mcp_{server_name}" / "*.py",  # 단일 서버만 스캔
    ]
```

| 문제 | `ms365` 같은 composite면 calendar 타입 누락 |
|------|-------------------------------------------|
| 누락 타입 | `EventFilterParams`, `EventSelectParams`, `DateTimeTimeZone` 등 |
| **해결** | registry module_path에서 **mcp_* 패키지들 추출 → 멀티 루트 스캔** |

### 3.5 도구 이름 충돌 가능성

**calendar 도구명** (`tool_definition_templates.yaml:79`):

```yaml
- name: get_event
- name: create_event
- name: update_event
- name: delete_event
```

| 문제 | 일반적인 이름으로 2개 이상 서비스 통합 시 충돌/혼선 |
|------|------------------------------------------------|
| **해결 옵션** | 1) prefix 정책: `calendar_get_event` 2) 충돌 없으면 유지 |

### 3.6 mcp_calendar 서버 생성물 미존재

```bash
$ ls mcp_calendar/
calendar_service.py  calendar_types.py  graph_calendar_client.py  ...
# mcp_server/ 폴더 없음!
```

| 문제 | calendar 단독 실행 불가 |
|------|------------------------|
| **결론** | 통합은 **새 서버 생성** 또는 **outlook에 calendar 추가** 형태가 자연스러움 |

---

## 4. 통합 방안

### 4.1 방안 1: Service 공유 (권장)

기존 `*_service.py` 코드 변경 없이 여러 서비스를 import

```python
# 통합 서버 (server_rest.py)
from mcp_outlook.outlook_service import MailService
from mcp_calendar.calendar_service import CalendarService

mail_service = MailService()
calendar_service = CalendarService()

SERVICE_INSTANCES = {
    "MailService": mail_service,
    "CalendarService": calendar_service,
}
```

**장점:**
- 기존 서비스 코드 재사용
- 각 서비스 독립성 유지
- 구현 복잡도 낮음

### 4.2 방안 2: Server 결합 (완전 통합)

여러 YAML 파일을 병합하여 단일 도구 세트 구성

```python
def _load_mcp_tools() -> List[Dict[str, Any]]:
    """여러 YAML에서 tools 병합"""
    all_tools = []
    yaml_paths = [
        "mcp_editor/mcp_outlook/tool_definition_templates.yaml",
        "mcp_editor/mcp_calendar/tool_definition_templates.yaml",
    ]
    for yaml_path in yaml_paths:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
            all_tools.extend(data.get("tools", []))
    return all_tools
```

---

## 5. 데이터 흐름

```
┌─────────────────────────────────────────────────────────────┐
│                      Merge 프로세스                          │
└─────────────────────────────────────────────────────────────┘

Step 1: YAML 병합
┌─────────────────┐    ┌─────────────────┐
│ mcp_outlook/    │    │ mcp_calendar/   │
│ tool_definition │ +  │ tool_definition │
│ _templates.yaml │    │ _templates.yaml │
└────────┬────────┘    └────────┬────────┘
         │                      │
         └──────────┬───────────┘
                    ▼
         ┌─────────────────────────┐
         │ mcp_merged_server/      │
         │ tool_definition_        │
         │ templates.yaml          │
         │ (병합된 tools 배열)      │
         └─────────────────────────┘

Step 2: 서비스 Import 통합
┌─────────────────────────────────────────────────────────┐
│ server_rest.py                                          │
│                                                         │
│ from mcp_outlook.outlook_service import MailService     │
│ from mcp_calendar.calendar_service import CalendarService│
│                                                         │
│ SERVICE_INSTANCES = {                                   │
│     "MailService": mail_service,                        │
│     "CalendarService": calendar_service,                │
│ }                                                       │
└─────────────────────────────────────────────────────────┘

Step 3: editor_config.json 업데이트
{
    "merged_server": {
        "source_dir": "../mcp_merged_server",
        "template_definitions_path": "mcp_merged_server/tool_definition_templates.yaml",
        "tool_definitions_path": "../mcp_merged_server/mcp_server/tool_definitions.py",
        "backup_dir": "mcp_merged_server/backups",
        "host": "0.0.0.0",
        "port": 8090,
        "is_merged": true,
        "source_profiles": ["outlook", "calendar"],
        "types_files": [
            "../mcp_outlook/outlook_types.py",
            "../mcp_calendar/calendar_types.py"
        ]
    }
}
```

---

## 6. UI 설계

### 6.1 버튼 추가 위치

`mcp_editor/templates/tool_editor.html`의 header-buttons 영역:

```html
<button class="btn btn-tooltip btn-expandable" data-debug-id="BTN_MERGE_SERVERS"
        onclick="showMergeServersModal()"
        style="background: linear-gradient(135deg, #0ea5e9, #0284c7); color: white;"
        data-tooltip="🔗 여러 MCP 서버 병합&#10;📁 outlook + calendar → merged_server&#10;⚙️ 도구 충돌 자동 처리">
    <span class="material-icons">merge_type</span>
    <span class="btn-text">Merge</span>
</button>
```

### 6.2 Merge 모달 UI

```
┌─────────────────────────────────────────────────────────────┐
│  🔗 Merge MCP Servers                                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Merged Server Name *                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ productivity                                         │   │
│  └─────────────────────────────────────────────────────┘   │
│  (예: productivity, unified, merged_server)                  │
│                                                             │
│  Source Profiles *                                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ☑ outlook    ☑ calendar    ☐ file_handler          │   │
│  └─────────────────────────────────────────────────────┘   │
│  (2개 이상 선택)                                             │
│                                                             │
│  Port                                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 8090                                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Tool Name Prefix Mode                                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Auto (prefix only on conflict)               ▼      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Protocol                                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ All (Stdio, Streamable HTTP)                 ▼      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                         [Cancel]  [🔗 Merge Servers]         │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. 백엔드 API 설계

### 7.1 병합 API

**파일**: `mcp_editor/tool_editor_core/routes/server_routes.py`

```python
@server_bp.route("/api/merge-servers", methods=["POST"])
def merge_servers():
    """
    여러 프로필을 하나의 통합 MCP 서버로 병합

    Request:
    {
        "name": "merged_server",
        "sources": ["outlook", "calendar"],
        "port": 8090,
        "prefix_mode": "auto",  # auto, always, none
        "protocol": "all"       # all, stdio, stream
    }

    Response:
    {
        "success": true,
        "merged_name": "merged_server",
        "tool_count": 15,
        "service_count": 10,
        "types_count": 30
    }
    """
```

### 7.2 서버 생성 로직 확장

**파일**: `jinja/generate_universal_server.py`

```python
def generate_merged_server(
    merged_name: str,
    source_profiles: List[str],
    port: int = 8080,
    protocol: str = 'all',
    prefix_mode: str = 'auto'
):
    """
    여러 프로필을 병합하여 통합 MCP 서버 생성

    구현된 함수:
    - merge_tool_definitions(): YAML 도구 정의 병합
    - normalize_module_path(): 모듈 경로 정규화
    - merge_registries(): 서비스 레지스트리 병합
    - find_type_locations_multi(): 멀티 루트 타입 스캔
    - check_tool_name_conflicts(): 도구 이름 충돌 검사
    - save_merged_yaml(): 병합된 YAML 저장
    - save_merged_registry(): 병합된 레지스트리 저장
    - update_editor_config_for_merge(): editor_config.json 업데이트
    """
```

### 7.3 CLI 명령어

```bash
# 병합 명령어 사용법
python jinja/generate_universal_server.py merge \
    --name <병합서버명> \
    --sources <프로필1>,<프로필2>[,...] \
    --port <포트> \
    --protocol <all|stdio|stream> \
    --prefix-mode <auto|always|none>

# 예시
python jinja/generate_universal_server.py merge \
    --name productivity \
    --sources outlook,calendar \
    --port 8090 \
    --protocol all \
    --prefix-mode auto
```

---

## 8. 호환성 분석

### 8.1 기존 기능 영향도

| 구분 | 단일 서비스 (현재) | 다중 서비스 (병합) | 영향 |
|------|-------------------|-------------------|------|
| `services` 딕셔너리 | 1개 항목 | 2개+ 항목 | 없음 |
| `tools` 리스트 | N개 | N+M개 | 없음 |
| Jinja 반복문 | 1회 실행 | 2회+ 실행 | 없음 |
| **템플릿 코드** | **동일** | **동일** | **없음** |

### 8.2 수정 범위

```
┌─────────────────────────────────────────────────────────┐
│                    영향 범위                             │
├─────────────────────────────────────────────────────────┤
│  ✅ universal_server_template.jinja2  → 수정 없음       │
│  ✅ 기존 서버 생성 흐름              → 영향 없음        │
│  ✅ editor_config.json 기존 항목     → 변경 없음        │
├─────────────────────────────────────────────────────────┤
│  📝 generate_universal_server.py     → 함수 추가 필요   │
│  📝 profile_routes.py                → API 추가 필요    │
│  📝 tool_editor.html                 → 모달 추가 필요   │
│  📝 editor_config.json               → 새 항목만 추가   │
└─────────────────────────────────────────────────────────┘
```

**결론**: 기존 기능 100% 유지, 새 병합 기능만 추가

---

## 9. 구현 작업 목록

### 9.1 우선순위별 작업 (병목 해결 중심)

| 순서 | 작업 | 해결 병목 | 파일 | 복잡도 |
|------|------|----------|------|--------|
| 1 | **YAML 병합 함수** | 3.1 YAML 단일 파일 | `generate_universal_server.py` | 낮음 |
| 2 | **Registry 병합 + module_path 정규화** | 3.2, 3.3 | `generate_universal_server.py` | 중간 |
| 3 | **타입 스캔 멀티 루트 지원** | 3.4 타입 누락 | `generate_universal_server.py` | 중간 |
| 4 | 도구명 prefix 정책 (선택) | 3.5 이름 충돌 | YAML 병합 시 적용 | 낮음 |
| 5 | CLI 명령 추가 | - | `generate_universal_server.py` | 낮음 |
| 6 | Web UI (선택) | - | `tool_editor.html`, `profile_routes.py` | 높음 |

### 9.2 CLI 우선 구현 (권장)

```bash
# 병합 서버 생성 CLI
python jinja/generate_universal_server.py merge \
    --name ms365 \
    --sources outlook,calendar \
    --port 8090 \
    --protocol all \
    --prefix auto  # calendar_ prefix 자동 추가 (선택)
```

### 9.3 테스트 시나리오

1. **단일 서버 생성 (기존)**: outlook 프로필로 서버 생성 → 기존과 동일 동작 확인
2. **병합 서버 생성 (신규)**: outlook + calendar 병합 → ms365 서버 생성
3. **병합 서버 실행**: ms365 서버 시작 → 두 서비스의 도구 모두 사용 가능 확인
4. **도구 호출 테스트**: Mail 도구와 Calendar 도구 각각 호출 성공 확인

---

## 10. 구현 시 발생한 문제 및 해결

### 10.1 웹에디터 시작 시 병합 레지스트리 덮어쓰기

**문제 상황:**
- 웹에디터(`tool_editor_web`) 시작 시 `scan_all_registries()` 함수가 모든 프로필의 레지스트리를 재스캔
- ms365 같은 병합 프로필은 자체 `*_service.py` 파일이 없음
- 스캔 결과 `services: {}` (0개)로 병합 레지스트리가 덮어써짐
- 결과: 웹에디터에서 ms365 프로필이 "fail to load"

**해결 방안:**
- `service_registry.py`의 `scan_all_registries()` 함수에서 `is_merged` 프로필 건너뛰기

```python
# mcp_editor/tool_editor_core/service_registry.py:76-80
for profile_name, profile_config in config.items():
    # Skip merged profiles - they don't have their own service files
    if profile_config.get("is_merged"):
        print(f"  Skipping {profile_name}: merged profile (registry preserved)")
        continue
```

**결과:** 웹에디터 시작 시 병합 레지스트리 보존 확인

---

### 10.2 editor_config.json 필수 필드 누락

**문제 상황:**
- 초기 `update_editor_config_for_merge()` 함수가 최소 필드만 생성
- 누락된 필드: `template_definitions_path`, `tool_definitions_path`, `backup_dir`, `host`
- 결과: 웹에디터에서 도구 로딩 실패 (잘못된 경로 참조)

**해결 방안:**
- 병합 프로필 생성 시 모든 필수 필드 포함

```python
# jinja/generate_universal_server.py:1377-1390
merged_config = {
    "source_dir": f"../mcp_{merged_name}",
    "template_definitions_path": f"mcp_{merged_name}/tool_definition_templates.yaml",
    "tool_definitions_path": f"../mcp_{merged_name}/mcp_server/tool_definitions.py",
    "backup_dir": f"mcp_{merged_name}/backups",
    "host": "0.0.0.0",
    "port": port,
    "is_merged": True,
    "source_profiles": source_profiles,
    "types_files": unique_types_files
}
```

**결과:** ms365 프로필 13개 도구 정상 로딩 확인

---

### 10.3 병합 서버 Web UI

**구현 내용:**
- 웹에디터 헤더에 "Merge" 버튼 추가 (파란색 그라디언트)
- 병합 모달 UI 구현 (프로필 선택, 포트, prefix 모드, 프로토콜)
- `/api/merge-servers` API 엔드포인트 추가

**구현 파일:**
- `mcp_editor/templates/tool_editor.html` - Merge 버튼 및 모달
- `mcp_editor/static/js/tool_editor_derive.js` - `showMergeServersModal()`, `executeMergeServers()`
- `mcp_editor/tool_editor_core/routes/server_routes.py` - `/api/merge-servers` API

**사용 방법:**

1. **CLI 방식:**
```bash
python jinja/generate_universal_server.py merge \
    --name merged_server \
    --sources outlook,calendar \
    --port 8090 \
    --protocol all \
    --prefix-mode auto
```

2. **Web UI 방식:**
   - 웹에디터 헤더의 "Merge" 버튼 클릭
   - 병합 서버 이름 입력 (예: `productivity`, `unified`)
   - 병합할 프로필 2개 이상 선택
   - 포트, prefix 모드, 프로토콜 설정
   - "Merge Servers" 버튼 클릭

---

### 10.4 병합 프로필 서비스 드롭다운 그룹화

**문제 상황:**
- 병합된 프로필(예: outlook + calendar)에서 서비스 선택 시 모든 서비스가 flat하게 나열
- 어떤 서비스가 어느 소스에서 왔는지 구분 어려움

**해결 방안:**
- API 응답에 `groups` 정보 추가 (class_name 기준 그룹화)
- 프론트엔드에서 `<optgroup>` 사용하여 서비스 그룹별 표시

**구현 파일:**
- `mcp_editor/tool_editor_core/routes/registry_routes.py` - `groups` 필드 추가
- `mcp_editor/static/js/tool_editor_tools.js` - 그룹 정보 저장
- `mcp_editor/static/js/tool_editor_render.js` - `<optgroup>` 렌더링

**결과:** 병합 프로필에서 서비스가 클래스별로 그룹화되어 표시
```
┌─────────────────────────────────┐
│ -- Select MCP Service Method -- │
├─────────────────────────────────┤
│ MailService                     │
│   query_mail_list               │
│   fetch_and_process             │
│   ...                           │
├─────────────────────────────────┤
│ CalendarService                 │
│   list_events                   │
│   calendar_view                 │
│   ...                           │
└─────────────────────────────────┘
```

---

### 10.5 병합 프로필 서버명 매핑

**목적:** 병합 프로필에서 서비스 레지스트리를 정상 조회하기 위한 서버명 매핑 로직

**대상 파일:** `mcp_editor/tool_editor_web_server_mappings.py`

**매핑 규칙:**

| 프로필 유형 | 조건 | 서버명 반환값 |
|------------|------|--------------|
| 병합 프로필 | `is_merged: true` | 프로필명 자체 (예: `test2` → `test2`) |
| 파생 프로필 | `is_reused: true` | `base_profile` 값 (예: `outlook_test` → `outlook`) |
| 일반 프로필 | `SERVER_NAMES` 포함 | 매칭된 서버명 (예: `outlook` → `outlook`) |

**함수 구조:**

```python
def get_server_name_from_profile(profile: str) -> str | None:
    # 1. editor_config.json 로드
    config = _load_editor_config()

    # 2. 병합 프로필 확인 → 프로필명 반환
    if config[profile].get("is_merged"):
        return profile

    # 3. 파생 프로필 확인 → base_profile 반환
    if config[profile].get("is_reused"):
        return config[profile]["base_profile"]

    # 4. SERVER_NAMES 리스트에서 매칭
    for server_name in SERVER_NAMES:
        if server_name in profile:
            return server_name

    return None
```

**레지스트리 파일 경로:**
- 병합: `mcp_service_registry/registry_{profile}.json` (예: `registry_test2.json`)
- 일반: `mcp_service_registry/registry_{server_name}.json` (예: `registry_outlook.json`)

---

### 10.6 도구 정의 템플릿 구조

**목적:** YAML을 단일 소스(Single Source of Truth)로 사용하여 도구 정의 일관성 유지

**파일 구조:**

```
mcp_editor/mcp_{profile}/
├── tool_definition_templates.yaml   # 실제 도구 정의 (수정 대상)
└── tool_definition_templates.py     # YAML 로더 래퍼 (수정 불필요)
```

**tool_definition_templates.py 표준 형식:**

```python
from typing import List, Dict, Any
from pathlib import Path
import yaml

def _load_tools_from_yaml() -> List[Dict[str, Any]]:
    yaml_path = Path(__file__).parent / "tool_definition_templates.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("tools", [])

MCP_TOOLS: List[Dict[str, Any]] = _load_tools_from_yaml()
```

**작업 지침:**
1. 새 프로필 생성 시 위 `.py` 파일을 복사하여 사용
2. 도구 정의 수정은 `.yaml` 파일에서만 수행
3. `.py` 파일은 수정하지 않음

---

## 11. 고려사항

### 11.1 도구 이름 충돌
- 병합 시 동일한 도구 이름이 있으면 충돌 발생
- **해결책**: 접두사 자동 추가 옵션 (`mail_list`, `calendar_list`)

### 11.2 서비스 초기화 순서
- 여러 서비스의 `initialize()` 호출 순서 관리 필요
- **해결책**: 순차 초기화 또는 병렬 초기화 옵션

### 11.3 에러 격리
- 한 서비스 오류가 다른 서비스에 영향 주지 않도록
- **해결책**: 각 서비스별 try-except 처리

---

## 12. 향후 확장

1. **동적 서비스 로딩**: 런타임에 서비스 추가/제거
2. **서비스 의존성**: 서비스 간 의존 관계 정의
3. **분할 기능**: 병합된 서버를 다시 개별 서버로 분할
4. **Web UI 병합 기능**: CLI 외에 웹 인터페이스에서 병합 서버 생성 (Section 6, 10.3 참조)
5. **병합 서버 수정**: 기존 병합 서버에 프로필 추가/제거
6. **병합 미리보기**: 병합 전 도구 충돌, 타입 충돌 미리 확인

---

*Last Updated: 2026-01-11*
