"""传感器时序数据表（sensor_reading）ORM 模型。

注意：本表按月分区（PARTITION BY RANGE (TO_DAYS(reported_at))），
MySQL 分区表不支持物理外键，故 device_id/plot_id 仅作逻辑关联，
分区由 scripts/init_db.py 以原生 ALTER TABLE 执行（失败降级普通表）。
"""
from datetime import datetime

from sqlalchemy import DECIMAL, Index, String
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class SensorReading(Base):
    """传感器时序数据表 ORM 模型（sensor_reading）。

    环境传感器每 15 分钟上报温湿度/光照/墒情数据；
    主键为联合主键 (id, reported_at) 以满足分区键约束。

    Attributes:
        id: 自增ID（联合主键之一）。
        device_id: 上报设备ID（逻辑外键 device.id）。
        plot_id: 冗余归属地块ID（逻辑外键 plot.id，避免联查）。
        metric: 指标 temp/humidity/light/soil_moisture。
        value: 数值。
        unit: 单位（℃/%R H/% 等）。
        reported_at: 上报时间（分区键，≥15 分钟间隔）。
    """
    __tablename__ = "sensor_reading"
    __table_args__ = (
        Index("idx_plot_metric_time", "plot_id", "metric", "reported_at"),
        Index("idx_device_time", "device_id", "reported_at"),
        {"comment": "传感器时序数据表（按月分区）"},
    )

    # 联合主键第一列必须为自增列（MySQL 分区约束）
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="自增ID")
    device_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False, comment="上报设备ID（逻辑FK）")
    plot_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False, comment="归属地块ID（逻辑FK）")
    metric: Mapped[str] = mapped_column(String(32), nullable=False, comment="temp/humidity/light/soil_moisture")
    value: Mapped[float] = mapped_column(DECIMAL(10, 3), nullable=False, comment="数值")
    unit: Mapped[str] = mapped_column(String(16), nullable=False, comment="单位")
    reported_at: Mapped[datetime] = mapped_column(DT3, primary_key=True, nullable=False, comment="上报时间（分区键）")
