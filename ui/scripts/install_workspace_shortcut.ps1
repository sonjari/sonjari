param(
    [string]$RuntimeRoot = "C:\RoboMetaFit\tools\alture-jarvis"
)

# Ontelic desktop shortcut (renamed from "ALTURE JARVIS" 2026-09-15).
# ASCII only: Windows PowerShell 5.1 misreads BOM-less UTF-8 with non-ASCII text.
# The icon comes from the exe itself (Tauri embeds icons/icon.ico). The old shortcut pointed at a separate
# ui\jarvis.ico, so the taskbar kept showing the old logo after the exe icon changed.

$ErrorActionPreference = "Stop"
$exe = Join-Path $RuntimeRoot "ui\alture-jarvis-hud.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Ontelic executable not found: $exe"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell

# Remove only our own old shortcut (same target exe). Anything else with that name is left alone.
$old = Join-Path $desktop "ALTURE JARVIS.lnk"
if (Test-Path -LiteralPath $old) {
    $target = $shell.CreateShortcut($old).TargetPath
    if ($target -and ([IO.Path]::GetFullPath($target) -eq [IO.Path]::GetFullPath($exe))) {
        Remove-Item -LiteralPath $old -Force
        Write-Output "Removed old shortcut: $old"
    }
}

$shortcutPath = Join-Path $desktop "Ontelic.lnk"
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.Arguments = ""
$shortcut.WorkingDirectory = Split-Path $exe
$shortcut.IconLocation = "$exe,0"
$shortcut.Description = "Ontelic"
$shortcut.Save()

# Ask Windows to refresh cached icons (the taskbar otherwise keeps the old picture for the same exe path).
$ie4 = Join-Path $env:SystemRoot "System32\ie4uinit.exe"
if (Test-Path -LiteralPath $ie4) { & $ie4 -show }

Write-Output "Installed Ontelic shortcut: $shortcutPath"
