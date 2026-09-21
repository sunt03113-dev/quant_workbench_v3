@echo off
rem Quant Workbench one-click launcher (Windows)
rem Double-click -> ensure backend -> open browser. Server: http://127.0.0.1:8000/
setlocal
set "ROOT=D:\09work\quant_workbench_v3\quant_workbench_package"
set "PY=C:\Users\21412\.workbuddy\binaries\python\envs\qwb\Scripts\python.exe"
set "URL=http://127.0.0.1:8000/"

rem --- already running? then just open the UI ---
powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing -Uri '%URL%api/daily/state' -TimeoutSec 3)|Out-Null;exit 0}catch{exit 1}" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
  echo [qwb] backend already running - opening browser...
  start "" "%URL%"
  goto :end
)

rem --- start backend in its own window, then wait until ready ---
cd /d "%ROOT%\app"
start "qwb-server" "%PY%" -X utf8 server.py
echo [qwb] starting backend, waiting for readiness (up to 120s)...
powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){try{(Invoke-WebRequest -UseBasicParsing -Uri '%URL%api/daily/state' -TimeoutSec 3)|Out-Null;exit 0}catch{Start-Sleep -Seconds 1}};exit 1"
if "%ERRORLEVEL%"=="0" (
  start "" "%URL%"
  echo [qwb] UI opened.
) else (
  echo [qwb] backend not ready after 120s - check the "qwb-server" window for errors.
)

:end
echo [qwb] this window closes in 5 seconds.
timeout /t 5 >nul
endlocal
