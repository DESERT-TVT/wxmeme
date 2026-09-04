# PyInstaller standalone Windows build (requires Python 3.9+ and WebView2 runtime)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dist = Join-Path $Root "dist"
$BuildVenv = Join-Path $Root ".build-venv-win"

Write-Host "wxmeme: preparing PyInstaller build environment ..."
python -m venv $BuildVenv
& (Join-Path $BuildVenv "Scripts\Activate.ps1")
python -m pip install -q -U pip
python -m pip install -q -r (Join-Path $Root "requirements-build.txt")

Remove-Item -Recurse -Force (Join-Path $Root "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Dist "wxmeme-standalone") -ErrorAction SilentlyContinue

Write-Host "wxmeme: building standalone app (about 1-2 minutes) ..."
pyinstaller (Join-Path $Root "app\wxmeme-windows.spec") --noconfirm --distpath $Dist --workpath (Join-Path $Root "build")

$Exe = Join-Path $Dist "wxmeme-standalone\wxmeme.exe"
Write-Host ""
Write-Host "wxmeme: standalone app -> $Exe"
Write-Host "Double-click wxmeme.exe to run. WebView2 runtime is required on Windows 10/11."
Write-Host ""
Write-Host "Verify CLI:"
Write-Host "  `"$Exe`" --cli --help"
