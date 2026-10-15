@echo off
title JARVIS 복구
echo.
echo   JARVIS 복구를 시작합니다. 몇 분 걸릴 수 있습니다.
echo   창을 닫지 마세요.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0repair_satellite.ps1" -Force
echo.
echo   끝났습니다. 위 내용을 대표님께 보여주세요.
echo.
pause
