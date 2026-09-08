param(
    [string]$BuildTools = "C:\BuildTools",
    [string]$WindowsSdk = "$PSScriptRoot\..\.sdk\windows-sdk-nuget",
    [string]$TradeSdk = "$PSScriptRoot\..\.sdk\esunny_trade",
    [string]$QuoteSdk = "$PSScriptRoot\..\.sdk\esunny_quote",
    [string]$CtpMdSdk = "$PSScriptRoot\..\.sdk\ctp\md_x64",
    [string]$CtpTdSdk = "$PSScriptRoot\..\.sdk\ctp\trader_x64",
    [string]$BuildDir = "$PSScriptRoot\..\build\native"
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$cmake = "C:\Program Files\CMake\bin\cmake.exe"
$msvcRoot = Join-Path $BuildTools "VC\Tools\MSVC"
$msvc = Get-ChildItem -LiteralPath $msvcRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1

if (-not $msvc) { throw "未找到 MSVC: $msvcRoot" }
if (-not (Test-Path -LiteralPath $cmake)) { throw "未找到 CMake: $cmake" }
foreach ($sdk in @($WindowsSdk, $CtpMdSdk, $CtpTdSdk)) {
    if (-not (Test-Path -LiteralPath $sdk)) { throw "未找到 SDK: $sdk" }
}

$msvcPath = $msvc.FullName
$sdkVersion = "10.0.26100.0"
$sdkInclude = Join-Path $WindowsSdk "cpp\c\Include\$sdkVersion"
$sdkBin = Join-Path $WindowsSdk "cpp\c\bin\$sdkVersion\x64"
$sdkLib = Join-Path $WindowsSdk "x64\c"
$nmake = Join-Path $msvcPath "bin\Hostx64\x64\nmake.exe"
$rc = Join-Path $sdkBin "rc.exe"

$env:INCLUDE = @(
    (Join-Path $msvcPath "include"), (Join-Path $sdkInclude "shared"),
    (Join-Path $sdkInclude "um"), (Join-Path $sdkInclude "ucrt"),
    (Join-Path $sdkInclude "winrt"), (Join-Path $sdkInclude "cppwinrt")
) -join ";"
$env:LIB = @(
    (Join-Path $msvcPath "lib\x64"), (Join-Path $sdkLib "ucrt\x64"),
    (Join-Path $sdkLib "um\x64")
) -join ";"
$env:Path = @(
    (Join-Path $msvcPath "bin\Hostx64\x64"), $sdkBin,
    (Split-Path -Parent $cmake), $env:Path
) -join ";"

$cmakeArgs = @(
    "-S", (Join-Path $projectRoot "native"), "-B", $BuildDir,
    "-G", "NMake Makefiles", "-DCMAKE_BUILD_TYPE=Release",
    "-DCMAKE_MAKE_PROGRAM=$nmake", "-DCMAKE_RC_COMPILER=$rc",
    "-DCTP_MD_SDK=$([IO.Path]::GetFullPath($CtpMdSdk))",
    "-DCTP_TD_SDK=$([IO.Path]::GetFullPath($CtpTdSdk))"
)
if ((Test-Path -LiteralPath $TradeSdk) -and (Test-Path -LiteralPath $QuoteSdk)) {
    $cmakeArgs += "-DESUNNY_TRADE_SDK=$([IO.Path]::GetFullPath($TradeSdk))"
    $cmakeArgs += "-DESUNNY_QUOTE_SDK=$([IO.Path]::GetFullPath($QuoteSdk))"
}

& $cmake @cmakeArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $cmake --build $BuildDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Copy-Item -LiteralPath (Join-Path $CtpMdSdk "thostmduserapi_se.dll") -Destination $BuildDir -Force
Copy-Item -LiteralPath (Join-Path $CtpTdSdk "thosttraderapi_se.dll") -Destination $BuildDir -Force
if (Test-Path -LiteralPath $TradeSdk) {
    Copy-Item -LiteralPath (Join-Path $TradeSdk "lib\win\x64\libdstartradeapi.dll") -Destination $BuildDir -Force
}
if (Test-Path -LiteralPath $QuoteSdk) {
    Copy-Item -LiteralPath (Join-Path $QuoteSdk "lib\win\x64\libdstarquoteapi.dll") -Destination $BuildDir -Force
}
Write-Host "原生桥接库构建完成: $([IO.Path]::GetFullPath($BuildDir))"
