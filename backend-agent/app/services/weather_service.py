"""和风天气（QWeather）气象服务模块。

职责（对应 PRD「气象灾害预警」与「水肥建议/每日简报的气象数据源」）：
- 7 天预报拉取：GET /v7/weather/7d（location=经度,纬度），
  逐日写入 weather_forecast_cache（data_json 字段与 advisory_service
  消费约定对齐：condition / precipitation_mm / temp_low）；
- 气象灾害预警拉取：新版实时天气预警 v1 —— GET /weatheralert/v1/current/{纬度}/{经度}
  （v7 /warning/now 已于 2026-10-01 停服），命中即经 create_or_merge_alert
  生成/合并 weather 类型预警（大棚地块附棚体风险提示，PRD 6.1）。

接口约定（新版统一专属 API Host）：
- 天气预报：{host}/v7/weather/7d?location=lon,lat
- 城市查询：{host}/geo/v2/city/lookup（注意 /geo 前缀）
- 实时预警：{host}/weatheralert/v1/current/{lat:.2f}/{lon:.2f}
- 鉴权：请求头 X-QW-Api-Key（.env 中 WEATHER_API_KEY）

坐标来源优先级：地块选点坐标 → 全局默认位置 WEATHER_DEFAULT_LOCATION
（"经度,纬度" 或 城市名，用于棚室等无坐标地块——棚室登记不含地图选点）。
坐标按 plot_id 进程内缓存，避免重复解析。
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.advice import WeatherForecastCache
from app.models.plot import Plot
from app.services.alert_service import create_or_merge_alert
from app.utils.time_utils import now

logger = logging.getLogger("farm_weather")

# 请求超时（秒）
TIMEOUT = 15.0
# 坐标进程内缓存：plot_id -> (lon, lat)
_COORDS_CACHE: dict[int, tuple[float, float]] = {}
# 新版预警 severity → 系统预警等级映射
_SEVERITY_LEVEL = {"minor": "info", "moderate": "warning", "severe": "critical", "extreme": "critical"}


def _headers() -> dict[str, str]:
    """构造和风天气鉴权请求头。

    Returns:
        dict[str, str]: 含 X-QW-Api-Key 的请求头。

    Raises:
        ValueError: 未配置 API Key 时抛出，由上层捕获记日志。
    """
    if not settings.weather_api_key:
        raise ValueError("未配置 WEATHER_API_KEY，跳过气象拉取")
    return {"X-QW-Api-Key": settings.weather_api_key}


def _lookup_city_coords(location: str) -> tuple[float, float] | None:
    """通过 GeoAPI 城市查询解析城市名/坐标串为中心坐标。

    Args:
        location: 城市名（如"北京"）或 "lng,lat" 坐标串。

    Returns:
        tuple[float, float] | None: (lon, lat)，查询失败返回 None。
    """
    resp = httpx.get(
        f"{settings.weather_geo_host}/geo/v2/city/lookup",
        params={"location": location, "number": 1},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != "200" or not body.get("location"):
        logger.warning("GeoAPI 城市查询失败: code=%s", body.get("code"))
        return None
    hit = body["location"][0]
    return float(hit["lon"]), float(hit["lat"])


def _resolve_coords(plot: Plot) -> tuple[float, float] | None:
    """解析地块坐标（lon, lat），带进程内缓存。

    优先地块选点坐标；无坐标棚室回退到全局默认位置配置。

    Args:
        plot: 地块 ORM 实例。

    Returns:
        tuple[float, float] | None: (lon, lat)；无法解析返回 None。
    """
    if plot.id in _COORDS_CACHE:
        return _COORDS_CACHE[plot.id]
    coords: tuple[float, float] | None = None
    if plot.lng is not None and plot.lat is not None:
        coords = (float(plot.lng), float(plot.lat))
    elif settings.weather_default_location:
        default = settings.weather_default_location.strip()
        if re.fullmatch(r"-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?", default):
            lon_s, lat_s = default.split(",")
            coords = (float(lon_s), float(lat_s))
        else:
            coords = _lookup_city_coords(default)
    if coords is None:
        logger.warning(
            "地块 %s(%s) 无坐标且未配置 WEATHER_DEFAULT_LOCATION，跳过气象拉取",
            plot.id, plot.name,
        )
        return None
    _COORDS_CACHE[plot.id] = coords
    return coords


def _upsert_cache(db: Session, plot_id: int, forecast_date: date, data_json: dict[str, Any]) -> None:
    """按 (plot, data_type, forecast_date) 唯一键更新或插入缓存行。

    Args:
        db: 数据库会话（本函数 commit）。
        plot_id: 地块ID。
        forecast_date: 预报目标日。
        data_json: 逐日数据体。
    """
    row = (
        db.query(WeatherForecastCache)
        .filter(
            WeatherForecastCache.plot_id == plot_id,
            WeatherForecastCache.data_type == "weather_forecast",
            WeatherForecastCache.forecast_date == forecast_date,
        )
        .first()
    )
    if row is None:
        row = WeatherForecastCache(
            plot_id=plot_id,
            data_type="weather_forecast",
            forecast_date=forecast_date,
        )
        db.add(row)
    row.data_json = data_json
    row.source_api = "qweather"
    row.fetched_at = now()


def fetch_forecast_for_plot(db: Session, plot: Plot) -> int:
    """拉取单个地块未来 7 天预报并写入缓存。

    Args:
        db: 数据库会话（本函数 commit）。
        plot: 地块 ORM 实例。

    Returns:
        int: 写入缓存的逐日条数（无法定位坐标返回 0）。

    Raises:
        ValueError: 未配置 API Key / 接口返回非 200 code。
        httpx.HTTPError: 网络异常。
    """
    coords = _resolve_coords(plot)
    if coords is None:
        return 0
    lon, lat = coords
    resp = httpx.get(
        f"{settings.weather_api_host}/v7/weather/7d",
        params={"location": f"{lon:.2f},{lat:.2f}"},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != "200":
        raise ValueError(f"和风天气 7d 接口返回 code={body.get('code')}")

    count = 0
    for day in body.get("daily", []):
        forecast_date = date.fromisoformat(day["fxDate"])
        data_json = {
            "condition": day.get("textDay", ""),
            "temp_high": _to_float(day.get("tempMax")),
            "temp_low": _to_float(day.get("tempMin")),
            "precipitation_mm": _to_float(day.get("precip")),
            "wind_dir": day.get("windDirDay", ""),
            "wind_scale": day.get("windScaleDay", ""),
            "humidity": _to_float(day.get("humidity")),
        }
        _upsert_cache(db, plot.id, forecast_date, data_json)
        count += 1
    db.commit()
    return count


def fetch_warnings_for_plot(db: Session, plot: Plot) -> int:
    """拉取单个地块所在区域的实时气象灾害预警（新版 v1 接口），命中则生成/合并预警。

    大棚地块在预警内容中附加棚体风险提示（PRD 6.1：大棚加棚体风险提示）。
    messageType=cancel 的预警取消通知不创建新预警。

    Args:
        db: 数据库会话（本函数 commit）。
        plot: 地块 ORM 实例。

    Returns:
        int: 本次命中的预警条数（无法定位坐标返回 0）。

    Raises:
        ValueError: 未配置 API Key / 接口返回异常。
        httpx.HTTPError: 网络异常。
    """
    coords = _resolve_coords(plot)
    if coords is None:
        return 0
    lon, lat = coords
    resp = httpx.get(
        f"{settings.weather_api_host}/weatheralert/v1/current/{lat:.2f}/{lon:.2f}",
        params={"lang": "zh"},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("metadata", {}).get("zeroResult"):
        return 0

    count = 0
    for item in body.get("alerts", []):
        if item.get("messageType", {}).get("code") == "cancel":
            continue  # 预警取消通知不作为新预警
        alert_id = item.get("id") or item.get("headline", "unknown")
        severity = item.get("severity", "moderate")
        title = item.get("headline") or f"{plot.name}气象预警"
        content: dict[str, Any] = {
            "type": (item.get("eventType") or {}).get("name", "气象灾害"),
            "text": item.get("description", ""),
            "instruction": item.get("instruction", ""),
            "severity": severity,
            "color": (item.get("color") or {}).get("code", ""),
            "sender": item.get("senderName", ""),
            "issued_time": item.get("issuedTime", ""),
            "expire_time": item.get("expireTime", ""),
            "source": "qweather",
        }
        if plot.type == "greenhouse":
            content["greenhouse_risk"] = (
                "大棚棚体风险提示：检查压膜线与骨架牢固度，大风前加固卷帘并关闭风口，"
                "暴雪/暴雨前清理棚顶排水，必要时增设临时支撑。"
            )
        create_or_merge_alert(
            db,
            plot_id=plot.id,
            alert_type="weather",
            case_key=f"plot:{plot.id}:weather:{alert_id}",
            title=title,
            content=content,
            level=_SEVERITY_LEVEL.get(severity, "warning"),
        )
        count += 1
    return count


def refresh_all_plots(db: Session) -> dict[str, int]:
    """为全部在种地块刷新气象预报与灾害预警（定时任务入口）。

    单地块失败仅记日志，不阻塞其余地块。

    Args:
        db: 数据库会话。

    Returns:
        dict[str, int]: 统计 {forecast_plots, warning_hits, failed}。
    """
    stats = {"forecast_plots": 0, "warning_hits": 0, "failed": 0}
    plots = db.query(Plot).filter(Plot.status == 1).all()
    for plot in plots:
        try:
            if fetch_forecast_for_plot(db, plot) > 0:
                stats["forecast_plots"] += 1
            stats["warning_hits"] += fetch_warnings_for_plot(db, plot)
        except Exception as exc:  # noqa: BLE001 单地块失败不阻塞整体
            stats["failed"] += 1
            logger.warning("气象刷新失败（plot=%s %s）: %s", plot.id, plot.name, exc)
    return stats


def _to_float(value: Any) -> float | None:
    """安全转 float，空值返回 None（advisory 消费端按空处理）。"""
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
