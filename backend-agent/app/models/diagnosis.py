"""诊断链路相关表 ORM 模型。

包含：诊断任务表（diagnosis_task）、任务-图像关联表（diagnosis_task_image）、
诊断结果表（diagnosis_result）、防治方案表（prevention_plan）。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import DECIMAL, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, JSON, TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.plot import Plot

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class DiagnosisTask(Base):
    """诊断任务表 ORM 模型（diagnosis_task）。

    一条诊断任务对应一次端到端诊断流水线执行，
    thread_id 关联 LangGraph Checkpoint 线程（后续模块使用）。

    Attributes:
        id: 任务ID。
        thread_id: LangGraph Checkpoint 线程ID（唯一）。
        plot_id: 地块/棚室ID。
        source: 来源 device/manual。
        growth_stage: 诊断时生育期。
        status: 状态 pending/running/done/failed。
        result_level: 结果级别 high 高置信 / low 低置信。
        fused_confidence: 融合置信度。
        failure_reason: 失败原因（超时降级等）。
        created_at: 创建时间。
        finished_at: 完成时间（时效统计）。
        plot: 关联地块。
    """
    __tablename__ = "diagnosis_task"
    __table_args__ = (
        Index("uk_thread", "thread_id", unique=True),
        Index("idx_plot_created", "plot_id", "created_at"),
        Index("idx_status", "status"),
        {"comment": "诊断任务表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="任务ID")
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="LangGraph线程ID")
    plot_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=False, comment="地块/棚室ID"
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, comment="device/manual")
    growth_stage: Mapped[str] = mapped_column(String(32), nullable=False, comment="诊断时生育期")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", comment="pending/running/done/failed")
    result_level: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="high/low")
    fused_confidence: Mapped[float | None] = mapped_column(DECIMAL(5, 4), nullable=True, comment="融合置信度")
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="失败原因")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
    finished_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True, comment="完成时间")

    plot: Mapped["Plot"] = relationship("Plot", lazy="joined")


class DiagnosisTaskImage(Base):
    """任务-图像关联表 ORM 模型（diagnosis_task_image）。

    手动上传支持 1–4 张图像，与任务多对多关联。

    Attributes:
        id: 关联ID。
        task_id: 诊断任务ID（级联删除）。
        image_id: 图像ID。
    """
    __tablename__ = "diagnosis_task_image"
    __table_args__ = (
        Index("uk_task_image", "task_id", "image_id", unique=True),
        Index("idx_image", "image_id"),
        {"comment": "诊断任务-图像关联表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="关联ID")
    task_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("diagnosis_task.id", ondelete="CASCADE"), nullable=False, comment="任务ID"
    )
    image_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("collected_image.id"), nullable=False, comment="图像ID"
    )


class DiagnosisResult(Base):
    """诊断结果表 ORM 模型（diagnosis_result）。

    VLM 与细分类小模型双路结果分别落库，便于溯源与评测。

    Attributes:
        id: 结果ID。
        task_id: 任务ID（级联删除）。
        model_path: 推理路径 vlm/small_model/fused。
        model_name: 具体模型版本名。
        disease_name: 病/虫名称（未识别时 unknown）。
        disease_category: 病种分类（可空）。
        confidence: 置信度。
        raw_output: 模型原始输出 JSON（可空）。
        created_at: 创建时间。
    """
    __tablename__ = "diagnosis_result"
    __table_args__ = (
        Index("idx_task_path", "task_id", "model_path"),
        Index("idx_disease", "disease_name"),
        {"comment": "诊断结果表：双路推理结果落库"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="结果ID")
    task_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("diagnosis_task.id", ondelete="CASCADE"), nullable=False, comment="任务ID"
    )
    model_path: Mapped[str] = mapped_column(String(32), nullable=False, comment="vlm/small_model/fused")
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="具体模型版本")
    disease_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="病/虫名称")
    disease_category: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="病种分类")
    confidence: Mapped[float] = mapped_column(DECIMAL(5, 4), nullable=False, comment="置信度")
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="模型原始输出")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class PreventionPlan(Base):
    """防治方案表 ORM 模型（prevention_plan）。

    方案卡内容与禁限用名录校验结论 JSON 落库，
    is_forbidden_blocked 标记是否因禁用药被拦截。

    Attributes:
        id: 方案ID。
        task_id: 来源任务ID。
        scheme_json: 方案卡内容（名称、用药方案、剂量）。
        compliance_result: 禁限用名录校验结论。
        is_forbidden_blocked: 是否因禁用药被拦截 0/1。
        disclaimer: 免责与安全提示文案（可空）。
        created_at: 创建时间。
    """
    __tablename__ = "prevention_plan"
    __table_args__ = (
        Index("idx_task", "task_id"),
        {"comment": "防治方案表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="方案ID")
    task_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("diagnosis_task.id"), nullable=False, comment="来源任务ID"
    )
    scheme_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="方案卡内容")
    compliance_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="禁限用校验结论")
    is_forbidden_blocked: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0, comment="是否禁用药拦截 0/1")
    disclaimer: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="免责与安全提示")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
