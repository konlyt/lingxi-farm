"""定时任务模块（APScheduler，随 FastAPI 进程运行）。

任务清单：
- 每日 06:00：全地块水肥建议生成（种植决策智能体）；
- 每日 07:00：每日农情简报生成 + 推送状态落库；
- 每小时：设备离线扫描（>24h 无心跳置 offline + device_offline 预警）；
- 每小时：采收禁令到期解除扫描（ban_until < 今天 的 active 置 expired）；
- 每 30 分钟：模拟设备上报（番茄1号棚 env_sensor 日曲线温湿度/墒情，
  走 report 逻辑以触发环境越限判定演示）。

不引入 Celery/Redis，全部任务独立创建数据库会话，异常只记日志不中断调度。
"""
import logging
import math
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session as DBSession

from app.core.database import SessionLocal
from app.services.advisory_service import generate_daily_brief, generate_water_fertilizer
from app.services.alert_service import create_or_merge_alert
from app.services.environment_service import save_readings_and_check
from app.utils.time_utils import now

logger = logging.getLogger("farm_scheduler")

# 全局调度器实例
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _daily_water_fertilizer_job() -> None:
    """每日 06:00 任务：为全部在种地块生成水肥建议。

    Returns:
        None: 单地块失败仅记日志，不阻塞其余地块。

    Raises:
        Exception: 不向外抛出。
    """
    from app.models.plot import Plot

    session: DBSession = SessionLocal()
    try:
        plots = session.query(Plot).filter(Plot.status == 1).all()
        for plot in plots:
            try:
                generate_water_fertilizer(session, plot.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("水肥建议生成失败（plot=%s）: %s", plot.id, exc)
    finally:
        session.close()


def _daily_brief_job() -> None:
    """每日 07:00 任务：生成每日农情简报并记录推送状态。

    Returns:
        None。

    Raises:
        Exception: 不向外抛出。
    """
    session: DBSession = SessionLocal()
    try:
        generate_daily_brief(session)
    except Exception as exc:  # noqa: BLE001
        logger.exception("每日简报生成失败: %s", exc)
    finally:
        session.close()


def _device_offline_scan_job() -> None:
    """每小时任务：设备离线扫描（最近心跳距今 >24h 置 offline 并生成预警）。

    预警聚合键 plot:{plot_id}:device_offline:{device_id}，同一设备未解决期间合并。

    Returns:
        None。

    Raises:
        Exception: 不向外抛出。
    """
    from app.models.device import Device

    session: DBSession = SessionLocal()
    try:
        threshold = now() - timedelta(hours=24)
        stale_devices = (
            session.query(Device)
            .filter(Device.status == "online", Device.last_heartbeat_at < threshold)
            .all()
        )
        for device in stale_devices:
            device.status = "offline"
            create_or_merge_alert(
                db=session,
                plot_id=device.plot_id,
                alert_type="device_offline",
                case_key=f"plot:{device.plot_id}:device_offline:{device.id}",
                title=f"设备「{device.name}」离线超过 24 小时",
                content={
                    "device_id": device.id,
                    "device_no": device.device_no,
                    "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
                },
                level="warning",
            )
            logger.info("设备离线告警: device=%s", device.device_no)
    finally:
        session.close()


def _harvest_restriction_release_job() -> None:
    """每小时任务：采收禁令到期解除（ban_until < 今天 的 active 置 expired）。

    Returns:
        None。

    Raises:
        Exception: 不向外抛出。
    """
    from app.models.knowledge import HarvestRestriction
    from app.utils.time_utils import today

    session: DBSession = SessionLocal()
    try:
        target_date = today()
        rows = (
            session.query(HarvestRestriction)
            .filter(HarvestRestriction.status == "active", HarvestRestriction.ban_until < target_date)
            .all()
        )
        for restriction in rows:
            restriction.status = "expired"
            restriction.released_at = now()
        if rows:
            session.commit()
            logger.info("采收禁令到期解除: %s 条", len(rows))
    finally:
        session.close()


def _mock_device_report_job() -> None:
    """每 30 分钟任务：模拟全部环境传感器上报（含日变化曲线）。

    数值生成规则与种子数据一致：温度正弦日变化（±7.5℃），湿度反相，
    墒情缓慢波动；走 report 逻辑以触发越限判定（演示 env 预警）。
    遍历所有 env_sensor 设备（每台按设备 id 做小幅偏移，露天/大棚曲线错开）。

    Returns:
        None。

    Raises:
        Exception: 不向外抛出。
    """
    from app.models.device import Device

    session: DBSession = SessionLocal()
    try:
        devices = session.query(Device).filter(Device.type == "env_sensor", Device.plot_id.isnot(None)).all()
        if not devices:
            return
        current = now()
        day_progress = (current.hour * 60 + current.minute) / 1440.0
        for device in devices:
            """每台传感器按 id 做稳定偏移（-1.2 ~ +1.2℃ / ±5% 湿度），模拟不同小环境。"""
            offset = ((device.id % 5) - 2) * 0.6
            hum_offset = ((device.id % 4) - 1.5) * 3.0
            temp_value = round(22.0 + 7.5 * math.sin(2 * math.pi * (day_progress - 0.29)) + offset, 1)
            humidity_value = round(
                max(30.0, min(95.0, 66.0 - 11.0 * math.sin(2 * math.pi * (day_progress - 0.29)) + hum_offset)), 1
            )
            soil_value = round(
                max(30.0, min(85.0, 62.0 - 6.0 * math.sin(2 * math.pi * day_progress)) + offset * 2.0), 1
            )
            save_readings_and_check(
                session,
                device,
                [
                    {"metric": "temp", "value": temp_value},
                    {"metric": "humidity", "value": humidity_value},
                    {"metric": "soil_moisture", "value": soil_value},
                ],
            )
        logger.info("模拟设备上报完成: %s 台环境传感器", len(devices))
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("模拟设备上报失败: %s", exc)
    finally:
        session.close()


def _weather_forecast_job() -> None:
    """每 3 小时任务：为全部在种地块拉取和风天气 7 天预报并写缓存。

    Returns:
        None。

    Raises:
        Exception: 不向外抛出。
    """
    from app.services.weather_service import refresh_all_plots

    session: DBSession = SessionLocal()
    try:
        stats = refresh_all_plots(session)
        logger.info("气象预报刷新完成: %s", stats)
    except Exception as exc:  # noqa: BLE001
        logger.warning("气象预报刷新失败: %s", exc)
    finally:
        session.close()


def _weather_warning_job() -> None:
    """每小时任务：拉取和风天气灾害预警，命中即生成/合并 weather 预警。

    Returns:
        None。

    Raises:
        Exception: 不向外抛出。
    """
    from app.models.plot import Plot
    from app.services.weather_service import fetch_warnings_for_plot

    session: DBSession = SessionLocal()
    try:
        plots = session.query(Plot).filter(Plot.status == 1).all()
        hits = 0
        for plot in plots:
            try:
                hits += fetch_warnings_for_plot(session, plot)
            except Exception as exc:  # noqa: BLE001 单地块失败不阻塞
                logger.warning("气象预警拉取失败（plot=%s）: %s", plot.id, exc)
        if hits:
            logger.info("气象灾害预警命中 %s 条", hits)
    except Exception as exc:  # noqa: BLE001
        logger.warning("气象预警任务失败: %s", exc)
    finally:
        session.close()


def _digest_email_job() -> None:
    """每小时任务：将当日 pending 每日汇总记录按用户聚合为单封邮件发送。

    Returns:
        None。

    Raises:
        Exception: 不向外抛出。
    """
    from app.services.alert_service import send_pending_digest_emails

    session: DBSession = SessionLocal()
    try:
        sent = send_pending_digest_emails(session)
        if sent:
            logger.info("每日汇总邮件已聚合发送: %s 封", sent)
    except Exception as exc:  # noqa: BLE001
        logger.warning("每日汇总邮件发送失败: %s", exc)
    finally:
        session.close()


def start_scheduler() -> None:
    """注册全部定时任务并启动调度器（随 FastAPI lifespan 启动）。

    Returns:
        None。

    Raises:
        Exception: 调度器启动失败时抛出（终止应用启动）。
    """
    # 每日 06:00 水肥建议
    scheduler.add_job(_daily_water_fertilizer_job, "cron", hour=6, minute=0, id="daily_water_fertilizer")
    # 每日 07:00 每日简报
    scheduler.add_job(_daily_brief_job, "cron", hour=7, minute=0, id="daily_brief")
    # 每小时设备离线扫描
    scheduler.add_job(_device_offline_scan_job, "interval", hours=1, id="device_offline_scan")
    # 每小时禁令解除扫描
    scheduler.add_job(_harvest_restriction_release_job, "interval", hours=1, id="harvest_restriction_release")
    # 每 30 分钟模拟设备上报
    scheduler.add_job(_mock_device_report_job, "interval", minutes=30, id="mock_device_report")
    # 每 3 小时气象预报拉取（启动后立即执行首次）
    scheduler.add_job(
        _weather_forecast_job, "interval", hours=3, id="weather_forecast",
        next_run_time=datetime.now(),
    )
    # 每小时气象灾害预警检查（启动后立即执行首次）
    scheduler.add_job(
        _weather_warning_job, "interval", hours=1, id="weather_warning",
        next_run_time=datetime.now(),
    )
    # 每小时聚合发送每日汇总邮件（pending 记录合并为每用户单封）
    scheduler.add_job(_digest_email_job, "interval", hours=1, id="digest_email")
    scheduler.start()
    logger.info("定时任务调度器已启动（9 项任务注册）")


def stop_scheduler() -> None:
    """停止调度器（FastAPI 关闭时调用）。

    Returns:
        None。
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("定时任务调度器已停止")
