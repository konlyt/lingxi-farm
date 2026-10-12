# =====================================================================
# 文件名称: status.ps1
# 文件说明: 农场智能管护系统服务状态查看脚本。
#           以表格形式展示 MySQL(3306)可达性、后端(8000)与前端(5173)
#           的监听状态及对应进程 PID / 进程名。
# 运行方式: powershell -ExecutionPolicy Bypass -File status.ps1
# 兼容环境: Windows PowerShell 5.1 及以上
# =====================================================================
param()

# 全局错误策略: 任何错误立即终止, 由外层 try/catch 统一输出中文提示
$ErrorActionPreference = 'Stop'

try {
    # ---------------- 通用输出函数 ----------------

    function Write-Ok {
        # <summary>输出成功信息(绿色)。</summary>
        # <param name="Msg">要输出的消息文本。</param>
        param([string]$Msg)
        Write-Host "[正常] $Msg" -ForegroundColor Green
    }

    function Write-Warn2 {
        # <summary>输出警告信息(黄色)。</summary>
        # <param name="Msg">要输出的消息文本。</param>
        param([string]$Msg)
        Write-Host "[提示] $Msg" -ForegroundColor Yellow
    }

    # ---------------- 网络工具函数 ----------------

    function Test-TcpPort {
        # <summary>检测目标主机指定 TCP 端口是否可达。</summary>
        # <param name="TargetHost">目标主机地址(IP 或域名)。</param>
        # <param name="Port">目标端口号。</param>
        # <param name="TimeoutMs">连接超时时间(毫秒), 默认 2000。</param>
        # <returns>可达返回 $true, 不可达或超时返回 $false。</returns>
        param([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 2000)
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $task = $client.ConnectAsync($TargetHost, $Port)
            if ($task.Wait($TimeoutMs) -and $client.Connected) { return $true }
            return $false
        }
        catch {
            # 网络异常(连接被拒绝/主机不可达等)一律视为不可达
            return $false
        }
        finally {
            $client.Close()
        }
    }

    function Get-ListenInfo {
        # <summary>获取本机端口监听信息(状态/PID/进程名)。</summary>
        # <param name="Port">本机端口号。</param>
        # <returns>返回哈希表: @{ Running=bool; Pid=int或$null; ProcName=string或'-' }。</returns>
        param([int]$Port)
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) {
            $procId = [int]$conn.OwningProcess
            $procName = '-'
            try { $procName = (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { $procName = '-' }
            return @{ Running = $true; Pid = $procId; ProcName = $procName }
        }
        return @{ Running = $false; Pid = $null; ProcName = '-' }
    }

    # ================= 主流程 =================

    Write-Host '==============================================' -ForegroundColor Magenta
    Write-Host '      农场智能管护系统 - 服务状态查看'          -ForegroundColor Magenta
    Write-Host '==============================================' -ForegroundColor Magenta
    Write-Host ''

    # 1. MySQL 可达性检查
    $mysqlOk = Test-TcpPort -TargetHost '127.0.0.1' -Port 3306

    # 2. 后端(8000)监听信息
    $backend = Get-ListenInfo -Port 8000

    # 3. 前端(5173)监听信息
    $frontend = Get-ListenInfo -Port 5173

    # 4. 组装表格并输出
    $rows = @(
        [PSCustomObject]@{
            '服务'          = 'MySQL 数据库'
            '端口'          = 3306
            '状态'          = $(if ($mysqlOk) { '可达' } else { '不可达' })
            'PID'           = '-'
            '进程名'        = '-'
        }
        [PSCustomObject]@{
            '服务'          = '后端(FastAPI)'
            '端口'          = 8000
            '状态'          = $(if ($backend.Running) { '运行中' } else { '未运行' })
            'PID'           = $(if ($backend.Pid) { $backend.Pid } else { '-' })
            '进程名'        = $backend.ProcName
        }
        [PSCustomObject]@{
            '服务'          = '前端(Vite)'
            '端口'          = 5173
            '状态'          = $(if ($frontend.Running) { '运行中' } else { '未运行' })
            'PID'           = $(if ($frontend.Pid) { $frontend.Pid } else { '-' })
            '进程名'        = $frontend.ProcName
        }
    )
    $rows | Format-Table -AutoSize | Out-Host

    # 5. 补充说明信息
    if ($mysqlOk) { Write-Ok 'MySQL(localhost:3306) 可达' } else { Write-Host '[提示] MySQL(localhost:3306) 不可达, 请先启动 MySQL 服务!' -ForegroundColor Yellow }
    if ($backend.Running) {
        Write-Ok "后端运行中: http://localhost:8000/docs (PID=$($backend.Pid), 进程=$($backend.ProcName))"
    }
    else {
        Write-Host '[提示] 后端未运行, 执行 start.ps1 可启动' -ForegroundColor Yellow
    }
    if ($frontend.Running) {
        Write-Ok "前端运行中: http://localhost:5173 (PID=$($frontend.Pid), 进程=$($frontend.ProcName))"
    }
    else {
        Write-Host '[提示] 前端未运行, 执行 start.ps1 可启动' -ForegroundColor Yellow
    }
    Write-Host ''
}
catch {
    Write-Host ''
    Write-Host "[状态查询失败] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
