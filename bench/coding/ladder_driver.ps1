# 코딩 사다리 드라이버 — 노트북(4B)과 이 PC(35B)에서 똑같이 돈다. 토큰은 출력하지 않는다.
#   -Manifest  ladder_manifest.json (과제 id·prompt·seed)
#   -Tasks     'L1_hello_page,L3_fix_bug'   (비우면 전부)
#   -Reps      과제당 반복 수
#   -Base      작업 폴더 뿌리
#   -Port      백엔드 포트 (노트북 8094 · 이 PC 8091)
param(
  [string]$Manifest, [string]$Tasks = '', [int]$Reps = 1, [string]$Base, [int]$Port = 8094,
  [string]$TokenFile = '', [int]$PerTaskSec = 1500, [string]$Tag = 'ladder'
)
$ErrorActionPreference = 'Stop'
$out = Split-Path -Parent $Manifest
$log = Join-Path $out "$Tag.log"
$resultsPath = Join-Path $out "$Tag.results.json"
# 로그를 다른 프로세스(tail -F 감시 등)가 잡고 있어도 판을 죽이지 않는다 (2026-10-02: L4 도중 드라이버가 죽었다).
function L($m) {
  $line = "{0} {1}" -f (Get-Date -Format s), $m
  foreach ($i in 1..10) { try { $line | Add-Content $log -Encoding UTF8 -ErrorAction Stop; return } catch { Start-Sleep -Milliseconds 300 } }
}
Remove-Item $log, $resultsPath -ErrorAction SilentlyContinue
try {
  if (-not $TokenFile) {
    $pkg = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter 'RoboMetaFit.OntelicMsixTest_*' | Select-Object -First 1
    $TokenFile = Join-Path $pkg.FullName 'LocalCache\Local\Ontelic\data\control.token'
  }
  $h = @{ 'X-JARVIS-TOKEN' = (Get-Content $TokenFile -Raw).Trim() }
  $m = Get-Content $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
  $want = if ($Tasks) { $Tasks -split ',' } else { @($m.tasks | ForEach-Object { $_.id }) }
  $results = @()
  $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 15
  L ("build={0} model={1}" -f $health.build, $health.ollama.model)
  foreach ($rep in 1..$Reps) {
    foreach ($id in $want) {
      $t = @($m.tasks | Where-Object { $_.id -eq $id })[0]
      $ws = Join-Path $Base ("{0}-r{1}" -f $id, $rep)
      if (Test-Path $ws) { Remove-Item $ws -Recurse -Force }
      New-Item -ItemType Directory -Force $ws | Out-Null
      foreach ($p in $t.seed.PSObject.Properties) {
        [IO.File]::WriteAllText((Join-Path $ws $p.Name), [string]$p.Value, (New-Object Text.UTF8Encoding($false)))
      }
      $body = @{ prompt = $t.prompt; session_id = "$Tag-$id-r$rep-$([int](Get-Date -UFormat %s))"; origin = 'workspace';
                 workspace_mode = 'code'; delivery = 'screen'; agent_mode = 'auto'; code_workspace = $ws } | ConvertTo-Json
      $t0 = Get-Date; L "start $id r$rep"
      $row = $null; $jobId = ''; $timedOut = $false
      try {
        $c = Invoke-RestMethod "http://127.0.0.1:$Port/v1/chat" -Method Post -Headers $h -ContentType 'application/json; charset=utf-8' `
             -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 120
        $jobId = if ($c.id) { $c.id } else { $c.job_id }
        while (((Get-Date) - $t0).TotalSeconds -lt $PerTaskSec) {
          Start-Sleep 10
          try { $row = Invoke-RestMethod "http://127.0.0.1:$Port/v1/jobs/$jobId" -Headers $h -TimeoutSec 30 } catch { continue }
          if ($row.status -in 'completed','failed','cancelled','needs_input') { break }
        }
        $row = Invoke-RestMethod "http://127.0.0.1:$Port/v1/jobs/$jobId" -Headers $h -TimeoutSec 60
        # ★ 시간 초과한 잡은 **취소한다** (2026-09-22). 예전에는 예산이 끝나도 서버에서 계속 돌았고 백엔드는 잡을 하나씩
        #   돌리므로, 그 잡이 다음 과제를 줄에 세웠다(AURORA 3회차가 29분 돌며 L3 를 막았다). 그러면 다음 과제의 소요는
        #   대기 시간을 일한 시간으로 센 값이 된다. 취소가 반영될 때까지 기다린 뒤에 다음으로 넘어간다.
        $timedOut = ([string]$row.status) -notin @('completed', 'failed', 'cancelled', 'needs_input')
        if ($timedOut) {
          L ("timeout $id r$rep — 취소한다 (status=$($row.status))")
          try { Invoke-RestMethod "http://127.0.0.1:$Port/v1/jobs/$jobId/cancel" -Method Post -Headers $h -TimeoutSec 30 | Out-Null }
          catch { L ("cancel 실패 " + $_.Exception.Message) }
          for ($w = 0; $w -lt 18; $w++) {
            Start-Sleep 5
            try { $row = Invoke-RestMethod "http://127.0.0.1:$Port/v1/jobs/$jobId" -Headers $h -TimeoutSec 30 } catch { }
            if ([string]$row.status -in @('cancelled', 'failed', 'completed')) { break }
          }
        }
      } catch { L ("ERROR $id " + $_.Exception.Message) }
      $secs = [int]((Get-Date) - $t0).TotalSeconds
      $steps = @(); if ($row -and $row.result -and $row.result.agent_trace) { $steps = @($row.result.agent_trace.steps) }
      $results += [ordered]@{
        id = $id; rep = $rep; job = $jobId; status = [string]$row.status; error = [string]$row.error; seconds = $secs; timed_out = [bool]$timedOut
        build = [string]$row.build; workspace = $ws
        completion_state = ($row.result.completion_state | ConvertTo-Json -Compress -Depth 3)
        steps = $steps.Count
        tools = @($steps | ForEach-Object { [string]$_.tool + $(if ($_.ok) { '' } else { '(X)' }) })
        diagnosis = ($row.result.diagnosis | ConvertTo-Json -Compress -Depth 4)
      }
      L ("end {0} r{1} status={2} secs={3} steps={4}{5}" -f $id, $rep, $row.status, $secs, $steps.Count, $(if ($timedOut) { ' timeout=True' } else { '' }))
      ($results | ConvertTo-Json -Depth 6) | Set-Content $resultsPath -Encoding UTF8
    }
  }
  # 채점은 이 PC 에서 한다 — 작업 폴더들을 압축해 가져간다.
  $zip = Join-Path $out "$Tag.workspaces.zip"; Remove-Item $zip -ErrorAction SilentlyContinue
  Compress-Archive -Path (Join-Path $Base '*') -DestinationPath $zip -Force
} catch { L ("FATAL " + $_.Exception.Message) }
L 'DONE'
