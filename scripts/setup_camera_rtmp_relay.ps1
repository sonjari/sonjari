<#
.SYNOPSIS
    Installs the local RTMP relay that lets JARVIS read the Pocket 3 over Wi-Fi.

.DESCRIPTION
    The Pocket 3 has no way to hand video to a PC by itself -- DJI only exposes
    livestreaming through the Mimo app on a phone or tablet. So the path is:

        Pocket 3  --(DJI's own Wi-Fi)-->  tablet running Mimo
                  --(office Wi-Fi, RTMP)-->  MediaMTX on this PC
                  --(localhost)-->  JARVIS vision (OpenCV/FFmpeg)

    The camera itself is then free to sit on a normal charger, which is the
    whole point -- USB trickle charge could not keep up with webcam mode.

    MediaMTX keeps listening whether or not anything is publishing, and JARVIS
    retries the read on a timer, so the tablet can leave the building and come
    back: once Mimo starts publishing again the picture returns on its own with
    nothing to restart on this side.

.PARAMETER InstallDir
    Where MediaMTX is installed. Defaults next to the other C: runtime tools.

.PARAMETER StreamKey
    Path segment of the stream. Must match what you type into Mimo.

.PARAMETER SkipFirewall
    Skip the inbound rule. Without the rule the tablet cannot reach port 1935.
    Adding it needs an elevated shell.

.PARAMETER NoAuth
    Drop the publish password. Only for working out whether Mimo is rejecting
    the credentials in the URL -- an open 1935 lets anything on the office
    Wi-Fi push video into the office camera feed. Reading stays localhost-only
    either way.
#>
param(
    [string]$InstallDir = "C:\RoboMetaFit\tools\mediamtx",
    [string]$StreamKey = "live/pocket3",
    [int]$RtmpPort = 1935,
    [switch]$SkipFirewall,
    [switch]$NoAuth
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$exePath = Join-Path $InstallDir "mediamtx.exe"

if (-not (Test-Path $exePath)) {
    Write-Step "Resolving the latest MediaMTX release"
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/bluenviron/mediamtx/releases/latest" -Headers @{ "User-Agent" = "alture-jarvis" }
    $asset = $release.assets | Where-Object { $_.name -like "*windows_amd64.zip" } | Select-Object -First 1
    if (-not $asset) { throw "No windows_amd64 asset in MediaMTX release $($release.tag_name)" }

    $zipPath = Join-Path $env:TEMP $asset.name
    Write-Step "Downloading $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $InstallDir -Force
    Remove-Item $zipPath -Force
    Write-Step "Installed MediaMTX $($release.tag_name) to $InstallDir"
} else {
    Write-Step "MediaMTX already present at $exePath"
}

# MediaMTX ships wide open: every protocol on, and an "any" user with publish,
# read and playback on every path. On an office Wi-Fi that means anyone could
# watch the office camera or push their own video into it. So the config below
# is written from scratch rather than patched.
#
#  - Only RTMP ingest and a loopback-only RTSP re-serve are enabled. HLS,
#    WebRTC, SRT and the API are off -- each one is another listener nobody here
#    needs.
#  - Reading is restricted to 127.0.0.1. JARVIS is on this machine; nothing on
#    the LAN has any reason to pull the office camera.
#  - Publishing needs a password, because that port has to be reachable from
#    the tablet and is therefore reachable from the rest of the Wi-Fi too.
$configPath = Join-Path $InstallDir "mediamtx.yml"

$publishUser = "jarvis-cam"
$publishPass = ""
if (-not $NoAuth) {
    # Alphanumeric only: this password is carried in an RTMP query string, and
    # anything needing percent-encoding is a debugging trap on a tablet keypad.
    $alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray()
    $publishPass = -join (1..20 | ForEach-Object { $alphabet[(Get-Random -Maximum $alphabet.Length)] })
}

$authBlock = if ($NoAuth) {
@"
authMethod: internal
authInternalUsers:
  # WARNING: publishing is unauthenticated. Anything on this Wi-Fi can replace
  # the office camera feed. Re-run without -NoAuth once Mimo is working.
  - user: any
    pass:
    ips: []
    permissions:
      - action: publish
        path: $StreamKey
  - user: any
    pass:
    ips: ["127.0.0.1", "::1"]
    permissions:
      - action: read
        path: $StreamKey
"@
} else {
@"
authMethod: internal
authInternalUsers:
  - user: $publishUser
    pass: $publishPass
    ips: []
    permissions:
      - action: publish
        path: $StreamKey
  # JARVIS reads over loopback, so this needs no password and cannot be reached
  # from the network.
  - user: any
    pass:
    ips: ["127.0.0.1", "::1"]
    permissions:
      - action: read
        path: $StreamKey
"@
}

$config = @"
# Written by scripts/setup_camera_rtmp_relay.ps1 for ALTURE JARVIS.
# Regenerate with that script rather than editing by hand.
logLevel: info
readTimeout: 10s
writeTimeout: 10s

rtmp: yes
rtmpAddress: :$RtmpPort
rtsp: yes
rtspAddress: 127.0.0.1:8554
rtspTransports: [tcp]

hls: no
webrtc: no
srt: no
api: no
metrics: no
pprof: no
playback: no

$authBlock

paths:
  ${StreamKey}:
    # No source: the tablet pushes into this path whenever Mimo is streaming.
    source: publisher
"@
# NOT Set-Content -Encoding utf8: on Windows PowerShell 5.1 that writes a BOM,
# and MediaMTX's YAML parser rejects the file outright ("value is not allowed in
# this context" pointing at line 2, which reads as anything but an encoding
# problem). WriteAllText with UTF8Encoding($false) is the BOM-free form.
[System.IO.File]::WriteAllText($configPath, $config, (New-Object System.Text.UTF8Encoding($false)))
Write-Step "Wrote $configPath"

# A config MediaMTX refuses leaves nothing listening, and the scheduled task
# reports success either way -- so prove it starts here, while the reason is
# still on screen. It has no --check-config, so start it and see if it survives
# (a bad config exits within a fraction of a second).
Write-Step "Validating the config"
$probeLog = Join-Path $env:TEMP "mediamtx-probe.log"
$probe = Start-Process -FilePath $exePath -ArgumentList "`"$configPath`"" -WorkingDirectory $InstallDir `
    -RedirectStandardOutput $probeLog -RedirectStandardError "$probeLog.err" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
if ($probe.HasExited) {
    Get-Content $probeLog, "$probeLog.err" -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    throw "MediaMTX exited immediately -- it rejected $configPath (see above)"
}
$listening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -eq $RtmpPort -and $_.OwningProcess -eq $probe.Id }
Stop-Process -Id $probe.Id -Force
Remove-Item $probeLog, "$probeLog.err" -ErrorAction SilentlyContinue
if (-not $listening) { throw "MediaMTX started but nothing is listening on $RtmpPort" }
Write-Step "Config accepted; RTMP listener came up on $RtmpPort"

if (-not $SkipFirewall) {
    $ruleName = "ALTURE JARVIS MediaMTX RTMP $RtmpPort"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Step "Firewall rule already present"
    } else {
        try {
            # Private only: the tablet is on the office LAN, and this port has
            # no authentication of any kind.
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
                -Protocol TCP -LocalPort $RtmpPort -Profile Private | Out-Null
            Write-Step "Added inbound firewall rule for TCP/$RtmpPort (Private profile)"
        } catch {
            Write-Warning "Could not add the firewall rule (needs an elevated shell): $_"
            Write-Warning "Re-run this script as administrator, or add it by hand, or the tablet cannot connect."
        }
    }
}

$taskName = "RoboMetaFit-Alture-Jarvis-CameraRelay"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Step "Scheduled task $taskName already registered"
} else {
    try {
        $action = New-ScheduledTaskAction -Execute $exePath -Argument $configPath -WorkingDirectory $InstallDir
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "RTMP relay that receives the Osmo Pocket 3 stream for ALTURE JARVIS" | Out-Null
        Write-Step "Registered scheduled task $taskName (starts at logon)"
    } catch {
        Write-Warning "Could not register the scheduled task: $_"
        Write-Warning "Start it by hand with: `"$exePath`" `"$configPath`""
    }
}

# Take the address of whichever interface carries the default route. Picking by
# interface metric instead grabs a VPN adapter -- a Tailscale 100.x address got
# printed here once, which the tablet on the office Wi-Fi cannot reach.
$defaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
    Sort-Object -Property { $_.RouteMetric + $_.InterfaceMetric } |
    Select-Object -First 1
$lanIp = $null
if ($defaultRoute) {
    $lanIp = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $defaultRoute.InterfaceIndex -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress
}
if (-not $lanIp) {
    Write-Warning "Could not resolve the LAN address from the default route; check ipconfig yourself."
    $lanIp = "<이 PC의 LAN IP>"
}

$credentials = if ($NoAuth) { "" } else { "?user=$publishUser&pass=$publishPass" }

Write-Host ""
Write-Host "Done. Two things left, both outside this script:" -ForegroundColor Green
Write-Host ""
Write-Host "  1) On the tablet, DJI Mimo -> Livestream -> RTMP."
Write-Host "     If it asks for one address:"
Write-Host "       rtmp://${lanIp}:$RtmpPort/$StreamKey$credentials" -ForegroundColor Yellow
Write-Host "     If it asks for a server and a stream key separately:"
$keyLeaf = $StreamKey.Split("/")[-1]
$keyRoot = ($StreamKey -replace "/[^/]+$", "")
Write-Host "       server: rtmp://${lanIp}:$RtmpPort/$keyRoot" -ForegroundColor Yellow
Write-Host "       key   : $keyLeaf$credentials" -ForegroundColor Yellow
if (-not $NoAuth) {
    Write-Host ""
    Write-Host "     The user/pass ride in the URL. If Mimo refuses to connect, that is the"
    Write-Host "     first thing to suspect -- re-run this script with -NoAuth to confirm,"
    Write-Host "     but do not leave it that way: an open 1935 lets anything on this"
    Write-Host "     Wi-Fi replace the office camera feed."
}
Write-Host ""
Write-Host "  2) In C:\RoboMetaFit\tools\alture-jarvis\.env set:"
Write-Host "       JARVIS_CAMERA_STREAM_URL=rtmp://127.0.0.1:$RtmpPort/$StreamKey" -ForegroundColor Yellow
Write-Host "     Use 127.0.0.1 here, not the LAN IP -- reading is restricted to loopback,"
Write-Host "     and a hardcoded LAN IP breaks silently the day it changes."
Write-Host "     Then restart the backend:"
Write-Host "       schtasks /End /TN RoboMetaFit-Alture-Jarvis; schtasks /Run /TN RoboMetaFit-Alture-Jarvis"
Write-Host ""
Write-Host "  Is it receiving?  The JARVIS /health vision block shows source/reconnecting/error."
Write-Host "  Relay log:        $InstallDir (run mediamtx.exe in a console to watch it live)"
