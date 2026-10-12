"""系统设置相关请求模型。

包含置信度阈值编辑、家庭成员创建/状态切换。
"""
from pydantic import BaseModel, Field, field_validator


class ConfidenceThresholdItem(BaseModel):
    """单条置信度阈值更新项。

    Attributes:
        id: 配置记录ID。
        threshold: 置信度阈值（0–1，最多两位小数）。
    """

    id: int = Field(..., gt=0, description="配置记录ID")
    threshold: float = Field(..., ge=0, le=1, description="置信度阈值 0-1")

    @field_validator("threshold")
    @classmethod
    def check_two_decimals(cls, value: float) -> float:
        """校验阈值最多保留两位小数。

        Args:
            value: 输入阈值。

        Returns:
            float: 校验通过的原值。

        Raises:
            ValueError: 超过两位小数时抛出。
        """
        if round(value, 2) != value:
            raise ValueError("阈值最多保留两位小数")
        return value


class ConfidenceThresholdUpdateRequest(BaseModel):
    """置信度阈值批量更新请求体。

    Attributes:
        items: 更新项列表。
    """

    items: list[ConfidenceThresholdItem] = Field(..., min_length=1, description="更新项列表")


class MemberCreateRequest(BaseModel):
    """家庭成员创建请求体（仅 owner）。

    Attributes:
        username: 登录名（唯一）。
        nickname: 显示名。
        password: 初始密码（至少 6 位）。
    """

    username: str = Field(..., min_length=2, max_length=64, description="登录名")
    nickname: str = Field(..., min_length=1, max_length=64, description="显示名")
    password: str = Field(..., min_length=6, max_length=64, description="初始密码")


class MemberStatusPatchRequest(BaseModel):
    """家庭成员状态切换请求体（仅 owner）。

    Attributes:
        status: 目标状态 1 启用 / 0 停用。
    """

    status: int = Field(..., ge=0, le=1, description="1启用/0停用")
