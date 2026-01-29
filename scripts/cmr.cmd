@echo off
setlocal

:: cmr - Shortcut for claude-model-router
:: Usage: cmr <command> [args...]

set "SCRIPT_DIR=%~dp0"
set "SRC_DIR=%SCRIPT_DIR%..\src"
set "CLI_PY=%SRC_DIR%\claude_model_router\cli.py"

call :EnsurePython "%~1"
if errorlevel 1 exit /b %errorlevel%

call :RunScript %*
exit /b %errorlevel%

:EnsurePython
set "CMD=%~1"
if /i "%CMD%"=="init" (
    call :CheckPython
    if not errorlevel 1 exit /b 0
    call :InstallPython
    call :CheckPython
    if not errorlevel 1 exit /b 0
    echo Python install failed or not on PATH. Reopen terminal or install manually.
    exit /b 1
)
call :CheckPython
if not errorlevel 1 exit /b 0
echo Python not found. Install it or run "cmr init".
exit /b 1

:CheckPython
where /q python
if not errorlevel 1 exit /b 0
where /q py
if not errorlevel 1 exit /b 0
exit /b 1

:InstallPython
where /q winget
if errorlevel 1 (
    echo Python not found and winget is unavailable. Install Python manually.
    exit /b 1
)
echo Python not found. Installing via winget...
winget install -e --id Python.Python.3 --source winget
exit /b %errorlevel%

:RunScript
:: Add src directory to PYTHONPATH for imports
set "PYTHONPATH=%SRC_DIR%;%PYTHONPATH%"
where /q python
if not errorlevel 1 (
    python "%CLI_PY%" %*
    exit /b %errorlevel%
)
where /q py
if not errorlevel 1 (
    py -3 "%CLI_PY%" %*
    exit /b %errorlevel%
)
echo Python not found. Reopen terminal and retry.
exit /b 1
