"""农事日历业务服务模块。

按地块作物 + 定植/播种日期，基于简单规则表推算关键农事节点，
支撑日历视图与 upcoming 30 天提醒列表。
"""
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.response import BusinessException
from app.models.plot import Plot

# 农事规则表：作物 → [(定植后偏移天数, 事项标题, 类型)]
# 类型：plant 定植 / irrigate 灌溉 / fertilize 施肥 / pestcontrol 病虫防治 /
#       farmwork 田间管理 / harvest 采收
FARMWORK_RULES: dict[str, list[tuple[int, str, str]]] = {
    "番茄": [
        (0, "定植/移栽", "plant"),
        (7, "浇缓苗水", "irrigate"),
        (15, "轻施提苗肥", "fertilize"),
        (25, "搭架绑蔓", "farmwork"),
        (35, "第一穗花坐果追肥", "fertilize"),
        (45, "重点巡查早疫病/晚疫病", "pestcontrol"),
        (60, "始收（依品种）", "harvest"),
        (75, "盛果期水肥管理", "fertilize"),
        (100, "拉秧清园消毒", "farmwork"),
    ],
    "黄瓜": [
        (0, "定植/移栽", "plant"),
        (5, "浇缓苗水", "irrigate"),
        (15, "吊蔓整枝", "farmwork"),
        (25, "根瓜坐住追肥", "fertilize"),
        (30, "重点巡查白粉病/霜霉病", "pestcontrol"),
        (40, "始收", "harvest"),
        (60, "盛瓜期水肥管理", "fertilize"),
        (90, "拉秧清园消毒", "farmwork"),
    ],
    "玉米": [
        (0, "播种", "plant"),
        (10, "查苗补种", "farmwork"),
        (20, "间苗定苗", "farmwork"),
        (30, "拔节期追肥", "fertilize"),
        (45, "大喇叭口期防玉米螟", "pestcontrol"),
        (60, "抽雄吐丝期灌水", "irrigate"),
        (75, "灌浆期巡查蚜虫", "pestcontrol"),
        (105, "成熟收获", "harvest"),
    ],
}

# 未知作物的通用规则（按 120 天通用生育期）
DEFAULT_RULES: list[tuple[int, str, str]] = [
    (0, "定植/播种", "plant"),
    (15, "苗期水肥管理", "fertilize"),
    (40, "生长旺期巡查病虫害", "pestcontrol"),
    (70, "中耕除草", "farmwork"),
    (110, "成熟收获", "harvest"),
]


def _rules_for(crop_name: str) -> list[tuple[int, str, str]]:
    """按作物名取农事规则（模糊匹配，未命中用通用规则）。

    Args:
        crop_name: 作物名称。

    Returns:
        list[tuple[int, str, str]]: 规则列表。
    """
    for crop, rules in FARMWORK_RULES.items():
        if crop in crop_name:
            return rules
    return DEFAULT_RULES


def _build_events_for_plot(plot: Plot, month: Optional[str] = None) -> list[dict[str, Any]]:
    """推算单个地块的农事事件列表。

    Args:
        plot: 地块实例。
        month: 月份过滤 YYYY-MM（空则不过滤）。

    Returns:
        list[dict]: [{date, title, type, plot_id, plot_name}] 按日期升序。
    """
    base = plot.planted_at
    if base is None:
        return []
    events = []
    for offset, title, event_type in _rules_for(plot.crop_name):
        event_date = base + timedelta(days=offset)
        if month is not None and event_date.strftime("%Y-%m") != month:
            continue
        events.append(
            {
                "date": event_date.isoformat(),
                "title": title,
                "type": event_type,
                "plot_id": plot.id,
                "plot_name": plot.name,
            }
        )
    events.sort(key=lambda item: item["date"])
    return events


def get_calendar(db: Session, plot_id: Optional[int], month: Optional[str] = None) -> list[dict[str, Any]]:
    """查询农事日历事件（单地块或全部在种地块）。

    Args:
        db: 数据库会话。
        plot_id: 地块ID（空则全部）。
        month: 月份过滤 YYYY-MM（空则不过滤）。

    Returns:
        list[dict]: 事件数组。

    Raises:
        BusinessException: 404 地块不存在。
    """
    query = db.query(Plot).filter(Plot.status == 1)
    if plot_id is not None:
        query = query.filter(Plot.id == plot_id)
    plots = query.all()
    if plot_id is not None and not plots:
        raise BusinessException(404, "地块不存在")
    events: list[dict[str, Any]] = []
    for plot in plots:
        events.extend(_build_events_for_plot(plot, month))
    events.sort(key=lambda item: item["date"])
    return events


def get_upcoming_reminders(db: Session, plot_id: Optional[int], days: int = 30) -> list[dict[str, Any]]:
    """查询未来 N 天内的农事提醒（含今天）。

    Args:
        db: 数据库会话。
        plot_id: 地块ID（空则全部）。
        days: 展望天数，默认 30。

    Returns:
        list[dict]: 事件数组（按日期升序，附 days_until 剩余天数）。
    """
    events = get_calendar(db, plot_id)
    today_value = date.today()
    horizon = today_value + timedelta(days=days)
    reminders = []
    for event in events:
        event_day = date.fromisoformat(event["date"])
        if today_value <= event_day <= horizon:
            reminders.append({**event, "days_until": (event_day - today_value).days})
    return reminders
