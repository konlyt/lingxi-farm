@echo off
rem ============================================================
rem 文件说明：一键停止包装脚本（双击即可运行，无需手动开 PowerShell）
rem 内部逻辑：以 Bypass 策略调用同目录 stop.ps1，安全终止后端与前端
rem           进程并校验端口释放、无残留进程。
rem ============================================================
chcp 65001 >nul
title 灵犀田园系统 - 停止
echo 正在停止灵犀田园系统服务...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo.
pause
