"""认证与权限模块。

提供 bcrypt 密码哈希、JWT 签发与校验、`get_current_user` 认证依赖
以及 `require_owner` 角色权限依赖（member 角色对写操作一律 403）。
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.response import BusinessException
from app.models.user import SysUser

# bcrypt 密码上下文
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer 提取器（无 token 时返回 None，由依赖函数给出 401）
_bearer = HTTPBearer(auto_error=False)


def hash_password(raw_password: str) -> str:
    """对明文密码做 bcrypt 哈希。

    Args:
        raw_password: 用户输入的明文密码。

    Returns:
        str: bcrypt 哈希串（含盐，可直接入库 password_hash 字段）。

    Raises:
        ValueError: 密码长度超过 bcrypt 72 字节限制时由底层抛出。
    """
    return _pwd_context.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    """校验明文密码与库中哈希是否匹配。

    Args:
        raw_password: 用户输入的明文密码。
        password_hash: 数据库中存储的 bcrypt 哈希。

    Returns:
        bool: 匹配返回 True，否则 False。
    """
    try:
        return _pwd_context.verify(raw_password, password_hash)
    except Exception:
        # 哈希串非法等情况一律视为校验失败
        return False


def create_access_token(user: SysUser) -> str:
    """为指定用户签发 JWT。

    Args:
        user: 已通过密码校验的用户 ORM 实例。

    Returns:
        str: 签名的 JWT 字符串（默认有效期 7 天）。
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    """解码并校验 JWT。

    Args:
        token: 待解码的 JWT 字符串。

    Returns:
        dict: 解码成功返回载荷字典（含 sub/username/role/exp）；
              过期或签名非法返回 None。
    """
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> SysUser:
    """FastAPI 依赖：解析 Bearer Token 并返回当前登录用户。

    Args:
        credentials: HTTP Bearer 凭证（Authorization: Bearer <token>）。
        db: 数据库会话。

    Returns:
        SysUser: 当前用户 ORM 实例。

    Raises:
        BusinessException: 401 未携带/非法/过期 Token，或用户不存在、已停用。
    """
    if credentials is None or not credentials.credentials:
        raise BusinessException(401, "未登录或 Token 缺失")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise BusinessException(401, "登录已过期，请重新登录")
    user_id = payload.get("sub")
    user = db.query(SysUser).filter(SysUser.id == int(user_id)).first()
    if user is None:
        raise BusinessException(401, "用户不存在或已被删除")
    if user.status != 1:
        raise BusinessException(401, "账号已停用")
    return user


def require_owner(
    request: Request,
    user: SysUser = Depends(get_current_user),
) -> SysUser:
    """FastAPI 依赖：角色权限控制（owner 全权限，member 仅 GET 类只读接口）。

    对 POST/PUT/PATCH/DELETE 等写方法，member 角色一律拒绝；
    GET/HEAD/OPTIONS 直接放行。

    Args:
        request: 当前 HTTP 请求对象（用于判断请求方法）。
        user: 经认证的当前用户。

    Returns:
        SysUser: 通过校验的当前用户实例。

    Raises:
        BusinessException: member 角色调用写接口时抛出 403。
    """
    if request.method.upper() in ("POST", "PUT", "PATCH", "DELETE") and user.role != "owner":
        raise BusinessException(403, "家庭成员仅可查看，无操作权限")
    return user
