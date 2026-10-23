# Python 로깅·HTTP 클라이언트 — 보안 관련 동작

## uvicorn `AccessFormatter` 는 `record.args` 를 5개로 언팩한다 (0.53 확인)
- `uvicorn.logging.AccessFormatter.formatMessage()` 는
  `client_addr, method, full_path, http_version, status_code = record.args` 를 한다. access 로그에서
  query string 등을 지우는 필터가 `record.args` 를 문자열 하나로 합치거나 개수를 바꾸면 포맷 단계에서
  `ValueError` 가 난다 — **튜플 모양(5개)은 유지하고 원소만** 고쳐야 한다(예: `full_path` 의 `?` 뒤 제거).

## `logging.config.dictConfig` 는 logger 의 기존 filter 를 지우지 않는다
- 설정에 이름이 있는 logger 는 기존 **handler 를 모두 제거**하고 새 handler 를 붙이지만, 기존
  **filter 는 그대로 둔다**(설정의 `filters` 는 추가만). uvicorn 처럼 기동 시 `dictConfig` 를 다시 부르는
  라이브러리가 있어도, 민감정보 필터를 handler 가 아니라 **logger 에** 붙이면 살아남는다.
- 설정에 없는 기존 logger 는 `disable_existing_loggers=True`(기본)면 비활성화된다.
- https://docs.python.org/3/library/logging.config.html

## aiohttp 는 다른 origin 으로 redirect 할 때 `Authorization` 을 떼어낸다 (3.14 확인)
- `ClientSession` 이 redirect 를 따라갈 때 요청 URL 과 redirect 대상의 **origin(scheme·host·port)** 이
  다르면 `Authorization`·`Cookie`·`Proxy-Authorization` 헤더와 `auth` 를 제거한다. 같은 origin 이면 유지한다.
- 그래도 bearer 를 실은 요청은 `allow_redirects=False` 로 redirect 를 직접 다루는 편이 안전하다 — 같은
  origin 안의 다른 경로로 가는 redirect 에는 헤더가 그대로 실리고, 사전 서명 URL 로 가는 요청에는 처음부터
  Authorization 을 붙이지 않아야 한다.
