param(
    [string]$BaseUrl = "http://127.0.0.1:8091"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TokenPath = Join-Path $ProjectRoot "data\control.token"

$Root = Invoke-RestMethod -Uri "$BaseUrl/" -TimeoutSec 5
$State = Invoke-RestMethod -Uri "$BaseUrl/v1/state" -TimeoutSec 5
$Tools = Invoke-RestMethod -Uri "$BaseUrl/v1/tools" -TimeoutSec 5

if ($Root.service -ne "alture-jarvis") { throw "Unexpected service response" }
if (-not $State.state) { throw "Missing state" }
if ($Tools.Count -lt 1) { throw "No tools registered" }
if (-not (Test-Path -LiteralPath $TokenPath)) { throw "Missing control token: $TokenPath" }

$ToolNames = $Tools | ForEach-Object { $_.name }
$RequiredWriteTools = @(
    "google_gmail_prepare_send",
    "google_gmail_send",
    "google_calendar_prepare_create",
    "google_calendar_create",
    "naver_blog_prepare_post",
    "naver_blog_publish"
)
foreach ($required in $RequiredWriteTools) {
    if ($ToolNames -notcontains $required) { throw "Missing expected tool registration: $required" }
}

Write-Host "Smoke OK: service=$($Root.service), state=$($State.state), tools=$($Tools.Count)"

