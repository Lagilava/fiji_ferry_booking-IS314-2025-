@echo off
REM ============================================================
REM  Fiji Ferry Booking - one-click local launcher
REM  Starts Redis, the Django/Daphne server, then opens Chrome.
REM ============================================================

setlocal
set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo [1/3] Starting Redis server...
start "Redis" /D "%PROJECT_DIR%Redis" "%PROJECT_DIR%Redis\redis-server.exe" "%PROJECT_DIR%Redis\redis.windows.conf"

REM Give Redis a moment to come up before the app connects.
timeout /t 3 /nobreak >nul

echo [2/3] Starting Django server...
start "Ferry Server" cmd /k "cd /d "%PROJECT_DIR%" && call venv\Scripts\activate && python manage.py runserver 0.0.0.0:8000"

REM Wait for the server to be ready before opening the browser.
echo Waiting for the server to start...
timeout /t 8 /nobreak >nul

echo [3/3] Opening booking site in Chrome...
start "" chrome "http://127.0.0.1:8000/"

echo.
echo All services launched. Close the Redis and Ferry Server windows to stop.
endlocal
