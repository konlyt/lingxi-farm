"""后端服务启动入口脚本。

负责以 uvicorn 方式启动 FastAPI 应用，监听 0.0.0.0:8000，
供开发环境一键启动使用（前端 Vite 代理指向本服务）。
"""
import uvicorn


def main() -> None:
    """启动 uvicorn 开发服务器。

    Returns:
        None: 无返回值，进程持续运行直至手动停止。

    Raises:
        Exception: 端口被占用或应用加载失败时由 uvicorn 抛出并终止进程。
    """
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
