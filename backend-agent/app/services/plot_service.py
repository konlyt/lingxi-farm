"""地块业务服务模块。

提供地块最新环境值查询、active 采收禁令角标查询等复用逻辑。
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.advice import EnvironmentThresholdConfig
from app.models.knowledge import HarvestRestriction as HarvestRestrictionModel
from app.models.knowledge import Pesticide
from app.models.plot import Plot
from app.models.sensor import SensorReading
from app.utils.time_utils import fmt_date

# 环境指标展示顺序与单位
ENV_METRICS = [
    ("temp", "℃"),
    ("humidity", "%RH"),
    ("soil_moisture", "%"),
]


def get_latest_env(db: Session, plot_id: int) -> dict[str, float | None]:
    """查询指定地块三个环境指标的最新值。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。

    Returns:
        dict: {temp, humidity, soil_moisture}，无数据项为 None。
    """
    result: dict[str, float | None] = {metric: None for metric, _unit in ENV_METRICS}
    for metric, _unit in ENV_METRICS:
        reading = (
            db.query(SensorReading)
            .filter(SensorReading.plot_id == plot_id, SensorReading.metric == metric)
            .order_by(SensorReading.reported_at.desc())
            .first()
        )
        if reading is not None:
            result[metric] = float(reading.value)
    return result


def get_active_restrictions(db: Session, plot_id: int) -> list[dict[str, Any]]:
    """查询指定地块 active 状态的采收禁令角标数组。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。

    Returns:
        list[dict]: [{id, pesticide_name, applied_at, ban_until}]，按截止日升序。
    """
    rows = (
        db.query(HarvestRestrictionModel, Pesticide.name)
        .join(Pesticide, HarvestRestrictionModel.pesticide_id == Pesticide.id)
        .filter(HarvestRestrictionModel.plot_id == plot_id, HarvestRestrictionModel.status == "active")
        .order_by(HarvestRestrictionModel.ban_until.asc())
        .all()
    )
    return [
        {
            "id": restriction.id,
            "pesticide_name": pesticide_name,
            "applied_at": fmt_date(restriction.applied_at),
            "ban_until": fmt_date(restriction.ban_until),
        }
        for restriction, pesticide_name in rows
    ]


def has_active_restriction(db: Session, plot_id: int) -> bool:
    """判断地块是否存在 active 采收禁令。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。

    Returns:
        bool: 存在返回 True。
    """
    return (
        db.query(HarvestRestrictionModel.id)
        .filter(HarvestRestrictionModel.plot_id == plot_id, HarvestRestrictionModel.status == "active")
        .first()
        is not None
    )


def get_effective_thresholds(db: Session, plot: Plot) -> list[EnvironmentThresholdConfig]:
    """获取地块生效阈值配置（地块级覆盖优先，回退默认模板）。

    Args:
        db: 数据库会话。
        plot: 地块 ORM 实例。

    Returns:
        list[EnvironmentThresholdConfig]: 生效的阈值配置列表。
    """
    # 1) 地块级覆盖
    plot_level = (
        db.query(EnvironmentThresholdConfig)
        .filter(
            EnvironmentThresholdConfig.plot_id == plot.id,
            EnvironmentThresholdConfig.enabled == 1,
        )
        .all()
    )
    covered_metrics = {config.metric for config in plot_level}
    # 2) 默认模板补齐未覆盖指标
    templates = (
        db.query(EnvironmentThresholdConfig)
        .filter(
            EnvironmentThresholdConfig.plot_id.is_(None),
            EnvironmentThresholdConfig.crop_name == plot.crop_name,
            EnvironmentThresholdConfig.growth_stage == plot.growth_stage,
            EnvironmentThresholdConfig.is_default_template == 1,
            EnvironmentThresholdConfig.enabled == 1,
        )
        .all()
    )
    merged = list(plot_level)
    for template in templates:
        if template.metric not in covered_metrics:
            merged.append(template)
    return merged
