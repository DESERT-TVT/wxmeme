@echo off
setlocal
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
  echo wxmeme: Python 3 not found. Install Python 3.9+ and retry.
  exit /b 1
)

python -m pip install -q -r exporter\requirements.txt

if exist "%USERPROFILE%\Desktop\wcdb-key-tool\all_keys.json" (
  python exporter\wxmeme.py --wcdb-keys "%USERPROFILE%\Desktop\wcdb-key-tool\all_keys.json" --cdn %*
) else if exist "%USERPROFILE%\Documents\wcdb-key-tool\all_keys.json" (
  python exporter\wxmeme.py --wcdb-keys "%USERPROFILE%\Documents\wcdb-key-tool\all_keys.json" --cdn %*
) else (
  echo wxmeme: all_keys.json not found. Using CDN + sync-persist fallback.
  echo For full sync, provide --db-key or --decrypted-db manually.
  python exporter\wxmeme.py --cdn --sync-persist %*
)
