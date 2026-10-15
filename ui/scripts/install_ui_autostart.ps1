[CmdletBinding()]
param(
    [string]$RuntimeRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "Alture-Jarvis-HUD"
)

$ErrorActionPreference = "Stop"
$exe = Join-Path ([System.IO.Path]::GetFullPath($RuntimeRoot)) "alture-jarvis-hud.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Run sync_ui_to_runtime.ps1 first. Missing: $exe"
}

$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $RuntimeRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "ALTURE JARVIS local desktop HUD" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Scheduled task installed and started: $TaskName"
