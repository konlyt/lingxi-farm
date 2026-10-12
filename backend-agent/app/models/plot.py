"""地块/棚室档案表（plot）ORM 模型。"""
from datetime import date, datetime

from sqlalchemy import DATE, DECIMAL, Index, String
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class Plot(Base):
    """地块/棚室档案表 ORM 模型（plot）。

    露天地块（经纬度选点）与大棚棚室统一建模。

    Attributes:
        id: 档案ID。
        name: 名称（唯一），如「番茄1号棚」。
        type: 类型 greenhouse 大棚 / open_field 露天。
        lng: 经度（露天地块选点，可空）。
        lat: 纬度（可空）。
        area_mu: 面积（亩，可空）。
        soil_type: 土壤类型（可空）。
        crop_name: 当前作物。
        crop_variety: 品种（可空）。
        growth_stage: 当前生育期。
        planted_at: 定植/播种日期（可空）。
        remark: 备注（可空）。
        status: 1在种/0停用。
        created_at: 创建时间。
        updated_at: 更新时间。
    """
    __tablename__ = "plot"
    __table_args__ = (
        Index("uk_name", "name", unique=True),
        Index("idx_type_status", "type", "status"),
        {"comment": "地块/棚室档案表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="档案ID")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="名称，如番茄1号棚")
    type: Mapped[str] = mapped_column(String(16), nullable=False, comment="greenhouse大棚/open_field露天")
    lng: Mapped[float | None] = mapped_column(DECIMAL(10, 6), nullable=True, comment="经度")
    lat: Mapped[float | None] = mapped_column(DECIMAL(10, 6), nullable=True, comment="纬度")
    area_mu: Mapped[float | None] = mapped_column(DECIMAL(8, 2), nullable=True, comment="面积（亩）")
    soil_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="土壤类型")
    crop_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="当前作物")
    crop_variety: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="品种")
    growth_stage: Mapped[str] = mapped_column(String(32), nullable=False, comment="当前生育期")
    planted_at: Mapped[date | None] = mapped_column(DATE, nullable=True, comment="定植/播种日期")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")
    status: Mapped[int] = mapped_column(TINYINT, nullable=False, default=1, comment="1在种/0停用")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DT3, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
