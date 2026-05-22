# OneNote MCP 툴 설계

## 사용자 시나리오

1. 사용자가 아무런 조건 없이 OneNote에 저장 요청 → 최근 접근한 페이지에 내용을 저장
2. 사용자가 관련된 페이지에 저장 요청 → 기간(기본 3개월) 내 페이지의 요약/키워드를 반환 → 선택된 페이지 본문 조회 후 저장 (스킬 연속 호출)
3. 키워드 검색으로 관련 페이지를 찾아 사용자 질의에 응답
4. 새로운 섹션 또는 페이지를 생성
5. 전체 페이지 목록을 조회

---

## 툴 구성: CRUD 기반 3개 툴

### 설계 원칙

- **CRUD 단위로 툴을 분리**: 조회(Read), 생성/수정(Write), 삭제(Delete)
- **`action` 파라미터로 세부 동작 구분**: 툴 수를 최소화하면서도 기능 확장 가능
- **스킬 연속 호출 고려**: 각 툴의 출력이 다음 툴의 입력으로 자연스럽게 연결
- **단일 책임**: 한 번의 호출이 한 가지 작업만 수행

---

### 1. `read_onenote` — 조회 (Read)

모든 조회 작업을 담당한다. LLM이 사용자 의도에 따라 조회 조건을 조합하여 호출한다.

#### 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| `user_email` | str | O | - | 사용자 이메일 |
| `action` | enum | O | - | `list_pages`, `list_sections`, `search`, `get_content`, `get_summary` |
| `keyword` | str | - | - | 검색 키워드 (`search` 시 필수) |
| `page_id` | str | - | - | 특정 페이지 지정 (`get_content`, `get_summary` 시 필수) |
| `section_id` | str | - | - | 섹션 범위 제한 (`list_pages`, `search` 시 선택) |
| `notebook_id` | str | - | - | 노트북 범위 제한 (`list_pages`, `list_sections` 시 선택) |
| `date_from` | str | - | - | 시작 날짜 (포함, >= 이 값, ISO 8601) 예: `"2024-12-01T00:00:00Z"` |
| `date_to` | str | - | - | 종료 날짜 (포함, <= 이 값, ISO 8601) 예: `"2024-12-31T23:59:59Z"` |
| `top` | int | - | 50 | 최대 반환 건수 (`list_pages`, `search` 시 선택) |

#### 조회 조건 조합 예시

LLM은 사용자 의도에 따라 파라미터를 조합한다:

```
# 전체 페이지 목록
read_onenote(action="list_pages")

# 특정 섹션의 페이지만
read_onenote(action="list_pages", section_id="X")

# 특정 기간의 페이지만 (ISO 8601, Outlook과 동일 형식)
read_onenote(action="list_pages", date_from="2025-01-01T00:00:00Z")

# 날짜 범위 지정
read_onenote(action="list_pages", date_from="2025-01-01T00:00:00Z", date_to="2025-01-31T23:59:59Z")

# 키워드로 검색 (전체 범위)
read_onenote(action="search", keyword="회의록")

# 키워드 + 특정 섹션 내에서만 검색
read_onenote(action="search", keyword="회의록", section_id="X")

# 키워드 + 날짜 범위 제한
read_onenote(action="search", keyword="예산", date_from="2025-01-01T00:00:00Z")

# 키워드 + 섹션 + 날짜 범위 모두 조합
read_onenote(action="search", keyword="예산", section_id="X", date_from="2025-01-01T00:00:00Z", date_to="2025-01-31T23:59:59Z")

# 특정 페이지 본문 조회
read_onenote(action="get_content", page_id="A")

# 특정 페이지 요약 조회
read_onenote(action="get_summary", page_id="A")
```

#### action별 동작

| action | 설명 | 필수 파라미터 | 조합 가능 조건 | 내부 호출 |
|--------|------|---------------|----------------|-----------|
| `list_pages` | 페이지 목록 조회 | - | `section_id`, `notebook_id`, `date_from`, `date_to`, `top` | `OneNoteReader.list_pages()` → 비어있으면 `sync_db()` |
| `list_sections` | 섹션 목록 조회 | - | `notebook_id` | `OneNoteReader.list_sections()` |
| `search` | 키워드 기반 페이지 검색 | `keyword` | `section_id`, `date_from`, `date_to`, `top` | `OneNoteAgent.search_pages()` |
| `get_content` | 페이지 본문 조회 | `page_id` | - | `OneNoteService.get_page_content()` |
| `get_summary` | 페이지 요약 조회 | `page_id` | - | `OneNoteAgent.get_page_summary()` |

#### 반환값

```python
# list_pages
{"pages": [{"page_id", "title", "section_name", "notebook_name", "last_accessed"}], "count": int}

# list_sections
{"sections": [{"section_id", "display_name", "notebook_name"}], "count": int}

# search
{"results": [{"page_id", "title", "summary", "keywords"}], "count": int, "total_scanned": int}

# get_content
{"page_id", "title", "content": "본문 텍스트"}

# get_summary
{"page_id", "title", "summary", "keywords"}
```

---

### 2. `write_onenote` — 생성/수정 (Create + Update)

페이지/섹션 생성 및 내용 추가를 담당한다.

#### 파라미터

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| `action` | enum | O | - | `append`, `create_page`, `create_section` |
| `user_email` | str | O | - | 사용자 이메일 |
| `content` | str | - | - | 저장할 내용 (`append`, `create_page` 시 필수) |
| `page_id` | str | - | - | 내용 추가 대상 (`append` 시 선택, 없으면 최근 페이지) |
| `section_id` | str | - | - | 페이지 생성 시 소속 섹션 (`create_page` 시 필수) |
| `notebook_id` | str | - | - | 섹션 생성 시 소속 노트북 (`create_section` 시 필수) |
| `title` | str | - | - | 제목 (`create_page`, `create_section` 시 필수) |

#### action별 동작

| action | 설명 | 필수 파라미터 | 내부 호출 |
|--------|------|---------------|-----------|
| `append` | 기존 페이지에 내용 추가 | `content` | `page_id` 없으면 `get_recent_items()` → `edit_page(APPEND)` |
| `create_page` | 새 페이지 생성 | `section_id`, `title`, `content` | `OneNotePageManager.create_page()` |
| `create_section` | 새 섹션 생성 | `notebook_id`, `title` | `OneNoteService.create_section()` |

#### 반환값

```python
# append
{"success": True, "page_id", "title", "web_url"}

# create_page
{"success": True, "page_id", "title", "section_name", "web_url"}

# create_section
{"success": True, "section_id", "section_name", "notebook_name"}
```

---

### 3. `delete_onenote` — 삭제 (Delete)

페이지 삭제를 담당한다.

#### 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `user_email` | str | O | 사용자 이메일 |
| `page_id` | str | O | 삭제할 페이지 ID |

#### 내부 호출

`OneNotePageManager.delete_page()` → DB에서도 삭제 + 요약 캐시 삭제

#### 반환값

```python
{"success": True, "deleted_page_id": str}
```

---

## 스킬 연속 호출 시나리오

### 시나리오 1: 조건 없이 저장

사용자: "이 내용 OneNote에 저장해줘"

```
write_onenote(action="append", content="오늘 회의 내용...")
```

→ **1회 호출** — `page_id` 미지정이므로 최근 접근 페이지에 자동 저장

---

### 시나리오 2: 관련 페이지 찾아서 저장

사용자: "프로젝트 관련 페이지에 이 내용 추가해줘"

```
① read_onenote(action="search", keyword="프로젝트 회의록", date_from="2025-11-01T00:00:00Z")
   → [{page_id: "A", title: "1월 프로젝트 회의록", summary: "...", keywords: [...]}]

② read_onenote(action="get_content", page_id="A")
   → {content: "기존 본문 내용..."}

③ write_onenote(action="append", page_id="A", content="추가할 내용")
   → {success: True}
```

→ **3회 연속 호출** (read → read → write)

---

### 시나리오 3: 키워드 검색 후 응답

사용자: "예산 관련 내용 찾아줘"

```
① read_onenote(action="search", keyword="예산 계획")
   → [{page_id: "B", title: "2025 예산", summary: "...", keywords: ["예산", "계획"]}]

② read_onenote(action="get_content", page_id="B")
   → {content: "예산 관련 본문..."}

③ LLM이 본문 기반으로 사용자에게 응답 생성
```

→ **2회 연속 호출** (read → read → LLM 응답)

---

### 시나리오 3-1: 특정 섹션 내에서 키워드 검색

사용자: "업무 노트 섹션에서 예산 관련 내용 찾아줘"

```
① read_onenote(action="list_sections")
   → [{section_id: "X", display_name: "업무 노트"}, ...]

② read_onenote(action="search", keyword="예산", section_id="X")
   → [{page_id: "B", title: "2025 예산", ...}]

③ read_onenote(action="get_content", page_id="B")
   → {content: "예산 관련 본문..."}
```

→ **3회 연속 호출** (read → read → read → LLM 응답)

---

### 시나리오 3-2: 기간 + 키워드 조합 검색

사용자: "최근 1개월 내 회의록 찾아줘"

```
① read_onenote(action="search", keyword="회의록", date_from="2026-01-01T00:00:00Z")
   → [{page_id: "C", title: "2월 회의록", ...}]

② read_onenote(action="get_content", page_id="C")
   → {content: "회의록 본문..."}
```

→ **2회 연속 호출** (read → read → LLM 응답)

---

### 시나리오 4: 새 페이지 생성

사용자: "업무 노트에 새 회의록 페이지 만들어줘"

```
① read_onenote(action="list_sections")
   → [{section_id: "X", display_name: "업무 노트"}]

② write_onenote(action="create_page", section_id="X", title="새 회의록", content="내용...")
   → {success: True, page_id: "C", web_url: "..."}
```

→ **2회 연속 호출** (read → write)

---

### 시나리오 5: 전체 페이지 목록 조회

사용자: "OneNote 페이지 목록 보여줘"

```
① read_onenote(action="list_pages")
   → [{page_id, title, section_name, notebook_name, last_accessed}]
```

→ **1회 호출**

---

### 시나리오 5-1: 특정 섹션의 최근 페이지만 조회

사용자: "업무 노트 섹션의 최근 페이지 5개만 보여줘"

```
① read_onenote(action="list_sections")
   → [{section_id: "X", display_name: "업무 노트"}]

② read_onenote(action="list_pages", section_id="X", date_from="2026-01-01T00:00:00Z", top=5)
   → [{page_id, title, last_accessed}, ...]
```

→ **2회 연속 호출** (read → read)

---

## 코드 매핑

| 툴 / action | Facade 라우터 | CRUD 모듈 | Implementation |
|-------------|--------------|-----------|----------------|
| read / `list_pages` | `read_onenote()` | `OneNoteReader.list_pages()` | `OneNoteDBService.list_items()` |
| read / `list_sections` | `read_onenote()` | `OneNoteReader.list_sections()` | `GraphOneNoteClient.list_sections()` |
| read / `search` | `read_onenote()` | `OneNoteReader.search()` | `OneNoteAgent.search_pages()` |
| read / `get_content` | `read_onenote()` | `OneNoteReader.get_content()` | `GraphOneNoteClient.get_page_content()` |
| read / `get_summary` | `read_onenote()` | `OneNoteReader.get_summary()` | `OneNoteAgent.get_page_summary()` |
| write / `append` | `write_onenote()` | `OneNoteWriter.append()` | `OneNotePageManager.edit_page()` |
| write / `create_page` | `write_onenote()` | `OneNoteWriter.create_page()` | `OneNotePageManager.create_page()` |
| write / `create_section` | `write_onenote()` | `OneNoteWriter.create_section()` | `GraphOneNoteClient.create_section()` |
| delete | `delete_onenote()` | `OneNoteDeleter.delete_page()` | `OneNotePageManager.delete_page()` |

---

## 파일 구조

```
mcp_onenote/
├── onenote_service.py          # Facade — read/write/delete 라우팅만
├── onenote_read.py             # OneNoteReader — 조회 로직 (5 actions)
├── onenote_write.py            # OneNoteWriter — 생성/수정 로직 (3 actions)
├── onenote_delete.py           # OneNoteDeleter — 삭제 로직
├── onenote_page.py             # OneNotePageManager — CRUD + DB 동기화
├── onenote_agent.py            # OneNoteAgent — AI 요약/검색
├── onenote_db_service.py       # OneNoteDBService — SQLite CRUD
├── onenote_db_query.py         # OneNoteDBQuery — DB 조회 래퍼
├── onenote_types.py            # 타입 정의 (ReadAction, WriteAction 등)
├── graph_onenote_client.py     # Graph API HTTP 클라이언트
└── __init__.py
```

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Server (Handler)                  │
│              tool 라우팅 + 요청/응답 변환                 │
├─────────────┬──────────────────┬────────────────────────┤
│ read_onenote│  write_onenote   │   delete_onenote       │
│  (5 actions)│   (3 actions)    │    (1 action)          │
└──────┬──────┴────────┬─────────┴──────────┬─────────────┘
       │               │                    │
       ▼               ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│            OneNoteService (Facade — 라우팅만)             │
│  read_onenote()  → OneNoteReader                         │
│  write_onenote() → OneNoteWriter                         │
│  delete_onenote()→ OneNoteDeleter                        │
└──────┬──────┬────────┬─────────┬──────────┬─────────────┘
       │      │        │         │          │
       ▼      ▼        ▼         ▼          ▼
┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌────────┐
│ OneNote  ││ OneNote  ││ OneNote  ││ OneNote  ││OneNote │
│ Reader   ││ Writer   ││ Deleter  ││ Agent    ││Page    │
│(조회)     ││(생성/수정)││(삭제)     ││(AI 요약) ││Manager │
└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘└───┬────┘
     │           │           │           │          │
     ▼           ▼           ▼           ▼          ▼
┌──────────────┐ ┌──────────────┐ ┌────────────────┐
│ GraphOneNote │ │ OneNoteAgent │ │ OneNoteDB      │
│ Client       │ │ (Claude SDK) │ │ Service        │
│ (Graph API)  │ │ (요약/검색)   │ │ (SQLite)       │
└──────────────┘ └──────────────┘ └────────────────┘
```
