<# ============================================================================
 survey_target_pc.ps1  —  "이 PC 에 자비스를 깔아도 되는 곳인가"를 읽기만 해서 본다.

 무엇을 하나
   · 이 PC 가 회사가 관리하는 기계인지(도메인/Intune)
   · 보안·감시 제품이 무엇이 돌고 있는지(백신·EDR·DLP·자산관리)
   · 실행 정책이 걸려 있는지(AppLocker/WDAC/ExecutionPolicy)
   · 바깥(api.anthropic.com)으로 나가지는지, 그리고 그 길에 회사 프록시가
     끼어 인증서를 갈아끼우고 있는지
   · 파이썬·노드·깃이 이미 있는지

 무엇을 안 하나
   · 아무것도 바꾸지 않는다. 설치·삭제·설정 변경 0. 순수 읽기다.
   · 감시를 피하거나 끄는 짓은 하지 않는다. 이 파일의 목적은 그 반대다 —
     무엇이 깔려 있는지 알고 **회사에 물어보기 위한** 자료를 만든다.

 쓰는 법 (더블클릭 말고, PowerShell 창에서)
   powershell -NoProfile -ExecutionPolicy Bypass -File .\survey_target_pc.ps1

 결과
   바탕화면에 jarvis_pc_survey.txt 가 생긴다. 그 파일을 통째로 클로드에
   붙여넣고 맨 아래 적힌 질문을 하면 된다.
============================================================================ #>

$ErrorActionPreference = 'Continue'
$out = New-Object System.Collections.Generic.List[string]
function Say([string]$t) { $out.Add($t); Write-Host $t }
function Head([string]$t) { Say ""; Say ("== " + $t + " " + ("=" * [Math]::Max(0, 60 - $t.Length))) }

Say "자비스 설치 가능성 조사 — 읽기 전용"
Say ("찍은 시각: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))

# ── 1. 기계 ─────────────────────────────────────────────────────────────────
Head "1. 이 기계는 누구 것인가"
try {
    $cs = Get-CimInstance Win32_ComputerSystem
    $os = Get-CimInstance Win32_OperatingSystem
    Say ("컴퓨터      : " + $cs.Name)
    Say ("OS          : " + $os.Caption + " (" + $os.Version + ")")
    Say ("도메인 가입 : " + $cs.PartOfDomain + "   도메인/작업그룹: " + $cs.Domain)
    Say ("메모리      : " + [Math]::Round($cs.TotalPhysicalMemory / 1GB, 1) + " GB")
} catch { Say ("기계 정보 실패: " + $_.Exception.Message) }

try {
    $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    Say ("로컬 관리자 : " + $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
} catch { }

# Intune/AzureAD 관리 여부 — 회사가 원격으로 정책을 밀어넣을 수 있다는 뜻이다
try {
    $ds = & dsregcmd.exe /status
    foreach ($line in $ds) {
        if ($line -match 'AzureAdJoined|DomainJoined|WorkplaceJoined|MDMUrl') { Say ("MDM         : " + $line.Trim()) }
    }
} catch { Say "dsregcmd 없음(개인 PC 일 수 있다)" }

try {
    $mdm = Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Enrollments' -ErrorAction Stop |
        Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).UPN }
    if ($mdm) { Say "MDM 등록    : 있음 (회사가 이 PC 에 정책을 내려보낼 수 있다)" }
} catch { }

# ── 2. 보안·감시 제품 ───────────────────────────────────────────────────────
Head "2. 무엇이 지켜보고 있나"
try {
    $av = Get-CimInstance -Namespace 'root\SecurityCenter2' -ClassName AntiVirusProduct -ErrorAction Stop
    foreach ($a in $av) { Say ("백신 등록   : " + $a.displayName) }
    if (-not $av) { Say "백신 등록   : (없음)" }
} catch { Say "백신 목록 조회 불가(서버 OS 일 수 있다)" }

# 이름으로 알아보는 감시·보안·자산관리 제품들. 있다고 나쁜 게 아니라,
# 있으면 **회사에 물어보고 깔아야 한다**는 뜻이다.
$markers = @(
    'CrowdStrike','csagent','SentinelOne','CarbonBlack','Cylance',
    'Cortex','Traps','Tanium','Defender','MsSense','Sophos','ESET','Symantec',
    'McAfee','Trellix','TrendMicro','TmListen','Kaspersky','Bitdefender','FireEye',
    'Rapid7','Qualys','Nessus','Netskope','Zscaler','Forcepoint','Digital Guardian',
    'Teramind','ActivTrak','Veriato','InterGuard','Time Doctor','Hubstaff',
    'AhnLab','V3Lite','V3Service','ASDSvc','TrusGuard','Softcamp','Fasoo','MarkAny',
    'Jiran','SGA','Waterwall','Somansa','DLP','Genian','WithSecure','Nasca','DRM'
)
$hits = New-Object System.Collections.Generic.List[string]
try {
    foreach ($s in (Get-Service -ErrorAction SilentlyContinue)) {
        foreach ($m in $markers) {
            if ($s.Name -like "*$m*" -or $s.DisplayName -like "*$m*") {
                $hits.Add("서비스    " + $s.Status + "  " + $s.Name + "  [" + $s.DisplayName + "]"); break
            }
        }
    }
} catch { }
try {
    foreach ($p in (Get-Process -ErrorAction SilentlyContinue)) {
        foreach ($m in $markers) {
            if ($p.ProcessName -like "*$m*") { $hits.Add("프로세스  " + $p.ProcessName); break }
        }
    }
} catch { }
$hits = $hits | Sort-Object -Unique
if ($hits) { foreach ($h in $hits) { Say $h } } else { Say "이름으로 아는 감시/보안 제품: 없음 (모른다는 뜻이지 없다는 증거는 아니다)" }

Say ""
Say "-- 자동 시작에 걸린 것 (회사가 심어둔 게 있으면 대개 여기 보인다) --"
try {
    Get-CimInstance Win32_StartupCommand -ErrorAction Stop |
        Select-Object -First 25 |
        ForEach-Object { Say ("  " + $_.Name + "  <-  " + $_.Command) }
} catch { Say "  조회 실패" }

# ── 3. 실행 정책 ────────────────────────────────────────────────────────────
Head "3. 프로그램을 새로 돌릴 수 있나"
try { Say ("ExecutionPolicy :`r`n" + (Get-ExecutionPolicy -List | Out-String).Trim()) } catch { }
try {
    $ap = Get-AppLockerPolicy -Effective -ErrorAction Stop
    $xml = $ap.ToXml()
    if ($xml -match 'EnforcementMode="Enabled"') { Say "AppLocker       : 켜짐 (허용 목록에 없는 exe 는 안 돈다)" }
    else { Say "AppLocker       : 없음 또는 감사 전용" }
} catch { Say "AppLocker       : 없음" }
try {
    $ci = Get-CimInstance -ClassName Win32_DeviceGuard -Namespace 'root\Microsoft\Windows\DeviceGuard' -ErrorAction Stop
    Say ("WDAC/DeviceGuard: 정책 적용상태 " + $ci.CodeIntegrityPolicyEnforcementStatus)
} catch { }
try {
    foreach ($f in (Get-NetFirewallProfile -ErrorAction Stop)) {
        Say ("방화벽 " + $f.Name + " : Enabled=" + $f.Enabled + "  Outbound=" + $f.DefaultOutboundAction)
    }
} catch { }

# ── 4. 바깥으로 나가는 길 ───────────────────────────────────────────────────
Head "4. 클로드 API 로 나갈 수 있나"
try {
    $px = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction Stop
    Say ("프록시 설정 : Enable=" + $px.ProxyEnable + "  Server=" + $px.ProxyServer)
} catch { Say "프록시 설정 : 못 읽음" }

foreach ($h in @('api.anthropic.com', 'registry.npmjs.org', 'pypi.org')) {
    try {
        $t = Test-NetConnection -ComputerName $h -Port 443 -WarningAction SilentlyContinue
        Say ("443 연결 " + $h + " : " + $t.TcpTestSucceeded)
    } catch { Say ("443 연결 " + $h + " : 실패") }
}

# 인증서 발급자를 본다. 공인 CA 가 아니면 회사 장비가 중간에서 통신을 열어보고 있다.
try {
    $tcp = New-Object System.Net.Sockets.TcpClient('api.anthropic.com', 443)
    $cb = [System.Net.Security.RemoteCertificateValidationCallback] { param($a, $b, $c, $d) $true }
    $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, $cb)
    $ssl.AuthenticateAsClient('api.anthropic.com')
    $issuer = $ssl.RemoteCertificate.Issuer
    Say ("인증서 발급자 : " + $issuer)
    if ($issuer -match "Amazon|DigiCert|Encrypt|Google|GlobalSign|Sectigo|ISRG|Cloudflare") {
        Say "  -> 공인 CA. 중간에서 뜯어보는 장비는 안 보인다."
    } else {
        Say "  -> ★ 공인 CA 가 아니다. 회사 프록시가 통신 내용을 열어보고 있다는 뜻이다."
        Say "     회사가 주고받는 내용까지 볼 수 있으니 반드시 먼저 허락을 받아야 한다."
    }
    $ssl.Dispose(); $tcp.Close()
} catch { Say ("인증서 확인 실패: " + $_.Exception.Message) }

# ── 5. 이미 있는 것 ─────────────────────────────────────────────────────────
Head "5. 이미 깔려 있는 도구"
foreach ($c in @('python', 'py', 'node', 'npm', 'git', 'claude', 'ollama')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { Say ("있음 : " + $c + "  ->  " + $cmd.Source) } else { Say ("없음 : " + $c) }
}
try {
    foreach ($g in (Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name)) { Say ("그래픽 : " + $g) }
} catch { }

# ── 6. 붙여넣을 질문 ────────────────────────────────────────────────────────
Head "6. 이제 이걸 클로드한테 물어봐라"
Say ""
Say "위 내용을 통째로 복사해서 아래처럼 물어보면 된다:"
Say ""
Say "  --------------------------------------------------------------"
Say "  이건 내 회사 PC 조사 결과야. (여기 붙여넣기)"
Say "  1) 이 PC 에 회사 감시/보안 제품이 뭐가 돌고 있는지 정리해줘."
Say "  2) 개인이 만든 파이썬 에이전트를 여기에 설치해서 브라우저를 자동으로"
Say "     조작하게 하면, 회사 정책상 문제가 될 만한 지점이 뭐가 있나?"
Say "  3) IT 팀에 뭐라고 물어봐야 하는지 질문 문장을 만들어줘."
Say "  --------------------------------------------------------------"
Say ""
Say "★ 감시 제품이 나왔다고 숨기고 까는 건 안 된다. 그건 사고다."
Say "  나왔으면 IT 에 물어보고, 안 나왔어도 회사 자산이면 물어보는 게 맞다."

$dest = Join-Path ([Environment]::GetFolderPath('Desktop')) 'jarvis_pc_survey.txt'
try {
    [System.IO.File]::WriteAllLines($dest, $out, (New-Object System.Text.UTF8Encoding($true)))
    Write-Host ""
    Write-Host ("저장했다 -> " + $dest) -ForegroundColor Green
} catch {
    Write-Host ("저장 실패: " + $_.Exception.Message) -ForegroundColor Red
}
