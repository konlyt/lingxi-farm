"""农场总览聚合业务服务模块。

聚合采收禁令横幅、地块实况卡片、今日待办、最新预警与今日天气，
供 GET /api/overview 一次返回首屏全部数据。
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.advice import WaterFertilizerAdvice, WeatherForecastCache
from app.models.alert import Alert
from app.models.image import CollectedImage
from app.models.diagnosis import DiagnosisResult, DiagnosisTask, DiagnosisTaskImage
from app.models.plot import Plot
from app.services.plot_service import (
    get_active_restrictions,
    get_latest_env,
)
from app.utils.time_utils import fmt_date, fmt_datetime, today


def _get_latest_image_info(db: Session, plot_id: int) -> dict[str, Any] | None:
    """查询地块最新一张采集图像及其 AI 诊断标注。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。

    Returns:
        dict | None: {url, ai_label, confidence, source, captured_at}；无图像返回 None。
    """
    image = (
        db.query(CollectedImage)
        .filter(CollectedImage.plot_id == plot_id)
        .order_by(CollectedImage.captured_at.desc(), CollectedImage.id.desc())
        .first()
    )
    if image is None:
        return None

    ai_label: str | None = None
    confidence: float | None = None
    # 查询该图像参与的最新诊断任务的融合结果（有诊断链路数据时返回）
    task_row = (
        db.query(DiagnosisTask)
        .join(DiagnosisTaskImage, DiagnosisTaskImage.task_id == DiagnosisTask.id)
        .filter(DiagnosisTaskImage.image_id == image.id)
        .order_by(DiagnosisTask.created_at.desc())
        .first()
    )
    if task_row is not None:
        fused = (
            db.query(DiagnosisResult)
            .filter(DiagnosisResult.task_id == task_row.id, DiagnosisResult.model_path == "fused")
            .order_by(DiagnosisResult.created_at.desc())
            .first()
        )
        if fused is not None:
            ai_label = fused.disease_name
            confidence = float(fused.confidence)

    return {
        "url": image.cos_url,
        "ai_label": ai_label,
        "confidence": confidence,
        "source": image.source,
        "captured_at": fmt_datetime(image.captured_at),
    }


def get_overview(db: Session) -> dict[str, Any]:
    """组装农场总览首屏数据。

    Args:
        db: 数据库会话。

    Returns:
        dict: {harvest_banners, plot_cards, today_todos, latest_alerts, weather}。
    """
    current_date = today()
    plots = db.query(Plot).filter(Plot.status == 1).order_by(Plot.id.asc()).all()

    # 1) 采收禁令横幅（全部在种地块的 active 禁令）
    harvest_banners: list[dict[str, Any]] = []
    plot_cards: list[dict[str, Any]] = []
    for plot in plots:
        restrictions = get_active_restrictions(db, plot.id)
        for restriction in restrictions:
            harvest_banners.append(
                {
                    "plot_id": plot.id,
                    "plot_name": plot.name,
                    "ban_until": restriction["ban_until"],
                    "pesticide_name": restriction["pesticide_name"],
                }
            )
        # 2) 地块实况卡片
        plot_cards.append(
            {
                "id": plot.id,
                "name": plot.name,
                "type": plot.type,
                "crop_name": plot.crop_name,
                "growth_stage": plot.growth_stage,
                "latest_env": get_latest_env(db, plot.id),
                "latest_image": _get_latest_image_info(db, plot.id),
                "has_active_restriction": len(restrictions) > 0,
            }
        )

    # 3) 今日待办：读取当日水肥建议（无则空数组）
    today_todos: list[dict[str, Any]] = []
    advice_rows = (
        db.query(WaterFertilizerAdvice, Plot.name)
        .join(Plot, WaterFertilizerAdvice.plot_id == Plot.id)
        .filter(WaterFertilizerAdvice.advice_date == current_date)
        .all()
    )
    for advice, plot_name in advice_rows:
        advice_data = advice.advice_json or {}
        today_todos.append(
            {
                "plot_id": advice.plot_id,
                "plot_name": plot_name,
                "title": advice_data.get("title", "水肥建议"),
                "content": advice_data.get("summary", ""),
            }
        )

    # 4) 最新预警：未解决（active）前 5 条
    alert_rows = (
        db.query(Alert)
        .filter(Alert.status == "active")
        .order_by(Alert.first_triggered_at.desc())
        .limit(5)
        .all()
    )
    latest_alerts = [
        {
            "id": alert.id,
            "type": alert.type,
            "level": alert.level,
            "plot_id": alert.plot_id,
            "title": alert.title,
            "occurrence_count": alert.occurrence_count,
            "first_triggered_at": fmt_datetime(alert.first_triggered_at),
        }
        for alert in alert_rows
    ]

    # 5) 今日天气：weather_forecast_cache 中当日数据
    weather_rows = (
        db.query(WeatherForecastCache, Plot.name)
        .join(Plot, WeatherForecastCache.plot_id == Plot.id)
        .filter(
            WeatherForecastCache.data_type == "weather_forecast",
            WeatherForecastCache.forecast_date == current_date,
        )
        .all()
    )
    weather_items = []
    for cache_row, plot_name in weather_rows:
        data = cache_row.data_json or {}
        weather_items.append(
            {
                "plot_id": cache_row.plot_id,
                "plot_name": plot_name,
                "condition": data.get("condition"),
                "temp_high": data.get("temp_high"),
                "temp_low": data.get("temp_low"),
                "precipitation_mm": data.get("precipitation_mm"),
                "wind": data.get("wind"),
            }
        )
    weather = {"date": fmt_date(current_date), "items": weather_items}

    return {
        "harvest_banners": harvest_banners,
        "plot_cards": plot_cards,
        "today_todos": today_todos,
        "latest_alerts": latest_alerts,
        "weather": weather,
    }
