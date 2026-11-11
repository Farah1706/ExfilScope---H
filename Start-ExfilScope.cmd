@echo off
rem Starts the ExfilScope platform and opens it in the browser. See docs\DEPLOYMENT.md.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-exfilscope.ps1" %*
if errorlevel 1 (
  echo.
  echo ExfilScope could not start. Read the message above, then press any key to close this window.
  pause >nul
)
