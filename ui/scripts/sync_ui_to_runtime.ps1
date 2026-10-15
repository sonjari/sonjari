[CmdletBinding()]
param(
    [string]$SourceRoot = "",
    [string]$RuntimeRoot = "C:\RoboMetaFit\tools\alture-jarvis\ui"
)

$ErrorActionPreference = "Stop"
if (-not $SourceRoot) {
    $SourceRoot = Split-Path -Parent $PSScriptRoot
}
$sourceExe = Join-Path $SourceRoot "src-tauri\target\release\alture-jarvis-hud.exe"
if (-not (Test-Path -LiteralPath $sourceExe)) {
    throw "HUD release executable not found: $sourceExe"
}

$resolvedRuntimeParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $RuntimeRoot))
$resolvedRuntime = [System.IO.Path]::GetFullPath($RuntimeRoot)
if (-not $resolvedRuntime.StartsWith($resolvedRuntimeParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Runtime path escaped its expected parent: $resolvedRuntime"
}

New-Item -ItemType Directory -Path $resolvedRuntime -Force | Out-Null
Copy-Item -LiteralPath $sourceExe -Destination (Join-Path $resolvedRuntime "alture-jarvis-hud.exe") -Force
Write-Output "JARVIS HUD synced to $resolvedRuntime"
