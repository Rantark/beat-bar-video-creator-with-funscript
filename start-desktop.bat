@echo off
REM funscript-gen desktop-app launcher.
REM
REM Runs the FastAPI backend inside the process and opens a native
REM WebView2 window pointed at it. The backend still binds 0.0.0.0:8000
REM so the phone can reach it over Tailscale exactly like start.bat.
REM
REM First run builds the frontend into frontend/dist and installs
REM pywebview. Subsequent runs skip both.

setlocal
set "REPO=%~dp0"

REM Frontend build — required so FastAPI can serve / at :8000.
if not exist "%REPO%frontend\dist\index.html" (
    echo Building frontend...
    pushd "%REPO%frontend"
    set "PATH=C:\Program Files\nodejs;%PATH%"
    call npm install
    if errorlevel 1 goto :err_npm
    call npm run build
    if errorlevel 1 goto :err_npm
    popd
)

REM Ensure pywebview is installed. Cheap check — pip is a no-op if
REM the package is already there at the required version.
"%REPO%backend\.venv\Scripts\python.exe" -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo Installing pywebview...
    "%REPO%backend\.venv\Scripts\python.exe" -m pip install "pywebview>=5.3"
    if errorlevel 1 goto :err_pip
)

echo Launching desktop app...
pushd "%REPO%backend"
"%REPO%backend\.venv\Scripts\python.exe" desktop.py
popd

endlocal
exit /b 0

:err_npm
echo.
echo Frontend build failed. Fix the error above and re-run.
popd
endlocal
exit /b 1

:err_pip
echo.
echo pywebview install failed. Fix the error above and re-run.
endlocal
exit /b 1
