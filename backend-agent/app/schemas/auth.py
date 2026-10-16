"""认证相关请求/响应模型。"""
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_phone(value: str) -> str:
    """校验中国大陆手机号格式。"""
    if not re.match(r"^1[3-9]\d{9}$", value):
        raise ValueError("手机号格式不正确")
    return value


class LoginRequest(BaseModel):
    """登录请求体（原 username+password 入口，保留兼容）。

    Attributes:
        username: 登录名。
        password: 明文密码。
    """

    username: str = Field(..., min_length=1, max_length=64, description="登录名")
    password: str = Field(..., min_length=1, max_length=64, description="密码")


class PhoneLoginRequest(BaseModel):
    """手机号+密码登录请求体。

    Attributes:
        phone: 11 位手机号。
        password: 明文密码。
    """

    phone: str = Field(..., description="手机号")
    password: str = Field(..., min_length=6, max_length=64, description="密码")

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, value: str) -> str:
        return _validate_phone(value)


class CodeLoginRequest(BaseModel):
    """手机号+短信验证码登录请求体。

    Attributes:
        phone: 11 位手机号。
        code: 6 位短信验证码。
    """

    phone: str = Field(..., description="手机号")
    code: str = Field(..., min_length=4, max_length=8, description="短信验证码")

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, value: str) -> str:
        return _validate_phone(value)


class RegisterRequest(BaseModel):
    """手机号注册请求体。

    Attributes:
        phone: 11 位手机号。
        password: 明文密码（至少 6 位）。
        code: 短信验证码。
        nickname: 可选昵称，缺省取「用户+手机号后 4 位」。
    """

    phone: str = Field(..., description="手机号")
    password: str = Field(..., min_length=6, max_length=64, description="密码")
    code: str = Field(..., min_length=4, max_length=8, description="短信验证码")
    nickname: str | None = Field(default=None, max_length=64, description="昵称")

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, value: str) -> str:
        return _validate_phone(value)


class SendCodeRequest(BaseModel):
    """发送短信验证码请求体。

    Attributes:
        phone: 11 位手机号。
        scene: 场景，login 或 register。
    """

    phone: str = Field(..., description="手机号")
    scene: str = Field(..., pattern="^(login|register)$", description="场景 login/register")

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, value: str) -> str:
        return _validate_phone(value)


class UserInfo(BaseModel):
    """用户基本信息（脱敏，不含密码哈希）。

    Attributes:
        id: 用户ID。
        username: 登录名。
        phone: 手机号。
        nickname: 显示名。
        role: 角色 owner/member。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="用户ID")
    username: str = Field(..., description="登录名")
    phone: str | None = Field(default=None, description="手机号")
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
