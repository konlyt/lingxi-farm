"""决策建议业务服务模块。

提供水肥建议（种植决策智能体生成，uk_plot_date 幂等）、
大棚环境调控建议（未来 12 小时）与每日农情简报生成/查询。
生成链路经 LangGraph advice 意图（DeepSeek 严格 JSON 输出）。
"""
import logging
from datetime import date as date_type
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agents.graph import build_farm_graph
from app.core.response import BusinessException
from app.models.advice import DailyBrief, WaterFertilizerAdvice, WeatherForecastCache
from app.models.alert import Alert
from app.models.plot import Plot
from app.services.plot_service import get_latest_env
from app.utils.time_utils import fmt_date, now, today

logger = logging.getLogger("farm_advice")


def generate_water_fertilizer(db: Session, plot_id: int) -> dict[str, Any]:
    """手动触发生成地块当日水肥建议（经种植决策智能体）。

    无墒情数据时智能体输入含降级标注（data_fallback_flag=1）；
    气象数据使用 weather_forecast_cache 缓存并标注 fetched_at。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。

    Returns:
        dict: 建议卡 {summary, items, risk_notes, data_fallback_flag}。

    Raises:
        BusinessException: 404 地块不存在；502 智能体生成失败。
    """
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    graph = build_farm_graph(db)
    try:
        state = graph.invoke(
            {
                "intent": "advice",
                "advice_kind": "water_fertilizer",
                "plot_id": plot_id,
                "thread_id": f"advice-wf-{plot_id}-{today().isoformat()}",
            }
        )
    except Exception as exc:  # noqa: BLE001 智能体失败转为业务异常
        logger.exception("水肥建议生成失败: plot=%s err=%s", plot_id, exc)
        raise BusinessException(502, f"种植决策智能体生成失败：{exc}")
    if state.get("error"):
        raise BusinessException(502, f"种植决策智能体生成失败：{state['error']}")
    result = state.get("advice_result", {})
    return {
        "plot_id": plot_id,
        "plot_name": plot.name,
        "advice_date": fmt_date(today()),
        "summary": result.get("summary"),
        "items": result.get("items", []),
        "risk_notes": result.get("risk_notes"),
        "data_fallback_flag": result.get("data_fallback_flag", 0),
    }


def get_water_fertilizer(db: Session, plot_id: int, query_date: Optional[str] = None) -> dict[str, Any]:
    """查询地块某日水肥建议（uk_plot_date 每日一条）。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。
        query_date: 查询日期 YYYY-MM-DD（空则当天）。

    Returns:
        dict: {plot_id, advice_date, items(7天逐日), basis_json, data_fallback_flag, push_status}；
              无记录时 data 为 None。

    Raises:
        BusinessException: 404 地块不存在或日期格式非法。
    """
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    try:
        target = date_type.fromisoformat(query_date) if query_date else today()
    except ValueError as exc:
        raise BusinessException(400, f"日期格式非法: {query_date}") from exc
    advice = (
        db.query(WaterFertilizerAdvice)
        .filter(WaterFertilizerAdvice.plot_id == plot_id, WaterFertilizerAdvice.advice_date == target)
        .first()
    )
    if advice is None:
        return {"plot_id": plot_id, "plot_name": plot.name, "advice_date": fmt_date(target), "data": None}
    advice_data = advice.advice_json or {}
    return {
        "plot_id": plot_id,
        "plot_name": plot.name,
        "advice_date": advice.advice_date.isoformat(),
        "data": {
            "summary": advice_data.get("summary"),
            "items": advice_data.get("items", []),
            "risk_notes": advice_data.get("risk_notes"),
            "basis_json": advice.basis_json,
            "data_fallback_flag": advice.data_fallback_flag,
            "horizon_days": advice.horizon_days,
            "push_status": advice.push_status,
            "created_at": advice.created_at.isoformat() if advice.created_at else None,
        },
    }


def get_environment_advice(db: Session, plot_id: int) -> dict[str, Any]:
    """生成/查询大棚未来 12 小时环境调控建议（仅大棚，露天空结果）。

    Args:
        db: 数据库会话。
        plot_id: 地块ID。

    Returns:
        dict: {plot_id, plot_name, items:[{time_range, action, reason}]}。

    Raises:
        BusinessException: 404 地块不存在；502 智能体失败。
    """
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    if plot is None:
        raise BusinessException(404, "地块不存在")
    if plot.type != "greenhouse":
        return {"plot_id": plot_id, "plot_name": plot.name, "items": [], "note": "露天地块无棚室调控建议"}
    graph = build_farm_graph(db)
    try:
        state = graph.invoke(
            {
                "intent": "advice",
                "advice_kind": "environment_control",
                "plot_id": plot_id,
                "thread_id": f"advice-env-{plot_id}-{now().strftime('%Y%m%d%H%M')}",
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("调控建议生成失败: plot=%s err=%s", plot_id, exc)
        raise BusinessException(502, f"环境调控智能体生成失败：{exc}")
    result = state.get("advice_result", {})
    return {"plot_id": plot_id, "plot_name": plot.name, "items": result.get("items", [])}


def generate_daily_brief(db: Session, brief_date: Optional[date_type] = None) -> DailyBrief:
    """生成每日农情简报：各地块实况摘要 + 今日待办 + 天气提醒。

    Args:
        db: 数据库会话。
        brief_date: 简报日期（空则今天）。

    Returns:
        DailyBrief: 简报 ORM 实例（uk_brief_date 幂等，已存在则更新）。
    """
    target = brief_date or today()
    plots = db.query(Plot).filter(Plot.status == 1).all()
    plot_summaries = []
    todos = []
    weather_reminders = []
    for plot in plots:
        env = get_latest_env(db, plot.id)
        active_alerts = (
            db.query(Alert)
            .filter(Alert.plot_id == plot.id, Alert.status == "active")
            .count()
        )
        plot_summaries.append(
            {
                "plot_id": plot.id,
                "plot_name": plot.name,
                "crop": f"{plot.crop_name}（{plot.growth_stage}）",
                "env": env,
                "active_alerts": active_alerts,
            }
        )
        # 今日待办：当日水肥建议
        advice = (
            db.query(WaterFertilizerAdvice)
            .filter(WaterFertilizerAdvice.plot_id == plot.id, WaterFertilizerAdvice.advice_date == target)
            .first()
        )
        if advice is not None:
            advice_data = advice.advice_json or {}
            todos.append(
                {
                    "plot_id": plot.id,
                    "plot_name": plot.name,
                    "irrigate": advice_data.get("items", [{}])[0].get("irrigate") if advice_data.get("items") else None,
                    "fertilize": advice_data.get("items", [{}])[0].get("fertilize") if advice_data.get("items") else None,
                }
            )
        # 天气提醒：降水/低温/大风
        weather = (
            db.query(WeatherForecastCache)
            .filter(
                WeatherForecastCache.plot_id == plot.id,
                WeatherForecastCache.data_type == "weather_forecast",
                WeatherForecastCache.forecast_date == target,
            )
            .first()
        )
        if weather is not None:
            data = weather.data_json or {}
            reminder = None
            if (data.get("precipitation_mm") or 0) > 0:
                reminder = f"{plot.name}今日有降水（{data.get('condition')} {data.get('precipitation_mm')}mm）"
            elif (data.get("temp_low") or 99) <= 5:
                reminder = f"{plot.name}今日低温（{data.get('temp_low')}℃）注意防寒"
            if reminder:
                weather_reminders.append(reminder)

    content = {
        "plot_summaries": plot_summaries,
        "today_todos": todos,
        "weather_reminders": weather_reminders,
    }
    brief = db.query(DailyBrief).filter(DailyBrief.brief_date == target).first()
    if brief is None:
        brief = DailyBrief(brief_date=target, content=content, push_status="sent", pushed_at=now())
        db.add(brief)
    else:
        brief.content = content
        brief.push_status = "sent"
        brief.pushed_at = now()
    db.commit()
    logger.info("每日简报已生成: date=%s", target)
    return brief


def get_daily_brief(db: Session, query_date: Optional[str] = None) -> dict[str, Any]:
    """查询每日农情简报。

    Args:
        db: 数据库会话。
        query_date: 查询日期 YYYY-MM-DD（空则当天）。

    Returns:
        dict: {date, content, push_status, pushed_at}；无记录 data 为 None。

    Raises:
        BusinessException: 400 日期格式非法。
    """
    try:
        target = date_type.fromisoformat(query_date) if query_date else today()
    except ValueError as exc:
        raise BusinessException(400, f"日期格式非法: {query_date}") from exc
    brief = db.query(DailyBrief).filter(DailyBrief.brief_date == target).first()
    if brief is None:
        return {"date": fmt_date(target), "data": None}
    return {
        "date": brief.brief_date.isoformat(),
        "data": {
            "content": brief.content,
            "push_status": brief.push_status,
            "pushed_at": brief.pushed_at.isoformat() if brief.pushed_at else None,
        },
    }
