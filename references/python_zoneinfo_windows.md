# Python zoneinfo 와 Windows

- `zoneinfo.ZoneInfo` 는 OS 의 IANA 시간대 DB(`/usr/share/zoneinfo`)를 읽는다. **Windows 에는
  그 DB 가 없어서** `ZoneInfo("Asia/Seoul")` 은 물론 `ZoneInfo("UTC")` 까지
  `ZoneInfoNotFoundError` 로 실패한다.
- 해결: PyPI `tzdata` 패키지를 설치하면 zoneinfo 가 그것을 폴백으로 쓴다. 의존성 선언은
  `tzdata; sys_platform == 'win32'` 처럼 조건부로 두면 된다(pandas 가 쓰는 방식과 동일).
- `ZoneInfo("UTC")` 를 폴백으로 쓰면 같은 이유로 또 실패하므로, 안전한 폴백은
  `datetime.timezone.utc` 다.
- https://docs.python.org/3/library/zoneinfo.html
