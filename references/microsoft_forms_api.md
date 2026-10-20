# Microsoft Forms — Graph 지원 여부와 비공식 formapi

2026-10-20 MCP 서버화 검토 중 웹 조사로 확인(실호출 검증 전).

## Graph 공식 지원: 없음

- 폼 생성·수정·질문 편집·응답 조회 **어느 것도 Graph 공식 엔드포인트가 없다**. Microsoft Q&A
  모더레이터 답변(2026-03): "Graph 는 Forms 응답을 직접 가져오는 지원 엔드포인트를 제공하지 않는다".
  https://learn.microsoft.com/en-us/answers/questions/5810347/extract-microsoft-forms-responses-data-using-api
- Graph 에 있는 Forms 관련 항목은 두 가지뿐:
  - 사용량 리포트(`reports/getFormsUserActivity*` 류, beta) — 활동 집계일 뿐 폼 내용이 아니다.
  - `OrgSettings-Forms.ReadWrite.All` — 테넌트 Forms 설정이다. 폼 생성 권한이 아니다.
- 공식 우회로: Power Automate Forms 커넥터("새 응답 제출 시" 트리거 + 응답 상세 조회). 폼 생성은 지원하지 않는다.

## 비공식 formapi (Forms 웹앱이 쓰는 내부 API)

- 문서도 없고 지원도 안 된다. 브라우저 개발자 도구로 역추적한 것이라 예고 없이 바뀔 수 있다.
- 호스트 이전 중: `forms.office.com` → `forms.cloud.microsoft` (2026 기준 코드들이 신규 호스트로 갱신됨).
- 토큰: Graph 토큰과 **별도**로 받아야 한다. scope `https://forms.cloud.microsoft/.default`
  (구 `https://forms.office.com/.default`). Entra 앱 등록의 "Microsoft Forms" API 권한.
  - 사용자 소유 폼: Application `Forms.Read.All`(관리자 동의) 사례가 있다.
  - 그룹 소유 폼: Delegated `Forms.Read` 만 된다(앱 권한 불가).
  - `Forms.ReadWrite` 같은 쓰기 권한 문서는 찾지 못했다 — 테넌트 앱 등록 화면에서 직접 확인해야 한다.
- 기본 경로: `https://forms.cloud.microsoft/formapi/api/{tenantId}/{users|groups}/{ownerObjectId}/light/forms`
  - 목록: `GET .../forms?$select=id,status,title,createdDate,modifiedDate,ownerId,version,softDeleted,type`
  - 메타: `GET .../forms('{formId}')?$select=id,title,description`
  - 질문: `GET .../forms('{formId}')?$select=questions&$expand=questions($expand=choices)`
  - 응답: `GET .../forms('{formId}')/responses?$expand=comments&$top={n}&$skip={offset}`
  - 응답 수: `GET .../forms('{formId}')?$select=rowCount`
- 생성·수정(POST/PATCH): 커뮤니티에서 "앱 권한으로 생성에 성공했다"는 댓글만 있다. 요청 형식(payload)이
  공개된 자료는 없다 — 웹앱 네트워크 탭을 캡처해야 알 수 있다.
- 출처: https://jackparker.co.uk/blog/unlocking-the-hidden-microsoft-forms-api-with-powershell-azure-app-registration/
  (2025-08 작성, 2026-08 갱신)

## 대안: Microsoft Lists(SharePoint 리스트) 폼

2024-03 공지(MC716006), 2024-05 배포. 리스트 열을 그대로 폼 문항으로 쓰는 기능.

- 제출 1건 = 리스트 항목 1개. 수집은 Graph 공식 API `GET /sites/{site-id}/lists/{list-id}/items?expand=fields`
  로 JSON 그대로 읽힌다(파싱 불필요). 리스트·열 생성도 Graph 공식(`POST /sites/{site-id}/lists`).
- 폼 자체 만들기·게시·"링크 복사"는 **UI 에서만** 한다 — API 언급을 찾지 못했다.
- 공유 범위는 "조직 내 링크가 있는 사람"만 된다. 게스트·외부·익명은 안 된다. 응답자는 로그인해야 한다.
- 응답자는 리스트나 다른 응답을 볼 수 없다. 리스트 편집 권한이 없는 사람에게는 Forms 메뉴가 숨겨진다.
- 제출 항목의 Created By 가 응답자로 찍히는지는 문서에 없다 — 실측 필요.
- 출처: https://mc.merill.net/message/MC716006 ,
  https://blog.topedia.com/2024/04/new-forms-experience-in-microsoft-lists-and-sharepoint-lists/
