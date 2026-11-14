@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0visualize.ps1" %*
exit /b %ERRORLEVEL%
