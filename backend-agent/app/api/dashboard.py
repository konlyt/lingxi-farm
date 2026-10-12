"""监测大屏数据聚合接口路由。

提供 GET /api/dashboard/stats 六面板数据：
诊断趋势 / 病虫害分布 / 地块虫情密度与墒情 / 设备健康度 / 实时预警流 / 环境实况。
"""
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.core.security import require_owner
from app.models.alert import Alert
from app.models.device import Device
from app.models.diagnosis import DiagnosisResult, DiagnosisTask
from app.models.plot import Plot
from app.services.device_service import get_device_stats
from app.services.plot_service import get_latest_env
from app.utils.time_utils import fmt_datetime, now, today

router = APIRouter(prefix="/api/dashboard", tags=["监测大屏"], dependencies=[Depends(require_owner)])


@router.get("/stats", summary="监测大屏聚合数据（六面板）")
def dashboard_stats(db: Session = Depends(get_db)) -> dict:
    """聚合大屏六个面板数据。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {diagnosis_trend, disease_distribution,
              plot_pest_density, device_health, recent_alerts, env_realtime}。
    """
    # 1) 诊断趋势：近 14 天每日任务数
    start_date = today() - timedelta(days=13)
    trend_rows = (
        db.query(
            func.date(DiagnosisTask.created_at).label("day"),
            func.count(DiagnosisTask.id).label("cnt"),
        )
        .filter(DiagnosisTask.created_at >= start_date)
        .group_by("day")
        .order_by("day")
        .all()
    )
    trend_map = {str(day): count for day, count in trend_rows}
    diagnosis_trend = []
    for offset in range(14):
        day = (start_date + timedelta(days=offset)).isoformat()
        diagnosis_trend.append({"date": day, "count": trend_map.get(day, 0)})

    # 2) 病虫害分布：fused 结果病名计数 top10（排除健康/unknown）
    disease_rows = (
        db.query(DiagnosisResult.disease_name, func.count(DiagnosisResult.id).label("cnt"))
        .filter(
            DiagnosisResult.model_path == "fused",
            ~DiagnosisResult.disease_name.in_(["健康", "healthy", "unknown", "正常", "无病虫害"]),
        )
        .group_by(DiagnosisResult.disease_name)
        .order_by(func.count(DiagnosisResult.id).desc())
        .limit(10)
        .all()
    )
    disease_distribution = [{"disease_name": name, "count": count} for name, count in disease_rows]

    # 3) 地块虫情密度与墒情
    plot_pest_density: list[dict[str, Any]] = []
    plots = db.query(Plot).filter(Plot.status == 1).all()
    for plot in plots:
        pest_count = (
            db.query(func.count(Alert.id))
            .filter(Alert.plot_id == plot.id, Alert.type == "pest")
            .scalar() or 0
        )
        env = get_latest_env(db, plot.id)
        plot_pest_density.append(
            {
                "plot_id": plot.id,
                "plot_name": plot.name,
                "pest_alert_count": pest_count,
                "soil_moisture": env.get("soil_moisture"),
            }
        )

    # 4) 设备健康度
    device_health = get_device_stats(db)

    # 5) 实时预警流：最新 10 条
    recent_rows = db.query(Alert).order_by(Alert.first_triggered_at.desc()).limit(10).all()
    plot_names = {plot.id: plot.name for plot in db.query(Plot).all()}
    recent_alerts = [
        {
            "id": alert.id,
            "type": alert.type,
            "level": alert.level,
            "plot_name": plot_names.get(alert.plot_id),
            "title": alert.title,
            "status": alert.status,
            "occurrence_count": alert.occurrence_count,
            "first_triggered_at": fmt_datetime(alert.first_triggered_at),
        }
        for alert in recent_rows
    ]

    # 6) 环境实况：各地块最新温湿度
    env_realtime = [
        {
            "plot_id": plot.id,
            "plot_name": plot.name,
            "type": plot.type,
            "temp": get_latest_env(db, plot.id).get("temp"),
            "humidity": get_latest_env(db, plot.id).get("humidity"),
        }
        for plot in plots
    ]

    return ok(
        {
            "diagnosis_trend": diagnosis_trend,
            "disease_distribution": disease_distribution,
            "plot_pest_density": plot_pest_density,
            "device_health": device_health,
            "recent_alerts": recent_alerts,
            "env_realtime": env_realtime,
        }
    )
