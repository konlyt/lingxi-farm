"""决策建议与配置缓存相关表 ORM 模型。

包含：每日农情简报表（daily_brief）、水肥建议表（water_fertilizer_advice）、
报警阈值配置表（environment_threshold_config）、
置信度阈值配置表（confidence_threshold_config）、
外部数据缓存表（weather_forecast_cache）。
"""
from datetime import date, datetime
from typing import Any

from sqlalchemy import DECIMAL, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, DATE, DATETIME, JSON, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class DailyBrief(Base):
    """每日农情简报表 ORM 模型（daily_brief）。

    每日 07:00 生成一次，brief_date 唯一。

    Attributes:
        id: 简报ID。
        brief_date: 简报日期（唯一）。
        content: 各地块实况摘要 + 今日待办 + 天气提醒 JSON。
        push_status: 推送状态 sent/failed。
        pushed_at: 推送时间（可空）。
        created_at: 创建时间。
    """
    __tablename__ = "daily_brief"
    __table_args__ = (
        Index("uk_brief_date", "brief_date", unique=True),
        {"comment": "每日农情简报表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="简报ID")
    brief_date: Mapped[date] = mapped_column(DATE, nullable=False, comment="简报日期")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="简报内容JSON")
    push_status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent", comment="sent/failed")
    pushed_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True, comment="推送时间")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class WaterFertilizerAdvice(Base):
    """水肥建议表 ORM 模型（water_fertilizer_advice）。

    每日 06:00 生成未来 7 天建议卡，每日每地块一条（uk_plot_date 唯一）。

    Attributes:
        id: 建议ID。
        plot_id: 地块ID。
        advice_date: 生成日期。
        horizon_days: 展望天数（默认 7）。
        advice_json: 建议卡 JSON（浇水/施肥计划）。
        basis_json: 依据 JSON（气象/墒情/生育期/Ndvi，含不确定性说明）。
        data_fallback_flag: 是否使用降级历史数据 0/1（降级须标注时间）。
        push_status: 推送状态 sent/failed。
        created_at: 创建时间。
    """
    __tablename__ = "water_fertilizer_advice"
    __table_args__ = (
        Index("uk_plot_date", "plot_id", "advice_date", unique=True),
        {"comment": "水肥建议表：每日每地块一条"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="建议ID")
    plot_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=False, comment="地块ID"
    )
    advice_date: Mapped[date] = mapped_column(DATE, nullable=False, comment="生成日期")
    horizon_days: Mapped[int] = mapped_column(TINYINT, nullable=False, default=7, comment="展望天数")
    advice_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="建议卡JSON")
    basis_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="依据JSON")
    data_fallback_flag: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0, comment="降级数据标记 0/1")
    push_status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent", comment="sent/failed")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class EnvironmentThresholdConfig(Base):
    """报警阈值配置表 ORM 模型（environment_threshold_config）。

    默认模板（plot_id 为 NULL，is_default_template=1）+ 地块级覆盖统一建模；
    模板唯一性（同 crop_name/growth_stage/metric 仅一条模板）由应用层保证，
    故该列组合仅建普通索引以兼容地块级覆盖行。

    Attributes:
        id: 配置ID。
        plot_id: 地块ID（NULL 表示默认模板）。
        crop_name: 作物名称。
        growth_stage: 生育期。
        metric: 指标 temp/humidity/soil_moisture。
        max_value: 越限上限（可空）。
        min_value: 越限下限（可空）。
        is_default_template: 是否默认值模板 0/1。
        enabled: 是否启用 0/1。
        created_at: 创建时间。
        updated_at: 更新时间。
    """
    __tablename__ = "environment_threshold_config"
    __table_args__ = (
        Index(
            "idx_lookup",
            "plot_id",
            "crop_name",
            "growth_stage",
            "metric",
            "enabled",
        ),
        # 模板唯一由应用层保证；此处为组合查询普通索引（避免阻碍地块级覆盖）
        UniqueConstraint(
            "crop_name", "growth_stage", "metric", "plot_id",
            name="uk_template_with_plot",
        ),
        {"comment": "报警阈值配置表：默认模板 + 地块级覆盖"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="配置ID")
    plot_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=True, comment="地块ID（NULL为默认模板）"
    )
    crop_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="作物名称")
    growth_stage: Mapped[str] = mapped_column(String(32), nullable=False, comment="生育期")
    metric: Mapped[str] = mapped_column(String(32), nullable=False, comment="temp/humidity/soil_moisture")
    max_value: Mapped[float | None] = mapped_column(DECIMAL(10, 3), nullable=True, comment="越限上限")
    min_value: Mapped[float | None] = mapped_column(DECIMAL(10, 3), nullable=True, comment="越限下限")
    is_default_template: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0, comment="是否默认模板 0/1")
    enabled: Mapped[int] = mapped_column(TINYINT, nullable=False, default=1, comment="是否启用 0/1")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DT3, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


class ConfidenceThresholdConfig(Base):
    """置信度阈值分病种配置表 ORM 模型（confidence_threshold_config）。

    按病种分类配置诊断置信度阈值（如常见病 0.85 / 默认 0.90 / 罕见病 0.95）。

    Attributes:
        id: 配置ID。
        disease_category: 病种分类（唯一）。
        threshold: 阈值（0–1，四位小数存储）。
        sample_count_baseline: 参考样本量（可空，动态调整依据）。
        enabled: 是否启用 0/1。
        updated_at: 更新时间。
    """
    __tablename__ = "confidence_threshold_config"
    __table_args__ = (
        Index("uk_category", "disease_category", unique=True),
        {"comment": "置信度阈值分病种配置表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="配置ID")
    disease_category: Mapped[str] = mapped_column(String(32), nullable=False, comment="病种分类")
    threshold: Mapped[float] = mapped_column(DECIMAL(5, 4), nullable=False, comment="置信度阈值")
    sample_count_baseline: Mapped[int | None] = mapped_column(nullable=True, comment="参考样本量")
    enabled: Mapped[int] = mapped_column(TINYINT, nullable=False, default=1, comment="是否启用 0/1")
    updated_at: Mapped[datetime] = mapped_column(
        DT3, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


class WeatherForecastCache(Base):
    """外部数据缓存表 ORM 模型（weather_forecast_cache）。

    缓存气象预报 / NDVI 等外部数据，按 (地块, 数据类型, 预报日期) 唯一。

    Attributes:
        id: 缓存ID。
        plot_id: 地块ID。
        data_type: 数据类型 weather_forecast/ndvi。
        forecast_date: 预报目标日（ndvi 类可空）。
        data_json: 数据体 JSON。
        source_api: 数据源标识。
        fetched_at: 拉取时间（缺失降级标注依据）。
    """
    __tablename__ = "weather_forecast_cache"
    __table_args__ = (
        Index("uk_plot_type_date", "plot_id", "data_type", "forecast_date", unique=True),
        {"comment": "外部数据缓存表：气象预报/NDVI"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="缓存ID")
    plot_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=False, comment="地块ID"
    )
    data_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="weather_forecast/ndvi")
    forecast_date: Mapped[date | None] = mapped_column(DATE, nullable=True, comment="预报目标日")
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="数据体JSON")
    source_api: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据源标识")
    fetched_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="拉取时间")
