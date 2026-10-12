"""设备管理接口路由。

提供设备统计、列表、详情（含最近 50 条心跳）、新增、心跳上报与远程配置下发。
写操作仅 owner 可用（心跳上报为 POST，同样受限）。
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok
from app.core.security import require_owner
from app.models.device import Device
from app.models.plot import Plot
from app.schemas.device import DeviceConfigRequest, DeviceCreateRequest
from app.schemas.sensor_report import SensorReportRequest
from app.services.device_service import get_device_stats, get_recent_heartbeats, report_heartbeat
from app.services.environment_service import save_readings_and_check
from app.utils.time_utils import fmt_datetime

router = APIRouter(prefix="/api/devices", tags=["设备管理"], dependencies=[Depends(require_owner)])


@router.get("/stats", summary="设备统计（总数/在线/离线）")
def device_stats(db: Session = Depends(get_db)) -> dict:
    """返回设备在线状态统计。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {total, online, offline}。
    """
    return ok(get_device_stats(db))


@router.get("", summary="设备列表（支持地块过滤）")
def list_devices(
    plot_id: Optional[int] = Query(None, gt=0, description="按安装地块过滤"),
    db: Session = Depends(get_db),
) -> dict:
    """查询设备列表，可按安装地块过滤。

    Args:
        plot_id: 可选地块ID过滤。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为设备数组。
    """
    query = db.query(Device)
    if plot_id is not None:
        query = query.filter(Device.plot_id == plot_id)
    rows = query.order_by(Device.id.asc()).all()
    items = [
        {
            "id": device.id,
            "device_no": device.device_no,
            "name": device.name,
            "type": device.type,
            "plot_id": device.plot_id,
            "plot_name": device.plot.name if device.plot else None,
            "protocol": device.protocol,
            "vendor": device.vendor,
            "status": device.status,
            "last_heartbeat_at": fmt_datetime(device.last_heartbeat_at),
        }
        for device in rows
    ]
    return ok(items)


@router.post("", summary="新增设备（接入向导参数保存）")
def create_device(body: DeviceCreateRequest, db: Session = Depends(get_db)) -> dict:
    """新增接入设备，设备编号全局唯一，安装地块必须存在。

    Args:
        body: 设备创建请求体。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, device_no}。

    Raises:
        BusinessException: 400 设备编号重复；404 安装地块不存在。
    """
    if db.query(Plot.id).filter(Plot.id == body.plot_id).first() is None:
        raise BusinessException(404, "安装地块不存在")
    if db.query(Device.id).filter(Device.device_no == body.device_no).first() is not None:
        raise BusinessException(400, f"设备编号「{body.device_no}」已存在")
    device = Device(
        device_no=body.device_no,
        name=body.name,
        type=body.type,
        plot_id=body.plot_id,
        protocol=body.protocol,
        vendor=body.vendor,
        collect_schedule=body.collect_schedule,
        config=body.config,
        status="offline",
        last_heartbeat_at=None,
    )
    db.add(device)
    db.commit()
    return ok({"id": device.id, "device_no": device.device_no})


@router.get("/{device_id}", summary="设备详情（含最近 50 条心跳）")
def get_device(device_id: int, db: Session = Depends(get_db)) -> dict:
    """查询设备详情，附带最近 50 条心跳时间。

    Args:
        device_id: 设备ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为详情（含 recent_heartbeats）。

    Raises:
        BusinessException: 404 设备不存在。
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise BusinessException(404, "设备不存在")
    data: dict[str, Any] = {
        "id": device.id,
        "device_no": device.device_no,
        "name": device.name,
        "type": device.type,
        "plot_id": device.plot_id,
        "plot_name": device.plot.name if device.plot else None,
        "protocol": device.protocol,
        "vendor": device.vendor,
        "collect_schedule": device.collect_schedule,
        "config": device.config,
        "status": device.status,
        "last_heartbeat_at": fmt_datetime(device.last_heartbeat_at),
        "recent_heartbeats": get_recent_heartbeats(db, device.id, limit=50),
    }
    return ok(data)


@router.post("/{device_id}/heartbeat", summary="设备心跳上报")
def device_heartbeat(device_id: int, db: Session = Depends(get_db)) -> dict:
    """设备心跳上报：刷新在线状态、最近心跳时间并记录心跳日志。

    Args:
        device_id: 设备ID。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {device_id, status, last_heartbeat_at}。

    Raises:
        BusinessException: 404 设备不存在。
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise BusinessException(404, "设备不存在")
    return ok(report_heartbeat(db, device))


@router.post("/{device_id}/config", summary="设备远程配置下发")
def update_device_config(device_id: int, body: DeviceConfigRequest, db: Session = Depends(get_db)) -> dict:
    """更新设备远程配置（config JSON 覆盖保存）。

    Args:
        device_id: 设备ID。
        body: 配置下发请求体 {config}。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, config}。

    Raises:
        BusinessException: 404 设备不存在。
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise BusinessException(404, "设备不存在")
    device.config = body.config
    db.commit()
    return ok({"id": device.id, "config": device.config})


@router.post("/{device_id}/report", summary="传感器数据上报（含越限判定）")
def device_report(device_id: int, body: SensorReportRequest, db: Session = Depends(get_db)) -> dict:
    """环境传感器数据上报：入库 sensor_reading 并执行环境越限判定。

    越限时生成/合并 env 预警（case_key=plot:{id}:env:{metric}）；
    恢复正常时自动解决对应 active 预警并记录 recovered_at。

    Args:
        device_id: 设备ID（须为 env_sensor 类型）。
        body: 上报请求体 {readings:[{metric,value,unit?,reported_at?}]}。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {device_id, results:[逐条判定]}。

    Raises:
        BusinessException: 404 设备不存在；400 设备类型或指标非法。
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise BusinessException(404, "设备不存在")
    if device.type != "env_sensor":
        raise BusinessException(400, "仅环境传感器（env_sensor）支持数据上报")
    results = save_readings_and_check(db, device, [item.model_dump() for item in body.readings])
    return ok({"device_id": device.id, "results": results})
