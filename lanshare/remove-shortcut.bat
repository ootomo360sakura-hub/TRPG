@echo off
rem Remove the desktop shortcut created by install-shortcut.bat.
rem It asks for confirmation before deleting; nothing else is removed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-shortcut.ps1" -Remove
if errorlevel 1 echo Failed to remove the shortcut.
pause
