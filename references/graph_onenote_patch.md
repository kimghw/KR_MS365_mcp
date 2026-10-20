# Microsoft Graph OneNote — 페이지 내용 PATCH(update) 로 확인한 사실

대상: `PATCH /me/onenote/pages/{id}/content` (본문 JSON 배열 `[{ target, action, content, position? }]`),
`GET /me/onenote/pages/{id}/content?includeIDs=true`. 2026-09-27 kr_ext_rerp(확장 Plus 예상 비용 동기화)
개발 중 실제 호출로 확인. 문서: https://learn.microsoft.com/graph/onenote-update-page

## replace 가 되는 target / 안 되는 target

| target 지정 | 요소 | 결과 |
|---|---|---|
| 생성 id (`table:{guid}{n}`, includeIDs=true 로 받은 값) | table | **성공**. 새 표에도 content 의 `data-id` 가 남는다 (생성 id 는 새로 바뀜) |
| `#data-id` (예 `#krx-plan`) | table | 500 `19999 "Something failed, the API cannot share any more information"` |
| `#data-id` | p, ul | 400 |
| 어떤 방식이든 | div | 400 `20141 "The PATCH target DIV for action replace is not supported."` |

→ "페이지의 한 블록을 매번 통째로 갱신"하려면 **표 하나**로 만들고, 읽을 때 `includeIDs=true` 로 받은
그 표의 **생성 id** 를 target 으로 `replace` 한다. div 는 append/prepend 의 컨테이너로만 쓴다.

## append / 읽기

- `append` (target `body`) 에 `<table data-id="…">` 를 넣으면 `data-id` 가 보존된다. `<p data-id>`, `<div data-id>`, `<ul data-id>` 도 보존.
- `div` 에 `append` (target `#data-id`) 는 된다(자식 추가).
- 기본 GET 응답에는 `id` 도 `data-id` 도 없다. `includeIDs=true` 여야 둘 다 온다.
- 되돌려 주는 HTML 은 정규화된다: 속성 순서·`style` 재작성(`border="1"` → `style="border:1px solid;border-collapse:collapse"`),
  `<b>` → `<span style="font-weight:bold">`, `·` → `&#183;`, 빈 셀 → `<br />`, 들여쓰기·줄바꿈 삽입.
  텍스트 자체는 보존되므로 기계용 값은 base64 로 넣으면 안전하다.

## 링크와 id

- OneNote "페이지 링크 복사"의 페이지 GUID(웹 `wd=target(섹션.one|{섹션 GUID}/{제목}|{페이지 GUID}/)`,
  클라이언트 `onenote:…&page-id={GUID}&end`)는 Graph `page id`(`1-<32 hex>!<n>-<섹션 GUID>`)와 **다르다**.
  대응은 페이지의 `links.oneNoteWebUrl.href`(같은 wd=target 형식)에 든 GUID 로 찾는다.
  `sourcedoc={GUID}` 는 문서 GUID 라 무관.
- 섹션 GUID 는 Graph 섹션 id 의 `1-` 뒤와 같다.
