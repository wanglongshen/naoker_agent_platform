@echo off
title BrainShell - Autostart Install
echo Installing the logon autostart task (current user, no admin required)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-autostart.ps1" %*
set EXITCODE=%errorlevel%
echo.
echo To remove it later, run: scripts\install-autostart.ps1 -Uninstall
echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 pause >nul
exit /b %EXITCODE%
