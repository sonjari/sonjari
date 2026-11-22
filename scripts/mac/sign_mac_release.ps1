# 맥 업데이트 서명 — 대표가 PC 터미널에서 한 번 (2026-11-22 · docs/설계_맥앱안업데이트_2026-11-22.ko.md §3-3)
#
#   powershell -ExecutionPolicy Bypass -File scripts\mac\sign_mac_release.ps1 -Version 0.4.51
#
# 하는 일: ① 앱 꾸러미(.app.tar.gz)를 서명(.sig) ② 파이썬 묶음 · 목록(sonjari-mac.json)을 만들고 목록 서명 ③ latest.json.
# ★ 암호는 이 창에서 한 번만 묻고, 이 창의 자식 프로그램 환경에만 잠깐 넣었다가 지운다. 화면 · 파일 · 기록에 남기지 않는다.
#   (11-16 결정: 비밀 열쇠는 C:\keys · 암호는 대표가 직접 넣는다 — 클로드는 넣지 않는다.)
# ★ 파이썬 묶음은 같은 판 앱에서만 받게 한다(--min-app-version) — 옛 앱이 파이썬만 어설프게 바꾸지 않고 앱 꾸러미부터 받게.
# ★ 올리기(gh release)는 하지 않는다. 끝에 올릴 파일 목록만 보여 준다.
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Tag = "",
    [string]$Folder = "",
    [string]$KeyPath = "C:\keys\sonjari-mac-update.key"
)
$ErrorActionPreference = "Stop"
# 한글 경로를 자식 프로그램 인자로 넘기면 조용히 죽는다(사고 J-2) — 저장소로 옮겨 가 상대 경로로 부른다.
Set-Location (Join-Path $PSScriptRoot "..\..")
if (-not $Tag) { $Tag = "v$Version-mac" }
if (-not $Folder) { $Folder = "..\..\generated_reports\mac_release_$Version" }
$tarName = "Sonjari-$Version-mac-arm64.app.tar.gz"
$tarball = Join-Path $Folder $tarName
if (-not (Test-Path $tarball)) { throw "앱 꾸러미가 없습니다: $tarball (맥 굽기의 dist 에서 가져와 주세요)" }
if (-not (Test-Path $KeyPath)) { throw "서명 열쇠가 없습니다: $KeyPath (외장 SSD 를 꽂았는지 보세요)" }
$tauri = "ui\node_modules\.bin\tauri.cmd"
$python = "C:\RoboMetaFit\tools\alture-jarvis\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "손자리 맥 $Version 서명 · 태그 $Tag · 폴더 $Folder"
$secure = Read-Host "서명 열쇠 암호(화면에 안 보입니다)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:TAURI_SIGNING_PRIVATE_KEY_PATH = $KeyPath
    $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    Remove-Item "$tarball.sig" -ErrorAction SilentlyContinue
    & $tauri signer sign $tarball
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$tarball.sig")) { throw "앱 꾸러미 서명 실패(암호 · 열쇠를 확인해 주세요)" }
    & $python scripts\mac\build_mac_update.py --out $Folder --app-version $Version --app-sig "$tarball.sig" `
        --app-tarball $tarName --release-tag $Tag --min-app-version $Version --sign
    if ($LASTEXITCODE -ne 0) { throw "목록 만들기 · 서명 실패(위 줄이 까닭)" }
}
finally {
    Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY_PATH -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
Write-Host ""
Write-Host "끝 — 이 릴리스($Tag)에 같이 올릴 파일:"
Get-ChildItem $Folder | Where-Object { $_.Name -match "^(Sonjari-$([regex]::Escape($Version))-mac-arm64\.(dmg|app\.tar\.gz|app\.tar\.gz\.sig)|latest\.json|sonjari-mac\.json(\.sig)?|python-.*\.zip)$" } |
    ForEach-Object { Write-Host ("  {0}  ({1:N0} 바이트)" -f $_.Name, $_.Length) }
