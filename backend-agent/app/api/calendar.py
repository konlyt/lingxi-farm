"""农事日历接口路由。

提供按地块/月份的农事节点日历数据与 upcoming 30 天提醒列表。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.core.security import require_owner
from app.services import calendar_service

router = APIRouter(prefix="/api/calendar", tags=["农事日历"], dependencies=[Depends(require_owner)])


@router.get("", summary="农事日历事件")
def get_calendar(
    plot_id: Optional[int] = Query(None, gt=0, description="地块ID（空为全部）"),
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$", description="月份过滤 YYYY-MM"),
    db: Session = Depends(get_db),
) -> dict:
    """查询农事日历事件（基于定植日期 + 作物规则表推算）。

    Args:
        plot_id: 地块ID。
        month: 月份过滤。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 events 数组。
    """
    events = calendar_service.get_calendar(db, plot_id, month)
    return ok({"events": events})


@router.get("/reminders", summary="upcoming 农事提醒（未来 30 天）")
def get_reminders(
    plot_id: Optional[int] = Query(None, gt=0, description="地块ID（空为全部）"),
    days: int = Query(30, ge=1, le=365, description="展望天数"),
    db: Session = Depends(get_db),
) -> dict:
    """查询未来 N 天内农事提醒。

    Args:
        plot_id: 地块ID。
        days: 展望天数。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为提醒数组（含 days_until）。
    """
    reminders = calendar_service.get_upcoming_reminders(db, plot_id, days)
    return ok({"reminders": reminders})
