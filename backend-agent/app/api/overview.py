"""农场总览接口路由。

提供首屏一次性聚合数据：采收禁令横幅、地块实况卡片、
今日待办、最新未解决预警与今日天气。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.core.security import require_owner
from app.services.overview_service import get_overview

router = APIRouter(prefix="/api/overview", tags=["农场总览"], dependencies=[Depends(require_owner)])


@router.get("", summary="农场总览聚合数据")
def overview(db: Session = Depends(get_db)) -> dict:
    """返回总览首屏聚合数据（GET，member 亦可查看）。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {harvest_banners, plot_cards, today_todos,
              latest_alerts, weather}。
    """
    return ok(get_overview(db))
