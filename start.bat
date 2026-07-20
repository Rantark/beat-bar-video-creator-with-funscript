@echo off
REM funscript-gen launcher.
REM Opens two terminals — backend on :8000, frontend on :5173.
REM Both bind 0.0.0.0 so the phone can reach them over Tailscale.
REM Close either terminal (or the launched cmd windows) to stop.

setlocal
set "REPO=%~dp0"

REM Backend: uvicorn with the venv's Python. /K keeps the terminal open
REM after uvicorn exits so you can see any error.
start "funscript-gen backend" cmd /K "cd /d ""%REPO%backend"" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

REM Frontend: Vite dev server. npm.cmd is prepended to PATH in case Node
REM was installed but not yet on the current user's PATH.
start "funscript-gen frontend" cmd /K "set PATH=C:\Program Files\nodejs;%%PATH%% && cd /d ""%REPO%frontend"" && npm run dev"

echo.
echo Started backend on :8000 and frontend on :5173.
echo Desktop: http://localhost:5173/
echo Phone:   http://^<tailscale-ip^>:5173/  (get IP with: tailscale ip -4)
echo.
echo Close the two cmd windows (or run stop.bat) to shut down.
echo.
endlocal
