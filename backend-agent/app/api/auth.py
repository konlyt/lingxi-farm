"""认证接口路由。

提供：
- 原 username+password 登录（保留兼容，后端仍可用）；
- 手机号+密码登录；
- 手机号+短信验证码登录；
- 手机号注册（新注册用户默认 owner 角色）；
- 发送短信验证码；
- 手机号是否已注册查询；
- 当前用户信息查询与修改密码。
"""
import re

from fastapi import APIRouter, Depends, Query
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
from app.schemas.auth import (
    CodeLoginRequest,
    LoginRequest,
    PasswordChangeRequest,
    PhoneLoginRequest,
    RegisterRequest,
    SendCodeRequest,
)
from app.services.sms_service import send_sms_code, verify_sms_code

router = APIRouter(prefix="/api/auth", tags=["认证"])

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def _to_user_payload(user: SysUser) -> dict:
    """把 SysUser ORM 实例转成登录响应中的 user 字典。"""
    return {
        "id": user.id,
        "username": user.username,
        "phone": user.phone,
        "nickname": user.nickname,
        "role": user.role,
    }


def _issue_login(user: SysUser) -> dict:
    """签发 JWT 并组装登录响应。"""
    token = create_access_token(user)
    return {"token": token, "user": _to_user_payload(user)}


@router.post("/login", summary="账号密码登录（保留兼容）")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """原 username+password 登录入口，保留以便调试与历史客户端兼容。

    Args:
        body: 登录请求体（username/password）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {token, user}。
    """
    user = db.query(SysUser).filter(SysUser.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise BusinessException(401, "用户名或密码错误")
    if user.status != 1:
        raise BusinessException(401, "账号已停用，请联系农场主")
    return ok(_issue_login(user))


@router.post("/login/phone", summary="手机号+密码登录")
def login_by_phone(body: PhoneLoginRequest, db: Session = Depends(get_db)) -> dict:
    """手机号+密码登录。

    Args:
        body: 手机号+密码请求体。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {token, user}。
    """
    user = db.query(SysUser).filter(SysUser.phone == body.phone).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise BusinessException(401, "手机号或密码错误")
    if user.status != 1:
        raise BusinessException(401, "账号已停用，请联系农场主")
    return ok(_issue_login(user))


@router.post("/login/code", summary="手机号+短信验证码登录")
def login_by_code(body: CodeLoginRequest, db: Session = Depends(get_db)) -> dict:
    """手机号+短信验证码登录。先校验验证码，再查用户。

    Args:
        body: 手机号+验证码请求体。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {token, user}。
    """
    verify_sms_code(body.phone, "login", body.code)
    user = db.query(SysUser).filter(SysUser.phone == body.phone).first()
    if user is None:
        raise BusinessException(401, "该手机号尚未注册")
    if user.status != 1:
        raise BusinessException(401, "账号已停用，请联系农场主")
    return ok(_issue_login(user))


@router.post("/send-code", summary="发送短信验证码")
def send_code(body: SendCodeRequest) -> dict:
    """发送短信验证码。

    注册场景要求手机号未注册；登录场景要求手机号已注册，避免任意号码被骚扰。

    Args:
        body: 手机号+场景请求体。

    Returns:
        dict: 统一响应，data 为 {sent: true, dev_code?: 验证码}；
              dev_mode 下 dev_code 直接返回便于联调。
    """
    # 由 service 内部再做一次格式兜底
    if not _PHONE_RE.match(body.phone):
        raise BusinessException(400, "手机号格式不正确")

    dev_code = send_sms_code(body.phone, body.scene)
    return ok({"sent": True, "dev_code": dev_code})


@router.get("/check-phone", summary="查询手机号是否已注册")
def check_phone(phone: str = Query(..., description="手机号"), db: Session = Depends(get_db)) -> dict:
    """供前端注册/登录场景预填判断使用。

    Args:
        phone: 手机号。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {exists: bool}。
    """
    if not _PHONE_RE.match(phone):
        raise BusinessException(400, "手机号格式不正确")
    exists = db.query(SysUser.id).filter(SysUser.phone == phone).first() is not None
    return ok({"exists": exists})


@router.post("/register", summary="手机号注册")
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    """手机号注册：先校验短信验证码，再创建用户。

    新用户默认角色为 ``owner``（单农场自用，注册即农场主）；
    username 自动取 ``u_<手机号后 6 位>`` 保证唯一。

    Args:
        body: 注册请求体（phone/password/code/nickname）。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {token, user}。
    """
    # 1. 校验验证码
    verify_sms_code(body.phone, "register", body.code)

    # 2. 重复注册检查
    existed = db.query(SysUser).filter(SysUser.phone == body.phone).first()
    if existed is not None:
        raise BusinessException(409, "该手机号已注册，请直接登录")

    # 3. 生成唯一 username（兼容原 username 唯一索引）
    username_candidate = f"u_{body.phone[-6:]}"
    if db.query(SysUser).filter(SysUser.username == username_candidate).first() is not None:
        # 极端情况后 6 位撞号，追加后 4 位
        username_candidate = f"u_{body.phone[-4:]}_{body.phone[-2:]}"

    nickname = body.nickname or f"用户{body.phone[-4:]}"
    user = SysUser(
        username=username_candidate,
        phone=body.phone,
        password_hash=hash_password(body.password),
        nickname=nickname,
        role="owner",
        wx_bind_status=0,
        status=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(_issue_login(user))


@router.get("/me", summary="获取当前用户信息")
def get_me(user: SysUser = Depends(get_current_user)) -> dict:
    """返回当前登录用户的基本信息。

    Args:
        user: 经认证的当前用户。

    Returns:
        dict: 统一响应，data 含 id/username/phone/nickname/role/wx_bind_status。
    """
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "phone": user.phone,
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
    """
    if not verify_password(body.old_password, user.password_hash):
        raise BusinessException(400, "原密码不正确")
    if body.old_password == body.new_password:
        raise BusinessException(400, "新密码不能与原密码相同")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return ok(None)
