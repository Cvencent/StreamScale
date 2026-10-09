@echo off
REM Start the StreamScale tray.
REM
REM Double-click this file. The tray icon appears in the notification area
REM (bottom-right of the taskbar; click the ^ chevron if it is hidden).
REM
REM Before starting, it checks that nothing is already running, because a
REM second copy would hit the single-instance guard and pop up a message
REM rather than doing anything useful.

setlocal
set "EXE=%~dp0StreamScale\StreamScale.exe"

if not exist "%EXE%" (
    echo.
    echo   StreamScale not found at:
    echo     %EXE%
    echo.
    echo   The program is a folder. Keep this file beside it.
    echo.
    pause
    exit /b 1
)

tasklist /FI "IMAGENAME eq StreamScale.exe" 2>nul | find /I "StreamScale.exe" >nul
if not errorlevel 1 (
    echo.
    echo   StreamScale is already running.
    echo   Look for its icon in the notification area
    echo   ^(bottom-right of the taskbar; click the ^^ chevron if hidden^).
    echo.
    timeout /t 4 >nul
    exit /b 0
)

echo.
echo   Starting StreamScale...
start "" "%EXE%"
echo.
echo   The icon should appear in the notification area shortly.
timeout /t 3 >nul
exit /b 0
