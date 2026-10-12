"""农情预警相关表 ORM 模型。

包含：预警表（alert）、预警推送记录表（alert_push_record）。
"""
from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.mysql import BIGINT, DATE, DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class Alert(Base):
    """预警表 ORM 模型（alert）。

    通过 case_key 聚合去重：同地块同病例未解决期间仅一条活跃预警，
    uk_active_case(case_key, status) 唯一约束在数据库层兜底。

    Attributes:
        id: 预警ID。
        type: 类型 pest/env/weather/device_offline。
        level: 级别 info/warning/critical。
        plot_id: 归属地块ID。
        task_id: 关联诊断任务ID（可空）。
        case_key: 聚合去重键，如 plot:1:pest:早疫病。
        title: 标题。
        content: 详情 JSON（含最新照片、病情变化、建议）。
        status: 状态 active/resolved。
        occurrence_count: 累计触发次数。
        first_triggered_at: 首次触发时间。
        resolved_at: 解决时间（可空）。
    """
    __tablename__ = "alert"
    __table_args__ = (
        Index("uk_active_case", "case_key", "status", unique=True),
        Index("idx_plot_type_status", "plot_id", "type", "status"),
        Index("idx_first_triggered", "first_triggered_at"),
        {"comment": "预警表：聚合去重支撑"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="预警ID")
    type: Mapped[str] = mapped_column(String(32), nullable=False, comment="pest/env/weather/device_offline")
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info", comment="info/warning/critical")
    plot_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("plot.id"), nullable=False, comment="归属地块ID"
    )
    task_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("diagnosis_task.id"), nullable=True, comment="关联诊断任务ID"
    )
    case_key: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="聚合去重键")
    title: Mapped[str] = mapped_column(String(128), nullable=False, comment="标题")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="详情JSON")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", comment="active/resolved")
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="累计触发次数")
    first_triggered_at: Mapped[datetime] = mapped_column(DT3, nullable=False, comment="首次触发时间")
    resolved_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True, comment="解决时间")


class AlertPushRecord(Base):
    """预警推送记录表 ORM 模型（alert_push_record）。

    uk_digest(alert_id, push_type, digest_date) 唯一约束兜底「同一预警每日汇总仅一条」。

    Attributes:
        id: 记录ID。
        alert_id: 预警ID（级联删除）。
        push_type: 推送类型 instant/daily_digest/local_sound。
        digest_date: 汇总归属日期（daily_digest 必填，其余可空）。
        channel: 渠道 wechat_sa/local_sound。
        receiver_user_id: 接收人ID。
        content: 模板消息内容 JSON。
        status: 发送状态 sent/failed。
        sent_at: 发送时间。
    """
    __tablename__ = "alert_push_record"
    __table_args__ = (
        # 同一预警同一日同一接收人的汇总推送仅一条（uk_digest 兜底；
        # 文档原三列定义在多用户推送下自相矛盾，故纳入 receiver_user_id）
        Index("uk_digest", "alert_id", "push_type", "digest_date", "receiver_user_id", unique=True),
        Index("idx_alert", "alert_id"),
        Index("idx_sent", "sent_at"),
        {"comment": "预警推送记录表：每日一条汇总去重兜底"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="记录ID")
    alert_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("alert.id", ondelete="CASCADE"), nullable=False, comment="预警ID"
    )
    push_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="instant/daily_digest/local_sound")
    digest_date: Mapped[date | None] = mapped_column(DATE, nullable=True, comment="汇总归属日期")
    channel: Mapped[str] = mapped_column(String(16), nullable=False, comment="wechat_sa/local_sound")
    receiver_user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("sys_user.id"), nullable=False, comment="接收人ID"
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, comment="模板消息内容JSON")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent", comment="sent/failed")
    sent_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="发送时间")
