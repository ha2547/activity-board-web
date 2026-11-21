@echo off
setlocal
cd /d "%~dp0"

if not exist logs mkdir logs

set ACTIVITY_BOARD_HOST=0.0.0.0
if "%ACTIVITY_BOARD_PORT%"=="" set ACTIVITY_BOARD_PORT=5050

set "PYTHON_EXE=C:\Users\taeuk.ha\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python executable not found: %PYTHON_EXE%
    exit /b 1
)

:run_server
echo [START] %date% %time% >> "logs\activity_board.log"
"%PYTHON_EXE%" app.py >> "logs\activity_board.log" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo [STOP]  %date% %time% exit_code=%EXIT_CODE% >> "logs\activity_board.log"

REM Keep retrying so the service comes back after transient failures.
timeout /t 5 /nobreak >nul
goto run_server
