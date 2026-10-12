"""认证相关请求/响应模型。"""
from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """登录请求体。

    Attributes:
        username: 登录名。
        password: 明文密码。
    """

    username: str = Field(..., min_length=1, max_length=64, description="登录名")
    password: str = Field(..., min_length=1, max_length=64, description="密码")


class UserInfo(BaseModel):
    """用户基本信息（脱敏，不含密码哈希）。

    Attributes:
        id: 用户ID。
        username: 登录名。
        nickname: 显示名。
        role: 角色 owner/member。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="用户ID")
    username: str = Field(..., description="登录名")
    nickname: str = Field(..., description="显示名")
    role: str = Field(..., description="角色 owner/member")


class LoginResponse(BaseModel):
    """登录响应体。

    Attributes:
        token: JWT 令牌。
        user: 用户基本信息。
    """

    token: str = Field(..., description="JWT令牌")
    user: UserInfo = Field(..., description="用户信息")


class PasswordChangeRequest(BaseModel):
    """修改密码请求体。

    Attributes:
        old_password: 原密码。
        new_password: 新密码（至少 6 位）。
    """

    old_password: str = Field(..., min_length=1, max_length=64, description="原密码")
    new_password: str = Field(..., min_length=6, max_length=64, description="新密码（至少6位）")
