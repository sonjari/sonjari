param(
    [string]$Destination = "C:\RoboMetaFit\tools\alture-jarvis"
)

$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $PSScriptRoot
$ResolvedParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $Destination))
$AllowedParent = [System.IO.Path]::GetFullPath("C:\RoboMetaFit\tools")

if ($ResolvedParent.TrimEnd('\') -ne $AllowedParent.TrimEnd('\')) {
    throw "Destination must be a direct child of C:\RoboMetaFit\tools"
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
foreach ($Directory in @("src", "scripts", "tests", "docs", "knowledge", "recipes", "skills", "packs")) {
    $TargetDirectory = Join-Path $Destination $Directory
    New-Item -ItemType Directory -Force -Path $TargetDirectory | Out-Null
    Copy-Item -Path (Join-Path $Source "$Directory\*") -Destination $TargetDirectory -Recurse -Force
}
foreach ($File in @("pyproject.toml", "requirements.txt", "requirements-hardware.txt", "requirements-torch-cuda.txt", "requirements-stt-cuda.txt", "requirements-tts.txt", ".env.example", "README.ko.md", "TODO.ko.md")) {
    Copy-Item -LiteralPath (Join-Path $Source $File) -Destination (Join-Path $Destination $File) -Force
}

# ★ **화면은 exe 에 구워진다** — 소스만 옮기면 옛 화면이 그대로 뜬다.
#
#   `frontendDist` 방식이라 `npm run build` 로 만든 dist 가 `tauri build` 때
#   exe 안에 들어간다. 이 스크립트는 오랫동안 `src` 만 옮겼고, 그래서 이틀 낡은
#   화면을 보며 파이썬을 디버깅한 적이 있다.
#
#   **돌고 있으면 덮어쓸 수 없다**(윈도우가 잠근다). 그때는 조용히 넘어가지 말고
#   말해 준다 — 조용히 실패하면 다음 사람이 또 옛 화면을 본다.
# 굽는 자리를 다른 디스크로 옮겼으면(cargo 의 표준 환경변수 CARGO_TARGET_DIR) 거기서 가져온다. 비우면 예전 자리.
$HudSource = if ($env:CARGO_TARGET_DIR) { Join-Path $env:CARGO_TARGET_DIR "release\alture-jarvis-hud.exe" } else { Join-Path $Source "ui\src-tauri\target\release\alture-jarvis-hud.exe" }
$HudTarget = Join-Path $Destination "ui\alture-jarvis-hud.exe"
if (Test-Path -LiteralPath $HudSource) {
    New-Item -ItemType Directory -Force -Path (Split-Path $HudTarget) | Out-Null
    $running = Get-Process alture-jarvis-hud -ErrorAction SilentlyContinue
    if ($running) {
        Write-Warning "화면(exe)이 실행 중이라 못 바꿨다 — 자비스 창을 닫고 다시 돌려라 (PID $($running.Id -join ', '))"
    } else {
        try {
            Copy-Item -LiteralPath $HudSource -Destination $HudTarget -Force
            Write-Host "화면(exe) 갱신: $((Get-Item $HudSource).LastWriteTime)"
        } catch {
            Write-Warning "화면(exe) 복사 실패 — $($_.Exception.Message)"
        }
    }
}

# Python 소스만 바뀐 뒤 낡은 bytecode가 런타임을 가리지 않게 한다. 삭제 경계는
# 위에서 검증한 Destination의 src 아래로 다시 제한한다.
$RuntimeSrc = [System.IO.Path]::GetFullPath((Join-Path $Destination "src"))
$AllowedRuntime = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
if (-not $RuntimeSrc.StartsWith($AllowedRuntime, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Runtime src escaped destination: $RuntimeSrc"
}
$Caches = @(Get-ChildItem -LiteralPath $RuntimeSrc -Directory -Filter "__pycache__" -Recurse -ErrorAction SilentlyContinue)
foreach ($Cache in $Caches) {
    $ResolvedCache = [System.IO.Path]::GetFullPath($Cache.FullName)
    if (-not $ResolvedCache.StartsWith($RuntimeSrc.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove cache outside runtime src: $ResolvedCache"
    }
    Remove-Item -LiteralPath $ResolvedCache -Recurse -Force
}

Write-Host "Synced ALTURE JARVIS to $Destination (data, outputs and .venv preserved; pycache removed: $($Caches.Count))"
