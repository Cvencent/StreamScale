@echo off
REM StreamScale launcher.
REM Kept ASCII-only: cmd.exe reads .bat using the system ANSI codepage, so
REM non-ASCII comments would corrupt the file on some machines.
start "" "%~dp0StreamScale.exe"
