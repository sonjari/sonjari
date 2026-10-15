<#
  고아 llama-server 청소.

  ollama.exe 가 죽어도 자식 llama-server.exe 는 살아남아 메모리를 그대로 쥔다.
  2026-08-28 실측: 고아 넷이 **커밋 84GB + VRAM 30GB** 를 물고 있었고, 시스템이
  스왑으로 넘어가 로더가 멈췄다. 물리 49.2GB(77%) -> 12.1GB(19%).

  이 저장소는 「Ollama 를 죽여도 llama-server 자식은 고아로 남아 VRAM 을 쥔다」를
  이미 기록해 뒀는데, VRAM 문제로만 알고 있었다. 호스트 RAM 도 32GB 씩 문다.
  자비스 재기동·정찰기 재기동·모델 pull 마다 하나씩 쌓인다.

  ## 오탐을 막는 두 가지

  1) 부모 PID 가 살아 있는 ollama.exe 목록에 있으면 건드리지 않는다.
  2) 윈도우는 PID 를 재사용한다. 그래서 부모라고 주장하는 ollama 가 자식보다
     **나중에 생겼으면** 진짜 부모가 아니다 - 그것도 고아로 본다.
  3) 갓 태어난 쌍을 죽이지 않도록 GraceSeconds 보다 어린 프로세스는 건너뛴다.
#>
param(
    [int]$GraceSeconds = 60,
    [switch]$WhatIfOnly
)

function Get-OrphanLlamaServer {
    param([int]$GraceSeconds = 60)

    $now = Get-Date
    $ollama = @{}
    foreach ($p in Get-CimInstance Win32_Process -Filter "Name='ollama.exe'" -ErrorAction SilentlyContinue) {
        $ollama[[int]$p.ProcessId] = $p.CreationDate
    }

    $found = @()
    foreach ($child in Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -like 'llama-server*' }) {
        $born = $child.CreationDate
        if ($born -and ($now - $born).TotalSeconds -lt $GraceSeconds) { continue }

        $ppid = [int]$child.ParentProcessId
        $orphan = $true
        if ($ollama.ContainsKey($ppid)) {
            $parentBorn = $ollama[$ppid]
            # 부모가 자식보다 나중에 생겼다면 PID 재사용이다 - 진짜 부모가 아니다.
            if (-not $parentBorn -or -not $born -or $parentBorn -le $born) { $orphan = $false }
        }
        if ($orphan) { $found += $child }
    }
    return $found
}

$orphans = Get-OrphanLlamaServer -GraceSeconds $GraceSeconds
if (-not $orphans -or $orphans.Count -eq 0) {
    Write-Output "고아 없음"
    exit 0
}

$freed = 0
foreach ($o in $orphans) {
    $mb = [math]::Round($o.PrivatePageCount / 1MB)
    $freed += $mb
    Write-Output ("고아 정리: pid {0} · 커밋 {1:N0} MB · 죽은 부모 {2}" -f $o.ProcessId, $mb, $o.ParentProcessId)
    if (-not $WhatIfOnly) {
        Stop-Process -Id $o.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
Write-Output ("합계 {0:N0} MB {1}" -f $freed, $(if ($WhatIfOnly) { "(보기만 함)" } else { "회수" }))
