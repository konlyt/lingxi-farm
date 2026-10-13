@echo off
rem ============================================================
rem 文件说明：一键启动包装脚本（双击即可运行，无需手动开 PowerShell）
rem 内部逻辑：以 Bypass 策略调用同目录 start.ps1，完成前置环境检查、
rem           按序启动后端(8000)与前端(5173)，并输出访问地址。
rem ============================================================
chcp 65001 >nul
title 农场智能管护系统 - 启动
echo 正在启动农场智能管护系统，请稍候...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
echo.
echo 窗口可关闭，不影响已启动的服务（日志见 logs\ 目录）。
pause
