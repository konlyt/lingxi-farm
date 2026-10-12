"""决策建议接口路由。

提供水肥建议查询/手动生成、大棚环境调控建议与每日农情简报查询。
生成类接口仅 owner 可用。
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.core.security import require_owner
from app.models.plot import Plot
from app.services import advisory_service

router = APIRouter(prefix="/api/advice", tags=["决策建议"], dependencies=[Depends(require_owner)])


class WaterFertilizerGenerateRequest(BaseModel):
    """水肥建议手动生成请求体。

    Attributes:
        plot_id: 地块ID（空则生成全部在种地块）。
    """

    plot_id: int | None = Field(None, gt=0, description="地块ID（空为全部地块）")


@router.get("/water-fertilizer", summary="水肥建议查询（当日 uk_plot_date 记录）")
def get_water_fertilizer_advice(plot_id: int = Query(..., gt=0, description="地块ID"),
                                date: str | None = Query(None, description="查询日期 YYYY-MM-DD"),
                                db: Session = Depends(get_db)) -> dict:
    """查询地块某日水肥建议（含未来 7 天逐日建议与依据）。

    Args:
        plot_id: 地块ID。
        date: 查询日期（空则当天）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 含 items/basis_json/data_fallback_flag。
    """
    return ok(advisory_service.get_water_fertilizer(db, plot_id, date))


@router.post("/water-fertilizer/generate", summary="手动触发生成水肥建议（owner）")
def generate_water_fertilizer_advice(body: WaterFertilizerGenerateRequest,
                                     db: Session = Depends(get_db)) -> dict:
    """调用种植决策智能体生成当日水肥建议（单地块或全部在种地块）。

    Args:
        body: 生成请求体（plot_id 空则全部地块）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {generated:[...], failed:[...]}。

    Raises:
        BusinessException: 502 智能体生成失败（单地块模式直接抛出）。
    """
    if body.plot_id is not None:
        return ok(advisory_service.generate_water_fertilizer(db, body.plot_id))
    plots = db.query(Plot).filter(Plot.status == 1).all()
    generated, failed = [], []
    for plot in plots:
        try:
            generated.append(advisory_service.generate_water_fertilizer(db, plot.id))
        except Exception:  # noqa: BLE001 单地块失败不阻塞其余
            failed.append({"plot_id": plot.id, "plot_name": plot.name})
    return ok({"generated": generated, "failed": failed})


@router.get("/environment", summary="大棚未来 12 小时环境调控建议")
def get_environment_advice(plot_id: int = Query(..., gt=0, description="地块ID"),
                           db: Session = Depends(get_db)) -> dict:
    """查询大棚通风/保温/降湿调控建议（露天地块返回空 items）。

    Args:
        plot_id: 地块ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {items:[{time_range, action, reason}]}。
    """
    return ok(advisory_service.get_environment_advice(db, plot_id))


@router.get("/daily-brief", summary="每日农情简报查询")
def get_daily_brief(date: str | None = Query(None, description="查询日期 YYYY-MM-DD"),
                    db: Session = Depends(get_db)) -> dict:
    """查询每日农情简报（07:00 定时生成，亦可手动触发）。

    Args:
        date: 查询日期（空则当天）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 含 content/push_status。
    """
    return ok(advisory_service.get_daily_brief(db, date))


@router.post("/daily-brief/generate", summary="手动触发每日简报生成（owner）")
def generate_daily_brief(db: Session = Depends(get_db)) -> dict:
    """手动触发生成今日农情简报（幂等，重复生成覆盖更新）。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为简报内容。
    """
    brief = advisory_service.generate_daily_brief(db)
    return ok({"date": brief.brief_date.isoformat(), "content": brief.content, "push_status": brief.push_status})
