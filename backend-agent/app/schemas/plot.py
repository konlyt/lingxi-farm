"""地块/棚室相关请求模型。"""
from datetime import date

from pydantic import BaseModel, Field, model_validator


class PlotCreateRequest(BaseModel):
    """地块/棚室创建请求体。

    Attributes:
        name: 名称（全局唯一）。
        type: 类型 greenhouse 大棚 / open_field 露天。
        lng: 经度（露天地块建议填写）。
        lat: 纬度（露天地块建议填写）。
        area_mu: 面积（亩）。
        soil_type: 土壤类型。
        crop_name: 当前作物。
        crop_variety: 品种。
        growth_stage: 当前生育期。
        planted_at: 定植/播种日期。
        remark: 备注。
    """

    name: str = Field(..., min_length=1, max_length=64, description="名称（唯一）")
    type: str = Field(..., pattern="^(greenhouse|open_field)$", description="greenhouse大棚/open_field露天")
    lng: float | None = Field(None, ge=-180, le=180, description="经度")
    lat: float | None = Field(None, ge=-90, le=90, description="纬度")
    area_mu: float | None = Field(None, gt=0, description="面积（亩）")
    soil_type: str | None = Field(None, max_length=32, description="土壤类型")
    crop_name: str = Field(..., min_length=1, max_length=64, description="当前作物")
    crop_variety: str | None = Field(None, max_length=64, description="品种")
    growth_stage: str = Field(..., min_length=1, max_length=32, description="当前生育期")
    planted_at: date | None = Field(None, description="定植/播种日期")
    remark: str | None = Field(None, max_length=255, description="备注")

    @model_validator(mode="after")
    def check_location(self) -> "PlotCreateRequest":
        """校验露天地块必须提供经纬度。

        Returns:
            PlotCreateRequest: 校验通过的原实例。

        Raises:
            ValueError: 露天地块缺少经纬度时抛出。
        """
        if self.type == "open_field" and (self.lng is None or self.lat is None):
            raise ValueError("露天地块必须提供经纬度")
        return self


class PlotUpdateRequest(BaseModel):
    """地块/棚室编辑请求体（全部字段可选，仅更新传入字段）。

    Attributes:
        name: 名称。
        type: 类型。
        lng: 经度。
        lat: 纬度。
        area_mu: 面积（亩）。
        soil_type: 土壤类型。
        crop_name: 当前作物。
        crop_variety: 品种。
        growth_stage: 当前生育期。
        planted_at: 定植/播种日期。
        remark: 备注。
    """

    name: str | None = Field(None, min_length=1, max_length=64, description="名称")
    type: str | None = Field(None, pattern="^(greenhouse|open_field)$", description="类型")
    lng: float | None = Field(None, ge=-180, le=180, description="经度")
    lat: float | None = Field(None, ge=-90, le=90, description="纬度")
    area_mu: float | None = Field(None, gt=0, description="面积（亩）")
    soil_type: str | None = Field(None, max_length=32, description="土壤类型")
    crop_name: str | None = Field(None, min_length=1, max_length=64, description="当前作物")
    crop_variety: str | None = Field(None, max_length=64, description="品种")
    growth_stage: str | None = Field(None, min_length=1, max_length=32, description="当前生育期")
    planted_at: date | None = Field(None, description="定植/播种日期")
    remark: str | None = Field(None, max_length=255, description="备注")


class PlotStatusPatchRequest(BaseModel):
    """地块状态切换请求体。

    Attributes:
        status: 目标状态 1 在种 / 0 停用。
    """

    status: int = Field(..., ge=0, le=1, description="1在种/0停用")
