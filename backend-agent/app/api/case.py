"""案例库接口路由。

提供案例统计头、按状态/病种分页列表（含图片）、
单条确认/纠正与批量确认接口（全部 owner only）。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok, page
from app.core.security import require_owner
from app.models.case import CaseImage, CaseLibrary
from app.models.diagnosis import DiagnosisTask
from app.models.image import CollectedImage
from app.utils.time_utils import now

router = APIRouter(prefix="/api/cases", tags=["案例库"], dependencies=[Depends(require_owner)])


class CaseCorrectRequest(BaseModel):
    """案例纠正请求体。

    Attributes:
        final_disease_name: 纠正后的病名。
        note: 纠正备注。
    """

    final_disease_name: str = Field(..., min_length=1, max_length=128, description="纠正后的病名")
    note: str | None = Field(None, max_length=255, description="纠正备注")


class BatchConfirmRequest(BaseModel):
    """批量确认请求体。

    Attributes:
        ids: 待确认案例ID列表。
    """

    ids: list[int] = Field(..., min_length=1, description="案例ID列表")


@router.get("/stats", summary="案例统计头")
def case_stats(db: Session = Depends(get_db)) -> dict:
    """统计案例总数、各状态数量与各病种样本量。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {total, pending, confirmed, corrected, by_category}。
    """
    total = db.query(func.count(CaseLibrary.id)).scalar() or 0
    status_rows = (
        db.query(CaseLibrary.status, func.count(CaseLibrary.id))
        .group_by(CaseLibrary.status)
        .all()
    )
    status_map = {status: count for status, count in status_rows}
    category_rows = (
        db.query(CaseLibrary.disease_category, func.count(CaseLibrary.id))
        .group_by(CaseLibrary.disease_category)
        .all()
    )
    by_category = {
        (category or "未分类"): count
        for category, count in category_rows
    }
    return ok(
        {
            "total": total,
            "pending": status_map.get("pending", 0),
            "confirmed": status_map.get("confirmed", 0),
            "corrected": status_map.get("corrected", 0),
            "by_category": by_category,
        }
    )


@router.get("", summary="案例分页列表")
def list_cases(
    status: Optional[str] = Query(None, pattern="^(pending|confirmed|corrected)$", description="状态过滤"),
    category: Optional[str] = Query(None, max_length=32, description="病种过滤"),
    page_no: int = Query(1, alias="page", ge=1, description="页码"),
    page_size: int = Query(20, alias="page_size", ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
) -> dict:
    """分页查询案例列表（items 含 image_urls）。

    Args:
        status: 状态过滤。
        category: 病种过滤。
        page_no: 页码。
        page_size: 每页条数。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {items, total, page, page_size}。
    """
    query = db.query(CaseLibrary)
    if status is not None:
        query = query.filter(CaseLibrary.status == status)
    if category is not None:
        query = query.filter(CaseLibrary.disease_category == category)
    total = query.count()
    rows = (
        query.order_by(CaseLibrary.id.desc())
        .offset((page_no - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for case in rows:
        task = db.query(DiagnosisTask).filter(DiagnosisTask.id == case.task_id).first()
        images = (
            db.query(CollectedImage)
            .join(CaseImage, CaseImage.image_id == CollectedImage.id)
            .filter(CaseImage.case_id == case.id)
            .order_by(CaseImage.id.asc())
            .all()
        )
        # 兜底：案例未关联 case_image 时取诊断任务的首图
        if not images and task is not None:
            from app.models.diagnosis import DiagnosisTaskImage

            images = (
                db.query(CollectedImage)
                .join(DiagnosisTaskImage, DiagnosisTaskImage.image_id == CollectedImage.id)
                .filter(DiagnosisTaskImage.task_id == task.id)
                .order_by(DiagnosisTaskImage.id.asc())
                .all()
            )
        items.append(
            {
                "id": case.id,
                "task_id": case.task_id,
                "ai_disease_name": case.ai_disease_name,
                "final_disease_name": case.final_disease_name,
                "status": case.status,
                "source": case.source,
                "disease_category": case.disease_category,
                "note": case.note,
                "created_at": case.created_at.isoformat() if case.created_at else None,
                "image_urls": [image.cos_url for image in images],
            }
        )
    return ok(page(items, total, page_no, page_size))


@router.post("/{case_id}/confirm", summary="案例确认（final=AI 初判）")
def confirm_case(case_id: int, db: Session = Depends(get_db)) -> dict:
    """确认案例：final_disease_name 取 AI 初判名称。

    Args:
        case_id: 案例ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, status, final_disease_name}。

    Raises:
        BusinessException: 404 案例不存在；400 已处理案例不可重复确认。
    """
    case = db.query(CaseLibrary).filter(CaseLibrary.id == case_id).first()
    if case is None:
        raise BusinessException(404, "案例不存在")
    if case.status != "pending":
        raise BusinessException(400, "该案例已处理，不可重复确认")
    case.status = "confirmed"
    case.final_disease_name = case.ai_disease_name
    case.confirmed_at = now()
    db.commit()
    return ok({"id": case.id, "status": case.status, "final_disease_name": case.final_disease_name})


@router.post("/{case_id}/correct", summary="案例纠正（final=输入病名）")
def correct_case(case_id: int, body: CaseCorrectRequest, db: Session = Depends(get_db)) -> dict:
    """纠正案例：final_disease_name 取用户输入病名，回流案例库。

    Args:
        case_id: 案例ID。
        body: 纠正请求体。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, status, final_disease_name}。

    Raises:
        BusinessException: 404 案例不存在；400 已处理案例不可重复纠正。
    """
    case = db.query(CaseLibrary).filter(CaseLibrary.id == case_id).first()
    if case is None:
        raise BusinessException(404, "案例不存在")
    if case.status != "pending":
        raise BusinessException(400, "该案例已处理，不可重复纠正")
    case.status = "corrected"
    case.final_disease_name = body.final_disease_name
    case.note = body.note
    case.confirmed_at = now()
    db.commit()
    return ok({"id": case.id, "status": case.status, "final_disease_name": case.final_disease_name})


@router.post("/batch-confirm", summary="批量确认案例")
def batch_confirm_cases(body: BatchConfirmRequest, db: Session = Depends(get_db)) -> dict:
    """批量确认待确认案例（仅处理 pending 状态，其余跳过）。

    Args:
        body: 批量确认请求体 {ids}。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {confirmed, skipped}。
    """
    rows = db.query(CaseLibrary).filter(CaseLibrary.id.in_(body.ids), CaseLibrary.status == "pending").all()
    for case in rows:
        case.status = "confirmed"
        case.final_disease_name = case.ai_disease_name
        case.confirmed_at = now()
    db.commit()
    return ok({"confirmed": len(rows), "skipped": len(body.ids) - len(rows)})
