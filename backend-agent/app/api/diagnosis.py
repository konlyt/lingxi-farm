"""诊断服务接口路由。

提供诊断任务创建（异步执行）、详情轮询、记录列表与失败重试。
任务创建后经 BackgroundTasks 执行 LangGraph 图，接口即时返回 task_id。
"""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.core.security import require_owner
from app.services import diagnosis_service

router = APIRouter(prefix="/api/diagnosis", tags=["智能诊断"], dependencies=[Depends(require_owner)])


class DiagnosisTaskCreateRequest(BaseModel):
    """诊断任务创建请求体。

    Attributes:
        plot_id: 地块/棚室ID。
        growth_stage: 诊断时生育期（空则取地块当前生育期）。
        image_ids: 图像ID列表（1-4 张，来自 POST /api/images 的返回）。
    """

    plot_id: int = Field(..., gt=0, description="地块ID")
    growth_stage: str | None = Field(None, max_length=32, description="生育期")
    image_ids: list[int] = Field(..., min_length=1, max_length=4, description="图像ID列表 1-4 张")


@router.post("/tasks", summary="创建诊断任务（异步执行）")
def create_diagnosis_task(body: DiagnosisTaskCreateRequest, background_tasks: BackgroundTasks,
                          db: Session = Depends(get_db)) -> dict:
    """创建手动上传通道诊断任务，后台异步执行诊断链路。

    Args:
        body: 任务创建请求体。
        background_tasks: FastAPI 后台任务。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {task_id, thread_id, status}，可轮询详情接口。

    Raises:
        BusinessException: 400 图像校验失败；404 地块不存在。
    """
    task = diagnosis_service.create_task(
        db, plot_id=body.plot_id, growth_stage=body.growth_stage,
        image_ids=body.image_ids, source="manual",
    )
    background_tasks.add_task(diagnosis_service.run_task, task.id)
    return ok({"task_id": task.id, "thread_id": task.thread_id, "status": task.status})


@router.get("/tasks/{task_id}", summary="诊断任务详情（轮询用）")
def get_diagnosis_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    """查询诊断任务详情（含 images/results/plan/case）。

    Args:
        task_id: 任务ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为任务详情。

    Raises:
        BusinessException: 404 任务不存在。
    """
    return ok(diagnosis_service.get_task_detail(db, task_id))


@router.get("/records", summary="诊断记录分页列表")
def list_diagnosis_records(
    plot_id: Optional[int] = Query(None, gt=0, description="地块过滤"),
    source: Optional[str] = Query(None, pattern="^(device|manual)$", description="来源过滤"),
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    level: Optional[str] = Query(None, pattern="^(high|low)$", description="结果级别过滤"),
    page_no: int = Query(1, alias="page", ge=1, description="页码"),
    page_size: int = Query(20, alias="page_size", ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
) -> dict:
    """分页查询诊断记录（联表返回缩略图/病名/案例状态）。

    Args:
        plot_id: 地块过滤。
        source: 来源过滤。
        start: 开始日期。
        end: 结束日期。
        level: 级别过滤。
        page_no: 页码。
        page_size: 每页条数。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {items, total, page, page_size}。
    """
    return ok(diagnosis_service.list_records(db, plot_id, source, start, end, level, page_no, page_size))


@router.post("/tasks/{task_id}/retry", summary="失败任务重试")
def retry_diagnosis_task(task_id: int, background_tasks: BackgroundTasks,
                         db: Session = Depends(get_db)) -> dict:
    """重试失败的诊断任务（重置后后台重新执行）。

    Args:
        task_id: 任务ID。
        background_tasks: FastAPI 后台任务。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {task_id, status}。

    Raises:
        BusinessException: 404 任务不存在；400 非失败任务。
    """
    task = diagnosis_service.reset_failed_task(db, task_id)
    background_tasks.add_task(diagnosis_service.run_task, task.id)
    return ok({"task_id": task.id, "status": task.status})
