<#
  온텔릭 시험판 서명 인증서를 이 PC 가 믿게 한다 — 스토어판(.msix)을 설치하려면 한 번 필요하다.

  실행: 이 파일을 오른쪽 클릭 → 「PowerShell에서 실행」
        관리자 권한이 필요하면 윈도우가 허용 창을 띄운다 — 「예」만 누르면 된다.

  하는 일은 하나뿐이다: Ontelic-test-signing.cer 를 로컬 컴퓨터\신뢰할 수 있는 사람(TrustedPeople)에 넣는다.
  되돌리기: certlm.msc → 신뢰할 수 있는 사람 → 인증서 → 「RoboMetaFit」 인증서 삭제.
#>
param([string]$CertPath = "")

$ErrorActionPreference = "Stop"

function Find-Cert {
  if ($CertPath -and (Test-Path -LiteralPath $CertPath)) { return (Resolve-Path -LiteralPath $CertPath).Path }
  $beside = Join-Path $PSScriptRoot "Ontelic-test-signing.cer"
  if (Test-Path -LiteralPath $beside) { return $beside }
  $published = Get-ChildItem "C:\RoboMetaFit\tools\OntelicUpdate" -Recurse -Filter "Ontelic-test-signing.cer" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($published) { return $published.FullName }
  throw "인증서 파일(Ontelic-test-signing.cer)을 못 찾았습니다. -CertPath 로 경로를 주세요."
}

$cert = Find-Cert
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
  # 관리자 창으로 다시 띄운다 — 윈도우가 허용 창을 띄우고, 사람이 「예」를 눌러야만 진행된다.
  Start-Process powershell.exe -Verb RunAs -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-CertPath", "`"$cert`"")
  return
}

Write-Host "인증서: $cert"
$imported = Import-Certificate -FilePath $cert -CertStoreLocation Cert:\LocalMachine\TrustedPeople
Write-Host ""
Write-Host ("등록했습니다 — {0}" -f $imported.Subject) -ForegroundColor Green
Write-Host ("지문: {0}" -f $imported.Thumbprint)
$check = Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object Thumbprint -eq $imported.Thumbprint
if ($check) { Write-Host "확인: 신뢰할 수 있는 사람 저장소에 있습니다." -ForegroundColor Green }
else { Write-Host "확인 실패: 저장소에서 못 찾았습니다." -ForegroundColor Red }
Write-Host ""
Read-Host "Enter 를 누르면 닫힙니다"
