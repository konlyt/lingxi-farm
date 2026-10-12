"""ORM 模型汇总导出包。

集中导出全部模型类与元数据基类，供 create_all 建表、
业务层 import 与 Alembic 类工具扫描使用。
"""
from app.core.database import Base
from app.models.user import SysUser
from app.models.plot import Plot
from app.models.device import Device, DeviceHeartbeatLog
from app.models.sensor import SensorReading
from app.models.image import CollectedImage
from app.models.diagnosis import (
    DiagnosisTask,
    DiagnosisTaskImage,
    DiagnosisResult,
    PreventionPlan,
)
from app.models.knowledge import KnowledgeDocument, Pesticide, HarvestRestriction
from app.models.case import CaseLibrary, CaseImage
from app.models.alert import Alert, AlertPushRecord
from app.models.advice import (
    DailyBrief,
    WaterFertilizerAdvice,
    EnvironmentThresholdConfig,
    ConfidenceThresholdConfig,
    WeatherForecastCache,
)
from app.models.chat import ChatSession, ChatMessage
from app.models.misc import (
    FarmOperationRecord,
    ExportLog,
    LanggraphCheckpoint,
    LanggraphCheckpointBlob,
    LanggraphCheckpointWrite,
)

# 全部模型清单（建表顺序无关，create_all 自动按外键依赖排序）
__all__ = [
    "Base",
    "SysUser",
    "Plot",
    "Device",
    "DeviceHeartbeatLog",
    "SensorReading",
    "CollectedImage",
    "DiagnosisTask",
    "DiagnosisTaskImage",
    "DiagnosisResult",
    "PreventionPlan",
    "KnowledgeDocument",
    "Pesticide",
    "HarvestRestriction",
    "CaseLibrary",
    "CaseImage",
    "Alert",
    "AlertPushRecord",
    "DailyBrief",
    "WaterFertilizerAdvice",
    "EnvironmentThresholdConfig",
    "ConfidenceThresholdConfig",
    "WeatherForecastCache",
    "ChatSession",
    "ChatMessage",
    "FarmOperationRecord",
    "ExportLog",
    "LanggraphCheckpoint",
    "LanggraphCheckpointBlob",
    "LanggraphCheckpointWrite",
]
