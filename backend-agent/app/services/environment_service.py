"""环境监测业务服务模块。

提供传感器数据上报入库 + 环境越限判定（生成/合并 env 预警、恢复自动解决）、
实时值查询、趋势聚合与告警记录查询。
"""
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.advice import EnvironmentThresholdConfig
from app.models.alert import Alert
from app.models.device import Device
from app.models.plot import Plot
from app.models.sensor import SensorReading
from app.services.alert_service import create_or_merge_alert
from app.services.plot_service import get_effective_thresholds
from app.utils.time_utils import fmt_datetime, now

logger = logging.getLogger("farm_env")

# 环境指标合法清单与默认单位
VALID_METRICS = {
    "temp": "℃",
    "humidity": "%RH",
    "light": "klx",
    "soil_moisture": "%",
}

# 越限方向标记
_EXCEEDED_HIGH = "high"
_EXCEEDED_LOW = "low"


def save_readings_and_check(db: Session, device: Device,
                            readings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保存传感器读数并执行环境越限判定。

    每条读数入库 sensor_reading；temp/humidity/soil_moisture 参与阈值比对：
    - 越限 → create_or_merge_alert（case_key=plot:{id}:env:{metric}，时间线追加）；
    - 正常 → 若该指标存在 active env 预警则置 resolved（content 记录 recovered_at）。

    Args:
        db: 数据库会话（本函数 commit）。
        device: 上报设备（须为 env_sensor 类型且归属地块）。
        readings: [{metric, value, unit?, reported_at?}] 列表。

    Returns:
        list[dict]: 逐条判定结果 [{metric, value, exceeded, direction, threshold}]。

    Raises:
        BusinessException: 400 指标非法或设备无归属地块。
    """
    if device.plot_id is None:
        raise BusinessException(400, "设备未绑定地块，无法上报环境数据")
    plot = db.query(Plot).filter(Plot.id == device.plot_id).first()
    if plot is None:
        raise BusinessException(404, "设备绑定的地块不存在")

    thresholds = {config.metric: config for config in get_effective_thresholds(db, plot)}
    current_time = now()
    results: list[dict[str, Any]] = []

    for item in readings:
        metric = str(item.get("metric", "")).strip()
        if metric not in VALID_METRICS:
            raise BusinessException(400, f"不支持的环境指标: {metric}")
        value = float(item["value"])
        unit = str(item.get("unit") or VALID_METRICS[metric])
        reported_at_raw = item.get("reported_at")
        reported_at = (
            datetime.fromisoformat(str(reported_at_raw))
            if reported_at_raw
            else current_time
        )
        db.add(
            SensorReading(
                device_id=device.id,
                plot_id=plot.id,
                metric=metric,
                value=value,
                unit=unit,
                reported_at=reported_at,
            )
        )

        config = thresholds.get(metric)
        exceeded: Optional[str] = None
        max_value = float(config.max_value) if config is not None and config.max_value is not None else None
        min_value = float(config.min_value) if config is not None and config.min_value is not None else None
        if max_value is not None and value > max_value:
            exceeded = _EXCEEDED_HIGH
        elif min_value is not None and value < min_value:
            exceeded = _EXCEEDED_LOW

        threshold_payload = {"max": max_value, "min": min_value}
        if exceeded is not None:
            _raise_env_alert(db, plot, metric, value, threshold_payload, exceeded, current_time)
        else:
            _resolve_env_alert(db, plot.id, metric, value, current_time)
        results.append(
            {
                "metric": metric,
                "value": value,
                "exceeded": exceeded is not None,
                "direction": exceeded,
                "threshold": threshold_payload,
                "reported_at": fmt_datetime(reported_at),
            }
        )

    # 上报即刷新设备在线状态
    device.status = "online"
    device.last_heartbeat_at = current_time
    db.commit()
    return results


def _raise_env_alert(db: Session, plot: Plot, metric: str, value: float,
                     threshold: dict[str, Any], direction: str, trigger_time: datetime) -> None:
    """生成或合并环境越限预警。

    Args:
        db: 数据库会话。
        plot: 地块实例。
        metric: 指标名。
        value: 越限值。
        threshold: {max, min} 阈值。
        direction: 越限方向 high/low。
        trigger_time: 触发时间。
    """
    direction_text = "高于上限" if direction == _EXCEEDED_HIGH else "低于下限"
    bound = threshold["max"] if direction == _EXCEEDED_HIGH else threshold["min"]
    create_or_merge_alert(
        db=db,
        plot_id=plot.id,
        alert_type="env",
        case_key=f"plot:{plot.id}:env:{metric}",
        title=f"{plot.name} {metric} 越限（{value}{VALID_METRICS[metric]} {direction_text} {bound}）",
        content={
            "metric": metric,
            "value": value,
            "unit": VALID_METRICS[metric],
            "threshold": threshold,
            "direction": direction,
            "latest_reported_at": fmt_datetime(trigger_time),
        },
        level="warning",
    )


def _resolve_env_alert(db: Session, plot_id: int, metric: str, value: float, resolve_time: datetime) -> None:
    """环境值恢复正常时自动解决对应 active 预警（记录 recovered_at）。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。
        metric: 指标名。
        value: 恢复后的正常值。
        resolve_time: 恢复时间。
    """
    active = (
        db.query(Alert)
        .filter(
            Alert.case_key == f"plot:{plot_id}:env:{metric}",
            Alert.status == "active",
        )
        .first()
    )
    if active is None:
        return
    active.status = "resolved"
    active.resolved_at = resolve_time
    content = dict(active.content or {})
    content["recovered_at"] = fmt_datetime(resolve_time)
    content["recovered_value"] = value
    updates = content.get("updates", [])
    updates.append(
        {
            "time": resolve_time.isoformat(),
            "event": "恢复正常",
            "content": {"metric": metric, "value": value},
        }
    )
    content["updates"] = updates
    active.content = content
    logger.info("环境预警恢复: plot=%s metric=%s", plot_id, metric)


def get_realtime(db: Session, plot_id: int) -> dict[str, Any]:
    """查询地块实时环境值与越限判定。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。

    Returns:
        dict: {plot_id, plot_name, metrics:{metric:{value,unit,exceeded,threshold,last_reported_at}}}。

    Raises:
        BusinessException: 404 地块不存在。
    """
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    thresholds = {config.metric: config for config in get_effective_thresholds(db, plot)}
    metrics: dict[str, Any] = {}
    for metric, unit in VALID_METRICS.items():
        reading = (
            db.query(SensorReading)
            .filter(SensorReading.plot_id == plot_id, SensorReading.metric == metric)
            .order_by(SensorReading.reported_at.desc())
            .first()
        )
        config = thresholds.get(metric)
        max_value = float(config.max_value) if config is not None and config.max_value is not None else None
        min_value = float(config.min_value) if config is not None and config.min_value is not None else None
        value = float(reading.value) if reading is not None else None
        exceeded = None
        if value is not None:
            if max_value is not None and value > max_value:
                exceeded = _EXCEEDED_HIGH
            elif min_value is not None and value < min_value:
                exceeded = _EXCEEDED_LOW
        metrics[metric] = {
            "value": value,
            "unit": unit,
            "exceeded": exceeded,
            "threshold": {"max": max_value, "min": min_value},
            "last_reported_at": fmt_datetime(reading.reported_at) if reading is not None else None,
        }
    return {"plot_id": plot.id, "plot_name": plot.name, "metrics": metrics}


def get_trend(db: Session, plot_id: int, range_key: str = "24h") -> dict[str, Any]:
    """查询地块环境趋势（按小时/天粒度取均值）。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。
        range_key: 时间范围 24h（逐小时 24 点）/ 7d（逐天 7 点）。

    Returns:
        dict: {range, times, series:{temp, humidity, soil_moisture}}。

    Raises:
        BusinessException: 400 range 非法。
    """
    if range_key not in ("24h", "7d"):
        raise BusinessException(400, "range 仅支持 24h/7d")
    current_time = now()
    if range_key == "24h":
        start_time = current_time - timedelta(hours=24)
        # 逐小时聚合：DATE_FORMAT 到小时
        fmt = "%Y-%m-%d %H:00:00"
        point_count = 24
    else:
        start_time = current_time - timedelta(days=7)
        fmt = "%Y-%m-%d"
        point_count = 7

    rows = (
        db.query(
            func.date_format(SensorReading.reported_at, fmt).label("bucket"),
            SensorReading.metric,
            func.avg(SensorReading.value).label("avg_value"),
        )
        .filter(
            SensorReading.plot_id == plot_id,
            SensorReading.reported_at >= start_time,
            SensorReading.metric.in_(["temp", "humidity", "soil_moisture"]),
        )
        .group_by("bucket", SensorReading.metric)
        .all()
    )
    bucket_data: dict[str, dict[str, float]] = {}
    for bucket, metric, avg_value in rows:
        bucket_data.setdefault(str(bucket), {})[metric] = round(float(avg_value), 1)

    # 生成完整时间轴（缺失补 None）
    times: list[str] = []
    series: dict[str, list[Optional[float]]] = {"temp": [], "humidity": [], "soil_moisture": []}
    if range_key == "24h":
        for offset in range(point_count, 0, -1):
            point = (current_time - timedelta(hours=offset - 1)).replace(minute=0, second=0, microsecond=0)
            key = point.strftime("%Y-%m-%d %H:00:00")
            _append_point(times, series, key, bucket_data)
    else:
        for offset in range(point_count - 1, -1, -1):
            point = (current_time - timedelta(days=offset)).date()
            key = point.strftime("%Y-%m-%d")
            _append_point(times, series, key, bucket_data)
    return {"range": range_key, "times": times, "series": series}


def _append_point(times: list[str], series: dict[str, list[Optional[float]]],
                  key: str, bucket_data: dict[str, dict[str, float]]) -> None:
    """向趋势时间轴追加一个数据点（缺失补 None）。

    Args:
        times: 时间轴列表（就地追加）。
        series: 指标序列字典（就地追加）。
        key: 时间桶键。
        bucket_data: 聚合查询结果。
    """
    times.append(key)
    values = bucket_data.get(key, {})
    for metric in ("temp", "humidity", "soil_moisture"):
        series[metric].append(values.get(metric))


def get_alarm_records(db: Session, plot_id: int) -> list[dict[str, Any]]:
    """查询地块环境越限告警记录（env 类型预警）。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。

    Returns:
        list[dict]: [{id, metric, value, threshold, direction, status,
                      triggered_at, recovered_at, occurrence_count}]。
    """
    rows = (
        db.query(Alert)
        .filter(Alert.plot_id == plot_id, Alert.type == "env")
        .order_by(Alert.first_triggered_at.desc())
        .limit(50)
        .all()
    )
    records = []
    for alert in rows:
        content = alert.content or {}
        records.append(
            {
                "id": alert.id,
                "metric": content.get("metric"),
                "value": content.get("value"),
                "unit": content.get("unit"),
                "threshold": content.get("threshold"),
                "direction": content.get("direction"),
                "level": alert.level,
                "status": alert.status,
                "occurrence_count": alert.occurrence_count,
                "triggered_at": fmt_datetime(alert.first_triggered_at),
                "recovered_at": content.get("recovered_at") or (
                    fmt_datetime(alert.resolved_at) if alert.resolved_at else None
                ),
            }
        )
    return records
