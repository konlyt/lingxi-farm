"""农情预警接口路由。

提供预警分页列表（状态 Tab/类型筛选）、详情（含病情时间线）与解决关闭接口。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok, page
from app.core.security import require_owner
from app.models.alert import Alert
from app.models.plot import Plot
from app.utils.time_utils import fmt_datetime, now

router = APIRouter(prefix="/api/alerts", tags=["农情预警"], dependencies=[Depends(require_owner)])


@router.get("", summary="预警分页列表")
def list_alerts(
    status: Optional[str] = Query(None, pattern="^(active|resolved)$", description="状态过滤"),
    type: Optional[str] = Query(None, pattern="^(pest|env|weather|device_offline)$", description="类型过滤"),
    page_no: int = Query(1, alias="page", ge=1, description="页码"),
    page_size: int = Query(20, alias="page_size", ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
) -> dict:
    """分页查询预警列表（items 含 plot_name、is_upgraded）。

    Args:
        status: 状态过滤 active/resolved。
        type: 类型过滤 pest/env/weather/device_offline。
        page_no: 页码。
        page_size: 每页条数。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {items, total, page, page_size}。
    """
    query = db.query(Alert)
    if status is not None:
        query = query.filter(Alert.status == status)
    if type is not None:
        query = query.filter(Alert.type == type)
    total = query.count()
    rows = (
        query.order_by(Alert.first_triggered_at.desc())
        .offset((page_no - 1) * page_size)
        .limit(page_size)
        .all()
    )
    plot_names = {plot.id: plot.name for plot in db.query(Plot).all()}
    items = [
        {
            "id": alert.id,
            "type": alert.type,
            "level": alert.level,
            "plot_id": alert.plot_id,
            "plot_name": plot_names.get(alert.plot_id),
            "title": alert.title,
            "status": alert.status,
            "occurrence_count": alert.occurrence_count,
            "is_upgraded": alert.occurrence_count > 1,
            "first_triggered_at": fmt_datetime(alert.first_triggered_at),
            "resolved_at": fmt_datetime(alert.resolved_at),
        }
        for alert in rows
    ]
    return ok(page(items, total, page_no, page_size))


@router.get("/{alert_id}", summary="预警详情（含病情时间线）")
def get_alert(alert_id: int, db: Session = Depends(get_db)) -> dict:
    """查询预警详情，timeline 取自 content.updates 时间线数组。

    Args:
        alert_id: 预警ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为详情（含 timeline）。

    Raises:
        BusinessException: 404 预警不存在。
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert is None:
        raise BusinessException(404, "预警不存在")
    plot = db.query(Plot).filter(Plot.id == alert.plot_id).first()
    content = alert.content or {}
    return ok(
        {
            "id": alert.id,
            "type": alert.type,
            "level": alert.level,
            "plot_id": alert.plot_id,
            "plot_name": plot.name if plot else None,
            "case_key": alert.case_key,
            "title": alert.title,
            "status": alert.status,
            "occurrence_count": alert.occurrence_count,
            # 关联诊断任务ID（病虫害预警可跳转诊断详情，无关联时为 null）
            "related_task_id": alert.task_id,
            "content": {k: v for k, v in content.items() if k != "updates"},
            "timeline": content.get("updates", []),
            "first_triggered_at": fmt_datetime(alert.first_triggered_at),
            "resolved_at": fmt_datetime(alert.resolved_at),
        }
    )


@router.post("/{alert_id}/resolve", summary="确认解决预警（关闭聚合窗口）")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)) -> dict:
    """解决预警：active→resolved，同 case_key 聚合窗口关闭（再次触发将新建）。

    Args:
        alert_id: 预警ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, status, resolved_at}。

    Raises:
        BusinessException: 404 预警不存在；400 已解决预警不可重复解决。
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert is None:
        raise BusinessException(404, "预警不存在")
    if alert.status != "active":
        raise BusinessException(400, "该预警已解决，不可重复操作")
    alert.status = "resolved"
    alert.resolved_at = now()
    content = dict(alert.content or {})
    updates = content.get("updates", [])
    updates.append(
        {
            "time": now().isoformat(),
            "event": "人工确认解决",
            "content": {},
        }
    )
    content["updates"] = updates
    alert.content = content
    db.commit()
    return ok({"id": alert.id, "status": alert.status, "resolved_at": fmt_datetime(alert.resolved_at)})
