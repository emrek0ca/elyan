@echo off
rem Elyan CLI sarmalayıcısı (Windows)
set ROOT=%~dp0..
if exist "%ROOT%\venv\Scripts\python.exe" (
  set PY=%ROOT%\venv\Scripts\python.exe
) else if exist "%ROOT%\.venv\Scripts\python.exe" (
  set PY=%ROOT%\.venv\Scripts\python.exe
) else (
  set PY=python
)
cd /d "%ROOT%"
"%PY%" -m cli %*
