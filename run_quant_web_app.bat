@echo off
title AI Quant Stock Predictor Web Simulator
cls
echo =======================================================================
echo     AI Quant Stock Predictor and Bitemporal Web Simulator Launcher
echo =======================================================================
echo.
echo Starting Web Server... Please wait.
echo.

rem codex 런타임은 갱신될 때 site-packages 가 통째로 초기화되어 streamlit 이 사라진다.
rem 사용자 파이썬(C:\Python314)을 우선 사용하고, 없을 때만 PATH 의 python 으로 넘어간다.
set "PYBIN=C:\Python314\python.exe"

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
