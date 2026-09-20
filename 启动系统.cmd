@echo off
title BrainShell - Start All
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-all.ps1"
set EXITCODE=%errorlevel%
echo.
if not "%EXITCODE%"=="0" echo [WARN] exit code %EXITCODE% - see .runtime\logs
echo Done. You can close this window.
echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 pause >nul
exit /b %EXITCODE%
