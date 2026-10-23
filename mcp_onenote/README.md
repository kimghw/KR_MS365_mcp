# MCP OneNote Module

Microsoft Graph API를 사용한 OneNote 서비스 모듈입니다.
Facade 패턴으로 `svc.page`, `svc.agent`, `svc.db` 접근자를 통해 기능별 모듈에 접근합니다.

## 구조

```
mcp_onenote/
├── __init__.py                # 모듈 초기화 및 export
├── onenote_types.py           # 타입 정의 (dataclass, enum)
├── graph_onenote_client.py    # Graph API 클라이언트
├── onenote_service.py         # Facade (svc.page, svc.agent, svc.db)
├── onenote_page.py            # 페이지 CRUD + DB 동기화
├── onenote_agent.py           # AI 요약/검색 (Claude Code SDK)
├── onenote_db_service.py      # DB 서비스 (테이블 관리, 마이그레이션, 동기화)
├── onenote_db_query.py        # DB 조회/저장 (외부 호출용)
├── summarize_config.yaml      # AI 요약 프롬프트 설정
├── tests/
│   ├── __init__.py
│   └── test_onenote_service.py
└── README.md
```

## 아키텍처

```
OneNoteService (Facade)
├── .page  → OneNotePageManager   (create_page, edit_page, delete_page, sync_db)
├── .agent → OneNoteAgent         (summarize_page, search_pages, get_page_summary)
├── .db    → OneNoteDBQuery       (get_recent_items, find_section_by_name, find_page_by_name)
│
├── Graph API 순수 위임            (list_notebooks, list_sections, list_pages, ...)
│
└── 내부 의존성
    ├── GraphOneNoteClient        (Graph API HTTP 호출)
    └── OneNoteDBService          (SQLite CRUD, 테이블 관리, 마이그레이션)
```

## 데이터베이스

| 모드 | 위치 | 소유자(`owner_key`) |
|------|------|---------------------|
| 단일 운영자 (기본) | `database/onenote.db` | 행의 `user_id`(이메일) |
| 멀티유저 (`MS365_MULTI_USER=1`) | `<MS365_DATA_ROOT>/users/<user_key>/db/onenote.db` | principal 의 `user_key` |

- `onenote_items`: 섹션/페이지 정보 (item_type, item_id, item_name, notebook_id, section_id, web_url 등)
- `onenote_page_summaries`: AI 요약 데이터 (summary, keywords, content_hash 등)
- `onenote_page_changes`: 페이지 변경 이력 (action, content_snippet, change_summary, change_keywords 등)

세 테이블 모두 `owner_key` 를 갖고, 유일성은 `(owner_key, item_id)` / `(owner_key, page_id)` 다.
조회·갱신·삭제·upsert 는 전부 소유자 조건을 단다 — 같은 Graph 페이지라도 사용자마다 요약·이력이
따로 있고, 다른 사용자의 page_id 로 요약을 읽거나 지울 수 없다. 스키마·구버전 이전은
`storage_schema.py`(구 DB 는 기동 시 `owner_key = user_id` 로 자동 이전, 멀티유저 DB 는 추정 이전 없음).
멀티유저에서는 `mcp_server/handlers.py` 의 `create_service()` 가 사용자별 서비스·DB·토큰 공급자를 만든다
([spec/spec_멀티유저.md](../spec/spec_멀티유저.md) ②-7.3).

## 기능

### Graph API 위임 (OneNoteService 직접)
- `list_notebooks(user_email)` — 노트북 목록 조회
- `list_sections(user_email, notebook_id)` — 섹션 목록 조회
- `create_section(user_email, notebook_id, section_name)` — 섹션 생성
- `list_pages(user_email, section_id)` — 페이지 목록 조회 (`@odata.nextLink` 페이징 지원)
- `get_page_content(user_email, page_id, include_ids=False)` — 페이지 내용 조회 (HTML). `include_ids=True` 면 `?includeIDs=true` 로 요소의 생성 id 와 `data-id` 를 함께 받는다 (replace target 용)
- `manage_sections(user_email, action, ...)` — 섹션 관리 통합 인터페이스
- `manage_page_content(user_email, action, ...)` — 페이지 관리 통합 인터페이스

### svc.page (OneNotePageManager)
- `create_page(user_email, section_id, title, content)` — 페이지 생성 + DB 자동 저장
- `edit_page(user_email, page_id, action, content)` — 페이지 편집 + 변경 이력 기록 + 요약 자동 갱신
  - 지원 action: `APPEND`, `PREPEND`, `INSERT`, `REPLACE`, `CLEAN`
  - 편집 시 AI 변경 요약 + 키워드를 자동 생성하여 `onenote_page_changes`에 기록
- `delete_page(user_email, page_id)` — 페이지 삭제 + DB/요약 삭제
- `sync_db(user_email)` — 전체 페이지 DB 동기화
  - MCP 도구 `read_onenote action=list_pages` 는 DB 가 비어 있으면 `sync_db` 를 먼저 부른다. 그 최초
    동기화가 실패하면 빈 목록으로 포장하지 않고 `success: false` + `error` 를 돌려준다.
- `replace(user_email, page_id, target, content)` — `target` 요소(생성 id, 예 `table:{guid}{n}`)를 `content` 로 통째로 교체. MCP 도구 `write_onenote action=replace`.
  `#data-id` 를 target 으로 주면 Graph 가 거부하고(table 500 · p/ul 400) div 는 대상이 안 된다 — [references/graph_onenote_patch.md](../references/graph_onenote_patch.md), 사양 [spec/spec_onenote_페이지블록갱신.md](../spec/spec_onenote_페이지블록갱신.md)

### svc.agent (OneNoteAgent)
- `summarize_page(user_email, page_id, force_refresh)` — AI 페이지 요약 생성/갱신
  - SHA256 해시로 변경 감지, 캐시 지원
  - Claude Code SDK로 요약 + 키워드 병렬 추출
- `get_page_summary(user_email, page_id)` — 저장된 요약 조회
- `list_summarized_pages(user_email)` — 요약된 페이지 목록
- `summarize_change(page_title, action, content)` — 편집 내용 AI 요약 (변경 요약 + 키워드)
- `search_pages(user_email, query, section_id, concurrency)` — 섹션 내 페이지 병렬 검색
  - Semaphore 기반 동시성 제어 (기본 5개)
  - AI가 관련성 판단 후 요약 반환

### svc.db (OneNoteDBQuery)
- `get_recent_items(user_email, item_type, limit)` — 최근 접근 섹션/페이지 조회
- `save_section(user_email, notebook_id, section_id, section_name)` — 섹션 DB 저장
- `save_page(user_email, section_id, page_id, page_title)` — 페이지 DB 저장
- `find_section_by_name(user_email, section_name)` — 이름으로 섹션 검색
- `find_page_by_name(user_email, page_title)` — 이름으로 페이지 검색
- `get_page_history(user_email, page_id, limit)` — 페이지 변경 이력 조회 (git log 스타일, 호출자 소유 이력만)
- `get_user_history(user_email, limit)` — 사용자별 변경 이력 조회

## 사용법

```python
from mcp_onenote import OneNoteService
from mcp_onenote.onenote_types import PageAction

async def main():
    svc = OneNoteService()
    await svc.initialize()

    try:
        # Graph API 직접 호출
        notebooks = await svc.list_notebooks("user@example.com")
        sections = await svc.list_sections("user@example.com", notebook_id="nb_id")

        # 페이지 CRUD (DB 연동)
        page = await svc.page.create_page(
            user_email="user@example.com",
            section_id="section_id",
            title="새 페이지",
            content="<p>Hello World</p>",
        )

        # AI 요약
        summary = await svc.agent.summarize_page("user@example.com", "page_id")
        print(summary["summary"], summary["keywords"])

        # 섹션 내 관련 페이지 검색
        results = await svc.agent.search_pages(
            "user@example.com", "디지털트윈 관련 내용", section_id="section_id"
        )

        # DB 조회
        recent = svc.db.get_recent_items("user@example.com", "page", limit=5)
        found = svc.db.find_page_by_name("user@example.com", "기획서")

        # 페이지 편집 (변경 이력 자동 기록)
        await svc.page.edit_page(
            "user@example.com", "page_id", PageAction.APPEND, "<p>새 내용</p>"
        )

        # 변경 이력 조회 (git log 스타일)
        history = svc.db.get_page_history("user@example.com", "page_id")
        # → [{"action": "append", "change_summary": "...", "change_keywords": [...], "created_at": "..."}]

        # 전체 페이지 동기화
        await svc.page.sync_db("user@example.com")
    finally:
        await svc.close()
```

## 인증

`session` 모듈의 `AuthManager`를 사용하여 인증을 처리합니다.
Azure AD OAuth 2.0 플로우를 통해 사용자 인증을 수행합니다.

## 테스트

```bash
pytest mcp_onenote/tests/ -v
```

## 원본 모듈

이 모듈은 [KR365](https://github.com/kimghw/KR365) 레포지토리의 `modules/onenote_mcp`를 기반으로 리팩토링되었습니다.
