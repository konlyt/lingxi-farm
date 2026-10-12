"""设备管理相关请求模型。"""
from typing import Any

from pydantic import BaseModel, Field


class DeviceCreateRequest(BaseModel):
    """设备新增（接入向导参数保存）请求体。

    Attributes:
        device_no: 设备编号（全局唯一）。
        name: 设备名称。
        type: 设备类型 camera/pest_light/spore_trap/env_sensor。
        plot_id: 安装地块ID。
        protocol: 接入协议 MQTT/RTSP/vendor_api。
        vendor: 厂商。
        collect_schedule: 采集计划 JSON。
        config: 远程配置 JSON。
    """

    device_no: str = Field(..., min_length=1, max_length=64, description="设备编号（唯一）")
    name: str = Field(..., min_length=1, max_length=64, description="设备名称")
    type: str = Field(..., pattern="^(camera|pest_light|spore_trap|env_sensor)$", description="设备类型")
    plot_id: int = Field(..., gt=0, description="安装地块ID")
    protocol: str = Field(..., pattern="^(MQTT|RTSP|vendor_api)$", description="接入协议")
    vendor: str | None = Field(None, max_length=64, description="厂商")
    collect_schedule: dict[str, Any] | None = Field(None, description="采集计划JSON")
    config: dict[str, Any] | None = Field(None, description="远程配置JSON")


class DeviceConfigRequest(BaseModel):
    """设备远程配置下发请求体。

    Attributes:
        config: 远程配置 JSON 内容。
    """

    config: dict[str, Any] = Field(..., description="远程配置JSON")
