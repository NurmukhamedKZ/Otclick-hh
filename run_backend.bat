@echo off
REM Otclick backend (FastAPI/uvicorn). Connects to the local shim (port 54321)
REM and the local Postgres-backed services. SUPABASE_URL is overridden to the shim.
setlocal
set "PATH=C:\Windows\System32;C:\Windows;C:\script\tender\Otclick-hh\.venv\Scripts"
set "SUPABASE_URL=http://127.0.0.1:54321"
set "PYTHONPATH=."
cd /d C:\script\tender\Otclick-hh\backend
C:\script\tender\Otclick-hh\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000
endlocal
