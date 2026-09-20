@echo off
title BrainShell - Status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\status-all.ps1"
set EXITCODE=%errorlevel%
echo.
echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 pause >nul
exit /b %EXITCODE%
