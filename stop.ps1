# =====================================================================
# 文件名称: stop.ps1
# 文件说明: 农场智能管护系统一键停止脚本。
#           依据 logs\pids.json 停止后端/前端进程(先优雅, 超时强杀),
#           并兜底扫描 8000/5173 端口残留进程与项目相关 python/node 进程,
#           最后校验端口释放情况并清理 PID 记录文件。
# 运行方式: powershell -ExecutionPolicy Bypass -File stop.ps1
# 兼容环境: Windows PowerShell 5.1 及以上
# =====================================================================
param()

# 全局错误策略: 任何错误立即终止, 由外层 try/catch 统一输出中文提示
$ErrorActionPreference = 'Stop'

try {
    # ---------------- 路径与常量定义 ----------------
    $rootDir      = $PSScriptRoot                        # 脚本所在目录(项目根目录)
    $logDir       = Join-Path $rootDir 'logs'            # 日志目录
    $pidsFile     = Join-Path $logDir 'pids.json'        # 子进程 PID 记录文件
    $gracefulWait = 5000                                 # 优雅停止最长等待时间(毫秒)

    # ---------------- 通用输出函数 ----------------

    function Write-Step {
        # <summary>输出阶段性步骤信息(青色)。</summary>
        # <param name="Msg">要输出的消息文本。</param>
        param([string]$Msg)
        Write-Host "[步骤] $Msg" -ForegroundColor Cyan
    }

    function Write-Ok {
        # <summary>输出成功信息(绿色)。</summary>
        # <param name="Msg">要输出的消息文本。</param>
        param([string]$Msg)
        Write-Host "[成功] $Msg" -ForegroundColor Green
    }

    function Write-Warn2 {
        # <summary>输出警告信息(黄色)。</summary>
        # <param name="Msg">要输出的消息文本。</param>
        param([string]$Msg)
        Write-Host "[提示] $Msg" -ForegroundColor Yellow
    }

    # ---------------- 进程停止工具函数 ----------------

    function Stop-ProcessGraceful {
        # <summary>按"先优雅后强杀"策略停止指定进程。</summary>
        # <param name="ProcId">目标进程 PID。</param>
        # <returns>无返回值; 结果通过控制台输出(优雅/强杀/跳过)。</returns>
        param([int]$ProcId)
        if ($ProcId -eq $PID) { return }   # 防止误杀脚本自身
        $proc = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
        if (-not $proc) {
            Write-Warn2 "PID=$ProcId 进程已不存在, 跳过"
            return
        }
        Write-Step "正在停止进程 PID=$ProcId ($($proc.ProcessName))..."
        # 第一步: 尝试优雅关闭(仅对拥有主窗口的进程有效)
        $null = $proc.CloseMainWindow()
        if ($proc.WaitForExit($gracefulWait)) {
            Write-Ok "已优雅停止 PID=$ProcId"
        }
        else {
            # 第二步: 超时未退出, 强制终止
            Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
            Write-Ok "优雅停止超时, 已强制终止 PID=$ProcId"
        }
    }

    function Get-ListenPids {
        # <summary>获取指定端口集合上所有监听进程的 PID(去重)。</summary>
        # <param name="Ports">端口号数组, 例如 @(8000, 5173)。</param>
        # <returns>PID 整型数组; 无监听时返回空数组。</returns>
        param([int[]]$Ports)
        $conns = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            return @($conns.OwningProcess | Select-Object -Unique | ForEach-Object { [int]$_ })
        }
        return @()
    }

    function Remove-ProjectLeftover {
        # <summary>兜底清理项目相关残留进程(按命令行特征过滤, 避免误杀无关进程)。</summary>
        # <returns>无返回值。</returns>
        # python 残留: 命令行含 run.py 的 python 进程
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
            Where-Object { $_.CommandLine -like '*run.py*' } |
            ForEach-Object {
                Write-Warn2 "发现残留后端进程 PID=$($_.ProcessId), 强制终止"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        # vite 残留: 命令行含 vite 的 node 进程
        Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
            Where-Object { $_.CommandLine -like '*vite*' } |
            ForEach-Object {
                Write-Warn2 "发现残留前端进程(vite) PID=$($_.ProcessId), 强制终止"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        # npm 残留: npm-cli.js run dev 的 node 进程
        Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
            Where-Object { $_.CommandLine -like '*npm-cli.js*run*' } |
            ForEach-Object {
                Write-Warn2 "发现残留前端进程(npm) PID=$($_.ProcessId), 强制终止"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
    }

    # ================= 主流程 =================

    Write-Host '==============================================' -ForegroundColor Magenta
    Write-Host '      农场智能管护系统 - 一键停止脚本'          -ForegroundColor Magenta
    Write-Host '==============================================' -ForegroundColor Magenta

    # 1. 读取 PID 记录文件
    $targetPids = @()
    if (Test-Path $pidsFile) {
        try {
            $json = Get-Content -Path $pidsFile -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($key in @('backend_pid', 'frontend_pid')) {
                $val = $json.$key
                if ($val -and [int]$val -gt 0) { $targetPids += [int]$val }
            }
            Write-Ok "已读取 PID 记录: $pidsFile"
        }
        catch {
            Write-Warn2 "PID 记录文件解析失败(可能已损坏), 将仅使用端口兜底扫描: $($_.Exception.Message)"
        }
    }
    else {
        Write-Warn2 "未找到 PID 记录文件: $pidsFile (服务可能未通过 start.ps1 启动), 将仅使用端口兜底扫描"
    }

    # 2. 逐个停止记录的进程(先优雅, 5 秒超时强杀)
    foreach ($p in ($targetPids | Select-Object -Unique)) {
        Stop-ProcessGraceful -ProcId $p
    }

    # 3. 兜底: 扫描仍监听 8000/5173 的进程并强制终止
    Start-Sleep -Milliseconds 500
    $leftoverPids = Get-ListenPids -Ports @(8000, 5173)
    foreach ($p in $leftoverPids) {
        if ($p -eq $PID) { continue }
        Write-Warn2 "兜底清理: 端口 8000/5173 仍被 PID=$p 监听, 强制终止"
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }

    # 4. 兜底: 清理项目相关残留 python/node 进程(按命令行特征)
    Remove-ProjectLeftover

    # 5. 校验端口已释放且无残留进程
    Start-Sleep -Seconds 1
    $stillListen = Get-NetTCPConnection -LocalPort 8000, 5173 -State Listen -ErrorAction SilentlyContinue
    $stillPython = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like '*run.py*' }
    $stillNode = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
        Where-Object { $_.CommandLine -like '*vite*' -or $_.CommandLine -like '*npm-cli.js*run*' }

    if (-not $stillListen -and -not $stillPython -and -not $stillNode) {
        Write-Ok '校验通过: 端口 8000/5173 已全部释放, 无残留 python/node 进程!'
    }
    else {
        Write-Warn2 '校验发现以下残留:'
        if ($stillListen) {
            $stillListen | ForEach-Object { Write-Warn2 "  端口 $($_.LocalPort) 仍被 PID=$($_.OwningProcess) 监听" }
        }
        if ($stillPython) { $stillPython | ForEach-Object { Write-Warn2 "  残留 python 进程 PID=$($_.ProcessId)" } }
        if ($stillNode)   { $stillNode   | ForEach-Object { Write-Warn2 "  残留 node 进程 PID=$($_.ProcessId)" } }
    }

    # 6. 清理 PID 记录文件
    if (Test-Path $pidsFile) {
        Remove-Item -Path $pidsFile -Force
        Write-Ok "已清理 PID 记录文件: $pidsFile"
    }

    Write-Host ''
    Write-Ok '全部服务已停止。'
}
catch {
    Write-Host ''
    Write-Host "[停止失败] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '可手动检查端口占用: netstat -ano | findstr "8000 5173"' -ForegroundColor Red
    exit 1
}
