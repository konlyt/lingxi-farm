"""认证接口路由。

提供登录签发 JWT、当前用户信息查询与修改密码三个接口。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.user import SysUser
from app.schemas.auth import LoginRequest, PasswordChangeRequest

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", summary="登录并签发 JWT")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """用户登录，校验账号密码并签发 JWT。

    Args:
        body: 登录请求体（username/password）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {token, user:{id, username, nickname, role}}。

    Raises:
        BusinessException: 401 用户名不存在、密码错误或账号已停用。
    """
    user = db.query(SysUser).filter(SysUser.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise BusinessException(401, "用户名或密码错误")
    if user.status != 1:
        raise BusinessException(401, "账号已停用，请联系农场主")
    token = create_access_token(user)
    return ok(
        {
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "role": user.role,
            },
        }
    )


@router.get("/me", summary="获取当前用户信息")
def get_me(user: SysUser = Depends(get_current_user)) -> dict:
    """返回当前登录用户的基本信息。

    Args:
        user: 经认证的当前用户。

    Returns:
        dict: 统一响应，data 为 {id, username, nickname, role, wx_bind_status}。
    """
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "role": user.role,
            "wx_bind_status": user.wx_bind_status,
        }
    )


@router.put("/password", summary="修改当前用户密码")
def change_password(
    body: PasswordChangeRequest,
    user: SysUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """修改当前登录用户的密码（原密码校验通过后更新）。

    Args:
        body: 修改密码请求体（old_password/new_password）。
        user: 经认证的当前用户。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 None。

    Raises:
        BusinessException: 400 原密码不正确，或新密码与原密码相同。
    """
    if not verify_password(body.old_password, user.password_hash):
        raise BusinessException(400, "原密码不正确")
    if body.old_password == body.new_password:
        raise BusinessException(400, "新密码不能与原密码相同")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return ok(None)
