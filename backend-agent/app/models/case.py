"""案例库相关表 ORM 模型。

包含：案例库表（case_library）、案例图像关联表（case_image）。
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class CaseLibrary(Base):
    """案例库表 ORM 模型（case_library）。

    待确认（低置信度回流）与已确认/纠正案例统一建模，
    支撑置信度阈值分病种样本量统计与本人确认自闭环。

    Attributes:
        id: 案例ID。
        task_id: 来源诊断任务ID。
        ai_disease_name: AI 初判名称。
        final_disease_name: 确认/纠正后名称（可空）。
        status: 状态 pending/confirmed/corrected。
        source: 来源 device/manual。
        disease_category: 病种分类（可空）。
        confirmed_by: 确认人ID（可空）。
        confirmed_at: 确认时间（可空）。
        note: 纠正备注（可空）。
        created_at: 创建时间。
    """
    __tablename__ = "case_library"
    __table_args__ = (
        Index("idx_status_category", "status", "disease_category"),
        Index("idx_task", "task_id"),
        Index("idx_source", "source"),
        {"comment": "案例库表：待确认与已确认案例统一建模"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="案例ID")
    task_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("diagnosis_task.id"), nullable=False, comment="来源诊断任务ID"
    )
    ai_disease_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="AI初判名称")
    final_disease_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="确认/纠正后名称")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", comment="pending/confirmed/corrected")
    source: Mapped[str] = mapped_column(String(16), nullable=False, comment="device/manual")
    disease_category: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="病种分类")
    confirmed_by: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("sys_user.id"), nullable=True, comment="确认人ID"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True, comment="确认时间")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="纠正备注")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class CaseImage(Base):
    """案例图像关联表 ORM 模型（case_image）。

    Attributes:
        id: 关联ID。
        case_id: 案例ID（级联删除）。
        image_id: 图像ID。
    """
    __tablename__ = "case_image"
    __table_args__ = (
        Index("uk_case_image", "case_id", "image_id", unique=True),
        {"comment": "案例图像关联表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="关联ID")
    case_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("case_library.id", ondelete="CASCADE"), nullable=False, comment="案例ID"
    )
    image_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("collected_image.id"), nullable=False, comment="图像ID"
    )
