@echo off
rem LAN file sharing server - double-click to start (Windows)
chcp 65001 > nul
setlocal
cd /d "%~dp0.."

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

where py > nul 2>&1
if %errorlevel%==0 (
    set PYCMD=py -3
) else (
    where python > nul 2>&1
    if errorlevel 1 (
        echo Python was not found. Install Python 3.9+ from https://www.python.org/downloads/windows/
        echo [Add python.exe to PATH] must be checked during installation.
        pause
        exit /b 1
    )
    set PYCMD=python
)

if not exist "shared" mkdir "shared"
%PYCMD% -m lanshare --dir "shared" --open %*
pause
