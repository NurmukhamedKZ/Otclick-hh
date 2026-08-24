@echo off
REM Otclick frontend (Next.js dev). Talks to the local shim (supabase) + backend.
setlocal
set "PATH=C:\Windows\System32;C:\Windows;C:\Program Files\nodejs;C:\script\tender\Otclick-hh\frontend\node_modules\.bin"
set "NODE_OPTIONS=--max-http-header-size=65536"
cd /d C:\script\tender\Otclick-hh\frontend
npx next dev --port 3000 --hostname 0.0.0.0
endlocal
