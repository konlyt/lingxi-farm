"""系统设置接口路由。

提供置信度阈值配置查询/编辑（owner）、家庭成员管理（owner）、
以及微信服务号绑定状态列表查询。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok
from app.core.security import hash_password, require_owner
from app.models.advice import ConfidenceThresholdConfig
from app.models.user import SysUser
from app.schemas.settings import (
    ConfidenceThresholdUpdateRequest,
    MemberCreateRequest,
    MemberStatusPatchRequest,
)
from app.utils.time_utils import now

router = APIRouter(prefix="/api/settings", tags=["系统设置"], dependencies=[Depends(require_owner)])


@router.get("/confidence-thresholds", summary="置信度阈值配置列表")
def list_confidence_thresholds(db: Session = Depends(get_db)) -> dict:
    """查询分病种置信度阈值配置列表。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为配置数组 [{id, disease_category, threshold, enabled}]。
    """
    rows = db.query(ConfidenceThresholdConfig).order_by(ConfidenceThresholdConfig.id.asc()).all()
    return ok(
        [
            {
                "id": row.id,
                "disease_category": row.disease_category,
                "threshold": float(row.threshold),
                "sample_count_baseline": row.sample_count_baseline,
                "enabled": bool(row.enabled),
            }
            for row in rows
        ]
    )


@router.put("/confidence-thresholds", summary="编辑置信度阈值（owner）")
def update_confidence_thresholds(body: ConfidenceThresholdUpdateRequest, db: Session = Depends(get_db)) -> dict:
    """批量更新置信度阈值（0–1，最多两位小数），即时生效于后续诊断判定。

    Args:
        body: 批量更新请求体 [{id, threshold}]。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为更新后的配置数组。

    Raises:
        BusinessException: 400 配置记录不存在。
    """
    updated = []
    for item in body.items:
        row = db.query(ConfidenceThresholdConfig).filter(ConfidenceThresholdConfig.id == item.id).first()
        if row is None:
            raise BusinessException(400, f"置信度配置 id={item.id} 不存在")
        row.threshold = round(item.threshold, 2)
        row.updated_at = now()
        updated.append(row)
    db.commit()
    return ok(
        [
            {
                "id": row.id,
                "disease_category": row.disease_category,
                "threshold": float(row.threshold),
                "enabled": bool(row.enabled),
            }
            for row in updated
        ]
    )


@router.get("/members", summary="家庭成员列表")
def list_members(db: Session = Depends(get_db)) -> dict:
    """查询全部用户（家庭成员管理列表）。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为用户数组（不含密码哈希）。
    """
    rows = db.query(SysUser).order_by(SysUser.id.asc()).all()
    return ok(
        [
            {
                "id": row.id,
                "username": row.username,
                "nickname": row.nickname,
                "role": row.role,
                "status": row.status,
                "wx_bind_status": row.wx_bind_status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    )


@router.post("/members", summary="新增家庭成员（member 角色）")
def create_member(body: MemberCreateRequest, db: Session = Depends(get_db)) -> dict:
    """创建家庭成员账号（固定 member 只读角色），用户名唯一。

    Args:
        body: 成员创建请求体 {username, nickname, password}。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, username, nickname, role}。

    Raises:
        BusinessException: 400 用户名已存在。
    """
    if db.query(SysUser.id).filter(SysUser.username == body.username).first() is not None:
        raise BusinessException(400, f"用户名「{body.username}」已存在")
    member = SysUser(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname,
        role="member",
        status=1,
    )
    db.add(member)
    db.commit()
    return ok({"id": member.id, "username": member.username, "nickname": member.nickname, "role": member.role})


@router.patch("/members/{member_id}/status", summary="启用/停用家庭成员")
def patch_member_status(member_id: int, body: MemberStatusPatchRequest, db: Session = Depends(get_db)) -> dict:
    """切换家庭成员启用/停用状态（仅允许操作 member 角色账号）。

    Args:
        member_id: 目标用户ID。
        body: 状态切换请求体 {status}。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, status}。

    Raises:
        BusinessException: 404 用户不存在；400 不允许操作 owner 账号。
    """
    member = db.query(SysUser).filter(SysUser.id == member_id).first()
    if member is None:
        raise BusinessException(404, "用户不存在")
    if member.role != "member":
        raise BusinessException(400, "仅允许停用/启用家庭成员账号")
    member.status = body.status
    db.commit()
    return ok({"id": member.id, "status": member.status})


@router.get("/wx-bind", summary="用户微信绑定状态列表")
def list_wx_bind(db: Session = Depends(get_db)) -> dict:
    """查询全部用户微信服务号绑定状态（种子账号默认未绑定）。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 [{id, username, nickname, role, wx_bind_status, wx_openid}]。
    """
    rows = db.query(SysUser).order_by(SysUser.id.asc()).all()
    return ok(
        [
            {
                "id": row.id,
                "username": row.username,
                "nickname": row.nickname,
                "role": row.role,
                "wx_bind_status": row.wx_bind_status,
                "wx_openid": row.wx_openid,
            }
            for row in rows
        ]
    )
