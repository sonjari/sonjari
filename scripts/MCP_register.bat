@echo off
title JARVIS MCP register
echo.
echo   Claude Desktop must be FULLY CLOSED first.
echo   (no claude.exe in Task Manager)
echo.
pause
py -3.11 "%~dp0apply_mcp_config.py" || python "%~dp0apply_mcp_config.py"
echo.
echo   Done. Now start Claude Desktop.
pause
