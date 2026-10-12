"""诊断任务业务服务模块。

负责任务创建校验、后台异步执行（LangGraph 图编排）、
任务状态流转（pending→running→done/failed）、失败重试与详情组装。
"""
import logging
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agents.graph import build_farm_graph
from app.core.database import SessionLocal
from app.core.response import BusinessException
from app.models.case import CaseLibrary
from app.models.device import Device
from app.models.diagnosis import DiagnosisResult, DiagnosisTask, DiagnosisTaskImage, PreventionPlan
from app.models.image import CollectedImage
from app.models.knowledge import HarvestRestriction
from app.models.plot import Plot
from app.utils.time_utils import fmt_datetime, now

logger = logging.getLogger("farm_diagnosis")


def create_task(db: Session, plot_id: int, growth_stage: str | None,
                image_ids: list[int], source: str = "manual",
                device_id: Optional[int] = None) -> DiagnosisTask:
    """创建诊断任务并关联图像（不执行，由后台任务执行）。

    Args:
        db: 数据库会话（调用方 commit，本函数 flush 取ID）。
        plot_id: 地块/棚室ID。
        growth_stage: 诊断时生育期（空则取地块当前生育期）。
        image_ids: 图像ID列表（1-4 张，须存在且属于该地块）。
        source: 来源 device/manual。
        device_id: 设备来源时的采集设备ID（可空）。

    Returns:
        DiagnosisTask: 新建任务 ORM 实例（status=pending）。

    Raises:
        BusinessException: 404 地块不存在；400 图像数量或归属校验失败。
    """
    if not 1 <= len(image_ids) <= 4:
        raise BusinessException(400, "诊断任务需 1-4 张图像")
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    valid_images = db.query(CollectedImage).filter(CollectedImage.id.in_(image_ids)).all()
    if len(valid_images) != len(image_ids):
        raise BusinessException(400, "存在无效图像ID")
    for image in valid_images:
        if image.plot_id != plot_id:
            raise BusinessException(400, f"图像 {image.id} 不属于地块「{plot.name}」，请检查")

    task = DiagnosisTask(
        thread_id=uuid.uuid4().hex,
        plot_id=plot_id,
        source=source,
        growth_stage=growth_stage or plot.growth_stage,
        status="pending",
    )
    db.add(task)
    db.flush()
    for image_id in image_ids:
        db.add(DiagnosisTaskImage(task_id=task.id, image_id=image_id))
    db.commit()
    return task


def run_task(task_id: int) -> None:
    """后台执行诊断任务（BackgroundTasks 入口，独立数据库会话）。

    流程：置 running → LangGraph 图执行（诊断→条件路由）→
    依据最终 state 更新 result_level/fused_confidence/status；
    异常时置 failed 并记录 failure_reason。

    Args:
        task_id: 诊断任务ID。

    Returns:
        None: 无返回值，状态变化直接落库。

    Raises:
        Exception: 不向外抛出（全部捕获落库为 failed），保证后台任务不崩溃。
    """
    session: Session = SessionLocal()
    try:
        task = session.query(DiagnosisTask).filter(DiagnosisTask.id == task_id).first()
        if task is None:
            logger.error("诊断任务不存在: %s", task_id)
            return
        task.status = "running"
        session.commit()

        image_links = (
            session.query(DiagnosisTaskImage.image_id)
            .filter(DiagnosisTaskImage.task_id == task.id)
            .order_by(DiagnosisTaskImage.id.asc())
            .all()
        )
        image_ids = [row[0] for row in image_links]

        graph = build_farm_graph(session)
        final_state = graph.invoke(
            {
                "intent": "diagnosis",
                "thread_id": task.thread_id,
                "task_id": task.id,
                "plot_id": task.plot_id,
                "source": task.source,
                "growth_stage": task.growth_stage,
                "image_ids": image_ids,
            }
        )

        if final_state.get("error"):
            task.status = "failed"
            task.failure_reason = str(final_state["error"])[:255]
            session.commit()
            return

        diagnosis = final_state.get("diagnosis", {})
        task.result_level = "low" if diagnosis.get("low_confidence") else "high"
        task.fused_confidence = diagnosis.get("confidence")
        task.status = "done"
        task.finished_at = now()
        session.commit()
        logger.info("诊断任务完成: id=%s level=%s disease=%s", task.id, task.result_level, diagnosis.get("disease_name"))
    except Exception as exc:  # noqa: BLE001 全部异常落库为 failed
        session.rollback()
        logger.exception("诊断任务执行失败: id=%s err=%s", task_id, exc)
        try:
            task = session.query(DiagnosisTask).filter(DiagnosisTask.id == task_id).first()
            if task is not None:
                task.status = "failed"
                task.failure_reason = str(exc)[:255]
                task.finished_at = now()
                session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("诊断任务失败状态落库失败: id=%s", task_id)
    finally:
        session.close()


def reset_failed_task(db: Session, task_id: int) -> DiagnosisTask:
    """重置失败任务为 pending（执行由 API 层 BackgroundTasks 触发）。

    Args:
        db: 数据库会话。
        task_id: 任务ID。

    Returns:
        DiagnosisTask: 重置后的任务实例。

    Raises:
        BusinessException: 404 任务不存在；400 仅失败任务可重试。
    """
    task = db.query(DiagnosisTask).filter(DiagnosisTask.id == task_id).first()
    if task is None:
        raise BusinessException(404, "诊断任务不存在")
    if task.status != "failed":
        raise BusinessException(400, "仅失败任务可重试")
    task.status = "pending"
    task.failure_reason = None
    task.finished_at = None
    db.commit()
    return task


def get_task_detail(db: Session, task_id: int) -> dict[str, Any]:
    """组装诊断任务详情（含 images/results/plan/case）。

    Args:
        db: 数据库会话。
        task_id: 任务ID。

    Returns:
        dict: 任务详情结构。

    Raises:
        BusinessException: 404 任务不存在。
    """
    task = db.query(DiagnosisTask).filter(DiagnosisTask.id == task_id).first()
    if task is None:
        raise BusinessException(404, "诊断任务不存在")
    plot = db.query(Plot).filter(Plot.id == task.plot_id).first()

    images = (
        db.query(DiagnosisTaskImage, CollectedImage)
        .join(CollectedImage, DiagnosisTaskImage.image_id == CollectedImage.id)
        .filter(DiagnosisTaskImage.task_id == task.id)
        .order_by(DiagnosisTaskImage.id.asc())
        .all()
    )
    results = (
        db.query(DiagnosisResult)
        .filter(DiagnosisResult.task_id == task.id)
        .order_by(DiagnosisResult.id.asc())
        .all()
    )
    plan = db.query(PreventionPlan).filter(PreventionPlan.task_id == task.id).first()
    case = db.query(CaseLibrary).filter(CaseLibrary.task_id == task.id).first()

    restrictions = []
    if plan is not None:
        rows = db.query(HarvestRestriction).filter(HarvestRestriction.plan_id == plan.id).all()
        restrictions = [
            {"id": r.id, "pesticide_id": r.pesticide_id, "applied_at": fmt_datetime(r.applied_at) if r.applied_at else None,
             "ban_until": r.ban_until.isoformat() if r.ban_until else None, "status": r.status}
            for r in rows
        ]

    return {
        "id": task.id,
        "thread_id": task.thread_id,
        "plot_id": task.plot_id,
        "plot_name": plot.name if plot else None,
        "source": task.source,
        "growth_stage": task.growth_stage,
        "status": task.status,
        "result_level": task.result_level,
        "fused_confidence": float(task.fused_confidence) if task.fused_confidence is not None else None,
        "failure_reason": task.failure_reason,
        "created_at": fmt_datetime(task.created_at),
        "finished_at": fmt_datetime(task.finished_at),
        "images": [
            {"id": image.id, "url": image.cos_url, "source": image.source, "captured_at": fmt_datetime(image.captured_at)}
            for _link, image in images
        ],
        "results": [
            {
                "model_path": result.model_path,
                "model_name": result.model_name,
                "disease_name": result.disease_name,
                "disease_category": result.disease_category,
                "confidence": float(result.confidence),
                "raw_output": result.raw_output,
            }
            for result in results
        ],
        "plan": (
            {
                "id": plan.id,
                "scheme_json": plan.scheme_json,
                "compliance_result": plan.compliance_result,
                "is_forbidden_blocked": plan.is_forbidden_blocked,
                "disclaimer": plan.disclaimer,
                "harvest_restrictions": restrictions,
            }
            if plan is not None
            else None
        ),
        "case": (
            {
                "id": case.id,
                "status": case.status,
                "ai_disease_name": case.ai_disease_name,
                "final_disease_name": case.final_disease_name,
            }
            if case is not None
            else None
        ),
    }


def list_records(db: Session, plot_id: Optional[int], source: Optional[str],
                 start: Optional[str], end: Optional[str], level: Optional[str],
                 page_no: int, page_size: int) -> dict[str, Any]:
    """诊断记录分页列表（联表：地块/融合结果/案例/首图）。

    Args:
        db: 数据库会话。
        plot_id: 地块过滤。
        source: 来源过滤 device/manual。
        start: 开始日期 YYYY-MM-DD（含）。
        end: 结束日期（含）。
        level: 结果级别过滤 high/low。
        page_no: 页码。
        page_size: 每页条数。

    Returns:
        dict: {items, total, page, page_size}；items 元素含
              thumb_url/disease_name/case_status_display 等。
    """
    from datetime import date as date_type

    query = db.query(DiagnosisTask)
    if plot_id is not None:
        query = query.filter(DiagnosisTask.plot_id == plot_id)
    if source is not None:
        query = query.filter(DiagnosisTask.source == source)
    if level is not None:
        query = query.filter(DiagnosisTask.result_level == level)
    if start:
        query = query.filter(DiagnosisTask.created_at >= date_type.fromisoformat(start))
    if end:
        from datetime import timedelta

        query = query.filter(DiagnosisTask.created_at < date_type.fromisoformat(end) + timedelta(days=1))
    total = query.count()
    tasks = (
        query.order_by(DiagnosisTask.id.desc())
        .offset((page_no - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for task in tasks:
        plot = db.query(Plot).filter(Plot.id == task.plot_id).first()
        fused = (
            db.query(DiagnosisResult)
            .filter(DiagnosisResult.task_id == task.id, DiagnosisResult.model_path == "fused")
            .order_by(DiagnosisResult.id.desc())
            .first()
        )
        case = db.query(CaseLibrary).filter(CaseLibrary.task_id == task.id).first()
        first_image = (
            db.query(CollectedImage)
            .join(DiagnosisTaskImage, DiagnosisTaskImage.image_id == CollectedImage.id)
            .filter(DiagnosisTaskImage.task_id == task.id)
            .order_by(DiagnosisTaskImage.id.asc())
            .first()
        )
        case_display = None
        if case is not None:
            case_display = {"pending": "待确认", "confirmed": "已确认", "corrected": "已纠正"}.get(case.status, case.status)
        items.append(
            {
                "id": task.id,
                "plot_id": task.plot_id,
                "plot_name": plot.name if plot else None,
                "source": task.source,
                "growth_stage": task.growth_stage,
                "status": task.status,
                "result_level": task.result_level,
                "disease_name": fused.disease_name if fused else None,
                "confidence": float(fused.confidence) if fused and fused.confidence is not None else None,
                "case_status": case.status if case else None,
                "case_status_display": case_display or ("已完成" if task.status == "done" else None),
                "thumb_url": first_image.cos_url if first_image else None,
                "created_at": fmt_datetime(task.created_at),
            }
        )
    return {"items": items, "total": total, "page": page_no, "page_size": page_size}
