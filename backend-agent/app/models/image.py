"""图像表（collected_image）ORM 模型。

双通道（设备自动采集 / 手动上传）统一建模，
图像文件本体不进向量库，仅存 URL 与元数据。
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.device import Device
from app.models.plot import Plot
from app.models.user import SysUser

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class CollectedImage(Base):
    """图像表 ORM 模型（collected_image）。

    Attributes:
        id: 图像ID。
        plot_id: 采集于地块/棚室ID。
        device_id: 采集设备ID（手动上传为 NULL）。
        source: 来源 device 自动通道 / manual 人为通道。
        cos_url: 图像存储地址（开发环境为本地 /uploads 相对路径）。
        thumb_url: 缩略图地址（可空）。
        quality_status: 质量 pass/blur模糊/overexposed过曝/invalid非作物。
        dedup_hash: 感知哈希（dhash 十六进制，质量筛选去重依据）。
        uploaded_by: 上传人ID（手动通道）。
        captured_at: 实际拍摄/采集时间。
        created_at: 入库时间。
        plot / device / uploader: 关联 ORM 对象。
    """
    __tablename__ = "collected_image"
    __table_args__ = (
        Index("uk_dedup", "dedup_hash", "plot_id", unique=True),
        Index("idx_plot_source_time", "plot_id", "source", "captured_at"),
        Index("idx_quality", "quality_status"),
        {"comment": "图像表：双通道采集图像统一建模"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="图像ID")
    plot_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=False, comment="地块/棚室ID"
    )
    device_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("device.id"), nullable=True, comment="采集设备ID（手动上传为NULL）"
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, comment="device自动/manual人为")
    cos_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="图像存储地址")
    thumb_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="缩略图地址")
    quality_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pass", comment="质量标记")
    dedup_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, comment="感知哈希去重键")
    uploaded_by: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("sys_user.id"), nullable=True, comment="上传人ID"
    )
    captured_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True, comment="实际拍摄/采集时间")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="入库时间")

    plot: Mapped["Plot"] = relationship("Plot", lazy="joined")
    device: Mapped["Device | None"] = relationship("Device", lazy="joined")
    uploader: Mapped["SysUser | None"] = relationship("SysUser", lazy="joined")
