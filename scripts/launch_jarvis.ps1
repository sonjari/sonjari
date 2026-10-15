param(
    [string]$RuntimeRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $RuntimeRoot) {
    if ($env:JARVIS_RUNTIME_ROOT) {
        $RuntimeRoot = $env:JARVIS_RUNTIME_ROOT
    } elseif ($env:LOCALAPPDATA) {
        $RuntimeRoot = Join-Path $env:LOCALAPPDATA "AltureJarvis"
    } else {
        $RuntimeRoot = Split-Path -Parent $PSScriptRoot
    }
}

function Test-LocalPort {
    param([int]$Port)
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $attempt = $client.ConnectAsync("127.0.0.1", $Port)
        if (-not $attempt.Wait(350)) { $client.Dispose(); return $false }
        $connected = $client.Connected
        $client.Dispose()
        return $connected
    } catch {
        return $false
    }
}

function Start-TaskOrProcess {
    param(
        [string]$TaskName,
        [string]$Executable,
        [string[]]$Arguments
    )
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        return
    }
    if (Test-Path -LiteralPath $Executable) {
        Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $RuntimeRoot -WindowStyle Hidden
    }
}

if (-not (Test-LocalPort -Port 7788)) {
    Start-TaskOrProcess -TaskName "Alture-Jarvis-Supertonic" `
        -Executable (Join-Path $RuntimeRoot ".venv\Scripts\supertonic.exe") `
        -Arguments @("serve", "--host", "127.0.0.1", "--port", "7788")
}

if (-not (Test-LocalPort -Port 11435)) {
    Start-TaskOrProcess -TaskName "Alture-Jarvis-Code-Scout" `
        -Executable "powershell.exe" `
        -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $RuntimeRoot "scripts\start_code_scout_ollama.ps1")
        )
}

if (-not (Test-LocalPort -Port 8091)) {
    Start-TaskOrProcess -TaskName "Alture-Jarvis" `
        -Executable (Join-Path $RuntimeRoot ".venv\Scripts\python.exe") `
        -Arguments @((Join-Path $RuntimeRoot "scripts\task_entry.py"))
}

$hud = Join-Path $RuntimeRoot "ui\alture-jarvis-hud.exe"
if (-not (Test-Path -LiteralPath $hud)) {
    throw "JARVIS HUD executable not found: $hud"
}
Start-Process -FilePath $hud -ArgumentList "--workspace" -WorkingDirectory (Split-Path -Parent $hud)
