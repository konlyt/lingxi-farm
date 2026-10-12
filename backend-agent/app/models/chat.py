"""知识问答会话相关表 ORM 模型。

包含：会话表（chat_session）、消息表（chat_message）。
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class ChatSession(Base):
    """知识问答会话表 ORM 模型（chat_session）。

    Attributes:
        id: 会话ID。
        user_id: 归属用户ID。
        title: 会话摘要标题（可空）。
        created_at: 创建时间。
    """
    __tablename__ = "chat_session"
    __table_args__ = (
        Index("idx_user", "user_id", "created_at"),
        {"comment": "知识问答会话表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="会话ID")
    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("sys_user.id"), nullable=False, comment="归属用户ID"
    )
    title: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="会话摘要标题")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")


class ChatMessage(Base):
    """知识问答消息表 ORM 模型（chat_message）。

    Attributes:
        id: 消息ID。
        session_id: 会话ID（级联删除）。
        user_id: 提问用户ID。
        role: 角色 user/assistant。
        content_type: 内容类型 text/voice。
        content: 文本内容。
        audio_url: 语音文件地址（可空）。
        created_at: 创建时间。
    """
    __tablename__ = "chat_message"
    __table_args__ = (
        Index("idx_session", "session_id", "created_at"),
        {"comment": "知识问答消息表"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="消息ID")
    session_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("chat_session.id", ondelete="CASCADE"), nullable=False, comment="会话ID"
    )
    user_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), ForeignKey("sys_user.id"), nullable=False, comment="提问用户ID"
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="user/assistant")
    content_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text", comment="text/voice")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="文本内容")
    audio_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="语音文件地址")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
