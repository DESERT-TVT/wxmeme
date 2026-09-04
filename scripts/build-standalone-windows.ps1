# PyInstaller standalone Windows build (requires Python 3.9+ and WebView2 runtime)
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    Write-Error @"
This script must run on Windows.

PyInstaller cannot cross-compile: running it on macOS/Linux only produces
binaries for that OS. On Mac, use:
  bash scripts/build-standalone-app.sh
"@
    exit 1
}

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dist = Join-Path $Root "dist"
$BuildVenv = Join-Path $Root ".build-venv-win"
$VenvPython = Join-Path $BuildVenv "Scripts\python.exe"

function Resolve-SystemPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        return @("python3")
    }
    throw "Python 3.9+ not found. Install from https://www.python.org/downloads/ and enable 'Add python.exe to PATH'."
}

$SystemPython = Resolve-SystemPython
Write-Host ("wxmeme: using Python command: " + ($SystemPython -join " "))

Write-Host "wxmeme: preparing PyInstaller build environment ..."
& @SystemPython -m venv $BuildVenv
if (-not (Test-Path $VenvPython)) {
    throw "Failed to create venv at $BuildVenv"
}

& $VenvPython -m pip install -U pip
& $VenvPython -m pip install -r (Join-Path $Root "requirements-build.txt")

Remove-Item -Recurse -Force (Join-Path $Root "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Dist "wxmeme-standalone") -ErrorAction SilentlyContinue

Write-Host "wxmeme: building standalone app (about 1-2 minutes) ..."
& $VenvPython -m PyInstaller (Join-Path $Root "app\wxmeme-windows.spec") `
    --noconfirm `
    --distpath $Dist `
    --workpath (Join-Path $Root "build")

$Exe = Join-Path $Dist "wxmeme-standalone\wxmeme.exe"
if (-not (Test-Path $Exe)) {
    throw "Build finished but exe not found: $Exe"
}

Write-Host ""
Write-Host "wxmeme: standalone app -> $Exe"
Write-Host "Double-click wxmeme.exe to run. WebView2 runtime is required on Windows 10/11."
Write-Host ""
Write-Host "Verify CLI:"
Write-Host "  `"$Exe`" --cli --help"
