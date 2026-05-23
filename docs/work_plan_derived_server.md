# MCP 파생 서버 생성 및 도구 이동 기능 작업 계획서

## 1. 프로젝트 목표

### 1.1 핵심 요구사항

| 번호 | 요구사항 | 설명 |
|:---:|---------|------|
| R1 | **동일 서비스 기반 파생 서버 생성** | 기존 MCP 서버의 서비스를 공유하면서 별도의 MCP 서버를 생성 |
| R2 | **서비스 경로 공유** | `source_dir`, `types_files`는 base 서버와 동일하게 유지 |
| R3 | **템플릿 경로 분리** | `template_definitions_path`, `tool_definitions_path`만 새 서버명 경로로 분리 |
| R4 | **초기 템플릿 복사** | 파생 서버 생성 시 base 서버의 `tool_definition_templates`를 복사 |
| R5 | **독립 운영** | 생성 후에는 별도 서버로 운영, 서비스만 공유 |
| R6 | **도구 이동 기능** | 동일 base를 공유하는 서버 간 도구를 자동으로 이동/복사 |

### 1.2 목표 구조 예시

```
[생성 전]
mcp_outlook/                     ← base 서비스
├── outlook_service.py
├── outlook_types.py
└── mcp_server/

mcp_editor/
├── editor_config.json
└── mcp_outlook/
    └── tool_definition_templates.yaml

[생성 후: outlook_read 파생 서버 추가]
mcp_outlook/                     ← 서비스 공유 (변경 없음)
├── outlook_service.py
├── outlook_types.py
└── mcp_server/

mcp_outlook_read/                ← 새 파생 서버
└── mcp_server/
    └── tool_definitions.py

mcp_editor/
├── editor_config.json           ← outlook_read 프로필 추가
├── mcp_outlook/
│   └── tool_definition_templates.yaml
└── mcp_outlook_read/            ← 새 프로필 폴더
    └── tool_definition_templates.yaml  ← base에서 복사
```

### 1.3 editor_config.json 목표 구조

```json
{
  "outlook": {
    "source_dir": "../mcp_outlook",
    "template_definitions_path": "mcp_outlook/tool_definition_templates.yaml",
    "tool_definitions_path": "../mcp_outlook/mcp_server/tool_definitions.py",
    "types_files": ["../mcp_outlook/outlook_types.py"],
    "is_base": true,
    "derived_profiles": ["outlook_read", "outlook_write"]
  },
  "outlook_read": {
    "source_dir": "../mcp_outlook",                    // ← base와 동일
    "template_definitions_path": "mcp_outlook_read/tool_definition_templates.yaml",
    "tool_definitions_path": "../mcp_outlook_read/mcp_server/tool_definitions.py",
    "types_files": ["../mcp_outlook/outlook_types.py"], // ← base와 동일
    "base_profile": "outlook",                          // ← 신규 필드
    "is_reused": true
  }
}
```

---

## 2. 현재 구현 상태 분석

### 2.1 웹에디터 구조 (리팩토링 완료)

```
mcp_editor/
├── tool_editor_web.py              ← 진입점 (래퍼)
├── tool_editor_core/               ← 핵심 모듈 (리팩토링됨)
│   ├── app.py                      ← Flask 팩토리
│   ├── config.py                   ← 설정 관리
│   ├── profile_management.py       ← 프로필 생성/삭제/재사용
│   ├── tool_loader.py              ← 도구 로딩
│   ├── tool_saver.py               ← 도구 저장
│   ├── schema_utils.py             ← JSON 스키마 처리
│   ├── backup_utils.py             ← 백업 관리
│   ├── service_registry.py         ← 서비스 레지스트리
│   └── routes/
│       ├── tool_routes.py          ← 도구 CRUD API
│       ├── profile_routes.py       ← 프로필 관리 API
│       ├── backup_routes.py        ← 백업 API
│       ├── server_routes.py        ← 서버 제어 API
│       ├── generator_routes.py     ← 서버 생성 API
│       └── ...
├── templates/
│   └── tool_editor.html            ← 메인 UI
└── static/js/
    └── tool_editor_*.js            ← 12개 모듈
```

### 2.2 이미 구현된 기능

| 기능 | 파일 | 함수/엔드포인트 | 상태 |
|-----|------|----------------|------|
| 프로필 재사용 생성 | `profile_management.py` | `create_reused_profile()` | ✅ 구현됨 |
| YAML 템플릿 복사 | `profile_management.py` | `copy_yaml_templates()` | ✅ 구현됨 |
| editor_config 업데이트 | `profile_management.py` | `update_editor_config_for_reuse()` | ✅ 구현됨 |
| 프로젝트 폴더 생성 | `profile_management.py` | `create_server_project_folder()` | ✅ 구현됨 |
| `is_reused` 플래그 | `editor_config.json` | - | ✅ 구현됨 |
| 재사용 API | `profile_routes.py` | `POST /api/create-mcp-project-reuse` | ✅ 구현됨 |

### 2.3 추가 구현 필요 항목

| 기능 | 현재 상태 | 필요 작업 |
|-----|----------|----------|
| `base_profile` 필드 | ❌ 없음 | 스키마 확장 필요 |
| `is_base` 플래그 | ❌ 없음 | 스키마 확장 필요 |
| `derived_profiles` 목록 | ❌ 없음 | 스키마 확장 필요 |
| 도구 이동/복사 | ❌ 없음 | 신규 구현 필요 |
| Sibling 프로필 조회 | ❌ 없음 | 신규 API 필요 |
| 파생 관계 UI 표시 | ❌ 없음 | 프론트엔드 개선 필요 |

---

## 3. 구현 계획

### Phase 1: editor_config.json 스키마 확장

**목표**: 파생 서버의 base 관계를 명시적으로 표현

#### 1.1 스키마 변경

**수정 파일**: [config.py](../mcp_editor/tool_editor_core/config.py)

```python
# 프로필 설정 스키마 확장
PROFILE_SCHEMA = {
    "source_dir": str,              # 서비스 소스 경로
    "template_definitions_path": str,
    "tool_definitions_path": str,
    "types_files": list,
    "host": str,
    "port": int,
    # 신규 필드
    "is_base": bool,                # base 서버 여부 (기본: True)
    "base_profile": str,            # 파생 시 base 프로필명 (선택)
    "derived_profiles": list,       # 파생 프로필 목록 (선택)
    "is_reused": bool,              # 기존 필드 유지 (호환성)
}
```

#### 1.2 마이그레이션 함수

**수정 파일**: [config.py](../mcp_editor/tool_editor_core/config.py)

```python
def migrate_config_schema(config: dict) -> dict:
    """
    기존 설정을 새 스키마로 마이그레이션

    - is_reused=True인 프로필에 base_profile 추출
    - base 프로필에 is_base=True, derived_profiles 추가
    """
```

#### 1.3 헬퍼 함수 추가

**수정 파일**: [config.py](../mcp_editor/tool_editor_core/config.py)

```python
def get_base_profile(profile_name: str) -> str | None:
    """프로필의 base 프로필 반환 (없으면 None)"""

def get_derived_profiles(profile_name: str) -> list[str]:
    """프로필의 파생 프로필 목록 반환"""

def get_sibling_profiles(profile_name: str) -> list[str]:
    """동일 base를 공유하는 형제 프로필 목록 반환"""

def is_base_profile(profile_name: str) -> bool:
    """base 프로필 여부 확인"""
```

---

### Phase 2: 파생 서버 생성 기능 개선

**목표**: 기존 `create_reused_profile()` 함수를 확장하여 base 관계 관리

#### 2.1 profile_management.py 개선

**수정 파일**: [profile_management.py](../mcp_editor/tool_editor_core/profile_management.py)

```python
def create_derived_profile(
    base_profile: str,
    new_profile_name: str,
    port: int = 5001
) -> dict:
    """
    base 프로필 기반 파생 프로필 생성 (기존 함수 확장)

    작업 순서:
    1. base_profile 유효성 검증
    2. 기존 create_reused_profile() 호출
    3. base_profile 필드 설정
    4. base 프로필의 derived_profiles에 추가
    5. is_base 플래그 설정

    반환: {
        "success": bool,
        "profile_name": str,
        "base_profile": str,
        "editor_dir": str,
        "project_dir": str
    }
    """

def update_base_derived_relationship(base_profile: str, derived_profile: str):
    """
    base-derived 관계 업데이트

    - base 프로필에 derived_profiles 추가
    - base 프로필에 is_base=True 설정
    """

def remove_from_derived_list(base_profile: str, derived_profile: str):
    """
    파생 프로필 삭제 시 base의 derived_profiles에서 제거
    """
```

#### 2.2 API 엔드포인트 추가

**수정 파일**: [profile_routes.py](../mcp_editor/tool_editor_core/routes/profile_routes.py)

```python
@bp.post("/api/profiles/derive")
def derive_profile():
    """
    파생 프로필 생성 API

    Request:
    {
        "base_profile": "outlook",
        "new_profile_name": "outlook_read",
        "port": 8092,
        "description": "읽기 전용 Outlook 도구"  # 선택
    }

    Response:
    {
        "success": true,
        "profile": {
            "name": "outlook_read",
            "base_profile": "outlook",
            "editor_dir": "mcp_editor/mcp_outlook_read",
            "project_dir": "mcp_outlook_read"
        }
    }
    """

@bp.get("/api/profiles/<profile>/siblings")
def get_sibling_profiles(profile: str):
    """
    동일 base를 공유하는 형제 프로필 목록

    Response:
    {
        "profile": "outlook_read",
        "base_profile": "outlook",
        "siblings": ["outlook", "outlook_write"],
        "is_base": false
    }
    """

@bp.get("/api/profiles/<profile>/family")
def get_profile_family(profile: str):
    """
    프로필의 전체 가족 관계 조회

    Response:
    {
        "base": "outlook",
        "derived": ["outlook_read", "outlook_write"],
        "current": "outlook_read"
    }
    """
```

---

### Phase 3: 도구 이동/복사 기능 구현

**목표**: 동일 base를 공유하는 서버 간 도구 교환

#### 3.1 신규 모듈 생성

**신규 파일**: [tool_mover.py](../mcp_editor/tool_editor_core/tool_mover.py)

```python
"""
도구 이동/복사 모듈

동일 base_profile을 공유하는 프로필 간 도구 이동/복사 기능 제공
"""

from typing import Literal

class ToolMover:
    def __init__(self):
        self.config = load_editor_config()

    def validate_move(
        self,
        source_profile: str,
        target_profile: str,
        tool_indices: list[int]
    ) -> dict:
        """
        이동 가능 여부 검증

        검증 항목:
        - source와 target이 동일 base_profile 공유
        - tool_indices가 유효한 범위
        - 도구의 mcp_service가 target에서 사용 가능

        반환: {
            "valid": bool,
            "errors": list[str],
            "warnings": list[str]
        }
        """

    def move_tools(
        self,
        source_profile: str,
        target_profile: str,
        tool_indices: list[int],
        mode: Literal["move", "copy"] = "move"
    ) -> dict:
        """
        도구 이동/복사 수행

        작업 순서:
        1. validate_move() 호출
        2. 소스 YAML 로드
        3. 지정된 도구들 추출
        4. 타겟 YAML 로드
        5. 도구 추가 (중복 이름 처리)
        6. mode가 "move"면 소스에서 삭제
        7. 양쪽 YAML 저장
        8. 백업 생성

        반환: {
            "success": bool,
            "moved_tools": list[str],  # 이동된 도구 이름들
            "source_backup": str,
            "target_backup": str
        }
        """

    def get_movable_tools(
        self,
        source_profile: str,
        target_profile: str
    ) -> list[dict]:
        """
        이동 가능한 도구 목록 조회

        반환: [
            {
                "index": 0,
                "name": "mail_list",
                "can_move": true,
                "reason": null
            },
            {
                "index": 1,
                "name": "mail_send",
                "can_move": false,
                "reason": "서비스 미지원"
            }
        ]
        """

    def _handle_duplicate_name(
        self,
        tool: dict,
        existing_tools: list[dict]
    ) -> dict:
        """
        중복 이름 처리 (예: mail_list -> mail_list_2)
        """
```

#### 3.2 API 엔드포인트 추가

**수정 파일**: [tool_routes.py](../mcp_editor/tool_editor_core/routes/tool_routes.py)

```python
@bp.post("/api/tools/move")
def move_tools():
    """
    도구 이동/복사 API

    Request:
    {
        "source_profile": "outlook",
        "target_profile": "outlook_read",
        "tool_indices": [0, 2, 5],
        "mode": "move"  // 또는 "copy"
    }

    Response:
    {
        "success": true,
        "moved_tools": ["mail_list", "mail_read", "mail_search"],
        "source_count": 7,   // 이동 후 소스 도구 수
        "target_count": 5    // 이동 후 타겟 도구 수
    }
    """

@bp.post("/api/tools/validate-move")
def validate_move():
    """
    이동 가능 여부 사전 검증 API

    Request:
    {
        "source_profile": "outlook",
        "target_profile": "outlook_read",
        "tool_indices": [0, 2, 5]
    }

    Response:
    {
        "valid": true,
        "movable": [0, 2, 5],
        "warnings": ["도구 'mail_list'가 타겟에 이미 존재합니다. 이름이 변경됩니다."]
    }
    """

@bp.get("/api/tools/movable")
def get_movable_tools():
    """
    이동 가능한 도구 목록 조회 API

    Query params:
    - source: 소스 프로필
    - target: 타겟 프로필

    Response:
    {
        "tools": [
            {"index": 0, "name": "mail_list", "can_move": true},
            {"index": 1, "name": "mail_send", "can_move": true}
        ]
    }
    """
```

---

### Phase 4: 서버 생성 시 base 프로필 참조

**목표**: 파생 서버 생성 시 올바른 서비스 import 경로 사용

#### 4.1 서버 생성기 수정

**수정 파일**: [generate_universal_server.py](../jinja/generate_universal_server.py)

```python
def resolve_service_paths(profile_name: str, config: dict) -> dict:
    """
    파생 프로필인 경우 base 프로필의 서비스 경로 사용

    반환:
    {
        "source_dir": base의 source_dir,
        "types_files": base의 types_files,
        "service_module": base 서비스 모듈 경로,
        "tool_definitions": 현재 프로필의 경로
    }
    """

def generate_server_for_profile(
    profile_name: str,
    protocol_type: str = "rest"
) -> str:
    """
    프로필에 맞는 서버 코드 생성

    - base_profile 있으면 서비스 경로는 base 사용
    - tool_definitions는 현재 프로필 사용
    """
```

#### 4.2 Jinja 템플릿 수정

**수정 파일**: [universal_server_template.jinja2](../jinja/universal_server_template.jinja2)

```jinja2
{# 서비스 import - base_profile 존재 시 base 경로 사용 #}
{% if base_source_module %}
# 파생 서버: {{ profile_name }} (base: {{ base_profile }})
from {{ base_source_module }} import {{ service_imports }}
{% else %}
# 기본 서버: {{ profile_name }}
from {{ source_module }} import {{ service_imports }}
{% endif %}

{# 도구 정의 - 항상 현재 프로필 사용 #}
TOOL_DEFINITIONS_PATH = "{{ tool_definitions_path }}"
```

---

### Phase 5: 프론트엔드 UI 개선

**목표**: 파생 관계 시각화 및 도구 이동 UI

#### 5.1 프로필 목록 개선

**수정 파일**: [tool_editor.html](../mcp_editor/templates/tool_editor.html)

```html
<!-- 프로필 트리 구조 표시 -->
<div class="profile-tree">
  <div class="profile-group" data-base="outlook">
    <div class="profile-item base" data-profile="outlook">
      <span class="icon">📦</span>
      <span class="name">outlook</span>
      <span class="badge">base</span>
    </div>
    <div class="profile-item derived" data-profile="outlook_read">
      <span class="indent">└─</span>
      <span class="name">outlook_read</span>
    </div>
    <div class="profile-item derived" data-profile="outlook_write">
      <span class="indent">└─</span>
      <span class="name">outlook_write</span>
    </div>
  </div>
</div>
```

#### 5.2 파생 서버 생성 모달

```html
<!-- 파생 서버 생성 버튼 -->
<button id="btn-derive-profile" class="btn btn-secondary">
  + 파생 서버 생성
</button>

<!-- 모달 -->
<div id="derive-modal" class="modal">
  <h3>파생 서버 생성</h3>
  <div class="form-group">
    <label>Base 프로필</label>
    <select id="derive-base">
      <!-- 동적으로 채워짐 -->
    </select>
  </div>
  <div class="form-group">
    <label>새 프로필명</label>
    <input type="text" id="derive-name" placeholder="outlook_read">
  </div>
  <div class="form-group">
    <label>포트</label>
    <input type="number" id="derive-port" value="8092">
  </div>
  <div class="actions">
    <button id="btn-derive-confirm">생성</button>
    <button id="btn-derive-cancel">취소</button>
  </div>
</div>
```

#### 5.3 도구 이동 UI

```html
<!-- 도구 목록에 체크박스 추가 -->
<div class="tool-item" data-index="0">
  <input type="checkbox" class="tool-select">
  <span class="tool-name">mail_list</span>
  <!-- ... -->
</div>

<!-- 도구 이동 버튼 (체크 시 활성화) -->
<button id="btn-move-tools" disabled>
  도구 이동/복사
</button>

<!-- 도구 이동 모달 -->
<div id="move-modal" class="modal">
  <h3>도구 이동/복사</h3>
  <div class="selected-tools">
    <p>선택된 도구: <span id="selected-count">3</span>개</p>
    <ul id="selected-tool-list">
      <!-- 동적으로 채워짐 -->
    </ul>
  </div>
  <div class="form-group">
    <label>대상 프로필</label>
    <select id="move-target">
      <!-- sibling 프로필만 표시 -->
    </select>
  </div>
  <div class="form-group">
    <label>모드</label>
    <div class="radio-group">
      <label>
        <input type="radio" name="move-mode" value="move" checked>
        이동 (원본에서 삭제)
      </label>
      <label>
        <input type="radio" name="move-mode" value="copy">
        복사 (원본 유지)
      </label>
    </div>
  </div>
  <div class="actions">
    <button id="btn-move-confirm">확인</button>
    <button id="btn-move-cancel">취소</button>
  </div>
</div>
```

#### 5.4 JavaScript 모듈 추가

**신규 파일**: [tool_editor_derive.js](../mcp_editor/static/js/tool_editor_derive.js)

```javascript
/**
 * 파생 서버 및 도구 이동 관련 기능
 */

// 파생 서버 생성
async function deriveProfile(baseProfile, newName, port) {
  const response = await fetch('/api/profiles/derive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      base_profile: baseProfile,
      new_profile_name: newName,
      port: port
    })
  });
  return response.json();
}

// 형제 프로필 조회
async function getSiblingProfiles(profile) {
  const response = await fetch(`/api/profiles/${profile}/siblings`);
  return response.json();
}

// 도구 이동
async function moveTools(sourceProfile, targetProfile, toolIndices, mode) {
  const response = await fetch('/api/tools/move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_profile: sourceProfile,
      target_profile: targetProfile,
      tool_indices: toolIndices,
      mode: mode
    })
  });
  return response.json();
}

// 이동 가능 여부 검증
async function validateMove(sourceProfile, targetProfile, toolIndices) {
  const response = await fetch('/api/tools/validate-move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_profile: sourceProfile,
      target_profile: targetProfile,
      tool_indices: toolIndices
    })
  });
  return response.json();
}
```

---

## 4. 파일 변경 요약

### 4.1 신규 파일

| 파일 | 설명 |
|-----|------|
| [tool_mover.py](../mcp_editor/tool_editor_core/tool_mover.py) | 도구 이동/복사 핵심 로직 |
| [tool_editor_derive.js](../mcp_editor/static/js/tool_editor_derive.js) | 파생 서버/도구 이동 UI 로직 |

### 4.2 수정 파일

| 파일 | 변경 내용 |
|-----|----------|
| [editor_config.json](../mcp_editor/editor_config.json) | `base_profile`, `is_base`, `derived_profiles` 필드 추가 |
| [config.py](../mcp_editor/tool_editor_core/config.py) | 스키마 확장, 헬퍼 함수 추가, 마이그레이션 |
| [profile_management.py](../mcp_editor/tool_editor_core/profile_management.py) | `create_derived_profile()`, 관계 관리 함수 |
| [profile_routes.py](../mcp_editor/tool_editor_core/routes/profile_routes.py) | `/derive`, `/siblings`, `/family` 엔드포인트 |
| [tool_routes.py](../mcp_editor/tool_editor_core/routes/tool_routes.py) | `/move`, `/validate-move`, `/movable` 엔드포인트 |
| [tool_editor.html](../mcp_editor/templates/tool_editor.html) | 프로필 트리, 파생 생성/도구 이동 모달 |
| [generate_universal_server.py](../jinja/generate_universal_server.py) | base_profile 참조 로직 |
| [universal_server_template.jinja2](../jinja/universal_server_template.jinja2) | base 서비스 import 처리 |

---

## 5. 구현 순서

```
Phase 1: 스키마 확장 (기반 작업)
    │
    ├── config.py 수정
    │   ├── PROFILE_SCHEMA 확장
    │   ├── migrate_config_schema()
    │   └── 헬퍼 함수들
    │
    └── editor_config.json 마이그레이션

    ↓

Phase 2: 파생 서버 생성 (핵심 기능)
    │
    ├── profile_management.py
    │   ├── create_derived_profile() 개선
    │   └── 관계 관리 함수들
    │
    └── profile_routes.py
        ├── POST /api/profiles/derive
        └── GET /api/profiles/{profile}/siblings

    ↓

Phase 4: 서버 생성 연계 (Phase 2와 연계)
    │
    ├── generate_universal_server.py
    │   └── resolve_service_paths()
    │
    └── universal_server_template.jinja2
        └── base_source_module 처리

    ↓

Phase 3: 도구 이동 기능 (독립 진행 가능)
    │
    ├── tool_mover.py (신규)
    │   ├── ToolMover 클래스
    │   └── validate_move(), move_tools()
    │
    └── tool_routes.py
        ├── POST /api/tools/move
        └── POST /api/tools/validate-move

    ↓

Phase 5: UI 개선 (최종 마무리)
    │
    ├── tool_editor.html
    │   ├── 프로필 트리 구조
    │   ├── 파생 생성 모달
    │   └── 도구 이동 모달
    │
    └── tool_editor_derive.js (신규)
        └── UI 이벤트 핸들러
```

---

## 6. 검증 시나리오

### 시나리오 1: 파생 서버 생성

```
[사전 조건]
- outlook 프로필 존재
- 도구 10개 정의됨

[실행]
1. 웹에디터에서 "파생 서버 생성" 클릭
2. Base 프로필: outlook 선택
3. 새 프로필명: outlook_read 입력
4. 포트: 8092 입력
5. "생성" 클릭

[검증]
✓ mcp_editor/mcp_outlook_read/ 폴더 생성됨
✓ tool_definition_templates.yaml 복사됨 (도구 10개)
✓ mcp_outlook_read/mcp_server/ 폴더 생성됨
✓ editor_config.json에 outlook_read 추가됨
  - source_dir: "../mcp_outlook" (base와 동일)
  - types_files: base와 동일
  - base_profile: "outlook"
✓ outlook 프로필에 derived_profiles: ["outlook_read"] 추가됨
✓ 웹에디터에서 outlook_read 프로필 선택 가능
```

### 시나리오 2: 도구 이동

```
[사전 조건]
- outlook 프로필: 도구 10개
- outlook_read 프로필: 도구 10개 (outlook에서 파생)

[실행]
1. outlook 프로필 선택
2. 도구 3개 체크박스 선택 (mail_list, mail_read, mail_search)
3. "도구 이동/복사" 클릭
4. 대상 프로필: outlook_read 선택
5. 모드: "이동" 선택
6. "확인" 클릭

[검증]
✓ outlook 프로필: 7개 도구 (3개 삭제됨)
✓ outlook_read 프로필: 13개 도구 (3개 추가됨)
✓ 양쪽 YAML 백업 생성됨
✓ 이동된 도구의 mcp_service 정보 유지됨
```

### 시나리오 3: 파생 서버 생성 및 실행

```
[사전 조건]
- outlook_read 프로필 생성됨 (base: outlook)

[실행]
1. outlook_read 프로필 선택
2. "서버 생성" 클릭
3. 프로토콜: REST 선택
4. "생성" 클릭
5. "서버 시작" 클릭

[검증]
✓ server_rest.py 생성됨 (mcp_outlook_read/mcp_server/)
✓ 서비스 import: from mcp_outlook.outlook_service import ...
✓ 도구 정의: mcp_outlook_read/tool_definition_templates.yaml 참조
✓ 서버 정상 시작됨 (포트 8092)
```

---

## 7. 주의사항

### 7.1 호환성

- 기존 `is_reused` 플래그 유지 (하위 호환)
- 마이그레이션 없이도 기존 설정 동작 보장
- 새 필드는 선택적 (optional)

### 7.2 에러 처리

- base 프로필 삭제 시 derived 프로필 처리 방안 필요
- 도구 이동 중 충돌 시 롤백 메커니즘
- 동시 수정 시 파일 락 고려

### 7.3 제약사항

- 도구 이동은 동일 base를 공유하는 프로필 간만 허용
- 순환 참조 방지 (파생의 파생 금지 또는 제한)
- 서비스 의존성 검증 필수

---

## 8. 향후 확장 고려사항

1. **도구 동기화**: base 프로필의 도구 변경 시 파생 프로필에 알림
2. **버전 관리**: 도구 정의의 버전 히스토리 관리
3. **권한 분리**: 프로필별 편집 권한 설정
4. **템플릿 상속**: 공통 도구 정의를 상속받는 구조

---

*작성일: 2026-01-10*
*버전: 1.0*
