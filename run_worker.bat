@echo off
REM Otclick worker (background apply loop). Reuses the same code as the API.
setlocal
set "PATH=C:\Windows\System32;C:\Windows;C:\script\tender\Otclick-hh\.venv\Scripts"
set "SUPABASE_URL=http://127.0.0.1:54321"
set "PYTHONPATH=."
cd /d C:\script\tender\Otclick-hh\backend
C:\script\tender\Otclick-hh\.venv\Scripts\python.exe worker_main.py
endlocal
