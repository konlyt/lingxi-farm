# =====================================================================
# 文件名称: start.ps1
# 文件说明: 灵犀田园系统一键启动脚本。
#           按序启动后端(FastAPI/uvicorn, 端口 8000)与前端(Vite, 端口 5173)，
#           具备环境检查与幂等启动能力(重复执行不会重复拉起已在运行的服务)。
# 运行方式: powershell -ExecutionPolicy Bypass -File start.ps1
# 兼容环境: Windows PowerShell 5.1 及以上
# =====================================================================

# 全局错误策略: 任何错误立即终止, 由外层 try/catch 统一输出中文提示
$ErrorActionPreference = 'Stop'

try {
    # ---------------- 路径与常量定义 ----------------
    $rootDir    = $PSScriptRoot                                       # 脚本所在目录(项目根目录)
    $backendDir = Join-Path $rootDir 'backend-agent'                  # 后端工作目录
    $frontDir   = Join-Path $rootDir 'front-web\project_six'          # 前端工作目录
    $logDir     = Join-Path $rootDir 'logs'                           # 日志目录
    $pythonExe  = Join-Path $backendDir '.venv\Scripts\python.exe'    # 后端虚拟环境解释器
    $pidsFile   = Join-Path $logDir 'pids.json'                       # 子进程 PID 记录文件
    $backendUrl = 'http://localhost:8000/docs'                        # 后端就绪探测地址(Swagger 文档页)
    $readyWait  = 30                                                  # 服务就绪最长等待时间(秒)

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

    # ---------------- 网络与端口工具函数 ----------------

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

    function Test-PortListening {
        # <summary>检测本机端口是否已处于监听状态(用于幂等判断)。</summary>
        # <param name="Port">本机端口号。</param>
        # <returns>有监听返回 $true, 否则返回 $false。</returns>
        param([int]$Port)
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return ($null -ne $conn)
    }

    function Get-ListenPid {
        # <summary>获取本机端口监听进程的 PID。</summary>
        # <param name="Port">本机端口号。</param>
        # <returns>监听进程的 PID(整型); 无监听时返回 $null。</returns>
        param([int]$Port)
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
        return $null
    }

    # ---------------- 服务启动函数 ----------------

    function Start-HiddenCmd {
        # <summary>生成临时启动批处理文件并以隐藏窗口方式执行(实现日志追加重定向)。
        #          说明: PS 5.1 的 Start-Process 会给含空格参数自动加引号导致 cmd /c
        #          嵌套引号转义失败, 故改用 .NET ProcessStartInfo 精确控制命令行。</summary>
        # <param name="BatPath">临时批处理文件的完整路径(位于 logs 目录)。</param>
        # <param name="WorkDir">批处理执行时的工作目录。</param>
        # <param name="Command">批处理中要执行的核心命令行(可含 >> 重定向)。</param>
        # <returns>返回 cmd.exe 包装进程的 System.Diagnostics.Process 对象(含 Id/HasExited)。</returns>
        param([string]$BatPath, [string]$WorkDir, [string]$Command)
        # 批处理内容全部为 ASCII 路径与命令, 使用 ASCII 编码写入避免兼容性问题
        $batContent = "@echo off`r`ncd /d `"$WorkDir`"`r`n$Command`r`n"
        [IO.File]::WriteAllText($BatPath, $batContent, [System.Text.Encoding]::ASCII)
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName         = $env:ComSpec
        $psi.Arguments        = "/c `"$BatPath`""
        $psi.WorkingDirectory = $WorkDir
        $psi.UseShellExecute  = $false
        $psi.CreateNoWindow   = $true
        return [System.Diagnostics.Process]::Start($psi)
    }

    function Start-BackendService {
        # <summary>后台启动后端 uvicorn 服务并轮询就绪(最多 $readyWait 秒)。</summary>
        # <param name="LogFile">日志文件路径(通过 cmd 追加重定向, 保留历史日志)。</param>
        # <returns>就绪后返回 uvicorn 实际 python 进程的 PID; 启动失败抛出异常。</returns>
        # <exception cref="System.Exception">30 秒内未就绪时抛出, 并清理已拉起的子进程。</exception>
        param([string]$LogFile)
        Write-Step '正在后台启动后端服务(uvicorn, 端口 8000)...'
        # 通过临时批处理执行: "python.exe" run.py >> 日志 2>&1 (追加合并输出)
        $cmdProc = Start-HiddenCmd -BatPath (Join-Path $logDir 'launch-backend.cmd') `
                                   -WorkDir $backendDir `
                                   -Command "`"$pythonExe`" run.py >> `"$LogFile`" 2>&1"
        Write-Step "后端进程已拉起(包装进程 PID=$($cmdProc.Id)), 轮询就绪中(最多 $readyWait 秒)..."
        for ($i = 1; $i -le $readyWait; $i++) {
            Start-Sleep -Seconds 1
            try {
                $resp = Invoke-WebRequest -Uri $backendUrl -UseBasicParsing -TimeoutSec 3
                if ($resp.StatusCode -eq 200) {
                    $realPid = Get-ListenPid -Port 8000
                    Write-Ok "后端已就绪: $backendUrl (python PID=$realPid)"
                    return $realPid
                }
            }
            catch {
                # 就绪前 HTTP 探测失败属预期情况, 继续轮询
            }
            # 包装进程已退出且端口仍未监听 => 启动失败, 提前终止轮询
            if ($cmdProc.HasExited -and -not (Test-PortListening -Port 8000)) { break }
        }
        # 失败清理: 终止可能残留的 python 子进程
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $($cmdProc.Id)" |
            Where-Object { $_.Name -like 'python*' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        throw "后端在 $readyWait 秒内未就绪, 请查看日志: $LogFile"
    }

    function Start-FrontService {
        # <summary>后台启动前端 Vite 开发服务器并轮询 5173 端口就绪。</summary>
        # <param name="LogFile">日志文件路径(通过 cmd 追加重定向, 保留历史日志)。</param>
        # <returns>就绪后返回 Vite 实际 node 进程的 PID; 启动失败抛出异常。</returns>
        # <exception cref="System.Exception">30 秒内 5173 端口未监听时抛出。</exception>
        param([string]$LogFile)
        Write-Step '正在后台启动前端服务(Vite, 端口 5173)...'
        # 通过临时批处理执行: npm run dev >> 日志 2>&1 (追加合并输出)
        $cmdProc = Start-HiddenCmd -BatPath (Join-Path $logDir 'launch-frontend.cmd') `
                                   -WorkDir $frontDir `
                                   -Command "npm run dev >> `"$LogFile`" 2>&1"
        Write-Step "前端进程已拉起(包装进程 PID=$($cmdProc.Id)), 轮询就绪中(最多 $readyWait 秒)..."
        for ($i = 1; $i -le $readyWait; $i++) {
            Start-Sleep -Seconds 1
            if (Test-PortListening -Port 5173) {
                $realPid = Get-ListenPid -Port 5173
                Write-Ok "前端已就绪: http://localhost:5173 (node PID=$realPid)"
                return $realPid
            }
        }
        throw "前端在 $readyWait 秒内未就绪(5173 未监听), 请查看日志: $LogFile"
    }

    # ================= 主流程 =================

    Write-Host '==============================================' -ForegroundColor Magenta
    Write-Host '      灵犀田园系统 - 一键启动脚本'          -ForegroundColor Magenta
    Write-Host '==============================================' -ForegroundColor Magenta

    # 1. 日志目录(不存在则创建)
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        Write-Ok "已创建日志目录: $logDir"
    }

    # 2. 环境检查: MySQL / 后端虚拟环境 / 前端依赖
    Write-Step '环境检查: MySQL(localhost:3306)...'
    if (-not (Test-TcpPort -TargetHost '127.0.0.1' -Port 3306)) {
        throw 'MySQL 服务不可达(localhost:3306), 请先启动 MySQL 服务后再重试!'
    }
    Write-Ok 'MySQL 可达'

    Write-Step '环境检查: 后端虚拟环境(.venv)...'
    if (-not (Test-Path $pythonExe)) {
        throw "未找到后端虚拟环境解释器: $pythonExe , 请先创建并安装依赖!"
    }
    Write-Ok "虚拟环境正常: $pythonExe"

    Write-Step '环境检查: 前端依赖(node_modules)...'
    if (-not (Test-Path (Join-Path $frontDir 'node_modules'))) {
        throw "前端依赖缺失, 请先执行: cd `"$frontDir`" 然后 npm install"
    }
    Write-Ok '前端依赖正常'

    # 3. 启动后端(幂等: 8000 已监听则跳过)
    if (Test-PortListening -Port 8000) {
        $backendPid = Get-ListenPid -Port 8000
        Write-Warn2 "端口 8000 已被监听(PID=$backendPid), 后端已在运行, 跳过启动"
    }
    else {
        $backendPid = Start-BackendService -LogFile (Join-Path $logDir 'backend.log')
    }

    # 4. 启动前端(幂等: 5173 已监听则跳过)
    if (Test-PortListening -Port 5173) {
        $frontPid = Get-ListenPid -Port 5173
        Write-Warn2 "端口 5173 已被监听(PID=$frontPid), 前端已在运行, 跳过启动"
    }
    else {
        $frontPid = Start-FrontService -LogFile (Join-Path $logDir 'frontend.log')
    }

    # 5. 写入 PID 记录文件(stop.ps1 依赖此文件停止服务)
    $pidsObj = [ordered]@{
        backend_pid  = $backendPid
        frontend_pid = $frontPid
        updated_at   = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    }
    $pidsObj | ConvertTo-Json | Set-Content -Path $pidsFile -Encoding UTF8
    Write-Ok "PID 记录已写入: $pidsFile (后端=$backendPid, 前端=$frontPid)"

    # 6. 打印访问地址
    Write-Host ''
    Write-Host '==============================================' -ForegroundColor Magenta
    Write-Ok '全部服务启动完成!'
    Write-Host "  前端页面  : http://localhost:5173" -ForegroundColor White
    Write-Host "  后端文档  : http://localhost:8000/docs" -ForegroundColor White
    Write-Host '==============================================' -ForegroundColor Magenta
}
catch {
    Write-Host ''
    Write-Host "[启动失败] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '请根据以上提示排查后重新执行 start.ps1' -ForegroundColor Red
    exit 1
}
