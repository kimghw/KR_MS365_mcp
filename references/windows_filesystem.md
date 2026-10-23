# Windows 파일시스템 — 경로·핸들·append 동작 (Python 기준)

## `ntpath.join` 은 드라이브 성분에서 루트를 버린다
- 두 번째 인자가 `x:...` 형태(드라이브 지정)면 앞의 루트를 버리고 그 드라이브로 바꾼다.
  `ntpath.join(r"D:\data\files", "a:b")` → `'a:b'` (A: 드라이브의 상대경로). `pathlib.PureWindowsPath`
  의 `/` 도 같다. 같은 드라이브 문자면(`"d:evil"`) 루트 뒤에 붙고, `"\x"` 는 그 드라이브의 루트로 간다.
- 원격 파일명처럼 신뢰할 수 없는 이름을 결합할 때는 `:` 와 구분자를 먼저 제거하고, 결합 결과가
  루트 안인지 **결합한 뒤에** 다시 확인해야 한다. NTFS 에서 `name:stream` 은 ADS(대체 데이터 스트림)다.

## `GetFinalPathNameByHandleW` 는 `\\?\` 접두사를 붙인다
- 열린 핸들의 실제 경로(junction·symlink·mount point 를 해소한 경로)를 돌려주며 형식은
  `\\?\C:\...` 또는 UNC 면 `\\?\UNC\server\share\...` 다(`VOLUME_NAME_DOS`). `os.path.realpath`
  결과와 비교하려면 접두사를 벗기고(`\\?\UNC\` → `\\`) 대소문자 무시로 비교한다.
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew

## append 모드 `"a"` 는 프로세스 사이에서 원자적이지 않다
- Windows CRT 의 append(`open(..., "a")`, `O_APPEND`)는 매 write 전에 파일 끝으로 seek 한 뒤 쓰는
  **에뮬레이션**이다. 여러 프로세스가 같은 파일에 동시에 쓰면 줄이 겹쳐 덮일 수 있다.
- `CreateFileW` 에 **`FILE_APPEND_DATA` 만**(+ `SYNCHRONIZE`, `FILE_WRITE_DATA` 없이) 요청해 연 핸들은
  OS 가 매 `WriteFile` 을 파일 끝에 원자적으로 붙인다 — 한 번의 write 에 한 줄을 쓰면 섞이지 않는다.
  POSIX 의 `O_APPEND` 는 커널이 원자적으로 처리한다.
- https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants
