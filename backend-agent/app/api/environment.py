"""大棚环境监控接口路由。

提供实时环境值（含越限判定）、趋势数据、越限告警记录与报警阈值 CRUD。
写接口（阈值增删改）仅 owner 可用。
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok
from app.core.security import require_owner
from app.models.advice import EnvironmentThresholdConfig
from app.models.plot import Plot
from app.services.environment_service import get_alarm_records, get_realtime, get_trend
from app.utils.time_utils import now

router = APIRouter(prefix="/api/environment", tags=["环境监控"], dependencies=[Depends(require_owner)])


class ThresholdUpsertRequest(BaseModel):
    """阈值创建/更新请求体。

    Attributes:
        plot_id: 地块ID（NULL 表示默认模板）。
        crop_name: 作物名称。
        growth_stage: 生育期。
        metric: 指标 temp/humidity/soil_moisture。
        max_value: 越限上限（与下限至少填一个）。
        min_value: 越限下限。
        is_default_template: 是否默认模板（仅 plot_id 为空时允许 1）。
        enabled: 是否启用。
    """

    plot_id: int | None = Field(None, gt=0, description="地块ID（空为模板）")
    crop_name: str = Field(..., min_length=1, max_length=64, description="作物名称")
    growth_stage: str = Field(..., min_length=1, max_length=32, description="生育期")
    metric: str = Field(..., pattern="^(temp|humidity|soil_moisture)$", description="指标")
    max_value: float | None = Field(None, description="越限上限")
    min_value: float | None = Field(None, description="越限下限")
    is_default_template: int = Field(0, ge=0, le=1, description="是否默认模板")
    enabled: int = Field(1, ge=0, le=1, description="是否启用")

    def validate_bounds(self) -> None:
        """校验上下限取值合法。

        Raises:
            ValueError: 上下限同时缺失、下限≥上限或模板/地块标记矛盾时抛出。
        """
        if self.max_value is None and self.min_value is None:
            raise ValueError("上限与下限至少填写一项")
        if self.max_value is not None and self.min_value is not None and self.min_value >= self.max_value:
            raise ValueError("下限必须小于上限")
        if self.is_default_template == 1 and self.plot_id is not None:
            raise ValueError("默认模板不能绑定具体地块")


def _serialize_threshold(config: EnvironmentThresholdConfig) -> dict[str, Any]:
    """序列化阈值配置行。

    Args:
        config: 阈值 ORM 实例。

    Returns:
        dict: 阈值 JSON 结构。
    """
    return {
        "id": config.id,
        "plot_id": config.plot_id,
        "crop_name": config.crop_name,
        "growth_stage": config.growth_stage,
        "metric": config.metric,
        "max_value": float(config.max_value) if config.max_value is not None else None,
        "min_value": float(config.min_value) if config.min_value is not None else None,
        "is_default_template": config.is_default_template,
        "enabled": bool(config.enabled),
    }


@router.get("/realtime", summary="地块实时环境值（含越限判定）")
def environment_realtime(plot_id: int = Query(..., gt=0, description="地块ID"),
                         db: Session = Depends(get_db)) -> dict:
    """查询地块各指标最新值、越限判定与最近上报时间。

    Args:
        plot_id: 地块ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {plot_id, plot_name, metrics}。

    Raises:
        BusinessException: 404 地块不存在。
    """
    return ok(get_realtime(db, plot_id))


@router.get("/trend", summary="环境趋势（24h/7d 聚合）")
def environment_trend(plot_id: int = Query(..., gt=0, description="地块ID"),
                      range: str = Query("24h", pattern="^(24h|7d)$", description="时间范围"),
                      db: Session = Depends(get_db)) -> dict:
    """查询环境趋势序列（逐小时/逐天均值，缺失补空）。

    Args:
        plot_id: 地块ID。
        range: 时间范围 24h/7d。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {range, times, series}。
    """
    return ok(get_trend(db, plot_id, range))


@router.get("/alarm-records", summary="环境越限告警记录")
def environment_alarm_records(plot_id: int = Query(..., gt=0, description="地块ID"),
                              db: Session = Depends(get_db)) -> dict:
    """查询地块 env 类型预警记录（含 metric/value/threshold/recovered_at）。

    Args:
        plot_id: 地块ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为告警记录数组。
    """
    return ok(get_alarm_records(db, plot_id))


@router.get("/thresholds", summary="阈值配置查询（模板 + 地块级）")
def list_thresholds(plot_id: Optional[int] = Query(None, gt=0, description="地块ID（空返回全部）"),
                    db: Session = Depends(get_db)) -> dict:
    """查询报警阈值配置：默认模板与地块级覆盖分返。

    Args:
        plot_id: 地块ID（空返回全部模板与全部地块配置）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {templates, plot_configs}。
    """
    template_query = db.query(EnvironmentThresholdConfig).filter(
        EnvironmentThresholdConfig.is_default_template == 1
    )
    plot_query = db.query(EnvironmentThresholdConfig).filter(
        EnvironmentThresholdConfig.plot_id.isnot(None)
    )
    if plot_id is not None:
        plot_query = plot_query.filter(EnvironmentThresholdConfig.plot_id == plot_id)
    return ok(
        {
            "templates": [_serialize_threshold(row) for row in template_query.order_by(EnvironmentThresholdConfig.id.asc()).all()],
            "plot_configs": [_serialize_threshold(row) for row in plot_query.order_by(EnvironmentThresholdConfig.id.asc()).all()],
        }
    )


@router.post("/thresholds", summary="新增阈值配置（owner）")
def create_threshold(body: ThresholdUpsertRequest, db: Session = Depends(get_db)) -> dict:
    """新增阈值配置（默认模板或地块级覆盖）。

    Args:
        body: 阈值请求体。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为新配置。

    Raises:
        BusinessException: 422 参数校验失败（min<max 等由 ValueError 转换）；
                           404 地块不存在。
    """
    try:
        body.validate_bounds()
    except ValueError as exc:
        raise BusinessException(400, str(exc))
    if body.plot_id is not None and db.query(Plot.id).filter(Plot.id == body.plot_id).first() is None:
        raise BusinessException(404, "地块不存在")
    config = EnvironmentThresholdConfig(
        plot_id=body.plot_id,
        crop_name=body.crop_name,
        growth_stage=body.growth_stage,
        metric=body.metric,
        max_value=body.max_value,
        min_value=body.min_value,
        is_default_template=body.is_default_template,
        enabled=body.enabled,
    )
    db.add(config)
    db.commit()
    return ok(_serialize_threshold(config))


@router.put("/thresholds/{config_id}", summary="修改阈值配置（owner）")
def update_threshold(config_id: int, body: ThresholdUpsertRequest, db: Session = Depends(get_db)) -> dict:
    """修改阈值配置（整条覆盖保存，重新校验上下限）。

    Args:
        config_id: 配置ID。
        body: 阈值请求体。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为更新后的配置。

    Raises:
        BusinessException: 404 配置不存在；400 上下限校验失败。
    """
    try:
        body.validate_bounds()
    except ValueError as exc:
        raise BusinessException(400, str(exc))
    config = db.query(EnvironmentThresholdConfig).filter(EnvironmentThresholdConfig.id == config_id).first()
    if config is None:
        raise BusinessException(404, "阈值配置不存在")
    config.plot_id = body.plot_id
    config.crop_name = body.crop_name
    config.growth_stage = body.growth_stage
    config.metric = body.metric
    config.max_value = body.max_value
    config.min_value = body.min_value
    config.is_default_template = body.is_default_template
    config.enabled = body.enabled
    config.updated_at = now()
    db.commit()
    return ok(_serialize_threshold(config))


@router.delete("/thresholds/{config_id}", summary="删除阈值配置（owner）")
def delete_threshold(config_id: int, db: Session = Depends(get_db)) -> dict:
    """删除阈值配置。

    Args:
        config_id: 配置ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, deleted}。

    Raises:
        BusinessException: 404 配置不存在。
    """
    config = db.query(EnvironmentThresholdConfig).filter(EnvironmentThresholdConfig.id == config_id).first()
    if config is None:
        raise BusinessException(404, "阈值配置不存在")
    db.delete(config)
    db.commit()
    return ok({"id": config_id, "deleted": True})
