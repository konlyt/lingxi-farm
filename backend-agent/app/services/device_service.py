"""设备业务服务模块。

提供设备统计、心跳上报、心跳历史查询等复用逻辑。
"""
from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.device import Device, DeviceHeartbeatLog
from app.utils.time_utils import fmt_datetime, now


def get_device_stats(db: Session) -> dict[str, int]:
    """统计设备总数与在线/离线数量。

    Args:
        db: 数据库会话。

    Returns:
        dict: {total, online, offline}。
    """
    total = db.query(func.count(Device.id)).scalar() or 0
    online = db.query(func.count(Device.id)).filter(Device.status == "online").scalar() or 0
    offline = total - online
    return {"total": total, "online": online, "offline": offline}


def report_heartbeat(db: Session, device: Device) -> dict[str, Any]:
    """上报设备心跳：刷新在线状态与最近心跳时间，并落心跳日志。

    Args:
        db: 数据库会话。
        device: 设备 ORM 实例。

    Returns:
        dict: {device_id, status, last_heartbeat_at}。
    """
    current = now()
    device.status = "online"
    device.last_heartbeat_at = current
    log = DeviceHeartbeatLog(device_id=device.id, heartbeat_at=current, status="online")
    db.add(log)
    db.commit()
    return {
        "device_id": device.id,
        "status": device.status,
        "last_heartbeat_at": fmt_datetime(current),
    }


def get_recent_heartbeats(db: Session, device_id: int, limit: int = 50) -> list[str]:
    """查询设备最近 N 条心跳时间（新→旧）。

    Args:
        db: 数据库会话。
        device_id: 设备ID。
        limit: 返回条数上限，默认 50。

    Returns:
        list[str]: 心跳时间 ISO 字符串列表。
    """
    logs = (
        db.query(DeviceHeartbeatLog)
        .filter(DeviceHeartbeatLog.device_id == device_id)
        .order_by(DeviceHeartbeatLog.heartbeat_at.desc())
        .limit(limit)
        .all()
    )
    return [fmt_datetime(log.heartbeat_at) for log in logs]


def is_offline(device: Device, threshold_hours: int = 24) -> bool:
    """判断设备是否应判定为离线（最近心跳距今超过阈值）。

    Args:
        device: 设备 ORM 实例。
        threshold_hours: 离线判定阈值（小时），默认 24。

    Returns:
        bool: 已离线返回 True；无心跳记录视为离线。
    """
    if device.last_heartbeat_at is None:
        return True
    return now() - device.last_heartbeat_at > timedelta(hours=threshold_hours)
