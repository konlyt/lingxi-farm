"""地块/棚室档案接口路由。

提供列表（含状态筛选/分页）、详情（含最新环境值与采收禁令角标）、
新增、编辑与状态切换五个接口；写接口仅 owner 可用。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok, page
from app.core.security import require_owner
from app.models.plot import Plot
from app.schemas.plot import PlotCreateRequest, PlotStatusPatchRequest, PlotUpdateRequest
from app.services.plot_service import get_active_restrictions, get_latest_env, has_active_restriction
from app.utils.time_utils import fmt_date

router = APIRouter(prefix="/api/plots", tags=["地块/棚室"], dependencies=[Depends(require_owner)])


@router.get("", summary="地块列表（支持状态筛选与分页）")
def list_plots(
    status: Optional[int] = Query(None, ge=0, le=1, description="状态筛选 1在种/0停用"),
    page_no: int = Query(1, alias="page", ge=1, description="页码"),
    page_size: int = Query(20, alias="page_size", ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db),
) -> dict:
    """分页查询地块/棚室档案列表。

    Args:
        status: 可选状态过滤（1 在种 / 0 停用）。
        page_no: 页码，从 1 开始。
        page_size: 每页条数。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {items, total, page, page_size}。
    """
    query = db.query(Plot)
    if status is not None:
        query = query.filter(Plot.status == status)
    total = query.count()
    rows = (
        query.order_by(Plot.id.asc())
        .offset((page_no - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id": plot.id,
            "name": plot.name,
            "type": plot.type,
            "lng": float(plot.lng) if plot.lng is not None else None,
            "lat": float(plot.lat) if plot.lat is not None else None,
            "area_mu": float(plot.area_mu) if plot.area_mu is not None else None,
            "soil_type": plot.soil_type,
            "crop_name": plot.crop_name,
            "crop_variety": plot.crop_variety,
            "growth_stage": plot.growth_stage,
            "planted_at": fmt_date(plot.planted_at),
            "remark": plot.remark,
            "status": plot.status,
            "has_active_restriction": has_active_restriction(db, plot.id),
        }
        for plot in rows
    ]
    return ok(page(items, total, page_no, page_size))


@router.post("", summary="新增地块/棚室")
def create_plot(body: PlotCreateRequest, db: Session = Depends(get_db)) -> dict:
    """新增地块/棚室档案，名称全局唯一。

    Args:
        body: 地块创建请求体。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为新建档案 {id, name}。

    Raises:
        BusinessException: 400 名称重复；露天地块缺经纬度由 Pydantic 校验拦截（422）。
    """
    exists = db.query(Plot.id).filter(Plot.name == body.name).first()
    if exists is not None:
        raise BusinessException(400, f"地块名称「{body.name}」已存在，请更换名称")
    plot = Plot(
        name=body.name,
        type=body.type,
        lng=body.lng,
        lat=body.lat,
        area_mu=body.area_mu,
        soil_type=body.soil_type,
        crop_name=body.crop_name,
        crop_variety=body.crop_variety,
        growth_stage=body.growth_stage,
        planted_at=body.planted_at,
        remark=body.remark,
        status=1,
    )
    db.add(plot)
    db.commit()
    return ok({"id": plot.id, "name": plot.name})


@router.get("/{plot_id}", summary="地块详情（含最新环境值与采收禁令角标）")
def get_plot(plot_id: int, db: Session = Depends(get_db)) -> dict:
    """查询单个地块详情，附带最新环境值与 active 采收禁令数组。

    Args:
        plot_id: 地块ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为详情（含 latest_env 与 harvest_restrictions）。

    Raises:
        BusinessException: 404 地块不存在。
    """
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    return ok(
        {
            "id": plot.id,
            "name": plot.name,
            "type": plot.type,
            "lng": float(plot.lng) if plot.lng is not None else None,
            "lat": float(plot.lat) if plot.lat is not None else None,
            "area_mu": float(plot.area_mu) if plot.area_mu is not None else None,
            "soil_type": plot.soil_type,
            "crop_name": plot.crop_name,
            "crop_variety": plot.crop_variety,
            "growth_stage": plot.growth_stage,
            "planted_at": fmt_date(plot.planted_at),
            "remark": plot.remark,
            "status": plot.status,
            "latest_env": get_latest_env(db, plot.id),
            "harvest_restrictions": get_active_restrictions(db, plot.id),
        }
    )


@router.put("/{plot_id}", summary="编辑地块/棚室")
def update_plot(plot_id: int, body: PlotUpdateRequest, db: Session = Depends(get_db)) -> dict:
    """编辑地块/棚室档案（仅更新传入字段）。

    Args:
        plot_id: 地块ID。
        body: 编辑请求体（字段可选）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为更新后的基本信息。

    Raises:
        BusinessException: 404 地块不存在；400 名称与其他地块重复。
    """
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] != plot.name:
        exists = db.query(Plot.id).filter(Plot.name == updates["name"], Plot.id != plot_id).first()
        if exists is not None:
            raise BusinessException(400, f"地块名称「{updates['name']}」已存在，请更换名称")
    for field, value in updates.items():
        setattr(plot, field, value)
    db.commit()
    return ok({"id": plot.id, "name": plot.name, "status": plot.status})


@router.patch("/{plot_id}/status", summary="切换地块状态（停用/在种）")
def patch_plot_status(plot_id: int, body: PlotStatusPatchRequest, db: Session = Depends(get_db)) -> dict:
    """切换地块在种/停用状态。

    Args:
        plot_id: 地块ID。
        body: 状态切换请求体 {status}。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, status}。

    Raises:
        BusinessException: 404 地块不存在。
    """
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    plot.status = body.status
    db.commit()
    return ok({"id": plot.id, "status": plot.status})
