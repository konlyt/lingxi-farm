"""FastAPI 应用主入口模块。

负责应用实例创建、CORS 配置、统一响应异常处理、
静态文件（上传图像）挂载、启动时自动建表与路由注册。
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import BASE_DIR
from app.core.database import Base, engine
from app.core.response import BusinessException, fail
from app.services.image_service import UPLOAD_DIR

# 应用日志器
logger = logging.getLogger("farm_app")

# 允许跨域的前端开发地址
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理：启动时建表、向量索引预热、启动调度器；关闭时停止调度器。

    Args:
        app: FastAPI 应用实例。

    Yields:
        None: 应用运行期间挂起。

    Raises:
        Exception: 数据库不可达时建表失败并抛出（终止启动）。
    """
    # 上传目录不存在则创建
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # 启动自动建表（幂等，已存在则跳过；分区由 init_db.py 负责）
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表结构检查/创建完成")
    # 向量索引预热：vectors.json 缺失时自动对种子知识文档切片向量化（失败不阻塞启动）
    try:
        _warmup_vector_store()
    except Exception as exc:  # noqa: BLE001
        logger.warning("向量索引预热失败（RAG 将降级）: %s", exc)
    # 启动定时任务调度器
    from app.core.scheduler import start_scheduler, stop_scheduler

    start_scheduler()
    yield
    stop_scheduler()
    return


def _warmup_vector_store() -> None:
    """向量索引预热：确保 vectors.json 就绪并同步知识文档元数据状态。

    vectors.json 不存在时对全部知识文档切片向量化建立索引；
    随后按向量库实际切片数回写 knowledge_document 的 chunk_count/embed_status。

    Returns:
        None。

    Raises:
        Exception: 数据库查询或向量化失败时抛出，由调用方记录警告。
    """
    from app.core.database import SessionLocal
    from app.models.knowledge import KnowledgeDocument
    from app.services import vector_store

    session = SessionLocal()
    try:
        if not vector_store.VECTOR_FILE.exists():
            docs = session.query(KnowledgeDocument).all()
            documents = []
            for doc in docs:
                relative = (doc.file_url or "").removeprefix("/uploads/")
                file_path = UPLOAD_DIR / relative
                content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
                if content:
                    documents.append({"id": doc.id, "title": doc.title, "category": doc.category, "content": content})
            chunk_count = vector_store.ensure_index_built(documents)
            logger.info("向量索引预热完成: %s 篇文档 / %s 个切片", len(documents), chunk_count)
        # 按向量库实际切片数同步文档元数据（done/pending）
        with open(vector_store.VECTOR_FILE, encoding="utf-8") as f:
            chunks = json.load(f).get("chunks", [])
        count_by_doc: dict[int, int] = {}
        for chunk in chunks:
            count_by_doc[chunk["doc_id"]] = count_by_doc.get(chunk["doc_id"], 0) + 1
        for doc in session.query(KnowledgeDocument).all():
            doc.chunk_count = count_by_doc.get(doc.id, 0)
            doc.embed_status = "done" if doc.chunk_count > 0 else "failed"
        session.commit()
    finally:
        session.close()


app = FastAPI(
    title="灵犀田园系统后端",
    description="单农场自用智能管护系统（蔬菜大棚 + 露天农田）FastAPI 后端",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------- CORS 中间件 ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 静态文件：上传图像 ----------
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ---------- 注册业务路由（统一挂 require_owner：member 仅 GET 放行）----------
from app.api import (  # noqa: E402
    alert,
    auth,
    calendar,
    case,
    chat,
    dashboard,
    device,
    diagnosis,
    environment,
    export,
    image,
    knowledge,
    overview,
    plot,
    settings,
)
from app.api import advisory as advisory_api  # noqa: E402
from app.api.settings import email_router  # noqa: E402

app.include_router(auth.router)
app.include_router(plot.router)
app.include_router(device.router)
app.include_router(image.router)
app.include_router(diagnosis.router)
app.include_router(case.router)
app.include_router(alert.router)
app.include_router(environment.router)
app.include_router(advisory_api.router)
app.include_router(dashboard.router)
app.include_router(knowledge.router)
app.include_router(chat.router)
app.include_router(export.router)
app.include_router(calendar.router)
app.include_router(overview.router)
app.include_router(settings.router)
# 邮箱绑定路由（owner/member 均可绑定自己的邮箱，独立于 require_owner 的 settings 主路由）
app.include_router(email_router)


@app.get("/", summary="健康检查")
def health_check() -> dict:
    """健康检查接口。

    Returns:
        dict: 统一响应，data 为 {service, status}。
    """
    return {"code": 0, "message": "ok", "data": {"service": "farm-care-agent", "status": "running"}}


# ---------- 全局异常处理 ----------

def _http_status(code: int) -> int:
    """将业务错误码映射为 HTTP 状态码。

    Args:
        code: 业务错误码。

    Returns:
        int: 400/401/403/404/422 直接映射，其余统一 400。
    """
    return code if code in (400, 401, 403, 404, 422) else 400


@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException) -> JSONResponse:
    """业务异常处理器：转换为统一响应结构。

    Args:
        request: 当前请求。
        exc: 业务异常实例。

    Returns:
        JSONResponse: {code, message, data} 结构，HTTP 状态码与业务 code 一致。
    """
    return JSONResponse(status_code=_http_status(exc.code), content=fail(exc.code, exc.message))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求参数校验异常处理器：统一转换为 422 业务响应。

    Args:
        request: 当前请求。
        exc: Pydantic/FastAPI 校验异常。

    Returns:
        JSONResponse: {code: 422, message, data: 错误明细}。
    """
    errors = jsonable_encoder(exc.errors())
    first = errors[0] if errors else {}
    location = ".".join(str(loc) for loc in first.get("loc", []))
    message = f"参数校验失败：{location} {first.get('msg', '')}".strip()
    return JSONResponse(status_code=422, content=fail(422, message, errors))


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Starlette HTTP 异常处理器（404 路由不存在等）。

    Args:
        request: 当前请求。
        exc: HTTP 异常实例。

    Returns:
        JSONResponse: 统一响应结构。
    """
    code = exc.status_code if exc.status_code in (400, 401, 403, 404, 422) else 400
    message = exc.detail if isinstance(exc.detail, str) else "请求资源不存在"
    return JSONResponse(status_code=exc.status_code, content=fail(code, message))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常兜底处理器：记录日志并返回 500 统一结构。

    Args:
        request: 当前请求。
        exc: 未捕获异常。

    Returns:
        JSONResponse: {code: 500, message: 服务器内部错误}。
    """
    logger.exception("未捕获异常: %s", exc)
    return JSONResponse(status_code=500, content=fail(500, "服务器内部错误，请稍后重试"))
