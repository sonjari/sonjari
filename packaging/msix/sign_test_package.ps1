# 시험판 MSIX 서명 — 다른 PC(노트북)에 실제로 설치해 보기 위한 것 (2026-09-16).
# ASCII only: Windows PowerShell 5.1 misreads BOM-less UTF-8 with non-ASCII text.
#
# Why: makeappx makes an UNSIGNED package. Windows refuses to install one. The Store signs the real package,
# so this certificate exists only to rehearse the install on our own machines - it is NOT the product's identity.
#
#   Subject must match the manifest Publisher exactly: CN=RoboMetaFit
#   The laptop trusts the .cer once (admin, Trusted People), then the .msix installs with a double click.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File packaging\msix\sign_test_package.ps1
#   powershell ... -Msix "C:\RoboMetaFit\tools\JarvisAppStage\RoboMetaFit.OntelicMsixTest.msix" -OutDir "C:\RoboMetaFit\tools\OntelicLaptop"

param(
    [string]$Msix = "C:\RoboMetaFit\tools\JarvisAppStage\RoboMetaFit.OntelicMsixTest.msix",
    [string]$OutDir = "C:\RoboMetaFit\tools\OntelicLaptop",
    [string]$Subject = "CN=RoboMetaFit",
    [string]$FriendlyName = "Ontelic test signing"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $Msix)) { throw "msix not found: $Msix" }
New-Item -ItemType Directory -Force $OutDir | Out-Null

# 1) certificate - reuse ours if it is still valid, never touch other certificates
$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object {
    $_.Subject -eq $Subject -and $_.FriendlyName -eq $FriendlyName -and $_.NotAfter -gt (Get-Date).AddDays(7)
} | Sort-Object NotAfter -Descending | Select-Object -First 1
if ($null -eq $cert) {
    $cert = New-SelfSignedCertificate -Type Custom -Subject $Subject -FriendlyName $FriendlyName `
        -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 2048 `
        -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddMonths(15) `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
    Write-Host "created test certificate $($cert.Thumbprint)"
} else {
    Write-Host "reusing test certificate $($cert.Thumbprint)"
}

# 2) sign (a copy - the unsigned build output stays as it is)
$signed = Join-Path $OutDir (Split-Path $Msix -Leaf)
Copy-Item $Msix $signed -Force
$signtool = (Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*\x64\*" } | Sort-Object FullName -Descending | Select-Object -First 1).FullName
if (-not $signtool) { throw "signtool.exe not found (Windows SDK)" }
& $signtool sign /fd SHA256 /sha1 $cert.Thumbprint /tr http://timestamp.digicert.com /td SHA256 $signed
if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE)" }
& $signtool verify /pa $signed | Out-Null
Write-Host "signed: $signed"

# 3) public certificate for the other PC (no private key - safe to copy around)
$cer = Join-Path $OutDir "Ontelic-test-signing.cer"
Export-Certificate -Cert $cert -FilePath $cer -Type CERT | Out-Null

# 4) what the other PC has to do
# ASCII name: PowerShell 5.1 mangles non-ASCII paths when they cross a process boundary (see CLAUDE.md, 사고 J-2).
$howto = Join-Path $OutDir "INSTALL-ko.txt"
@"
Ontelic 시험판 설치 (다른 PC)

준비물: 이 폴더의 두 파일
  - $(Split-Path $signed -Leaf)  (앱, 약 100MB)
  - Ontelic-test-signing.cer     (이 앱을 서명한 시험용 인증서)

1) 인증서 등록 - 관리자 PowerShell 에서 한 번만
   Import-Certificate -FilePath ".\Ontelic-test-signing.cer" -CertStoreLocation Cert:\LocalMachine\TrustedPeople

2) 설치
   $(Split-Path $signed -Leaf) 더블클릭 -> 설치

3) 처음 실행
   시작 메뉴에서 Ontelic -> 첫 실행 마법사(PC 확인 -> 모델 -> 쓰임 -> 연결)
   Ollama 가 없으면 마법사가 설치하고, 고른 모델(수 GB)을 받습니다. 인터넷이 필요합니다.

4) 지울 때
   설정 > 앱 > Ontelic > 제거. 사용자 폴더의 기억 복제본과 받은 모델 파일은 남습니다.

주의
- 이 인증서는 **시험용**입니다. 스토어에 올라간 앱은 Microsoft 가 서명하므로 이 과정이 필요 없습니다.
- 시험이 끝나면 인증서도 지울 수 있습니다(관리자 PowerShell):
    Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object { `$_.Subject -eq "$Subject" } | Remove-Item
"@ | Out-File -FilePath $howto -Encoding utf8

Get-ChildItem $OutDir | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
