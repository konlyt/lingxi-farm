"""用户表（sys_user）ORM 模型。"""
from datetime import datetime

from sqlalchemy import Index, String
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# MySQL 专用毫秒精度 DATETIME(3)
DT3 = DATETIME(fsp=3)


class SysUser(Base):
    """用户表 ORM 模型（sys_user）。

    农场主（owner，全部权限）与家庭成员（member，只读 + 接收预警）统一建模。

    Attributes:
        id: 用户ID。
        username: 登录名（唯一）。
        password_hash: bcrypt 密码哈希。
        nickname: 显示名。
        role: 角色 owner/member。
        wx_openid: 微信服务号 OpenID（推送定向，可空）。
        wx_bind_status: 服务号绑定状态 0未绑/1已绑。
        email: 推送邮箱（唯一，可空，未绑定为 NULL）。
        email_bind_status: 邮箱绑定状态 0未绑/1已绑。
        status: 1启用/0停用。
        created_at: 创建时间。
    """
    __tablename__ = "sys_user"
    __table_args__ = (
        Index("uk_username", "username", unique=True),
        Index("uk_wx_openid", "wx_openid", unique=True),
        Index("uk_email", "email", unique=True),
        {"comment": "用户表：农场主与家庭成员"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="用户ID")
    username: Mapped[str] = mapped_column(String(64), nullable=False, comment="登录名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt密码哈希")
    nickname: Mapped[str] = mapped_column(String(64), nullable=False, comment="显示名")
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="角色 owner/member")
    wx_openid: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="微信服务号OpenID")
    wx_bind_status: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0, comment="服务号绑定状态 0未绑/1已绑")
    email: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="推送邮箱（唯一）")
    email_bind_status: Mapped[int] = mapped_column(TINYINT, nullable=False, default=0, server_default="0", comment="邮箱绑定状态 0未绑/1已绑")
    status: Mapped[int] = mapped_column(TINYINT, nullable=False, default=1, comment="1启用/0停用")
    created_at: Mapped[datetime] = mapped_column(DT3, nullable=False, default=datetime.now, comment="创建时间")
