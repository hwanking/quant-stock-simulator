@echo off
title AI Quant Stock Predictor Web Simulator
cls
echo =======================================================================
echo     AI Quant Stock Predictor and Bitemporal Web Simulator Launcher
echo =======================================================================
echo.
echo Starting Web Server... Please wait.
echo.

set "PYBIN=C:\Users\HWAN-9800X3D\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not exist "%PYBIN%" (
    set "PYBIN=python"
)

set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

echo [1/2] Checking python environment: %PYBIN%
"%PYBIN%" -m pip install streamlit matplotlib pandas numpy >nul 2>&1

echo [2/2] Launching Streamlit Web Server (http://localhost:8501)...
echo.

"%PYBIN%" -m streamlit run web_app.py --server.port 8501 --server.headless false

pause
