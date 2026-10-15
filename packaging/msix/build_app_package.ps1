# W1-7: lay out the real app (Tauri exe + Python runtime + backend) as an MSIX loose-file package and validate it.
# ASCII only: Windows PowerShell 5.1 misreads BOM-less UTF-8 with non-ASCII text.
#
# Two flavours (renamed to Ontelic 2026-09-15; the dev/live build keeps alture-jarvis-hud.exe on purpose):
#   default  test build  - tauri.msix.conf.json, backend port 8094, identity RoboMetaFit.OntelicMsixTest (safe beside the live 8091)
#   -Store   store build - tauri.store.conf.json, backend port 8091, identity RoboMetaFit.Sonjari, display "Sonjari"
#   - Tauri exe is built into target-msix (never target\release, which the live HUD sync copies)
#   - Python = copy of the local CPython the dev venv was created from + the venv's site-packages (no downloads).
#     GPU extras (nvidia CUDA wheels) and Playwright browsers are left out, as the plan's optional component split says.
#   - Stage on NTFS outside AppData (exFAT E: refuses loose registration; a shell inside Claude's MSIX sees a merged AppData).
param(
    [string]$Stage = "C:\RoboMetaFit\tools\JarvisAppStage",
    [int]$Port = 0,
    [string]$Identity = "",
    [string]$Display = "",
    [string]$Version = "0.4.0.0",
    [string]$VenvPython = "",
    [switch]$Store,
    [switch]$SkipTauri,
    # The .appinstaller URL this build is published to (publish_update_channel.ps1 passes it). Written into the
    # package so an install made from the bare .msix (no App Installer URI in Windows) can still find its updates.
    [string]$UpdateChannel = ""
)
if ($Store) {
    if (-not $Port) { $Port = 8091 }; if (-not $Identity) { $Identity = "RoboMetaFit.Sonjari" }; if (-not $Display) { $Display = "Sonjari" }
    $TauriConf = "src-tauri/tauri.store.conf.json"
    # 2026-09-29 name Sonjari: the Start/Store name is DisplayName, and the Store only accepts a name RESERVED for this
    # product. 2026-10-01: a new Store app was reserved as "Sonjari" (9N458V8HPTR2) instead of adding the name to the old
    # Ontelic app, so the identity is RoboMetaFit.Sonjari too - the identity shows in install folder names.
    # 2026-09-23: the Store assigns the publisher (Partner Center > Product identity). It must match exactly or the
    # upload is rejected. store_identity.json holds what Partner Center shows (PFN hash re-checked against the CN).
    $sid = Get-Content (Join-Path $PSScriptRoot "store_identity.json") -Raw | ConvertFrom-Json
    if ($Identity -ne $sid.IdentityName) { throw "Identity $Identity does not match the Store reservation $($sid.IdentityName)" }
    $Publisher = $sid.Publisher
    if ($Version -notmatch '\.0$') { throw "Store packages must end the version with .0 (revision is reserved by the Store): $Version" }
} else {
    if (-not $Port) { $Port = 8094 }; if (-not $Identity) { $Identity = "RoboMetaFit.OntelicMsixTest" }; if (-not $Display) { $Display = "Sonjari Beta" }
    $TauriConf = "src-tauri/tauri.msix.conf.json"
    # the test build is signed by sign_test_package.ps1 with a self-made cert whose subject is this
    $Publisher = "CN=RoboMetaFit"
}
# Same values as src/alture_jarvis/brand.py (MCP_ALIAS) and ui/src-tauri/src/package.rs (STARTUP_TASK_ID).
# 2026-09-29 name stage 2: Sonjari.exe / sonjari-mcp.exe. The old alias stays declared too, so a Claude/Codex config
# written by an earlier beta keeps working without re-running Connect.
$ExeName = "Sonjari.exe"
$Alias = "sonjari-mcp.exe"
$LegacyAlias = "ontelic-mcp.exe"
$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Here "..\..")
if (-not $VenvPython) {
    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $VenvPython)) { throw "bundle Python not found: $VenvPython" }
$venvRoot = Split-Path -Parent (Split-Path -Parent $VenvPython)
Write-Host "bundle Python: $VenvPython"
$Ui = Join-Path $Root "ui"
# 굽는 자리(약 9GB · 파일 수만 개)를 다른 디스크에 둘 수 있다 — 비우면 예전 자리 그대로다.
# 2026-10-07: 작업 폴더가 외장 USB 에 있어 굽기가 그 디스크에서 돈다. 내장 SSD 를 단 날의 밑작업(아직 그쪽으로 구워 재 보지 않았다).
$TargetDir = if ($env:SONJARI_MSIX_TARGET_DIR) { $env:SONJARI_MSIX_TARGET_DIR } else { Join-Path $Ui "src-tauri\target-msix" }
$Log = Join-Path $Stage "build.log"
New-Item -ItemType Directory -Force $Stage | Out-Null

# 1) Tauri exe (frontend build runs as beforeBuildCommand)
if (-not $SkipTauri) {
    $cmd = "set CARGO_TARGET_DIR=$TargetDir&& set JARVIS_DEFAULT_BACKEND_URL=http://127.0.0.1:$Port&& npx.cmd tauri build --config $TauriConf"
    # ★ `-Wait` 를 쓰지 않는다 (2026-09-16 실측). `-Wait` 는 **프로세스 나무 전체**를 기다리는데,
    #   MSVC 툴체인이 남기는 `vctip.exe` 가 빌드가 끝난 뒤에도 몇 분~무한정 살아 있어서 기다림이
    #   안 풀린다. 이날 빌드는 13:06 에 컴파일이 끝났는데 13:20 까지 「도는 중」으로 보였고,
    #   로그는 통째로 비어 있었다 — 어젯밤에도 같은 자리에서 판 하나를 날렸다.
    #   `WaitForExit()` 는 **그 cmd 하나만** 기다린다. 손자가 남아 있어도 안 붙잡힌다.
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/d", "/c", "$cmd > `"$Log`" 2>&1" -WorkingDirectory $Ui -NoNewWindow -PassThru
    # 2026-09-16 (2): -PassThru 로 받은 객체는 **핸들을 먼저 잡아야** ExitCode 가 산다.
    # 안 잡으면 WaitForExit() 뒤에도 $p.ExitCode 가 비어 오고, 그러면 아래 -ne 0 이 참이 되어
    # **성공한 빌드를 실패로 단정한다.** 이날 실제로 그랬다: 로그에 "Built application at ...
    # Ontelic.exe" 와 "Finished release in 2m 48s" 가 찍혔는데 스크립트는 throw 했다.
    $null = $p.Handle
    $p.WaitForExit()
    $code = $p.ExitCode
    Write-Host "tauri build exit=$code (log: $Log)"
    # 그리고 코드를 못 읽었으면 **실패로 단정하지 않는다.** 이 저장소가 반복해 배운 것:
    # 「끝났다」는 증거가 아니고 **산출물**이 증거다(사고 J-2). 바로 아래 세 줄이 exe 의 존재와
    # 그 안에 구워진 포트를 직접 확인하므로, 판정은 그쪽에 맡긴다.
    if ($null -ne $code -and $code -ne 0) { throw "tauri build failed (exit $code)" }
    if ($null -eq $code) { Write-Host "exit code unreadable - judging by the artifact below" }
}
$exe = Join-Path $TargetDir "release\$ExeName"
if (-not (Test-Path $exe)) { throw "exe not found: $exe" }
$bytes = [IO.File]::ReadAllBytes($exe)
$text = [Text.Encoding]::ASCII.GetString($bytes)
if (-not $text.Contains("127.0.0.1:$Port")) { throw "exe does not carry backend port $Port" }
Write-Host "exe carries 127.0.0.1:$Port"

# 2) layout
# Square*Logo.png / StoreLogo.png are gitignored build outputs of the Ontelic mark - regenerate so a clean checkout has them.
& $VenvPython (Join-Path $Root "scripts\make_brand_icons.py") | Out-Null
$App = Join-Path $Stage "app"
# 2026-10-05: a staged app left running by a capture run held these files. Remove-Item half-deleted the stage and the
# build died two lines later with a Copy-Item error that named the wrong thing. Say what is wrong before touching it.
$held = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "$App\*" })
if ($held.Count) { throw "the staged app is still running from $App (PID $($held.ProcessId -join ', ')) - close it, then build again" }
if (Test-Path $App) { Remove-Item $App -Recurse -Force }
New-Item -ItemType Directory -Force (Join-Path $App "Assets") | Out-Null
Copy-Item $exe $App
# 2026-09-29: one 44px image made the taskbar/Start show the logo on a plate (laptop beta looked "strange").
# The per-scale/targetsize/unplated set is indexed into resources.pri below, after the manifest is written.
$msixAssets = Join-Path $Ui "src-tauri\icons\msix"
if (-not (Get-ChildItem $msixAssets -Filter "Square44x44Logo.targetsize-24_altform-unplated.png" -ErrorAction SilentlyContinue)) {
    throw "msix logo set missing in $msixAssets - scripts\make_brand_icons.py did not run"
}
Copy-Item (Join-Path $msixAssets "*.png") (Join-Path $App "Assets")
$base = (& $VenvPython -c "import sys; print(sys.base_prefix)").Trim()
$py = Join-Path $App "backend\python"
& robocopy $base $py /E /XD "$base\Doc" "$base\Tools" "$base\tcl" "$base\include" "$base\Scripts" "$base\libs" "$base\share" "$base\Lib\site-packages" "$base\Lib\test" "$base\Lib\idlelib" "$base\Lib\tkinter" "$base\Lib\turtledemo" /NFL /NDL /NJH /NJS /NP | Out-Null
$site = Join-Path $py "Lib\site-packages"
# playwright (107 MB) stays IN: the app drives the user's real Chrome over CDP through it.
# 2026-09-16: it was excluded and the packaged app answered "No module named 'playwright'" on the first web task -
# a shipped build that cannot browse. Browser binaries are NOT here (they live in %LOCALAPPDATA%\ms-playwright) so
# leaving the package in does not pull the ~500 MB chromium.
# 2026-09-26: pip is shipped now. It was excluded, so pip-audit (an allowed code tool) and the project-declared install
# path (`python -m pip install -r requirements.txt`) both failed in the packaged app; the strengthened gate caught it.
& robocopy (Join-Path $venvRoot "Lib\site-packages") $site /E /XD nvidia setuptools _distutils_hack __pycache__ /XF "__editable__*" "distutils-precedence.pth" "*.pyc" /NFL /NDL /NJH /NJS /NP | Out-Null
Get-ChildItem $site -Filter "alture_jarvis-*.dist-info" -Directory | Remove-Item -Recurse -Force
# 2026-09-26 fresh-laptop code-mode E2E: ruff ships as a native binary in the venv's Scripts\ (ruff.exe), which this
# build never copied - the packaged app answered "RuffNotFound: Could not find the ruff binary". ruff looks for
# <python>\Scripts\ruff.exe, so copy the binaries the allowed code tools need. Missing one stops the build.
$scriptsOut = Join-Path $py "Scripts"
New-Item -ItemType Directory -Force $scriptsOut | Out-Null
foreach ($tool in @("ruff.exe")) {
    $toolSrc = Join-Path $venvRoot "Scripts\$tool"
    if (-not (Test-Path $toolSrc)) { throw "code tool binary missing in venv: $toolSrc" }
    Copy-Item $toolSrc (Join-Path $scriptsOut $tool) -Force
}
# makeappx refuses any file named [Content_Types].xml (0x8007007B). python-docx ships an unzipped copy of its
# template for developers; the code only opens templates\default.docx, so the folder is dropped.
$docxDev = Join-Path $site "docx\templates\default-docx-template"
if (Test-Path $docxDev) { Remove-Item $docxDev -Recurse -Force }
& robocopy (Join-Path $Root "src\alture_jarvis") (Join-Path $site "alture_jarvis") /E /XD __pycache__ /XF "*.pyc" /NFL /NDL /NJH /NJS /NP | Out-Null
# 2026-09-24: the packaged backend DIED (0xc0000005 in MSVCP140.dll) the moment voice loaded on a fresh laptop.
# The winrt wheel ships an OLD msvcp140.dll (14.29) in its folder; once it is loaded, ctranslate2 (built for >= 14.40)
# crashes on std::mutex. The laptop's System32 copy was 14.38 - also too old. So the package carries this build PC's
# current VC++ runtime (app-local deployment is allowed for these files) next to python.exe, every old msvcp140.dll
# inside site-packages is replaced by it, and the build fails if any runtime DLL in the package is still < 14.40.
# msvc_runtime.py preloads the newest one at backend start so load order cannot bring the old one back.
$vcNames = @("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll")
$sys32 = Join-Path $env:SystemRoot "System32"
$minVc = [version]"14.40.0.0"
foreach ($n in $vcNames) {
    $src = Join-Path $sys32 $n
    if (-not (Test-Path $src)) { continue }
    if ([version](Get-Item $src).VersionInfo.FileVersionRaw -lt $minVc) { throw "build PC runtime $n is older than $minVc - install the latest VC++ redistributable x64 first" }
    Copy-Item $src (Join-Path $py $n) -Force
}
Get-ChildItem $site -Recurse -File | Where-Object { $vcNames -contains $_.Name.ToLower() } | ForEach-Object {
    if ([version]$_.VersionInfo.FileVersionRaw -lt $minVc) {
        Write-Host "replacing old runtime $($_.FullName.Substring($site.Length)) $($_.VersionInfo.FileVersionRaw)"
        Copy-Item (Join-Path $sys32 $_.Name.ToLower()) $_.FullName -Force
    }
}
$oldVc = Get-ChildItem $py -Recurse -File | Where-Object { $vcNames -contains $_.Name.ToLower() -and [version]$_.VersionInfo.FileVersionRaw -lt $minVc }
if ($oldVc) { throw "package still carries VC++ runtime older than ${minVc}: $($oldVc.FullName -join ', ')" }
if ($UpdateChannel) {
    if ($UpdateChannel -notmatch "^https://[^\s]+\.appinstaller$") { throw "bad -UpdateChannel $UpdateChannel" }
    Set-Content -Path (Join-Path $site "alture_jarvis\update_channel.txt") -Value $UpdateChannel -Encoding ascii
}
# 2026-09-16: recipes/ and skills/ were NOT in the package - the same shape as the missing playwright. The reviewed
# saramin procedure and the skills simply were not there, so the packaged app could not use them and fell back to
# guessing. config.py resolves both as <alture_jarvis>/../../ ; in the package that is python\Lib, so they go there.
# (tests/test_bundle_requirements.py keeps this rule and config.py from drifting apart.)
$lib = Join-Path $py "Lib"
# 2026-10-07: recipes\drafts is what the app writes at runtime ON THIS PC (git-ignored drafts and replaced backups).
# Copying the folder whole shipped three of them in the store package. Only reviewed recipes go out.
& robocopy (Join-Path $Root "recipes") (Join-Path $lib "recipes") /E /XD __pycache__ drafts /XF "*.pyc" /NFL /NDL /NJH /NJS /NP | Out-Null
& robocopy (Join-Path $Root "skills") (Join-Path $lib "skills") /E /XD __pycache__ /XF "*.pyc" /NFL /NDL /NJH /NJS /NP | Out-Null
# 2026-09-27 field packs (strategy section 50): packs\<id>\pack.json + recipes + skills. Off by default; the user turns them on in Settings.
& robocopy (Join-Path $Root "packs") (Join-Path $lib "packs") /E /XD __pycache__ /XF "*.pyc" /NFL /NDL /NJH /NJS /NP | Out-Null
# NOT alture_jarvis.api: importing it builds a runtime and writes a token/db under %LOCALAPPDATA% (seen 2026-09-15).
$check = & (Join-Path $py "python.exe") -c "import alture_jarvis, alture_jarvis.runtime, alture_jarvis.mcp_server; print(alture_jarvis.__file__)" 2>&1 | Out-String
Write-Host "bundled python import: $check"
# 2026-09-16: the build only checked "does our own code import" and playwright was silently excluded - the shipped
# app answered "No module named 'playwright'" on the first web task. Now the bundled python imports EVERYTHING the
# product needs; a missing required module fails the build here instead of in the user's hands.
$bundle = & (Join-Path $py "python.exe") (Join-Path $Here "check_bundle.py") 2>&1 | Out-String
Write-Host "bundle check: $bundle"
if ($LASTEXITCODE -ne 0) { throw "bundled python is missing required modules - see the list above" }
# 2026-10-07: the package copies src\alture_jarvis, recipes, skills and packs AS THEY ARE - the name rewriting and the
# leftover check only ran for the GitHub export. Source comments carrying a person's name, birth year and school
# went out in the store package. The same list now gates the package: a hit stops the build (fix the source).
$people = & $VenvPython (Join-Path $Here "scan_package_people.py") $App 2>&1 | Out-String
Write-Host $people
if ($LASTEXITCODE -ne 0) { throw "the package carries personal names or facts - see the list above; fix the source and build again" }

# 3) manifest + pack (pack validates the schema; the loose folder is what gets registered)
$template = [IO.File]::ReadAllText((Join-Path $Here "AppxManifest.template.xml"))
$xml = $template.Replace("{{IDENTITY}}", $Identity).Replace("{{DISPLAY}}", $Display).Replace("{{VERSION}}", $Version).Replace("{{ALIAS}}", $Alias).Replace("{{LEGACY_ALIAS}}", $LegacyAlias).Replace("{{EXE}}", $ExeName).Replace("{{PUBLISHER}}", $Publisher)
[IO.File]::WriteAllText((Join-Path $App "AppxManifest.xml"), $xml, (New-Object System.Text.UTF8Encoding($false)))
$makeappx = (Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Recurse -Filter makeappx.exe -ErrorAction SilentlyContinue |
    Where-Object FullName -like "*\x64\*" | Sort-Object FullName -Descending | Select-Object -First 1).FullName
# resources.pri: lets Windows pick Assets\Square44x44Logo.targetsize-24_altform-unplated.png etc. for the plain names
# in the manifest. Indexed from a small folder (Assets + manifest only) - pointing makepri at $App would index the
# whole bundled python (thousands of files) as resources.
$makepri = Join-Path (Split-Path $makeappx) "makepri.exe"
if (-not (Test-Path $makepri)) { throw "makepri.exe not found next to $makeappx" }
$priRoot = Join-Path $Stage "pri"
if (Test-Path $priRoot) { Remove-Item $priRoot -Recurse -Force }
New-Item -ItemType Directory -Force $priRoot | Out-Null
Copy-Item (Join-Path $App "Assets") $priRoot -Recurse
Copy-Item (Join-Path $App "AppxManifest.xml") $priRoot
$priConfig = Join-Path $priRoot "priconfig.xml"
$priLog = & $makepri createconfig /cf $priConfig /dq ko-KR /pv 10.0.0 /o 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { Write-Host $priLog; throw "makepri createconfig failed" }
# The default config splits Scale/Language into resource packs (for bundles). This is ONE msix, so the split pris
# would never be installed and high-DPI laptops would fall back to the scale-100 art - keep every candidate in one pri.
$priXml = [xml](Get-Content $priConfig -Raw)
$splitNode = $priXml.SelectSingleNode("//packaging")
if ($splitNode) { [void]$splitNode.ParentNode.RemoveChild($splitNode); $priXml.Save($priConfig) }
$priLog = & $makepri new /pr $priRoot /cf $priConfig /mn (Join-Path $priRoot "AppxManifest.xml") /of (Join-Path $App "resources.pri") /o 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { Write-Host $priLog; throw "makepri new failed" }
Write-Host "resources.pri written"
$msix = Join-Path $Stage "$Identity.msix"
# 2026-10-01: a manifest error made makeappx fail, but the script went on, printed the OLD msix size and exited 0 -
# a failed build read as a fresh package. Remove the old file first and stop on failure.
if (Test-Path $msix) { Remove-Item $msix -Force }
$packLog = & $makeappx pack /d $App /p $msix /o 2>&1 | Out-String
$packExit = $LASTEXITCODE
Write-Host "makeappx exit=$packExit"
if ($packExit -ne 0 -or -not (Test-Path $msix)) { Write-Host $packLog; throw "makeappx pack failed (exit $packExit) - no package was written" }
$size = (Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("layout {0:N0} MB, msix {1:N0} MB" -f $size, ((Get-Item $msix -ErrorAction SilentlyContinue).Length / 1MB))
