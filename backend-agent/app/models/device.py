"""设备表（device）与设备心跳日志表（device_heartbeat_log）ORM 模型。"""
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.plot import Plot

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class Device(Base):
    """设备表 ORM 模型（device）。

    摄像头/虫情测报灯/孢子捕捉仪/环境传感器统一建模，
    protocol 字段路由至对应协议 Adapter（MQTT/RTSP/vendor_api）。

    Attributes:
        id: 设备ID。
        device_no: 设备编号（唯一）。
        name: 设备名称。
        type: 类型 camera/pest_light/spore_trap/env_sensor。
        plot_id: 安装地块ID。
        protocol: 接入协议 MQTT/RTSP/vendor_api。
        vendor: 厂商（可空）。
        collect_schedule: 采集计划 JSON（可空）。
        config: 远程配置 JSON（可空）。
        status: 在线状态 online/offline。
        last_heartbeat_at: 最近心跳时间。
        created_at: 创建时间。
        updated_at: 更新时间。
        plot: 关联地块 ORM 对象。
    """
    __tablename__ = "device"
    __table_args__ = (
        Index("uk_device_no", "device_no", unique=True),
        Index("idx_plot", "plot_id"),
        Index("idx_status_heartbeat", "status", "last_heartbeat_at"),
        {"comment": "设备表：摄像头/测报灯/传感器等接入设备"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="设备ID")
    device_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="设备编号")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="设备名称")
    type: Mapped[str] = mapped_column(String(32), nullable=False, comment="camera/pest_light/spore_trap/env_sensor")
    plot_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=False, comment="安装地块ID"
    )
    protocol: Mapped[str] = mapped_column(String(32), nullable=False, comment="MQTT/RTSP/vendor_api")
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="厂商")
    collect_schedule: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="采集计划JSON")
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="远程配置JSON")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="offline", comment="online/offline")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True, comment="最近心跳时间")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DT3, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    plot: Mapped["Plot"] = relationship("Plot", lazy="joined")


class DeviceHeartbeatLog(Base):
    """设备心跳日志表 ORM 模型（device_heartbeat_log）。

    记录每次心跳上报时间，支撑设备详情页「最近 N 条心跳」展示。
    （架构文档未单列此表，为满足设备详情心跳历史展示需求而补充。）

    Attributes:
        id: 日志ID。
        device_id: 设备ID。
        heartbeat_at: 心跳上报时间。
        status: 上报时设备状态。
        created_at: 入库时间。
    """
    __tablename__ = "device_heartbeat_log"
    __table_args__ = (
        Index("idx_device_time", "device_id", "heartbeat_at"),
        {"comment": "设备心跳日志表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="日志ID")
    device_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("device.id"), nullable=False, comment="设备ID"
    )
    heartbeat_at: Mapped[datetime] = mapped_column(DT3, nullable=False, comment="心跳上报时间")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="online", comment="上报时状态")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="入库时间")
