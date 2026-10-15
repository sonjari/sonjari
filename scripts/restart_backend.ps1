# 백엔드만 다시 띄운다 — **형제를 안 건드린다.**
#
# ★ 2026-09-21: 이걸 손으로 하다가 **코덱스의 MCP 서버를 죽였다.**
#
#     Get-Process python | ? { $_.CommandLine -match 'alture_jarvis' } | Stop-Process
#
#   이 필터는 `python -m alture_jarvis`(백엔드)와 `python -m alture_jarvis.mcp_server`
#   (MCP) 를 **둘 다** 잡는다. MCP 는 클라이언트가 띄우는 stdio 자식이라, 죽으면
#   클라이언트에는 `Transport closed` 한 줄만 뜬다 — 조용히 죽는다.
#
#   이 저장소에 이미 있는 교훈이다: 「명령줄로 죽이면 형제까지 잡힌다」
#   (자비스 재시작이 TTS 를 다섯 번 죽였고 아무도 몰랐다). **두 번째 재발이다.**
#
# 그래서 여기서는 이름이 아니라 **포트로 찾는다.** 8091 을 듣고 있는 프로세스는
# 정의상 백엔드 하나뿐이고, 형제는 포트를 안 듣는다.
[CmdletBinding()]
param(
    [int]$Port = 8091,
    [string]$TaskName = "RoboMetaFit-Alture-Jarvis",
    # 포트가 닫히기를 기다릴 시간. 안 닫힌 채로 sync 하면 옛 프로세스가 파일을 쥔다.
    [int]$WaitSec = 20
)

$ErrorActionPreference = "Stop"

function Get-BackendPid {
    param([int]$Port)
    $listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listen) { return $null }
    return ($listen | Select-Object -First 1).OwningProcess
}

Write-Host "1) 예약 작업 정지"
schtasks /End /TN $TaskName 2>&1 | Out-Null

Write-Host "2) 포트 $Port 를 듣는 프로세스만 찾는다 (이름으로 찾지 않는다)"
$procId = Get-BackendPid -Port $Port
if ($procId) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    Write-Host "   PID $procId ($($p.ProcessName)) — 종료"
    Stop-Process -Id $procId -Force -Confirm:$false -ErrorAction SilentlyContinue
} else {
    Write-Host "   듣는 프로세스 없음 — 이미 내려갔다"
}

Write-Host "3) 포트가 실제로 닫혔는지 확인"
$deadline = (Get-Date).AddSeconds($WaitSec)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-BackendPid -Port $Port)) { break }
    Start-Sleep -Milliseconds 400
}
if (Get-BackendPid -Port $Port) {
    throw "포트 $Port 가 $WaitSec 초 안에 안 닫혔다 — 이 상태로 sync 하면 파일이 잠긴다"
}
Write-Host "   닫혔다"

# 죽이면 안 되는 형제가 살아 있는지 **말해 준다.** 조용히 넘어가면 다음에 또 모른다.
$siblings = Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd -match 'alture_jarvis') { "PID $($_.Id)" }
}
if ($siblings) {
    Write-Host "   (형제 살아 있음: $($siblings -join ', ') — 일부러 안 건드렸다)"
}

Write-Host "4) 다시 띄운다"
schtasks /Run /TN $TaskName 2>&1 | Out-Null

Write-Host "5) 살아났는지 확인"
$deadline = (Get-Date).AddSeconds(60)
$ok = $false
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
        if ($health.ok) { $ok = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $ok) { throw "60초 안에 /health 가 안 떴다" }

# ★ 「200 이 온다」는 새 코드라는 뜻이 아니다 — 안 죽은 옛 프로세스가 답할 수 있다.
#   판 해시를 찍어서 사람이 **바뀌었는지** 보게 한다.
Write-Host "   ok — build $($health.build) · 모델 $($health.ollama.model) · 상주 $($health.ollama.resident)"
