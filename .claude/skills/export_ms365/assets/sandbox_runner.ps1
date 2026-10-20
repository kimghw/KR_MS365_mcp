<#
    Windows Sandbox 안에서 도는 검증 러너.

    샌드박스는 매번 백지 상태다 — Python 도 pip 도 없다. 그래서 "받은 사람이 하는 일"을
    그대로 한다: uv 를 깔고, `uv sync --frozen` 으로 잠금 그대로 환경을 만들고, 번들을 돌린다.
    이 스크립트가 통과하면 그 번들은 남의 PC 에서도 뜬다고 볼 수 있다.

    Python 을 따로 챙기지 않는다 — `.python-version` 을 보고 uv 가 받아온다. 전에는 python.org
    설치본을 `/quiet` 로 돌렸는데 15분 무응답으로 멎었고(2026-09-16), 임베디드 zip 은 `._pth`
    를 손보고 get-pip 을 따로 받아야 했다. uv 로 오면서 그 단계가 통째로 사라졌다.

    매핑 (sandbox_test.py 가 .wsb 에 적는다)
        C:\Users\WDAGUtilityAccount\Desktop\bundle_src  (읽기 전용) — 번들 원본
        C:\Users\WDAGUtilityAccount\Desktop\out         (쓰기 가능) — 결과가 호스트로 나가는 통로

    호스트는 out\done.json 이 생기는 것을 기다린다. 어떤 경로로 실패하든 done.json 은 쓴다.
#>

[CmdletBinding()]
param(
    [string]$Src        = "C:\Users\WDAGUtilityAccount\Desktop\bundle_src",
    [string]$Out        = "C:\Users\WDAGUtilityAccount\Desktop\out",
    [string]$Work       = "C:\work",
    [string]$BundleName = "",
    [int]$StepTimeoutSec = 600,
    [switch]$NoShutdown
)

$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

New-Item -ItemType Directory -Force -Path $Out  | Out-Null
New-Item -ItemType Directory -Force -Path $Work | Out-Null

$steps  = New-Object System.Collections.ArrayList
$logPath = Join-Path $Out "runner.log"
Start-Transcript -Path $logPath -Force | Out-Null

# `Set-Content -Encoding utf8` 은 Windows PowerShell 5.1 에서 **BOM 을 붙인다.** 그러면
# 호스트의 json.loads 가 매번 JSONDecodeError 를 내서, 검사는 다 통과했는데 호스트만
# 시간 초과로 끝나는 유령 실패가 된다(2026-09-16 실제로 겪었다). BOM 없이 쓴다.
function Write-JsonFile {
    param([string]$Path, [object]$Value, [int]$Depth = 6)
    $json = $Value | ConvertTo-Json -Depth $Depth
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Write-Progress-File {
    param([string]$Stage, [string]$State, [string]$Detail = "")
    $null = $steps.Add([pscustomobject]@{
        stage  = $Stage
        state  = $State
        detail = $Detail
        at     = (Get-Date).ToString("s")
    })
    Write-JsonFile -Path (Join-Path $Out "progress.json") -Depth 5 -Value ([pscustomobject]@{
        current = $Stage; state = $State; steps = $steps
    })
    Write-Host "[$State] $Stage $Detail"
}

function Complete-Run {
    param([bool]$Ok, [string]$Stage, [string]$Detail)
    Write-JsonFile -Path (Join-Path $Out "done.json") -Value ([pscustomobject]@{
        ok      = $Ok
        stage   = $Stage
        detail  = $Detail
        steps   = $steps
        at      = (Get-Date).ToString("s")
    })

    try { Stop-Transcript | Out-Null } catch { }

    if (-not $NoShutdown) {
        Start-Sleep -Seconds 3
        shutdown /s /t 2 /f
    }
}

try {
    # ---- 1. 번들을 쓰기 가능한 위치로 복사 -------------------------------
    Write-Progress-File -Stage "copy" -State "running"
    if (-not (Test-Path $Src)) { throw "매핑된 번들 폴더가 없다: $Src" }
    if ([string]::IsNullOrWhiteSpace($BundleName)) {
        # _runner 는 이 스크립트가 실려 온 자리다 — 번들이 아니다.
        $BundleName = (Get-ChildItem -Path $Src -Directory |
                       Where-Object { $_.Name -ne '_runner' } |
                       Select-Object -First 1).Name
    }
    if (-not $BundleName) { throw "$Src 아래에 번들 디렉터리가 없다" }
    $bundle = Join-Path $Work $BundleName
    if (-not (Test-Path (Join-Path $Src $BundleName))) { throw "번들이 없다: $Src\$BundleName" }
    Copy-Item -Path (Join-Path $Src $BundleName) -Destination $Work -Recurse -Force
    Write-Progress-File -Stage "copy" -State "ok" -Detail $bundle

    # ---- 2. uv 설치 ------------------------------------------------------
    # 공식 설치 스크립트. Python 이 없어도 되고 관리자 권한도 필요 없다.
    Write-Progress-File -Stage "uv-install" -State "running"
    $uvInstall = Join-Path $Work "uv-install.ps1"
    Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile $uvInstall -UseBasicParsing
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uvInstall 2>&1 |
        Tee-Object -FilePath (Join-Path $Out "uv-install.log")

    # 설치 스크립트가 PATH 를 고쳐도 현재 세션에는 반영되지 않는다 — 직접 찾는다.
    $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (-not (Test-Path $uv)) {
        $found = Get-Command uv -ErrorAction SilentlyContinue
        if ($found) { $uv = $found.Source } else { throw "uv 설치 후에도 uv.exe 를 찾지 못했다 — out\uv-install.log 참조" }
    }
    $uvVer = (& $uv --version) -join " "
    Write-Progress-File -Stage "uv-install" -State "ok" -Detail $uvVer

    # ---- 3. 환경 구성 (Python 조달 + 의존성) -----------------------------
    # `uv sync --frozen` 하나로 끝난다: .python-version 을 보고 Python 을 받아오고,
    # uv.lock 에 적힌 조합 그대로 설치한다. --frozen 이라 재해석하지 않는다 —
    # 잠금이 실제로 재현되는지 보는 것이 이 검증의 핵심이다.
    Write-Progress-File -Stage "uv-sync" -State "running"
    if (-not (Test-Path (Join-Path $bundle "uv.lock"))) { throw "uv.lock 이 번들에 없다" }
    $env:UV_NO_PROGRESS = "1"
    Push-Location $bundle
    & $uv sync --frozen 2>&1 | Tee-Object -FilePath (Join-Path $Out "uv-sync.log")
    $syncExit = $LASTEXITCODE
    if ($syncExit -eq 0) {
        & $uv pip freeze | Set-Content -Path (Join-Path $Out "pip-freeze.txt") -Encoding utf8
    }
    Pop-Location
    if ($syncExit -ne 0) { throw "uv sync --frozen 실패 (exit=$syncExit) — out\uv-sync.log 참조" }
    Write-Progress-File -Stage "uv-sync" -State "ok"

    # ---- 4. 번들 자체 점검 (import + 스키마 + /health) -------------------
    Write-Progress-File -Stage "verify" -State "running"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    Push-Location $bundle
    & $uv run --frozen verify_bundle.py --http --out (Join-Path $Out "result.json") 2>&1 |
        Tee-Object -FilePath (Join-Path $Out "verify.log")
    $verifyExit = $LASTEXITCODE
    Pop-Location

    if ($verifyExit -ne 0) {
        Write-Progress-File -Stage "verify" -State "fail" -Detail "exit=$verifyExit"
        Complete-Run -Ok $false -Stage "verify" -Detail "verify_bundle.py 가 실패했다 (exit=$verifyExit) — out\result.json 참조"
        exit 1
    }

    Write-Progress-File -Stage "verify" -State "ok"
    Complete-Run -Ok $true -Stage "verify" -Detail "모든 검사 통과"
    exit 0
}
catch {
    $msg = $_.Exception.Message
    Write-Progress-File -Stage "error" -State "fail" -Detail $msg
    Complete-Run -Ok $false -Stage "error" -Detail $msg
    exit 1
}
