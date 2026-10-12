"""知识库与药剂/采收禁令相关表 ORM 模型。

包含：知识库文档元数据表（knowledge_document）、
药剂基础信息表（pesticide）、采收禁令表（harvest_restriction）。
"""
from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, DATE, DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class KnowledgeDocument(Base):
    """知识库文档元数据表 ORM 模型（knowledge_document）。

    仅管理文档元数据与向量化入库状态；向量数据本体在向量存储中（RAG 切片用）。

    Attributes:
        id: 文档ID。
        title: 文档标题。
        category: 分类 disease_map/treatment/pesticide_regulation。
        file_url: 原文存储地址。
        milvus_collection: 对应向量库 Collection 名。
        chunk_count: 切片数量。
        embed_status: 向量化状态 pending/done/failed。
        created_at: 创建时间。
        updated_at: 更新时间。
    """
    __tablename__ = "knowledge_document"
    __table_args__ = (
        Index("idx_category_status", "category", "embed_status"),
        {"comment": "知识库文档元数据表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="文档ID")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="文档标题")
    category: Mapped[str] = mapped_column(String(32), nullable=False, comment="disease_map/treatment/pesticide_regulation")
    file_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="原文存储地址")
    milvus_collection: Mapped[str] = mapped_column(String(64), nullable=False, comment="向量库Collection名")
    chunk_count: Mapped[int] = mapped_column(nullable=False, default=0, comment="切片数量")
    embed_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", comment="pending/done/failed")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DT3, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


class Pesticide(Base):
    """药剂基础信息表 ORM 模型（pesticide）。

    支撑禁限用名录校验（allowed/restricted/banned）与
    采收安全间隔期自动计算（applied_at + interval = ban_until）。

    Attributes:
        id: 药剂ID。
        name: 药剂名称。
        active_ingredient: 有效成分（唯一）。
        safety_interval_days: 安全间隔期（天）。
        forbidden_flag: 管控级别 allowed/restricted/banned。
        target_pests: 防治对象列表 JSON（可空）。
        source_doc_id: 名录出处知识文档ID（可空）。
        updated_at: 更新时间。
    """
    __tablename__ = "pesticide"
    __table_args__ = (
        Index("uk_active_ingredient", "active_ingredient", unique=True),
        Index("idx_forbidden", "forbidden_flag"),
        {"comment": "药剂基础信息表：禁限用名录与安全间隔期"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="药剂ID")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="药剂名称")
    active_ingredient: Mapped[str] = mapped_column(String(128), nullable=False, comment="有效成分")
    safety_interval_days: Mapped[int] = mapped_column(nullable=False, comment="安全间隔期（天）")
    forbidden_flag: Mapped[str] = mapped_column(String(16), nullable=False, comment="allowed/restricted/banned")
    target_pests: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="防治对象JSON")
    source_doc_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("knowledge_document.id"), nullable=True, comment="名录出处文档ID"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DT3, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


class HarvestRestriction(Base):
    """采收禁令表 ORM 模型（harvest_restriction）。

    用药后按安全间隔期自动生成，实况面板角标查询依赖 idx_plot_status_until。

    Attributes:
        id: 禁令ID。
        plot_id: 禁令归属地块ID。
        plan_id: 来源防治方案ID。
        pesticide_id: 触发药剂ID。
        applied_at: 用药日期。
        ban_until: 采收禁令截止日（applied_at + 安全间隔期）。
        status: 状态 active/expired（到期自动解除）。
        released_at: 实际解除时间（可空）。
    """
    __tablename__ = "harvest_restriction"
    __table_args__ = (
        Index("idx_plot_status_until", "plot_id", "status", "ban_until"),
        Index("idx_until", "ban_until"),
        {"comment": "采收禁令表：安全间隔期管理"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="禁令ID")
    plot_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=False, comment="禁令归属地块ID"
    )
    plan_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("prevention_plan.id"), nullable=False, comment="来源方案ID"
    )
    pesticide_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("pesticide.id"), nullable=False, comment="触发药剂ID"
    )
    applied_at: Mapped[date] = mapped_column(DATE, nullable=False, comment="用药日期")
    ban_until: Mapped[date] = mapped_column(DATE, nullable=False, comment="禁令截止日")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", comment="active/expired")
    released_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True, comment="实际解除时间")
