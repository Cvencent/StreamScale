@echo off
REM Repair the Sunshine prep-commands.
REM
REM The installed apps.json named a copy of the tray executable sitting in
REM Downloads. That copy did not understand "apply": it started a second
REM tray instead, and Sunshine waits for its prep-command to exit. The
REM session teardown stalled, the client showed an empty desktop, and the
REM display configuration was never restored.
REM
REM Needs administrator rights because Sunshine lives in Program Files.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo === Repairing Sunshine prep-commands ===
echo.
"C:\Users\vencent\AppData\Local\Programs\Python\Python313\python.exe" "E:\StreamScale\_fix_prepcmd.py" --apply --exe "E:\StreamScale\StreamScale\StreamScale.exe"
echo.
echo Press any key to close.
pause >nul
