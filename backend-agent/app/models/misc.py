"""杂项功能表 ORM 模型。

包含：农事操作记录表（farm_operation_record，预留）、导出记录表（export_log）、
LangGraph Checkpoint 简化三表（langgraph_checkpoints / langgraph_checkpoint_blobs /
langgraph_checkpoint_writes，供后续 LangGraph 持久化模块使用）。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.mysql import BIGINT, DATE, DATETIME, JSON, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class FarmOperationRecord(Base):
    """农事操作记录表 ORM 模型（farm_operation_record）。

    PRD 13.3 后续功能池项目，M1 仅预留表结构，不开发功能。

    Attributes:
        id: 记录ID。
        plot_id: 地块ID。
        op_type: 操作类型 spray/fertilize/irrigate。
        op_at: 操作时间。
        content: 操作详情 JSON（药剂/用量等）。
        created_at: 创建时间。
    """
    __tablename__ = "farm_operation_record"
    __table_args__ = (
        Index("idx_plot_time", "plot_id", "op_at"),
        {"comment": "农事操作记录表（预留）"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="记录ID")
    plot_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=False, comment="地块ID"
    )
    op_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="spray/fertilize/irrigate")
    op_at: Mapped[datetime] = mapped_column(DT3, nullable=False, comment="操作时间")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="操作详情JSON")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class ExportLog(Base):
    """导出记录表 ORM 模型（export_log）。

    Attributes:
        id: 记录ID。
        user_id: 操作人ID。
        export_type: 导出类型 diagnosis_cases/env_data。
        file_url: 导出文件地址。
        status: 状态 done/failed。
        created_at: 创建时间。
    """
    __tablename__ = "export_log"
    __table_args__ = (
        Index("idx_user_time", "user_id", "created_at"),
        {"comment": "导出记录表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="记录ID")
    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("sys_user.id"), nullable=False, comment="操作人ID"
    )
    export_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="diagnosis_cases/env_data")
    file_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="导出文件地址")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="done", comment="done/failed")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class LanggraphCheckpoint(Base):
    """LangGraph 检查点主表 ORM 模型（langgraph_checkpoints）。

    简化版自定义 MySQLSaver 结构，支撑诊断/问答链路全流程持久化可回放。

    Attributes:
        id: 自增ID。
        thread_id: 线程ID。
        checkpoint_ns: 检查点命名空间。
        checkpoint_id: 检查点ID。
        checkpoint_metadata: 检查点元数据（列名 metadata，避开 ORM 保留属性名）。
        channel_values: 通道值快照（MEDIUMTEXT）。
        channel_versions: 通道版本映射 JSON。
        created_at: 创建时间。
    """
    __tablename__ = "langgraph_checkpoints"
    __table_args__ = (
        Index("idx_thread", "thread_id", "checkpoint_ns", "checkpoint_id"),
        {"comment": "LangGraph 检查点主表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="自增ID")
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="线程ID")
    checkpoint_ns: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="检查点命名空间")
    checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="检查点ID")
    checkpoint_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True, comment="检查点元数据"
    )
    channel_values: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True, comment="通道值快照")
    channel_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="通道版本映射")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class LanggraphCheckpointBlob(Base):
    """LangGraph 检查点 Blob 存储表 ORM 模型（langgraph_checkpoint_blobs）。

    按通道存储序列化后的状态数据 Blob。

    Attributes:
        id: 自增ID。
        thread_id: 线程ID。
        checkpoint_ns: 检查点命名空间。
        channel: 通道名。
        version: 通道版本。
        type: 序列化类型标识。
        blob: 序列化数据体。
        created_at: 创建时间。
    """
    __tablename__ = "langgraph_checkpoint_blobs"
    __table_args__ = (
        Index("idx_blob_thread", "thread_id", "checkpoint_ns", "channel", "version"),
        {"comment": "LangGraph 检查点 Blob 存储表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="自增ID")
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="线程ID")
    checkpoint_ns: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="检查点命名空间")
    channel: Mapped[str] = mapped_column(String(64), nullable=False, comment="通道名")
    version: Mapped[str] = mapped_column(String(64), nullable=False, comment="通道版本")
    type: Mapped[str] = mapped_column(String(32), nullable=False, comment="序列化类型")
    blob: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True, comment="序列化数据体")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class LanggraphCheckpointWrite(Base):
    """LangGraph 检查点增量写入表 ORM 模型（langgraph_checkpoint_writes）。

    记录节点增量输出，用于断点恢复与回放。

    Attributes:
        id: 自增ID。
        thread_id: 线程ID。
        checkpoint_ns: 检查点命名空间。
        checkpoint_id: 检查点ID。
        task_id: 任务ID。
        idx: 写入序号。
        channel: 通道名。
        type: 序列化类型标识。
        blob: 序列化增量数据。
        created_at: 创建时间。
    """
    __tablename__ = "langgraph_checkpoint_writes"
    __table_args__ = (
        Index("idx_write_thread", "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
        {"comment": "LangGraph 检查点增量写入表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="自增ID")
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="线程ID")
    checkpoint_ns: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="检查点命名空间")
    checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="检查点ID")
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="任务ID")
    idx: Mapped[int] = mapped_column(nullable=False, default=0, comment="写入序号")
    channel: Mapped[str] = mapped_column(String(64), nullable=False, comment="通道名")
    type: Mapped[str] = mapped_column(String(32), nullable=False, comment="序列化类型")
    blob: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True, comment="序列化增量数据")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
