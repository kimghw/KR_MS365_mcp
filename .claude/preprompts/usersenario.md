# 사용자 시나리오 기록

## 최근 세션 기록

### 2026-01-12: Java MCP 스킬 워크플로우 순서 변경 (Code-First)

#### 요청 사항
- Java mcp-setup-java 스킬의 워크플로우를 Python mcp-setup과 동일하게 **코드 우선(Code-First)**으로 변경
- YAML 먼저 → 코드 생성 → 비즈니스 로직 순서를 **비즈니스 로직 → 코드 분석 → YAML 생성** 순서로 변경
- `mcp_{server}` 폴더 명명 규칙 추가

#### 변경 전 워크플로우
1. `tool_definition_templates.yaml` 작성
2. `service_manifest.yaml` 작성
3. Java 서버 생성 (스텁 포함)
4. 비즈니스 로직 구현 (스텁에 채우기)

#### 변경 후 워크플로우 (Code-First)
1. **비즈니스 로직 구현** - `mcp_{server}/` 폴더에 `@McpTool`, `@McpParam` 어노테이션으로 Java 서비스 작성
2. **Java 코드 분석** - 어노테이션 스캔하여 툴 스키마 추출
3. **YAML 자동 생성** - `mcp_editor_java/mcp_{server}/`에 YAML 파일 생성
4. **MCP 서버 래퍼 생성** - 기존 Bean을 주입받는 MCP 래퍼 생성
5. **실행** - 서버 실행

#### 핵심 변경점
| 항목 | 변경 전 | 변경 후 |
|------|--------|--------|
| 워크플로우 | YAML 우선 | 코드 우선 (Code-First) |
| 스텁 생성 | 필요 (구현 필요) | 불필요 (기존 Bean 재사용) |
| 메타데이터 정의 | YAML 수동 작성 | `@McpTool`, `@McpParam` 어노테이션 |
| 대상 폴더 명명 | 규칙 없음 | `mcp_{server}` 접두사 필수 |

#### 수정된 파일
| 파일 | 수정 내용 |
|------|----------|
| `Asset/.claude/skills/mcp-setup-java/SKILL.md` | Quick Start, Step 1-5 순서 변경, 핵심 원칙에 mcp_ 접두사 추가 |
| `Asset/.claude/skills/mcp-setup-java/references/required_folders.md` | mcp_{server} 폴더 구조, analyzer 폴더 추가 |
| `Asset/.claude/skills/mcp-setup-java/references/java_templates_overview.md` | 생성 흐름 다이어그램 Code-First로 수정 |

#### Python vs Java 스킬 비교 (동기화됨)
| 항목 | mcp-setup (Python) | mcp-setup-java |
|------|-------------------|----------------|
| 워크플로우 | 코드 우선 (Code-First) | 코드 우선 (Code-First) |
| 대상 폴더 명명 | `mcp_{server}` | `mcp_{server}` |
| 서비스 연결 | @mcp_service AST 스캔 | @McpTool 어노테이션 스캔 |

---

### 2026-01-11: commands/preprompts 문서 전체 업데이트

#### 요청 사항
- `.claude/commands/`와 `.claude/preprompts/` 디렉토리의 모든 문서를 최신 코드베이스에 맞게 업데이트
- 서버 대시보드, 프로토콜별 독립 제어, 서버 병합 웹 UI 등 신규 기능 문서화

#### 구현 완료 항목

**1. commands 디렉토리 업데이트**

| 파일 | 변경 내용 | 버전 |
|------|----------|------|
| `web.md` | 서버 대시보드 섹션 추가, 프로토콜별 제어 API, 병합 웹 UI | 3.2 |
| `test.md` | 대시보드 테스트, 프로토콜별 제어 테스트 추가 | 1.1 |
| `terminology.md` | 프로필 타입 (Base, Reused, Merged) 용어 추가 | 3.1 |
| `common.md` | preprompts 관련 문서 링크 추가 | - |
| `mcp_service.md` | 관련 문서 및 버전 업데이트 | 1.3.0 |

**2. 추가된 주요 내용**

- **서버 대시보드**: MCP 로고 클릭으로 접근, 프로필별 상태 조회
- **프로토콜별 독립 제어**: REST, STDIO, Stream 각각 시작/중지/재시작
- **대시보드 API**: `/api/server/dashboard`, `/api/server/start?protocol=...`
- **프로필 계층**: Base → Reused → Merged 관계 표시
- **병합 웹 UI**: "Merge" 버튼으로 GUI에서 서버 병합

#### 수정된 파일 (총 6개)
- `.claude/commands/web.md`
- `.claude/commands/test.md`
- `.claude/commands/terminology.md`
- `.claude/commands/common.md`
- `.claude/commands/mcp_service.md`
- `.claude/preprompts/web_dataflow.md` - 서버 병합/대시보드 섹션 추가 (v3.2)

---

### 2026-01-10: MCP 서버 대시보드 및 프로토콜별 제어 기능

#### 요청 사항
- 모든 MCP 서버 상태를 한눈에 확인하는 대시보드 추가
- REST, STDIO, Stream 프로토콜 각각 독립적으로 제어

#### 구현 완료 항목

**1. 대시보드 UI**
- 웹에디터 좌측 상단 MCP 로고 클릭 → 대시보드 모달
- 프로필별 서버 상태, 실행 중인 PID, 프로토콜별 상태 표시
- Base/Reused/Merged 프로필 계층 구분

**2. 프로토콜별 독립 제어**
- 각 프로토콜마다 별도의 PID/로그 파일 관리
- REST만 실행하거나 Stream만 실행 가능
- 포트 충돌 방지 (프로필별 고유 포트 할당)

**3. API 엔드포인트**

| API | 설명 |
|-----|------|
| `GET /api/server/dashboard` | 전체 프로필 상태 조회 |
| `POST /api/server/start?protocol=rest` | 특정 프로토콜 서버 시작 |
| `POST /api/server/stop?protocol=rest` | 특정 프로토콜 서버 중지 |
| `GET /api/server/logs?protocol=rest` | 특정 프로토콜 로그 조회 |

#### 수정된 파일

| 파일 | 변경 내용 |
|------|----------|
| `mcp_editor/mcp_server_controller.py` | 프로토콜별 프로세스 관리 로직 |
| `mcp_editor/static/js/tool_editor_dashboard.js` | 대시보드 UI 로직 (신규) |
| `mcp_editor/static/js/tool_editor_server.js` | 프로토콜 선택 드롭다운 추가 |
| `mcp_editor/templates/tool_editor.html` | 대시보드 모달 UI |
| `mcp_editor/tool_editor_core/routes/server_routes.py` | 대시보드 API |

---

### 2026-01-10: MCP 서버 병합(Merge) 기능 구현

#### 요청 사항
- 2개 이상의 MCP 서버(예: outlook + calendar)를 하나의 통합 MCP 서버로 병합
- 기존 서비스 코드 수정 없이 여러 서비스를 하나의 서버에서 제공
- CLI 명령으로 병합 서버 생성

#### 구현 완료 항목

**1. 병합 핵심 함수 (generate_universal_server.py)**

| 함수명 | 기능 |
|-------|------|
| `merge_tool_definitions()` | 여러 프로필의 YAML 도구 정의 병합, 충돌 시 prefix 자동 추가 |
| `normalize_module_path()` | module_path에 mcp_ prefix 정규화 (outlook → mcp_outlook) |
| `merge_registries()` | 서비스 레지스트리 병합, module_path 정규화 포함 |
| `find_type_locations_multi()` | 여러 프로필의 타입 정의 스캔 (Pydantic, Enum) |
| `check_tool_name_conflicts()` | 도구 이름 충돌 검사 및 보고 |
| `save_merged_yaml()` | 병합된 도구 정의 YAML 저장 |
| `save_merged_registry()` | 병합된 레지스트리 JSON 저장 |
| `update_editor_config_for_merge()` | editor_config.json에 병합 프로필 추가 |
| `generate_merged_server()` | 병합 서버 생성 메인 함수 |

**2. CLI 명령 추가**
```bash
# 병합 서버 생성
python jinja/generate_universal_server.py merge \
    --name ms365 \
    --sources outlook,calendar \
    --port 8090 \
    --protocol all \
    --prefix auto
```

**옵션:**
- `--name`: 병합 서버 이름 (필수)
- `--sources`: 병합할 프로필 목록, 콤마 구분 (필수)
- `--port`: 서버 포트 (기본: 8080)
- `--protocol`: 프로토콜 타입 (rest/stdio/stream/all, 기본: all)
- `--prefix`: 도구명 prefix 모드 (auto/always/none, 기본: auto)

**3. 생성되는 파일**
- `mcp_editor/mcp_{merged_name}/tool_definition_templates.yaml` - 병합된 도구 정의
- `mcp_editor/mcp_service_registry/registry_{merged_name}.json` - 병합된 레지스트리
- `mcp_{merged_name}/mcp_server/server_rest.py` - REST 서버
- `mcp_{merged_name}/mcp_server/server_stdio.py` - STDIO 서버
- `mcp_{merged_name}/mcp_server/server_stream.py` - Stream 서버
- `mcp_editor/editor_config.json` - 병합 프로필 추가

#### 설계 문서
- `/home/kimghw/Connector_auth/docs/mcp_server_merge_design.md`

#### 해결된 병목 지점
| 병목 | 해결 방법 |
|------|----------|
| YAML 단일 파일 전제 | `merge_tool_definitions()` - 빌드타임 병합 |
| Registry 단일 서버 전제 | `merge_registries()` - 통합 registry 생성 |
| module_path 정규화 | `normalize_module_path()` - mcp_ prefix 자동 추가 |
| 타입 스캔 단일 서버 | `find_type_locations_multi()` - 멀티 루트 스캔 |
| 도구 이름 충돌 | prefix 정책 (auto/always/none) |

#### 테스트 결과
- outlook + calendar 병합 → ms365 서버 생성 성공
- 13개 도구 병합 (outlook: 7, calendar: 6)
- 18개 서비스 통합
- 53개 타입 스캔
- 3개 프로토콜 서버 생성 (REST, STDIO, Stream)
- import 테스트 통과 (MailService, CalendarService, FilterParams, EventFilterParams)

#### 수정된 파일
| 파일 | 수정 내용 |
|------|----------|
| `jinja/generate_universal_server.py` | 9개 병합 함수 추가, CLI merge 명령 추가 |

---

### 2026-01-10: MCP 파생 서버 생성 및 도구 이동 기능 구현

#### 요청 사항
- 기존 MCP 서버의 서비스를 공유하면서 별도의 MCP 서버(파생 서버) 생성
- 서비스 경로(source_dir, types_files)는 base 서버와 동일하게 유지
- 템플릿 경로(template_definitions_path, tool_definitions_path)만 새 서버명 경로로 분리
- 동일 base를 공유하는 서버 간 도구 이동/복사 기능

#### 구현 완료 항목

**Phase 1: editor_config.json 스키마 확장**
- `config.py`에 PROFILE_SCHEMA 추가 (base_profile, is_base, derived_profiles, is_reused)
- 헬퍼 함수 추가: `get_base_profile()`, `get_derived_profiles()`, `get_sibling_profiles()`, `is_base_profile()`, `get_profile_family()`
- 마이그레이션 함수: `migrate_config_schema()` - is_reused 프로필에서 base_profile 자동 추론

**Phase 2: 파생 서버 생성 기능 개선**
- `profile_management.py`에 `create_derived_profile()` 함수 추가
- `update_base_derived_relationship()`, `remove_from_derived_list()` 함수 추가
- API 엔드포인트 추가:
  - `POST /api/profiles/derive` - 파생 프로필 생성
  - `GET /api/profiles/<profile>/siblings` - 형제 프로필 목록
  - `GET /api/profiles/<profile>/family` - 프로필 가족 관계

**Phase 3: 도구 이동/복사 기능 구현**
- `tool_mover.py` 신규 모듈 생성 (ToolMover 클래스)
- 메서드: `validate_move()`, `move_tools()`, `get_movable_tools()`
- API 엔드포인트 추가:
  - `POST /api/tools/move` - 도구 이동/복사
  - `POST /api/tools/validate-move` - 이동 가능 여부 검증
  - `GET /api/tools/movable` - 이동 가능한 도구 목록

**Phase 4: 서버 생성 시 base 프로필 참조**
- `generate_universal_server.py`에 `resolve_service_paths()` 함수 추가
- `prepare_context()`에 base_profile, base_service_paths 파라미터 추가
- `universal_server_template.jinja2` 수정 - 파생 서버 시 base 모듈에서 서비스 import

**Phase 5: 프론트엔드 UI 개선**
- `tool_editor_derive.js` 신규 생성 (파생 서버/도구 이동 UI 로직)
- `tool_editor.html`에 파생 서버 생성 모달, 도구 이동 모달 추가
- "파생 생성" 버튼, "도구 이동" 버튼 추가

#### editor_config.json 목표 구조
```json
{
  "outlook": {
    "source_dir": "../mcp_outlook",
    "is_base": true,
    "derived_profiles": ["outlook_read", "outlook_write"]
  },
  "outlook_read": {
    "source_dir": "../mcp_outlook",
    "base_profile": "outlook",
    "is_reused": true
  }
}
```

#### 테스트 결과
- Phase 1-5 모든 기능 테스트 통과 (39/39)
- 스키마 확장, 함수 정의, API 엔드포인트, 프론트엔드 파일 모두 정상

#### 수정된 파일 (총 9개)

| 파일 | 변경 내용 |
|------|----------|
| `mcp_editor/tool_editor_core/config.py` | PROFILE_SCHEMA, 헬퍼 함수들, 마이그레이션 함수 |
| `mcp_editor/tool_editor_core/profile_management.py` | create_derived_profile(), 관계 관리 함수들 |
| `mcp_editor/tool_editor_core/tool_mover.py` | ToolMover 클래스 (신규) |
| `mcp_editor/tool_editor_core/routes/profile_routes.py` | /derive, /siblings, /family API |
| `mcp_editor/tool_editor_core/routes/tool_routes.py` | /move, /validate-move, /movable API |
| `mcp_editor/templates/tool_editor.html` | 모달 UI, 버튼 추가 |
| `mcp_editor/static/js/tool_editor_derive.js` | 프론트엔드 로직 (신규) |
| `jinja/generate_universal_server.py` | resolve_service_paths(), base_profile 지원 |
| `jinja/universal_server_template.jinja2` | 파생 서버 서비스 import 로직 |

---

### 2026-01-09: Internal 파라미터 Primitive 타입 기본값 렌더링 수정

#### 요청 사항
- `mcp_service_factors`의 internal 파라미터에서 primitive 타입(integer, string, boolean)의 기본값이 핸들러에 렌더링되지 않는 문제 해결
- 예: `call_args["top"] = integer()` → `call_args["top"] = 50`으로 수정되어야 함

#### 문제 분석
- **근본 원인**: Primitive 타입은 `parameters: []`로 저장되어 `properties = {}`가 되므로 default 값이 추출되지 않음
- **영향 받는 조건**: 템플릿의 `arg_info.value != {}` 조건이 primitive 타입을 처리하지 못함
- **결과**: `integer()` → `0`으로 렌더링되어 기본값 손실

#### 해결 방안

**1. YAML 구조 확장**
```yaml
ttt:
  source: internal
  type: integer
  targetParam: top
  default: 50               # ← primitive 기본값 필드 추가
  description: 'top 파라미터 기본값'
  parameters: []
```

**2. generate_universal_server.py 수정**
- `extract_service_factors_from_tools()` 함수에서 `primitive_default` 추출 로직 추가
- `factor_data.get('default')`로 primitive 기본값 추출
- `factor_info`에 `primitive_default` 필드 추가

**3. universal_server_template.jinja2 수정**
- primitive 타입 목록 정의: `['integer', 'int', 'string', 'str', 'boolean', 'bool', 'number', 'float']`
- primitive 타입 분기 처리: `arg_info.primitive_default` 값 직접 렌더링
- 객체 unpacking 없이 값 할당

**4. tool_editor_web.py 수정**
- `extract_service_factors()` 함수에서 `primitive_default` 저장

#### 렌더링 결과 비교

| 수정 전 | 수정 후 |
|--------|--------|
| `call_args["top"] = integer()` | `call_args["top"] = 50` |
| 값: 0 (손실) | 값: 50 (정상) |

#### 검증 결과
- outlook 서버 3개 프로토콜 (REST, STDIO, Stream) 생성 성공 ✅
- `server_rest.py`, `server_stdio.py`, `server_stream.py` 모두 `call_args["top"] = 50` 확인 ✅

#### 수정된 파일
- `jinja/generate_universal_server.py`: primitive_default 추출 로직 추가
- `jinja/universal_server_template.jinja2`: primitive 타입 렌더링 조건 추가
- `mcp_editor/tool_editor_web.py`: primitive_default 저장 추가
- `mcp_editor/mcp_outlook/tool_definition_templates.yaml`: ttt에 default 값 추가

---

### 2026-01-09: fetch_and_save() 옵션 추가 (save_file, include_body)

#### 요청 사항
- `attachment.md` 문서에 정의된 `save_file`, `include_body` 옵션 구현
- 저장하지 않고 메모리로 반환하는 기능 (`save_file=False`)
- 본문 포함/제외 선택 기능 (`include_body=False`)

#### 구현 완료 항목

**1. fetch_and_save() 새 옵션**
```python
async def fetch_and_save(
    user_email: str,
    message_ids: List[str],
    save_file: bool = True,           # 신규: 저장 여부
    storage_type: str = "local",
    convert_to_txt: bool = False,
    include_body: bool = True,        # 신규: 본문 포함 여부
    onedrive_folder: str = "/Attachments",
    ...
)
```

**2. 반환 결과 구조 확장**
```python
result = {
    ...
    "body_contents": [],          # save_file=False 시 본문
    "attachment_contents": [],    # save_file=False 시 첨부파일
    "save_file": True,
    "include_body": True,
}
```

**3. 옵션 조합**

| save_file | include_body | 결과 |
|:---------:|:------------:|------|
| True | True | 본문 + 첨부파일 저장 (기본) |
| True | False | 첨부파일만 저장 |
| False | True | 본문 + 첨부파일 메모리 반환 |
| False | False | 첨부파일만 메모리 반환 |

#### 수정된 파일
- `mcp_outlook/mail_attachment.py`: fetch_and_save(), _process_mail_with_options() 수정
- `.claude/preprompts/attachment.md`: API 문서 업데이트

---

### 2026-01-09: 첨부파일 저장 시스템 테스트 구현

#### 요청 사항
- `attachment_storage_plan.md` 문서에 따라 테스트 코드 작성
- 8가지 테스트 시나리오 검증 (로컬 저장, TXT 변환, OneDrive 업로드 등)
- OneDrive 청크 업로드 로직 개선

#### 구현 완료 항목

**1. 테스트 디렉토리 구조**
```
mcp_outlook/tests/
├── __init__.py
├── conftest.py                      # 테스트 공통 Fixtures
├── test_mail_attachment.py          # MailFolderManager, MailMetadataManager 테스트
├── test_mail_attachment_converter.py # FileConverter, ConversionPipeline 테스트
├── test_mail_attachment_storage.py  # StorageBackend 테스트
├── test_integration.py              # 통합 테스트
└── run_tests.py                     # 독립 실행 테스트 스크립트
```

**2. OneDrive 청크 업로드 로직 개선**
- `mail_attachment_storage.py`의 `_upload_large()` 메서드 개선
- 마지막 청크에서만 200/201을 처리하도록 `is_last_chunk` 플래그 추가
- 비정상 종료(모든 청크가 202로 끝남) 시 에러 메시지 출력

**3. 테스트 결과: 19/19 통과**
- ConversionPipeline 테스트: 6개 ✓
- LocalStorageBackend 테스트: 8개 ✓
- 통합 워크플로우 테스트: 1개 ✓
- 메타데이터 관리 테스트: 4개 ✓

#### 테스트 시나리오 검증 현황

| 시나리오 | 상태 | 비고 |
|---------|------|------|
| 1. 로컬 저장 + 원본 | ✅ | test_integration.py |
| 2. 로컬 저장 + TXT 변환 | ✅ | test_integration.py |
| 3. OneDrive 저장 + 원본 (4MB 이하) | ⚠️ | 모킹 테스트 |
| 4. OneDrive 저장 + 청크 업로드 | ⚠️ | 모킹 테스트 |
| 5. OneDrive + TXT 변환 | ⚠️ | 모킹 테스트 |
| 6. 변환 실패 시 fallback | ✅ | 원본 저장 확인 |
| 7. 중복 파일명 처리 | ✅ | file_1.txt 자동 생성 |
| 8. 메타데이터 중복 제거 | ✅ | filter_new_messages() |

#### 테스트 실행 방법
```bash
# 독립 실행 스크립트 (ROS 환경 충돌 방지)
python mcp_outlook/tests/run_tests.py
```

#### 수정된 파일
- `mcp_outlook/mail_attachment_storage.py`: 청크 업로드 로직 개선
- `mcp_outlook/docs/attachment_storage_plan.md`: 테스트 현황 업데이트
- `mcp_outlook/tests/*`: 테스트 파일 추가

---

### 2026-01-08: YAML Single Source of Truth 리팩토링

#### 요청 사항
- `tool_definitions.py`와 `tool_definition_templates.yaml` 중복 제거
- YAML 파일을 Single Source of Truth로 통합
- 웹에디터 Save 시 YAML만 저장
- 서버 코드가 런타임에 YAML에서 직접 로드

#### 문제점 분석
- 기존: 웹에디터 Save 시 두 개 파일 생성
  - `tool_definitions.py`: LLM API용 클린 버전
  - `tool_definition_templates.yaml`: mcp_service_factors 포함
- `tool_definitions.py`의 모든 내용이 YAML에도 있어 중복됨

#### 해결 방안

**1. universal_server_template.jinja2 수정**
- `from tool_definitions import MCP_TOOLS` 제거
- `_load_mcp_tools()` 함수 추가: YAML에서 직접 로드
```python
def _load_mcp_tools() -> List[Dict[str, Any]]:
    yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_{server}" / "tool_definition_templates.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data.get("tools", [])

MCP_TOOLS = _load_mcp_tools()
```

**2. tool_editor_web.py 수정**
- `tool_definitions.py` 생성 로직 제거 (라인 856-942)
- YAML만 저장하도록 변경
- 반환값 변경: `{"success": True, "saved": yaml_path}`

**3. 삭제된 파일**
- `/home/kimghw/Connector_auth/mcp_outlook/mcp_server/tool_definitions.py`
- `/home/kimghw/Connector_auth/mcp_file_handler/mcp_server/tool_definitions.py`

#### 검증 결과
- 웹에디터 Save API 테스트 ✅
  - `tool_definitions.py` 생성 안 됨 ✅
  - `tool_definition_templates.yaml` 저장 성공 (9개 도구) ✅
- 서버 재생성 테스트 ✅
  - 3개 프로토콜 (REST, STDIO, Stream) 생성 성공 ✅
- 런타임 YAML 로드 테스트 ✅
  - MCP_TOOLS: 9개 도구 로드 ✅
  - SERVICE_FACTORS: 6개 도구 추출 ✅

#### 수정된 파일
- `jinja/universal_server_template.jinja2`: YAML 런타임 로드 추가
- `mcp_editor/tool_editor_web.py`: tool_definitions.py 생성 로직 제거
- `.claude/commands/web.md`: v3.0 업데이트
- `.claude/commands/handler.md`: YAML 참조로 변경

---

### 2026-01-08: targetParam 기준 Internal/Defaults 병합 렌더링 개선

#### 요청 사항
- 핸들러에서 default(signature_defaults)와 internal을 targetParam 기준으로 **먼저 하드코딩**하여 렌더링
- 그 후 Signature(사용자 입력)가 default를 덮어쓰도록 구성

#### 문제점 분석
- 기존: `tool.signature_defaults.get(param_name, {}).get('value', {})`로 찾음
- `param_name`은 inputSchema의 property name (예: `DatePeriodFilter`)
- `signature_defaults`의 키는 factor_name이므로 **targetParam 기준 매칭이 안 됨**

#### 해결 방안

**1. generate_universal_server.py 수정**
- `object_params` 생성 시 targetParam 기준으로 매칭된 값을 미리 계산
- 새로 추가된 필드:
  - `target_param`: 서비스 메서드 파라미터명
  - `internal_defaults`: targetParam 기준 internal factor의 value
  - `signature_defaults_values`: targetParam 기준 signature_defaults factor의 value

**2. universal_server_template.jinja2 수정**
- pre-computed된 `param_info.internal_defaults`와 `param_info.signature_defaults_values` 사용
- 변수 이름 변경: `_internal_data` → `_internal_defaults`, `sig_defaults` → `_sig_defaults`
- 주석 추가: `# Pre-computed defaults by targetParam: {{ param_info.target_param }}`

#### 생성된 핸들러 코드 예시 (mail_fetch_filter)
```python
# Pre-computed defaults by targetParam: filter_params
filter_params_internal_defaults = {}
filter_params_sig_defaults = {'test_field': 'test_value'}
# Merge: Internal < Signature Defaults < Signature (user input)
filter_params_data = merge_param_data(filter_params_internal_defaults, filter_params, filter_params_sig_defaults)
```

#### 병합 우선순위
```
Internal < Signature Defaults < Signature (사용자 입력)
```

#### 검증 결과
- outlook 서버 3개 프로토콜 (REST, STDIO, Stream) 생성 성공
- `mail_fetch_filter`에서 signature_defaults 정상 적용 확인
- `mail_list_period`에서 internal args (select_params, client_filter) 정상 적용 확인

#### 수정된 파일
- `jinja/generate_universal_server.py`: object_params에 targetParam 기준 defaults 추가
- `jinja/universal_server_template.jinja2`: pre-computed values 사용하도록 수정

---

### 2026-01-07: 핸들러 지침에 따른 제너레이터/템플릿 개선

#### 요청 사항
- 핸들러 지침(handler.md)에 따라 `generate_universal_server.py`와 `universal_server_template.jinja2` 검토 및 업데이트
- signature_defaults 처리 로직 추가

#### 문제점 분석
1. **signature_defaults 미처리**: `extract_internal_args_from_tools()` 함수가 `source='internal'`만 처리하고 `source='signature_defaults'`를 무시
2. **병합 우선순위 불완전**: Signature → Signature Defaults → Internal 우선순위 미구현

#### 핸들러 파라미터 체계 정리
- **Signature**: LLM이 제공하는 사용자 입력값 (inputSchema에 정의)
- **Signature Defaults**: Signature 파라미터의 기본값 (같은 targetParam, mcp_service_factors source='signature_defaults')
- **Internal**: LLM에게 숨겨진 시스템 고정값 (다른 targetParam, mcp_service_factors source='internal')
- **중요**: Signature와 Internal은 서로 다른 targetParam을 가리키므로 겹치지 않음

#### 수정 내용

**1. generate_universal_server.py**
- `extract_service_factors_from_tools()` 함수 추가: `internal`과 `signature_defaults` 모두 처리
- `extract_internal_args_from_tools()` 함수를 레거시 호환성을 위해 유지
- `prepare_context()`에 `service_factors` 파라미터 추가
- 각 tool에 `signature_defaults`, `service_factors` 속성 추가

**2. universal_server_template.jinja2**
- `SERVICE_FACTORS` 변수 추가 (internal + signature_defaults 구조)
- `merge_param_data()` 함수 개선: 세 번째 인자로 `signature_defaults` 받음
- `get_signature_defaults()`, `apply_signature_defaults()`, `merge_with_priority()` 헬퍼 함수 추가
- object_params 처리 시 signature_defaults 적용

#### 병합 우선순위
```
merge_param_data(internal_data, runtime_data, signature_defaults)
→ 최종값 = internal < signature_defaults < runtime (사용자 입력)
```

#### 검증 결과
- outlook 서버 3개 프로토콜 (REST, STDIO, Stream) 생성 성공
- `mail_fetch_filter`에서 signature_defaults 적용 확인:
  ```python
  filter_params_data = merge_param_data(filter_params_internal_data, filter_params, {'test_field': 'test_value'})
  ```
- Python 문법 검사 통과

#### 수정된 파일
- `jinja/generate_universal_server.py`
- `jinja/universal_server_template.jinja2`

---

### 2026-01-07: MCP 핸들러 전체 테스트 완료

#### 요청 사항
- MCP Outlook 서버 핸들러 전체 테스트
- 파라미터 처리 검증 (Signature, Defaults, Internal)
- client_filter를 통한 수신 후 필터링 테스트

#### 테스트 결과

| 항목 | 결과 | 비고 |
|------|------|------|
| 서버 시작 (REST 8001) | ✅ 성공 | uvicorn 정상 구동 |
| 도구 목록 조회 | ✅ 성공 | 9개 도구 등록 확인 |
| mail_list_period | ✅ 성공 | 24개 메일 조회 (2026-01-01~07) |
| mail_list_keyword | ✅ 성공 | 키워드 검색 정상 동작 |
| mail_fetch_search | ✅ 성공 | 검색 모드 동작 확인 |
| mail_attachment_meta | ✅ 성공 | 첨부파일 메타정보 조회 |
| client_filter (수신 후 필터링) | ✅ 성공 | block@krs.co.kr 제외: 24→9개 |

#### 파라미터 처리 검증
- **Signature 파라미터**: DatePeriodFilter 정상 전달 ✅
- **Internal 파라미터 (select_params)**: id, subject, sender, bodyPreview, hasAttachments, receivedDateTime, internetMessageId 필드 정상 적용 ✅
- **targetParam 매핑**: DatePeriodFilter → filter_params 정상 ✅
- **client_filter (수신 후 필터링)**: exclude_sender_address 정상 동작 ✅

#### 수정된 파일
- `mcp_outlook/graph_mail_query.py`: `_apply_client_side_filter` 함수 - ExcludeParams 전체 필드 지원 추가
- `mcp_outlook/mcp_server/server_rest.py`: `handle_mail_fetch_filter` 함수 - client_filter 파라미터 추가
- `mcp_outlook/outlook_service.py`: `fetch_filter` 함수 - client_filter 파라미터 추가

#### 파라미터 구조
- **exclude_params**: Graph API `$filter`에 적용 (서버 측 필터링)
- **client_filter**: 메일 수신 후 클라이언트 측 필터링 (`_apply_client_side_filter`)

#### 등록된 도구 목록
1. `mail_list_period` - 기간별 메일 목록 조회
2. `mail_list_keyword` - 키워드로 메일 검색
3. `mail_query_if_emaidID` - 메일 ID로 상세 조회
4. `mail_attachment_meta` - 첨부파일 메타정보 조회
5. `mail_attachment_download` - 첨부파일 다운로드
6. `mail_fetch_filter` - 필터 조건으로 메일 조회
7. `mail_fetch_search` - 키워드 검색 (본문 포함)
8. `mail_process_with_download` - 메일 조회 및 첨부파일 다운로드
9. `mail_query_url` - Graph API URL 직접 호출

---

### 2026-01-07: inputSchema default 값 동기화 문제 해결

#### 요청 사항
- 웹 에디터에서 설정한 `inputSchema.properties.default` 값이 `tool_definitions.py`에 반영되지 않는 문제 해결

#### 문제 원인
- **위치**: `mcp_editor/tool_editor_web.py` - `save_tool_definitions()` 함수 (라인 778-781)
- **원인**: `remove_defaults()` 함수가 `tool_definitions.py` 생성 시 모든 default 값을 의도적으로 제거
- **영향**: `server_rest.py`의 `apply_schema_defaults()` 함수가 default 값을 읽을 수 없음

#### 해결 방법
- `remove_defaults()` 함수 호출 제거
- 이제 웹 에디터에서 저장 시 default 값이 `tool_definitions.py`에 유지됨

#### 수정된 파일
- `mcp_editor/tool_editor_web.py` (라인 778-784)

#### 관련 구조 (두 단계 기본값 처리)
```
1단계: apply_schema_defaults() - inputSchema.properties.default에서 동적 적용 (우선)
2단계: 핸들러 함수 하드코딩 - mcp_service.parameters.default에서 생성 시 결정 (폴백)
```

#### 검증 완료
- `mail_attachment_download` 도구에서 `save_directory: 'downloadsssss'`, `skip_duplicates: False` 기본값 적용 확인

---

### 2026-01-07: MCP Tool-Service 매핑 수정

#### 요청 사항
1. `tool_definitions.py`에 `mcp_service.name` 필드가 누락되어 서버에서 `MailService` 메서드를 찾지 못하는 오류 수정
2. `select_params` internal arguments가 제대로 적용되는지 검증

#### 해결된 문제
- **오류**: `'MailService' object has no attribute 'mail_list_period'`
- **원인**: 웹에디터 Save 시 `tool_definitions.py`에 `mcp_service.name` 필드가 포함되지 않음
- **수정 파일**: `mcp_editor/tool_editor_web.py` (lines 787-796)
  - `mcp_service` 필드가 있을 때 `name` 값만 추출하여 `tool_definitions.py`에 포함하도록 수정

#### 검증 완료
- `mail_list_period` → `query_mail_list()` 매핑 정상 동작
- `mail_attachment_meta` → `fetch_attachments_metadata()` 매핑 정상 동작
- `select_params` internal arguments 정상 적용 (API 응답에서 지정된 필드만 반환)

---

### 2025-01-07: 첨부파일 처리 기능 구현

#### 요청 사항
1. `batch_and_attachment` 메서드에 메타데이터만 조회하는 옵션 추가
2. `GraphAttachmentHandler` 메서드 통합 (3개 → 2개)
3. `fetch_attachments_metadata`, `download_attachments` 통합 함수 구현
4. Facade 패턴 적용

#### 구현 완료 항목
- 메타데이터 전용 조회 기능 (`fetch_attachments_metadata`)
- 통합 다운로드 함수 (다형성 지원 - 메일 ID 또는 첨부파일 ID 쌍)
- Facade 패턴 적용 (`outlook_service.py`)
- 실제 데이터 테스트 완료

#### 관련 파일
- `mcp_outlook/graph_mail_attachment.py` (+240 lines)
- `mcp_outlook/graph_mail_client.py` (+118 lines)
- `mcp_outlook/outlook_service.py` (+78 lines)

---

## 이전 세션 요약

### MCP 서버 아키텍처
- Jinja2 템플릿 기반 서버 생성 시스템
- 3가지 프로토콜 지원: REST, STDIO, Stream
- `tool_definition_templates.py` → `tool_definitions.py` 생성 파이프라인

### 핵심 파일 관계
```
tool_definition_templates.py (mcp_service_factors 포함)
        ↓
generate_universal_server.py
        ↓
server_rest.py / server_stdio.py / server_stream.py
```

### 파라미터 체계
- **Signature**: LLM이 직접 제공하는 파라미터
- **Signature Defaults**: LLM에게 보이지만 기본값 제공
- **Internal**: 시스템 고정값 (LLM에게 숨김)

---

### 2026-01-10: 기존 서비스 재사용 MCP 프로필 생성 및 삭제 기능 구현

#### 요청 사항
- 기존 MCP 서비스를 재사용하여 도구 세트가 다른 새 프로필 생성
- YAML 템플릿 복사 방식으로 독립적인 도구 관리
- MCP 프로필 삭제 기능 추가

#### 구현 완료 항목

**1. 선행 작업 (치명적 이슈 해결)**

| 작업 | 파일 | 내용 |
|------|------|------|
| 0-1 | tool_editor_tools.js | `createNewProject()` 중복 함수 제거 (Line 758 → `createNewProfileProject()`로 변경) |
| 0-2 | mcp_server_controller.py | `_get_server_path()` editor_config.json 기반 경로 해석으로 수정 |
| 0-3 | universal_server_template.jinja2 | YAML 경로 `profile_name` 기반으로 수정 + 환경변수 MCP_YAML_PATH 지원 |
| 0-4 | universal_server_template.jinja2 | 포트 변수화 (MCP_SERVER_PORT 환경변수 지원) |
| 0-5 | generate_editor_config.py | merge 전략 추가 (기존 재사용 프로필 보존) |
| 0-6 | tool_editor_web.py | `discover_mcp_modules()` 프로필별 경로 해석 지원 |

**2. 본 기능 구현 - 프로필 재사용 생성**

- `copy_yaml_templates()`: 기존 프로필의 YAML을 새 프로필로 복사
- `update_editor_config_for_reuse()`: 기존 source_dir, types_files 재사용하는 프로필 추가
- `create_server_project_folder()`: mcp_{new_profile}/mcp_server/ 폴더 생성
- `create_reused_profile()`: 위 함수들 통합, 새 프로필 생성 완료
- `/api/create-mcp-project-reuse` API 추가

**3. 본 기능 구현 - 프로필 삭제**

- `delete_mcp_profile()`: mcp_editor/mcp_{profile}/ 폴더, editor_config.json 프로필 완전 삭제
- `/api/delete-mcp-profile` API 추가
- `/api/available-services` API 추가 (재사용 가능 서비스 목록)
- 원본 프로필 (outlook, calendar, file_handler) 삭제 방지

**4. UI 수정**

- tool_editor.html: Create Project 모달에 프로젝트 타입 선택 추가
  - "Create from scratch" (기존 로직)
  - "Reuse existing service" (새 로직)
- tool_editor_tools.js: `toggleReuseOptions()`, `loadAvailableServices()` 함수 추가, `createNewProject()` 확장
- tool_editor_ui.js: `renderProfileTabs()` 수정 - 삭제 버튼 추가 (hover 시 표시)

#### 사용 예시
```
기존: outlook (11개 도구, mcp_outlook 참조)
    ↓ 재사용 생성
신규: outlook_read (YAML 복사 → 6개만 선택, mcp_outlook 참조)
    ↓ 삭제
삭제: outlook_read 프로필 완전 제거
```

#### 장점
- 같은 서비스 로직 재사용 (코드 중복 없음)
- 권한 분리 (도구별 프로필 분리)
- 중앙 Registry 관리 (mcp_editor/mcp_service_registry/)
- 독립적인 YAML 관리 (각 프로필별 도구 편집 가능)
- 불필요한 프로필 쉽게 삭제

#### 수정된 파일 (총 8개)

| 파일 | 수정 내용 |
|------|----------|
| mcp_editor/tool_editor_web.py | 5개 함수 + 3개 API 엔드포인트 추가 |
| mcp_editor/templates/tool_editor.html | UI 추가 (프로젝트 타입 선택, 재사용 옵션) |
| mcp_editor/static/js/tool_editor_tools.js | 3개 함수 추가/수정, 중복 함수 이름 변경 |
| mcp_editor/static/js/tool_editor_ui.js | 삭제 버튼 추가, 3개 함수 추가 |
| mcp_editor/mcp_server_controller.py | `_get_server_path()` 수정 |
| jinja/universal_server_template.jinja2 | YAML 경로 및 포트 변수화 |
| jinja/generate_editor_config.py | merge 전략 추가 |
| jinja/generate_universal_server.py | `prepare_context()`에 profile_name, port 추가 |

#### 테스트 결과
- 프로필 재사용 생성: OK
- YAML 복사: OK
- editor_config.json 업데이트: OK
- 프로젝트 폴더 생성: OK
- 프로필 삭제: OK
- 원본 프로필 보호: OK

---

### 2026-01-11: 타입/서비스 파일 자동 스캔 기능 추가

#### 요청 사항
- 웹에디터 시작 시 `*_types.py`, `*_service.py` 파일 자동 스캔
- editor_config.json에 스캔된 파일 경로 자동 반영

#### 구현 완료 항목

**1. 자동 스캔 함수 추가 (generate_universal_server.py)**

| 함수명 | 기능 |
|-------|------|
| `scan_types_files()` | `*_types.py` 파일 재귀 스캔 |
| `scan_service_files()` | `*_service.py` 파일 재귀 스캔 |

**2. 스캔 제외 디렉토리**
- `__pycache__`, `venv`, `node_modules`
- `test`, `tests`
- `.`으로 시작하는 숨김 폴더

**3. 스캔 시점**
- 웹에디터 시작 시 자동 실행
- `generate_editor_config.py` 실행 시
- 서버 병합 시

#### 수정된 파일
| 파일 | 수정 내용 |
|------|----------|
| `jinja/generate_universal_server.py` | scan_types_files(), scan_service_files() 함수 추가 |
| `jinja/generate_editor_config.py` | 스캔 함수 호출 로직 추가 |

---

*마지막 업데이트: 2026-01-12*
