# Microsoft Graph API — 동작·제약 메모 (프로젝트 무관 재사용 지식)

## 메시지 페이징 (`/me/messages`)
- 공식 방식은 응답의 `@odata.nextLink` 를 따라가는 것이다. `$skip` 을 직접 계산해 병렬로
  받으면 조회 중 새 메일이 들어올 때 페이지 경계가 밀려 **같은 메일이 두 페이지에 걸치고
  한 통이 빠질 수 있다**. 병렬 조회를 유지하려면 최소한 `id` 로 중복 제거해야 한다.
- https://learn.microsoft.com/en-us/graph/api/user-list-messages

## calendarView 의 시간 파라미터
- `startDateTime` / `endDateTime` 은 ISO 8601. **오프셋이 없으면 UTC 로 해석**되며
  `Prefer: outlook.timezone` 헤더는 응답 표시 시간대만 바꾸고 파라미터 해석에는 영향이 없다.
- 값에 `+09:00` 처럼 `+` 가 들어가면 쿼리 문자열에서 공백으로 읽히므로 반드시 퍼센트
  인코딩(`%2B`)한다.
- https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview

## OneDrive 경로 주소 지정 (`/me/drive/root:/{path}`)
- 경로는 URL 경로 조각 규칙으로 인코딩해야 한다. `#` 은 fragment 로, `%` 는 이스케이프 시작으로,
  `?` 는 쿼리 시작으로 읽혀 **다른 아이템을 가리키거나 경로가 잘린다** (`report#v2.txt` → `report`).
  `/` 만 구분자로 남기고 `urllib.parse.quote(path, safe="/")`.
- `search(q='...')` 의 OData 문자열 리터럴은 `'` 를 `''` 로 두 번 적는다.
- https://learn.microsoft.com/en-us/graph/onedrive-addressing-driveitems

## 공유 URL 로 아이템 조회 (`/shares/{token}/driveItem`)
- 토큰 = `"u!"` + base64url(공유 URL) 에서 `=` 패딩 제거. **`u!` 접두사가 없으면 400**.
- https://learn.microsoft.com/en-us/graph/api/shares-get#encoding-sharing-urls

## 5,000개 제한
- OneNote `/sections/{id}/pages` 는 섹션당 5,000개를 넘기면 403. 전체 페이지(`/me/onenote/pages`)
  기준으로 돌면 회피된다 — 프로젝트 내 적용은 [graph_onenote_patch.md](graph_onenote_patch.md).

## `/me` 는 로그인 사용자의 별칭
- delegated 토큰에서 `/me/...` 는 `/users/{로그인 사용자 id 또는 UPN}/...` 과 같은 리소스를 가리킨다.
  그래서 "현재 사용자 경로만 허용"하는 URL 정책은 `/me/...` 와 `/users/{자기 id·UPN}/...` 를 둘 다
  받아야 하고, `/users/{다른 사용자}/...` 는 따로 막아야 한다(Graph 가 공유 권한으로 허용할 수 있다).
- app-only(클라이언트 자격증명) 토큰에는 로그인 사용자가 없어 `/me` 를 쓸 수 없다.
- https://learn.microsoft.com/en-us/graph/call-api#me
