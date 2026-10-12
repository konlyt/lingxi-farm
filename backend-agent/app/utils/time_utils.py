"""时间工具模块。

统一时间取值入口（本地时区 naive datetime），便于后续统一切换时区或 Mock 时间。
"""
from datetime import date, datetime


def now() -> datetime:
    """获取当前本地时间（naive）。

    Returns:
        datetime: 当前时间的 naive datetime 实例。
    """
    return datetime.now()


def today() -> date:
    """获取当前本地日期。

    Returns:
        date: 当前日期实例。
    """
    return date.today()


def fmt_date(value: date | datetime | None) -> str | None:
    """将日期/时间对象格式化为 ISO 日期字符串。

    Args:
        value: 日期或时间对象（可空）。

    Returns:
        str | None: 形如 2026-10-12 的字符串；入参为 None 时返回 None。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def fmt_datetime(value: datetime | date | None) -> str | None:
    """将时间/日期对象格式化为 ISO 字符串（含秒，date 类型仅日期部分）。

    Args:
        value: datetime 或 date 对象（可空）。

    Returns:
        str | None: datetime 形如 2026-10-12T08:30:00；date 形如 2026-10-12；
                    入参为 None 时返回 None。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.microsecond:
            return value.replace(microsecond=0).isoformat()
        return value.isoformat()
    return value.isoformat()
