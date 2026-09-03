@echo off
rem Create a desktop shortcut for the LAN file sharing app.
rem The PowerShell script prints the result (in Japanese).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-shortcut.ps1"
if errorlevel 1 echo Failed to create the shortcut.
pause
