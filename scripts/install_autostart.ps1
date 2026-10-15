param(
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Supertonic = Join-Path $ProjectRoot ".venv\Scripts\supertonic.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) { throw "Missing: $VenvPython" }
if (-not (Test-Path -LiteralPath $Supertonic)) { throw "Missing: $Supertonic" }

function Register-JarvisTask {
    param(
        [string]$Name,
        [string]$Executable,
        [string]$Arguments,
        [int]$DelaySeconds
    )

    $Action = New-ScheduledTaskAction -Execute $Executable -Argument $Arguments -WorkingDirectory $ProjectRoot
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
    $Trigger.Delay = "PT${DelaySeconds}S"
    $Principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
    $Settings = New-ScheduledTaskSettingsSet -RestartCount 6 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
    if ($RunNow) {
        Start-ScheduledTask -TaskName $Name
    }
}

# Public installs expose local services on loopback only. Managed multi-device
# deployments must opt into a network listener and configure their own guard.
Register-JarvisTask -Name "Alture-Jarvis-Supertonic" -Executable $Supertonic -Arguments "serve --host 127.0.0.1 --port 7788" -DelaySeconds 10
Register-JarvisTask -Name "Alture-Jarvis-Code-Scout" `
    -Executable "powershell.exe" `
    -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_code_scout_ollama.ps1')`" -Wait" `
    -DelaySeconds 5
Register-JarvisTask -Name "Alture-Jarvis" -Executable $VenvPython -Arguments "`"$(Join-Path $PSScriptRoot 'task_entry.py')`"" -DelaySeconds 20

Write-Host "Registered JARVIS, Qwen3.5 code scout, and Supertonic for $CurrentUser"
