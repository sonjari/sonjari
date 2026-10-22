param(
    [switch]$RunNow,
    [switch]$Unregister
)

# 디스코드 다리(python -m alture_jarvis.messaging)를 로그온 때 켜는 작업 스케줄러 항목 (2026-10-17).
#
# - 관리자 권한 없이(RunLevel Limited) 이 사용자로 돈다 — 봇 토큰이 이 사용자의 자격 증명 관리자에 있다.
# - 죽으면 1분 뒤 다시 켠다(최대 999번). 다리는 둘이 뜨면 스스로 하나만 남긴다(잠금 파일).
# - 창 없는 pythonw.exe 로 돈다. 기록은 <데이터 폴더>\logs\discord_bridge.log.
# - 먼저 `python -m alture_jarvis.messaging setup` 으로 토큰 · 허용 목록을 넣어야 한다.
#
# 등록:   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_discord_bridge_task.ps1
# 바로 켜기: 위 명령 뒤에 -RunNow
# 지우기: 위 명령 뒤에 -Unregister
#
# ★ 이 파일은 한글이 들어 있어 UTF-8 BOM 으로 저장한다(Windows PowerShell 5.1, 사고 J).

$ErrorActionPreference = "Stop"
$TaskName = "RoboMetaFit-Sonjari-Discord"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$VenvPythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed $TaskName"
    return
}

if (-not (Test-Path -LiteralPath $VenvPythonW)) { throw "Missing: $VenvPythonW" }

$Action = New-ScheduledTaskAction -Execute $VenvPythonW -Argument "-m alture_jarvis.messaging run" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
# 본체(Alture-Jarvis 20초)보다 늦게 — 본체가 먼저 떠 있어야 첫 일을 바로 받는다(안 떠 있어도 다리는 기다린다).
$Trigger.Delay = "PT40S"
$Principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
}

Write-Host "Registered $TaskName for $CurrentUser"
