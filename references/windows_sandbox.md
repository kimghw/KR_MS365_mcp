# Windows Sandbox — 자동화로 쓸 때의 동작과 제약

외부 시스템 지식 저장소. 프로젝트 내부 구현 이력은 [spec/spec_번들내보내기.md](../spec/spec_번들내보내기.md) 에 있다.

측정 환경: Windows 11 Pro 26200 (2026-09-16).

## 기본

- 기능 이름은 `Containers-DisposableClientVM`. Pro/Enterprise/Education 전용 — Home 에는 없다.
  ```powershell
  Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM   # State
  Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All   # 재부팅 필요
  ```
- 실행 파일: `%WINDIR%\System32\WindowsSandbox.exe`. `.wsb` 파일을 인자로 준다.
- **동시에 하나만 뜬다.** 두 번째 기동은 실패한다.
- 게스트는 매번 백지 Windows 다. Python·pip·개발 도구가 **없다**. 창을 닫는 순간 디스크가 사라진다.
- 게스트 사용자는 `WDAGUtilityAccount`, 관리자 권한. 데스크톱은
  `C:\Users\WDAGUtilityAccount\Desktop`.

## 프로세스 이름 (빌드마다 다르다)

26200 에서 실제로 보이는 것:

| 프로세스 | 역할 |
|---|---|
| `vmmemWindowsSandbox` | 컨테이너 메모리. **어느 빌드에서든 이게 있으면 샌드박스가 살아 있다** |
| `WindowsSandboxServer` | 호스트 측 서버 |
| `WindowsSandboxRemoteSession` | GUI 세션 |

`WindowsSandboxClient.exe` 는 **이 빌드에서는 보이지 않는다.** "이미 실행 중인가"를 판별할
때 클라이언트 이름만 보면 놓친다 — `vmmemWindowsSandbox` 를 같이 봐야 한다.

**2026-10-20 재관측(같은 26200, 누적 업데이트 뒤)**: 샌드박스가 떠 있는 동안 `vmmemWindowsSandbox` 와
`WindowsSandboxServer` 가 **보이지 않고** `WindowsSandboxRemoteSession` 만 보였다. `hcsdiag list` 도
실행 중인 컨테이너를 내놓지 않는다(`SavedAsTemplate` 한 줄뿐). `vmmemCmZygote` 는 샌드박스 기동과
무관하게 상주하므로 판별 근거가 못 된다. 그래서 "실행 중인가"는 세 이름을 모두 본다 —
`vmmemWindowsSandbox` / `WindowsSandboxClient` / `WindowsSandboxRemoteSession`. `tasklist` 는 이름을
25자로 잘라 `WindowsSandboxRemoteSessi` 로 찍으니 접두어로 비교한다. 이 빌드에서는 `RemoteSession` 을
`Stop-Process` 로 끝내면 VM 도 같이 내려간다(고아 없음, 곧바로 재기동 가능).

## 고아 VM 정리

`WindowsSandboxServer`/`RemoteSession` 을 강제 종료해도 `vmmemWindowsSandbox` 가 메모리를
쥔 채 남는다(1.6GB 관측). `Stop-Process` 는 Access Denied 로 거부된다. 컨테이너 관리
서비스를 재시작하면 정리된다:

```powershell
Restart-Service CmService -Force     # 관리자 권한 필요. 8초쯤 뒤 vmmem 사라짐
```

관련 서비스: `CmService`(Container Manager), `HvHost`, `vmcompute`.

## `.wsb` 설정

```xml
<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Default</Networking>          <!-- 인터넷 필요하면 Default/Enable -->
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <PrinterRedirection>Disable</PrinterRedirection>
  <MemoryInMB>6144</MemoryInMB>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>C:\host\path</HostFolder>
      <SandboxFolder>C:\Users\WDAGUtilityAccount\Desktop\name</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\...\runner.ps1" -Arg "v"</Command>
  </LogonCommand>
</Configuration>
```

- `LogonCommand` 는 **명령 하나만** 지원한다. 여러 단계면 스크립트 파일로 묶는다.
- 매핑 폴더는 읽기 전용으로도 걸 수 있다. 읽기 전용 매핑에서 Python 을 돌리면 `__pycache__`
  쓰기가 막히므로, 게스트 안 쓰기 가능 경로로 복사한 뒤 실행하는 편이 안전하다.
- 결과를 호스트로 빼내는 유일한 통로는 **쓰기 가능 매핑 폴더**다. 게스트가
  `shutdown /s` 를 부르면 샌드박스가 닫히므로, 남길 것은 전부 그 폴더에 쓴 뒤 종료해야 한다.

## 함정 1 — BOM 없는 `.ps1` 은 조용히 죽는다

게스트의 **Windows PowerShell 5.1** 은 BOM 없는 `.ps1` 을 UTF-8 이 아니라 ANSI 코드페이지
(한국어 Windows 는 cp949)로 읽는다. 한글 주석 한 줄이면 곧바로 파싱 오류가 나고,
`LogonCommand` 는 **아무 흔적도 남기지 않고** 끝난다 — 매핑 폴더가 텅 빈 채 시간 초과까지
간다. 8분을 태우고 나서야 원인을 알게 된다.

대응:

1. 러너 `.ps1` 은 **UTF-8 BOM(`EF BB BF`)** 으로 저장한다.
2. 게스트로 복사할 때 `utf-8-sig` 로 다시 써서 BOM 을 강제한다(누가 BOM 없이 저장해도 교정).
3. 보내기 전에 호스트에서 파싱만 해 본다 — 1초에 잡힌다:
   ```powershell
   $e = $null
   [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$e) | Out-Null
   if ($e.Count) { $e | % { "line $($_.Extent.StartLineNumber): $($_.Message)" } }
   ```

PowerShell 7 은 BOM 없는 UTF-8 을 올바로 읽지만, 게스트에는 5.1 만 있다.

## 함정 2 — 자동 변수를 덮어쓰지 말 것

`[CmdletBinding()]` 을 쓴 스크립트에서 `$args = "..."` 처럼 자동 변수를 대입하면 런타임에
깨진다. `$installArgs` 같은 다른 이름을 쓴다.

## 함정 3 — 진행 상황을 파일로 흘려야 한다 (그리고 그 파일에 BOM 이 붙는다)

호스트는 게스트 콘솔을 볼 수 없다. 단계마다 매핑 폴더에 `progress.json` 을 갱신하고,
끝나면 `done.json` 을 쓰는 식으로 해야 호스트가 "살아 있는지 / 어디서 멈췄는지"를 안다.
`Start-Transcript` 로 전체 로그를 같이 남겨 두면 실패 분석이 쉽다.

**그 JSON 을 `Set-Content -Encoding utf8` 로 쓰면 안 된다.** Windows PowerShell 5.1 에서
`-Encoding utf8` 은 **BOM 을 붙인다.** 호스트가 `json.loads(path.read_text(encoding="utf-8"))`
로 읽으면 매번 `JSONDecodeError` 가 나고, 결과적으로 **게스트는 다 통과했는데 호스트만 시간
초과로 끝나는 유령 실패**가 된다(2026-09-16 실제로 겪었다 — 14/14 통과한 실행을 실패로 보고했다).

양쪽 다 막는다:

```powershell
# 게스트: BOM 없이 쓴다 (PS 5.1 에는 -Encoding utf8NoBOM 이 없다)
$json = $value | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))
```

```python
# 호스트: BOM 이 있어도 읽는다
json.loads(path.read_text(encoding="utf-8-sig"))
```

## 게스트에 Python 을 챙기는 가장 쉬운 방법: uv

아래 "함정 4"의 설치본 문제도, 임베디드 배포판의 `._pth` 손질도, uv 를 쓰면 **둘 다 필요 없다.**
uv 는 단일 실행 파일이라 Python 없이 설치되고, `.python-version` 을 보고 Python 을 직접 받아온다.

```powershell
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Invoke-WebRequest "https://astral.sh/uv/install.ps1" -OutFile $uvInstall -UseBasicParsing
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uvInstall

# 설치 스크립트가 PATH 를 고쳐도 **현재 세션에는 반영되지 않는다** — 직접 찾는다.
$uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"

Push-Location $project
& $uv sync --frozen        # Python 조달 + 잠금 그대로 설치, 한 번에
& $uv run --frozen <스크립트>
```

실측(2026-09-16, Windows 11 26100 게스트): uv 설치 **~6초**, `uv sync --frozen`(77 패키지)
**~9초**. 관리자 권한도, 재부팅도, PATH 손질도 없다. 같은 일을 python.org 설치본 + pip 으로
하면 4~8분이었다.

`$env:UV_NO_PROGRESS = "1"` 을 켜 두면 로그가 진행 막대로 뒤덮이지 않는다.

## 함정 4 — 공식 Python 설치본이 `/quiet` 로 멎는다

`python-3.12.10-amd64.exe` 를 `/quiet` 로 돌렸더니 **15분 무응답**이었다(2026-09-16 관측).
다운로드(25.7MB)는 정상이었고 그 다음 단계에서 진행이 멈췄다. 게스트 콘솔이 안 보여 원인은
확정하지 못했다 — WiX burn 부트스트래퍼가 자식 프로세스로 재기동하는 구조라 `Start-Process
-Wait` 의 대기 의미와 얽혔을 가능성이 있다.

대응은 둘 다 해 둔다:

1. **대기에 상한을 건다.** `-Wait` 대신 `WaitForExit(ms)` 를 써서 멎으면 보고하고 죽인다.
   ```powershell
   $proc = Start-Process $installer -ArgumentList $installArgs -PassThru
   if (-not $proc.WaitForExit(300 * 1000)) { $proc.Kill(); throw "설치본이 300초 안에 안 끝났다" }
   ```
2. **임베디드 배포판을 기본으로 쓴다.** 설치 프로그램이 없어 멎을 구석이 없다.

### 임베디드 배포판으로 Python 준비하기 (권장)

```powershell
$ProgressPreference = 'SilentlyContinue'                       # 없으면 다운로드가 몇 배 느리다
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Invoke-WebRequest "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip" `
                  -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath C:\Py312 -Force

# 임베디드는 site 를 끄고 site-packages 를 경로에서 뺀다 — pip 로 깐 패키지를 import 하려면
# ._pth 를 다시 써야 한다. 이 4줄을 빼먹으면 pip 는 되는데 import 가 안 된다.
@("python312.zip", ".", "Lib\site-packages", "import site") |
    Set-Content -Path C:\Py312\python312._pth -Encoding ascii

Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing
& C:\Py312\python.exe $getPip --no-warn-script-location
```

`._pth` 파일 이름은 버전에서 온다: 3.12.x → `python312._pth`. 임베디드에는 `sqlite3`·`ssl`
확장이 들어 있어 SQLite 토큰 저장과 HTTPS 호출은 그대로 된다. 없는 것은 `tkinter`·`venv`
같은 것들이다.

`winget` 은 있을 때도 없을 때도 있어 믿지 않는다.

## 소요 시간 (파이썬 프로젝트 하나를 세워 돌리기까지, 실측)

6개 MCP 서버 + 77개 의존성 기준. **uv 경로**(2026-09-16, 2회 측정):

| 단계 | 대략 |
|---|---|
| 부팅 + 로그온 + 매핑 폴더에서 복사 | 21~24초 |
| uv 설치 (`install.ps1`) | ~6초 |
| `uv sync --frozen` (Python 조달 + 77 패키지) | ~9초 |
| 서버 6개 기동 + `/health` 확인 | ~21초 |
| **전체** | **약 63초** |

같은 일을 **pip 경로**로 하면 4~8분이었다 (참고용, 이제 쓰지 않는다):

| 단계 | 대략 |
|---|---|
| Python 다운로드 | 임베디드(~10MB) 10~30초 / 설치본(25.7MB) 10~60초 |
| Python 준비 | 임베디드 압축 해제 수 초 / **설치본은 멎을 수 있다(함정 4)** |
| `get-pip.py` | 20~60초 |
| `pip install` (휠 캐시 없음) | 60~180초 |

타임아웃은 넉넉히 잡아 두는 편이 낫다 — 회선이 느리면 다운로드 구간이 늘어난다.

## 호스트 프로세스가 죽으면 샌드박스도 죽는다

`WindowsSandbox.exe` 를 그냥 자식 프로세스로 띄우면, 띄운 쪽이 죽을 때(시간 초과, Ctrl+C,
잡 오브젝트 정리) 샌드박스가 같이 끌려 내려간다. 게스트 상태를 사후에 들여다볼 수 없게 되므로
분리해서 띄운다:

```python
subprocess.Popen([sandbox_exe, wsb],
                 creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                 close_fds=True)
```
