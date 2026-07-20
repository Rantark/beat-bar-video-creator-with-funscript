@echo off
REM funscript-gen shutdown — kills whatever is listening on :5173 and :8000.
REM Safer than closing terminals if a server got orphaned.

setlocal EnableDelayedExpansion
for %%P in (8000 5173) do (
  set "found="
  for /F "tokens=5" %%I in ('netstat -ano ^| findstr :%%P ^| findstr LISTENING') do (
    set "found=1"
    echo Killing PID %%I on :%%P
    taskkill /F /PID %%I >nul 2>&1
  )
  if not defined found echo Port %%P was already free.
)
endlocal
