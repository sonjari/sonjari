param(
    [string]$RuntimeRoot = "C:\RoboMetaFit\tools\alture-jarvis"
)

$ErrorActionPreference = "Stop"
$downloadUrl = "https://github.com/hancom-io/devcenter-archive/raw/main/hwp-automation/%EB%B3%B4%EC%95%88%EB%AA%A8%EB%93%88%28Automation%29.zip"
$expectedSha256 = "5D87292EFAFD7311CBA6D35E4B416AC8BFA78608A64DDE1656C8CB827B051BD8"
$moduleName = "FilePathCheckerModuleExample"
$installDir = Join-Path $RuntimeRoot "data\hwp-security"
$modulePath = Join-Path $installDir "FilePathCheckerModuleExample.dll"
$temporary = Join-Path ([IO.Path]::GetTempPath()) ("jarvis-hwp-security-" + [Guid]::NewGuid().ToString("N"))
$archive = Join-Path $temporary "security.zip"
$expanded = Join-Path $temporary "expanded"

try {
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri $downloadUrl -OutFile $archive
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
    if ($actual -ne $expectedSha256) {
        throw "Official Hancom security module archive hash mismatch: $actual"
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    $source = Join-Path $expanded "FilePathCheckerModuleExample.dll"
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "FilePathCheckerModuleExample.dll is missing from the official archive"
    }
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $modulePath -Force

    $registryPath = "HKCU:\Software\HNC\HwpAutomation\Modules"
    New-Item -Path $registryPath -Force | Out-Null
    New-ItemProperty -Path $registryPath -Name $moduleName -PropertyType String `
        -Value $modulePath -Force | Out-Null

    [pscustomobject]@{
        ModuleName = $moduleName
        ModulePath = $modulePath
        DllSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $modulePath).Hash
        RegistryPath = $registryPath
    }
}
finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
