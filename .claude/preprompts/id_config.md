---
description: Debug ID Configuration (MCP Tool Editor) (project)
---

> **공통 지침**: 작업 전 [common.md](common.md) 참조

# Debug ID Configuration (MCP Tool Editor)

Source file: `mcp_editor/templates/tool_editor.html`

## How to Find an ID (UI -> DevTools -> Code)
- UI: hover elements to see a tooltip with the ID and inline handlers; click the `IDs` button to show labels on elements.
- DevTools (Elements search): `[data-debug-id="BTN_SAVE"]` or `[data-debug-auto-id="a1"]`.
- Console:
  - `document.querySelector('[data-debug-id="BTN_SAVE"]')`
  - `document.querySelector('[data-debug-auto-id="a1"]')`
- Code search:
  - `rg 'BTN_SAVE' mcp_editor/templates/tool_editor.html`
  - If you need the handler, search the `onclick` function name (ex: `rg 'saveTools' mcp_editor/templates/tool_editor.html`).

## Categories and Colors
- AREA_*: orange `#ff8c00` (`.debug-id-label.area`)
- BTN_*: blue `#1d4ed8` (default `.debug-id-label`)
- FIELD_*: teal `#0f766e` (`.debug-id-label.field`)

## Classification Rules
- `refreshDebugIndexes()` processes in order: areas -> buttons -> fields.
- `getDebugTargets()`:
  - Buttons: all `<button>` elements (filtered by `isValidDebugTarget`).
  - Fields: `input/textarea/select` that are text-like.
  - Areas: non-button/field elements with `data-debug-id` starting `AREA_`.
  - Other manual targets: if `input/textarea/select` -> field, else -> button.
- `data-debug-skip` (or ancestor) excludes elements.
- Overlay/tooltip elements are excluded.

## ID Sources
- Manual: `data-debug-id` if present and not `data-debug-auto="1"`.
- Legacy: `data-fixed-debug-id` if manual missing.
- Auto: generated when no manual/legacy ID:
  - Area auto IDs: `a1`, `a2`, ...
  - Button auto IDs: `1`, `2`, ...
  - Field auto IDs: `f1`, `f2`, ...
- Auto IDs stored via `data-debug-auto="1"` and `data-debug-auto-id`.
- Inline handlers are captured into `data-debug-actions` for hover tooltip.

---

## 관련 파일 경로

### 핵심 파일
- `mcp_editor/templates/tool_editor.html` - 웹에디터 HTML (Debug ID 시스템 구현)
- `mcp_editor/tool_editor_web.py` - 웹에디터 서버

### JavaScript 함수 위치 (tool_editor.html 내)
- `refreshDebugIndexes()` - Debug ID 인덱스 갱신
- `getDebugTargets()` - Debug 대상 요소 수집
- `isValidDebugTarget()` - 유효한 대상 판별
- `toggleDebugLabels()` - Debug 라벨 표시/숨기기

### CSS 클래스 (tool_editor.html 내)
- `.debug-id-label` - 기본 라벨 스타일 (파란색)
- `.debug-id-label.area` - AREA 라벨 스타일 (주황색)
- `.debug-id-label.field` - FIELD 라벨 스타일 (청록색)

---

## 사용법

### 웹에디터에서 Debug ID 확인
1. 웹에디터 실행: `python mcp_editor/tool_editor_web.py`
2. 브라우저에서 http://localhost:8080 접속
3. 상단 툴바의 `IDs` 버튼 클릭하여 라벨 표시
4. 요소에 마우스 호버하여 툴팁으로 상세 정보 확인

### 개발자 도구에서 검색
```javascript
// 특정 Debug ID 찾기
document.querySelector('[data-debug-id="BTN_SAVE"]')

// 모든 버튼 찾기
document.querySelectorAll('[data-debug-id^="BTN_"]')

// 자동 생성된 ID 찾기
document.querySelectorAll('[data-debug-auto="1"]')
```

### 코드에서 검색
```bash
# Debug ID 검색
rg 'data-debug-id="BTN_' mcp_editor/templates/tool_editor.html

# 핸들러 함수 검색
rg 'onclick="saveTools' mcp_editor/templates/tool_editor.html

# 특정 영역 검색
rg 'AREA_PROFILE_TABS' mcp_editor/templates/tool_editor.html
```

---

## 체크리스트

Debug ID 추가/수정 시:
- [ ] 카테고리별 네이밍 규칙 준수 (AREA_*, BTN_*, FIELD_*)
- [ ] 중복 ID 없는지 확인
- [ ] 동적 생성 요소는 인덱스 포함 (TOOL_0, PROFILE_1)
- [ ] data-debug-skip으로 제외 필요한 요소 표시
- [ ] refreshDebugIndexes() 호출하여 인덱스 갱신

---

## 관련 파일

| 파일 | 설명 |
|------|------|
| `mcp_editor/static/js/tool_editor_dashboard.js` | 대시보드 UI (Debug ID 사용) |
| `mcp_editor/static/js/tool_editor_derive.js` | 파생 서버 UI |
| `mcp_editor/static/js/tool_editor_server.js` | 서버 제어 UI |

---
*Last Updated: 2026-01-11*