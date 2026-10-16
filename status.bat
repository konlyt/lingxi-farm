@echo off
rem ============================================================
rem 文件说明：服务状态查看包装脚本（双击即可运行）
rem 内部逻辑：以 Bypass 策略调用同目录 status.ps1，显示 MySQL/
rem           后端(8000)/前端(5173)运行状态与进程 PID。
rem ============================================================
chcp 65001 >nul
title 灵犀田园系统 - 状态
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0status.ps1"
echo.
pause
