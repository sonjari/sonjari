param(
    [int]$Port = 11435,
    [string]$Model = "qwen3.5:9b",
    [string]$GpuUuid = "GPU-00000000-0000-0000-0000-000000000000",
    [switch]$Pull,
    [switch]$Wait
)

$ErrorActionPreference = "Stop"

function Test-ScoutPort {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/version" -TimeoutSec 2
        return [bool]$response.version
    } catch {
        return $false
    }
}

# 이 인스턴스를 다시 띄우기 전에 **이전 판의 고아**부터 치운다. 안 치우면
# 재기동할 때마다 llama-server 가 하나씩 쌓여, 2026-08-28 에는 넷이 커밋 84GB 를
# 물고 시스템을 스왑으로 밀어 넣었다.
$cleaner = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "..\scripts\clean_orphan_llama.ps1"
if (-not (Test-Path $cleaner)) {
    $cleaner = Join-Path $PSScriptRoot "clean_orphan_llama.ps1"
}
if (Test-Path $cleaner) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cleaner | ForEach-Object { Write-Host $_ }
}

$Ollama = (Get-Command ollama.exe -ErrorAction Stop).Source

if (-not (Test-ScoutPort)) {
    # 두 Ollama 프로세스는 포트와 GPU를 둘 다 분리한다. 전역 사용자
    # 환경의 CUDA_VISIBLE_DEVICES=0을 이 자식 프로세스에서만 3060 UUID로 덮어쓴다.
    $env:OLLAMA_HOST = "127.0.0.1:$Port"
    $env:CUDA_VISIBLE_DEVICES = $GpuUuid
    $env:OLLAMA_FLASH_ATTENTION = "1"
    $env:OLLAMA_KV_CACHE_TYPE = "q8_0"
    # 정찰기와 **임베더(bge-m3)** 가 같이 산다. 1 로 두면 서로를 축출해서
    # 둘 다 조용히 실패한다 — 2026-08-27 에 실제로 그랬다(정찰기 6판 거부,
    # 의미 검색 0건). 이 카드에서 9.9GB + 1.2GB 는 들어간다.
    $env:OLLAMA_MAX_LOADED_MODELS = "2"
    $env:OLLAMA_NUM_PARALLEL = "1"
    $env:OLLAMA_KEEP_ALIVE = "30m"
    Start-Process -FilePath $Ollama -ArgumentList @("serve") -WindowStyle Hidden | Out-Null

    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not (Test-ScoutPort)) {
        if ([DateTime]::UtcNow -ge $deadline) {
            throw "Code scout Ollama did not open port $Port"
        }
        Start-Sleep -Milliseconds 500
    }
}

if ($Pull) {
    $env:OLLAMA_HOST = "127.0.0.1:$Port"
    & $Ollama pull $Model
    if ($LASTEXITCODE -ne 0) { throw "ollama pull failed: $Model" }
}

Write-Host "Code scout Ollama ready: $Model on 127.0.0.1:$Port (GPU $GpuUuid)"

if ($Wait) {
    # 예약 작업이 포트 상태를 감시하게 한다. 서버가 죽으면 비정상
    # 종료하고 Windows 작업 스케줄러의 재시작 정책을 탄다.
    while (Test-ScoutPort) { Start-Sleep -Seconds 10 }
    throw "Code scout Ollama stopped responding on port $Port"
}
