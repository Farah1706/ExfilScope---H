@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch-hackathon.ps1" -Live
if errorlevel 1 pause