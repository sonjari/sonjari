[CmdletBinding()]
param(
    [int]$ContextWindow = 24576,
    [string]$Model = "plopfit-gemma4:latest",
    [string]$OllamaBaseUrl = "http://127.0.0.1:11434"
)

$ErrorActionPreference = "Stop"
$body = @{
    model = $Model
    messages = @(@{ role = "user"; content = "Context residency probe. Reply OK." })
    stream = $false
    think = $false
    keep_alive = "24h"
    options = @{ num_ctx = $ContextWindow; num_predict = 16; temperature = 0 }
} | ConvertTo-Json -Depth 6

$timer = [Diagnostics.Stopwatch]::StartNew()
$response = Invoke-RestMethod `
    -Uri "$OllamaBaseUrl/api/chat" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($body)) `
    -TimeoutSec 240
$timer.Stop()
Start-Sleep -Seconds 2
$running = Invoke-RestMethod -Uri "$OllamaBaseUrl/api/ps" -TimeoutSec 10
$resident = $running.models | Where-Object {
    $_.name -eq $Model -and [int64]$_.context_length -eq $ContextWindow
} | Select-Object -First 1

[pscustomobject]@{
    model = $Model
    requested_context = $ContextWindow
    wall_sec = [math]::Round($timer.Elapsed.TotalSeconds, 2)
    load_ms = [math]::Round(($response.load_duration / 1e6), 1)
    total_ms = [math]::Round(($response.total_duration / 1e6), 1)
    resident = [bool]$resident
    resident_context = if ($resident) { [int64]$resident.context_length } else { 0 }
    processor = if ($resident) { $resident.details.parent_model } else { "unloaded" }
} | Format-List

if (-not $resident) {
    throw "Model answered but did not remain resident at context=$ContextWindow"
}
