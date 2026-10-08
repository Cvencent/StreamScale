@echo off
REM StreamScale launcher.
REM
REM Starts the tray from the onedir layout: the program is a folder, and the
REM exe inside it needs its _internal folder beside it in order to run.
REM
REM Kept ASCII-only: cmd.exe reads .bat using the system ANSI codepage, so
REM non-ASCII comments would corrupt the file on some machines.

setlocal
set "APPDIR=%~dp0StreamScale"
if not exist "%APPDIR%\StreamScale.exe" (
    echo StreamScale not found at:
    echo   %APPDIR%\StreamScale.exe
    echo.
    echo The program is a folder. Keep it together with this script.
    pause
    exit /b 1
)

start "" "%APPDIR%\StreamScale.exe"
