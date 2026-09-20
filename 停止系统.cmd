@echo off
title BrainShell - Stop All
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-all.ps1"
set EXITCODE=%errorlevel%
echo.
echo Done. You can close this window.
echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 pause >nul
exit /b %EXITCODE%
