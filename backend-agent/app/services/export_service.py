"""数据导出业务服务模块。

生成 CSV 导出文件（诊断案例/环境数据）落盘 backend-agent/exports/，
export_log 落库，供列表与下载接口使用。
"""
import csv
import logging
import uuid
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.core.response import BusinessException
from app.models.case import CaseLibrary
from app.models.diagnosis import DiagnosisResult, DiagnosisTask
from app.models.misc import ExportLog as ExportLogModel
from app.models.plot import Plot
from app.models.sensor import SensorReading
from app.utils.time_utils import now

logger = logging.getLogger("farm_export")

# 导出文件目录
EXPORT_DIR = BASE_DIR / "exports"


def _resolve_range(start: Optional[str], end: Optional[str]) -> tuple[date_type, date_type]:
    """解析时间范围参数（默认近 30 天）。

    Args:
        start: 开始日期 YYYY-MM-DD（空则 30 天前）。
        end: 结束日期（空则今天）。

    Returns:
        tuple[date, date]: (start_date, end_date)。

    Raises:
        BusinessException: 400 日期格式非法。
    """
    try:
        end_date = date_type.fromisoformat(end) if end else date_type.today()
        start_date = date_type.fromisoformat(start) if start else end_date - timedelta(days=30)
    except ValueError as exc:
        raise BusinessException(400, f"日期格式非法: {start} ~ {end}") from exc
    if start_date > end_date:
        raise BusinessException(400, "开始日期不能晚于结束日期")
    return start_date, end_date


def run_export(export_id: int, export_type: str, start: Optional[str], end: Optional[str]) -> None:
    """后台执行导出任务（BackgroundTasks 入口，独立数据库会话）。

    根据 export_type 生成 CSV 后更新对应 export_log 记录为 done/failed。

    Args:
        export_id: 预创建的 export_log 记录ID（status=pending）。
        export_type: 导出类型 diagnosis_cases/env_data。
        start: 开始日期。
        end: 结束日期。

    Returns:
        None: 无返回值，结果直接落库。

    Raises:
        Exception: 不向外抛出（失败落库为 failed）。
    """
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        log = session.query(ExportLogModel).filter(ExportLogModel.id == export_id).first()
        if log is None:
            logger.error("导出记录不存在: %s", export_id)
            return
        try:
            start_date, end_date = _resolve_range(start, end)
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            file_name = f"{export_type}_{uuid.uuid4().hex[:12]}.csv"
            file_path = EXPORT_DIR / file_name
            if export_type == "diagnosis_cases":
                _export_diagnosis_cases(session, file_path, start_date, end_date)
            elif export_type == "env_data":
                _export_env_data(session, file_path, start_date, end_date)
            else:
                raise BusinessException(400, "export_type 仅支持 diagnosis_cases/env_data")
            log.file_url = f"/exports/{file_name}"
            log.status = "done"
            session.commit()
            logger.info("导出完成: %s -> %s", export_type, file_path)
        except Exception as exc:  # noqa: BLE001 失败落库
            session.rollback()
            log = session.query(ExportLogModel).filter(ExportLogModel.id == export_id).first()
            if log is not None:
                log.status = "failed"
                session.commit()
            logger.exception("导出失败: %s", exc)
    finally:
        session.close()


def _export_diagnosis_cases(db: Session, file_path: Path, start_date: date_type, end_date: date_type) -> None:
    """导出诊断案例 CSV。

    Args:
        db: 数据库会话。
        file_path: 目标文件路径。
        start_date: 开始日期。
        end_date: 结束日期。
    """
    rows = (
        db.query(DiagnosisTask, Plot, CaseLibrary, DiagnosisResult)
        .join(Plot, DiagnosisTask.plot_id == Plot.id)
        .outerjoin(CaseLibrary, CaseLibrary.task_id == DiagnosisTask.id)
        .outerjoin(
            DiagnosisResult,
            (DiagnosisResult.task_id == DiagnosisTask.id) & (DiagnosisResult.model_path == "fused"),
        )
        .filter(DiagnosisTask.created_at >= start_date, DiagnosisTask.created_at < end_date + timedelta(days=1))
        .order_by(DiagnosisTask.id.asc())
        .all()
    )
    with file_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["任务ID", "地块", "来源", "生育期", "任务状态", "结果级别",
                         "病名", "置信度", "案例状态", "最终病名", "创建时间"])
        for task, plot, case, result in rows:
            writer.writerow(
                [
                    task.id,
                    plot.name,
                    task.source,
                    task.growth_stage,
                    task.status,
                    task.result_level or "",
                    result.disease_name if result else "",
                    float(result.confidence) if result and result.confidence is not None else "",
                    case.status if case else "",
                    (case.final_disease_name or "") if case else "",
                    task.created_at.isoformat() if task.created_at else "",
                ]
            )


def _export_env_data(db: Session, file_path: Path, start_date: date_type, end_date: date_type) -> None:
    """导出环境数据 CSV。

    Args:
        db: 数据库会话。
        file_path: 目标文件路径。
        start_date: 开始日期。
        end_date: 结束日期。
    """
    rows = (
        db.query(SensorReading, Plot, Device)
        .join(Plot, SensorReading.plot_id == Plot.id)
        .join(Device, SensorReading.device_id == Device.id)
        .filter(SensorReading.reported_at >= start_date, SensorReading.reported_at < end_date + timedelta(days=1))
        .order_by(SensorReading.reported_at.asc())
        .limit(100000)
        .all()
    )
    with file_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["读数ID", "地块", "设备编号", "指标", "数值", "单位", "上报时间"])
        for reading, plot, device in rows:
            writer.writerow(
                [
                    reading.id,
                    plot.name,
                    device.device_no,
                    reading.metric,
                    float(reading.value),
                    reading.unit,
                    reading.reported_at.isoformat() if reading.reported_at else "",
                ]
            )


def list_exports(db: Session, user_id: int) -> list[dict[str, Any]]:
    """查询当前用户的导出记录列表。

    Args:
        db: 数据库会话。
        user_id: 用户ID。

    Returns:
        list[dict]: 导出记录数组。
    """
    rows = (
        db.query(ExportLogModel)
        .filter(ExportLogModel.user_id == user_id)
        .order_by(ExportLogModel.id.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": row.id,
            "export_type": row.export_type,
            "file_url": row.file_url,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def get_export_file(db: Session, export_id: int, user_id: int) -> Path:
    """定位导出文件物理路径（校验归属）。

    Args:
        db: 数据库会话。
        export_id: 导出记录ID。
        user_id: 当前用户ID。

    Returns:
        Path: 文件绝对路径。

    Raises:
        BusinessException: 404 记录不存在；400 文件已丢失。
    """
    log = db.query(ExportLogModel).filter(ExportLogModel.id == export_id).first()
    if log is None:
        raise BusinessException(404, "导出记录不存在")
    relative = (log.file_url or "").removeprefix("/exports/")
    file_path = EXPORT_DIR / relative
    if not file_path.exists():
        raise BusinessException(400, "导出文件已丢失，请重新导出")
    return file_path
