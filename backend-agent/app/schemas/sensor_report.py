"""传感器数据上报请求模型。"""
from typing import Any

from pydantic import BaseModel, Field


class SensorReadingItem(BaseModel):
    """单条传感器读数。

    Attributes:
        metric: 指标 temp/humidity/light/soil_moisture。
        value: 数值。
        unit: 单位（空则按指标默认单位）。
        reported_at: 上报时间 ISO 字符串（空则取当前时间）。
    """

    metric: str = Field(..., min_length=1, max_length=32, description="指标名")
    value: float = Field(..., description="数值")
    unit: str | None = Field(None, max_length=16, description="单位")
    reported_at: str | None = Field(None, max_length=32, description="上报时间 ISO（可空）")


class SensorReportRequest(BaseModel):
    """传感器数据上报请求体。

    Attributes:
        readings: 读数列表（1-20 条）。
    """

    readings: list[SensorReadingItem] = Field(..., min_length=1, max_length=20, description="读数列表")
