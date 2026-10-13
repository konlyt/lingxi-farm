"""预警聚合去重业务服务模块。

实现 create_or_merge_alert：同 case_key 未解决期间合并（occurrence_count+1、
时间线追加），病情加重时升级 level 并补即时推送记录；新预警落库并即时推送。
推送真实化：为每个启用用户落 alert_push_record（channel=email），对已绑定
邮箱的用户经 notifier 真实发送 HTML 邮件，push_status 按发送结果置 sent/failed
（失败含重试 1 次，错误信息写入 content.error）；未绑定/邮箱通道未配置的记录
置 failed 并记录原因。uk_digest(alert_id, push_type, digest_date, receiver_user_id)
唯一约束兜底每日汇总一条。
"""
import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertPushRecord
from app.models.plot import Plot
from app.models.user import SysUser
from app.services import notifier
from app.utils.time_utils import now

logger = logging.getLogger("farm_alert")

# 预警级别权重（用于升级判定）
_LEVEL_ORDER = {"info": 0, "warning": 1, "critical": 2}
# occurrence_count 达到阈值时的级别升级规则
_LEVEL_BY_OCCURRENCE = [(5, "critical"), (3, "warning")]


def _next_level(current_level: str, incoming_level: str, occurrence_count: int) -> str:
    """计算合并后的预警级别（病情加重升级判定）。

    规则：取当前级别与传入级别的较高者；occurrence 达阈值（≥3 warning / ≥5 critical）再抬升。

    Args:
        current_level: 现有预警级别。
        incoming_level: 本次触发传入级别。
        occurrence_count: 合并后的累计次数。

    Returns:
        str: 新级别 info/warning/critical。
    """
    level = max(_LEVEL_ORDER.get(current_level, 0), _LEVEL_ORDER.get(incoming_level, 0))
    for threshold, upgrade_level in _LEVEL_BY_OCCURRENCE:
        if occurrence_count >= threshold:
            level = max(level, _LEVEL_ORDER[upgrade_level])
    order_to_level = {v: k for k, v in _LEVEL_ORDER.items()}
    return order_to_level[level]


def _push_single_email(alert: Alert, user: SysUser, plot_name: str, push_type: str) -> tuple[str, Optional[str]]:
    """对单个用户执行预警邮件真实发送。

    规则：
    - 邮箱通道未配置（EMAIL_USER/PASSWORD 占位空）→ (failed, '邮箱未配置')，全员一致；
    - 用户未绑定邮箱（email 为空或 email_bind_status != 1）→ (failed, '接收人未绑定邮箱')；
    - 已绑定 → 按 push_type 渲染即时/汇总模板真实发送，重试由 notifier 内部处理。

    Args:
        alert: 预警 ORM 实例。
        user: 接收用户 ORM 实例。
        plot_name: 归属地块名称。
        push_type: 推送类型 instant/daily_digest。

    Returns:
        tuple[str, str|None]: (推送状态 sent/failed, 失败原因或 None)。
    """
    if not notifier.is_email_configured():
        return "failed", "邮箱未配置"
    if not user.email or user.email_bind_status != 1:
        return "failed", "接收人未绑定邮箱"
    if push_type == "daily_digest":
        html = notifier.render_daily_digest_email(alert, plot_name)
        subject = f"【每日汇总】{alert.title}"
    else:
        html = notifier.render_alert_email(alert, plot_name)
        subject = f"【农情预警】{alert.title}"
    sent, err = notifier.send_email(user.email, subject, html)
    return ("sent" if sent else "failed"), err


def _create_push_records(db: Session, alert: Alert, push_type: str, digest_date: Optional[date]) -> bool:
    """为预警写入推送记录并按策略发送邮件（所有启用用户，channel=email）。

    发送策略（v2.5 刷屏治理）：
    - instant：同预警 60 分钟内已发过即时邮件则节流跳过（不落记录）；
    - daily_digest：仅落库 status=pending，不即时发送——由
      send_pending_digest_emails 按小时聚合为「每用户单封汇总邮件」发送。

    为每个启用用户各落一条记录（保持推送记录数与启用用户数一致）：
    已绑定邮箱者真实发送并按结果置 sent/failed（失败原因写入 content.error），
    未绑定者置 failed 并记录「接收人未绑定邮箱」，邮箱通道未配置时全员
    failed + 「邮箱未配置」。发送失败不影响记录落库。

    Args:
        db: 数据库会话（由调用方 commit）。
        alert: 预警实例。
        push_type: 推送类型 instant/daily_digest。
        digest_date: 汇总日期（daily_digest 必填，instant 传 None）。

    Returns:
        bool: 是否有实际发送动作（instant 节流跳过时返回 False）。
    """
    if push_type == "instant":
        # 即时邮件节流：同预警 60 分钟内已发过则跳过（防连续升级/重复触发刷屏）
        throttle_since = now() - timedelta(minutes=60)
        throttled = (
            db.query(AlertPushRecord.id)
            .filter(
                AlertPushRecord.alert_id == alert.id,
                AlertPushRecord.push_type == "instant",
                AlertPushRecord.channel == "email",
                AlertPushRecord.status == "sent",
                AlertPushRecord.sent_at >= throttle_since,
            )
            .first()
        )
        if throttled is not None:
            logger.info(
                "即时邮件节流跳过（60 分钟内已发送）: alert_id=%s title=%s", alert.id, alert.title
            )
            return False
    users = db.query(SysUser).filter(SysUser.status == 1).all()
    for user in users:
        if push_type == "daily_digest":
            # 汇总记录只落库待聚合，不即时发送
            content: dict[str, Any] = {
                "title": alert.title,
                "level": alert.level,
                "occurrence_count": alert.occurrence_count,
                "plot": (db.query(Plot).filter(Plot.id == alert.plot_id).first().name
                         if db.query(Plot).filter(Plot.id == alert.plot_id).first() else ""),
                "triggered_at": now().isoformat(),
            }
            db.add(AlertPushRecord(
                alert_id=alert.id,
                push_type=push_type,
                digest_date=digest_date,
                channel="email",
                receiver_user_id=user.id,
                content=content,
                status="pending",
                sent_at=now(),
            ))
            continue
        status, error = _push_single_email(alert, user, _plot_name(db, alert.plot_id), push_type)
        content = {
            "title": alert.title,
            "level": alert.level,
            "occurrence_count": alert.occurrence_count,
        }
        if error:
            content["error"] = error
        record = AlertPushRecord(
            alert_id=alert.id,
            push_type=push_type,
            digest_date=digest_date,
            channel="email",
            receiver_user_id=user.id,
            content=content,
            status=status,
            sent_at=now(),
        )
        db.add(record)
    if not notifier.is_email_configured():
        logger.info("邮箱通道未配置，预警推送记录全部置 failed（系统不受影响）: alert_id=%s", alert.id)
    return True


def _plot_name(db: Session, plot_id: int) -> str:
    """查询地块名称（查不到返回空串）。"""
    plot = db.query(Plot).filter(Plot.id == plot_id).first()
    return plot.name if plot is not None else ""


def send_pending_digest_emails(db: Session) -> int:
    """将当日 pending 的每日汇总记录按用户聚合为单封邮件发送（定时任务入口）。

    每个用户当日内所有 pending 汇总记录合并为一封邮件（标题含条数），
    发送成功统一置 sent，失败置 failed（记录错误原因）。由此保证
    「同一用户每小时至多一封汇总邮件、典型每天 1–2 封」。

    Args:
        db: 数据库会话（本函数 commit）。

    Returns:
        int: 发送的邮件数（成功）。
    """
    pending = (
        db.query(AlertPushRecord)
        .filter(AlertPushRecord.push_type == "daily_digest", AlertPushRecord.status == "pending")
        .all()
    )
    if not pending:
        return 0
    sent_count = 0
    by_user: dict[int, list[AlertPushRecord]] = {}
    for record in pending:
        by_user.setdefault(record.receiver_user_id, []).append(record)
    for user_id, records in by_user.items():
        user = db.query(SysUser).filter(SysUser.id == user_id).first()
        if user is None or not user.email or user.email_bind_status != 1:
            for record in records:
                record.status = "failed"
                record.content = {**(record.content or {}), "error": "接收人未绑定邮箱"}
            db.commit()
            continue
        if not notifier.is_email_configured():
            for record in records:
                record.status = "failed"
                record.content = {**(record.content or {}), "error": "邮箱未配置"}
            db.commit()
            continue
        rows_html = "".join(
            f"<tr>"
            f"<td style='padding:6px 10px;border:1px solid #eee;'>{r.content.get('plot', '')}</td>"
            f"<td style='padding:6px 10px;border:1px solid #eee;'>{r.content.get('title', '')}</td>"
            f"<td style='padding:6px 10px;border:1px solid #eee;'>{r.content.get('level', '')}</td>"
            f"<td style='padding:6px 10px;border:1px solid #eee;'>累计 {r.content.get('occurrence_count', 1)} 次</td>"
            f"</tr>"
            for r in records
        )
        html = (
            f"<div style='font-family:sans-serif;max-width:640px;margin:auto;'>"
            f"<h2 style='color:#2e7d32;'>【每日汇总】今日 {len(records)} 条预警更新</h2>"
            f"<p>以下为今日有更新的预警（同一预警每日至多一条汇总，已合并本邮件）：</p>"
            f"<table style='border-collapse:collapse;font-size:14px;'>"
            f"<tr style='background:#f5f5f5;'>"
            f"<th style='padding:6px 10px;border:1px solid #eee;'>地块</th>"
            f"<th style='padding:6px 10px;border:1px solid #eee;'>预警</th>"
            f"<th style='padding:6px 10px;border:1px solid #eee;'>等级</th>"
            f"<th style='padding:6px 10px;border:1px solid #eee;'>触发次数</th>"
            f"</tr>{rows_html}</table>"
            f"<p style='color:#888;font-size:12px;'>请前往系统「预警中心」处理——农场智能管护系统（自动邮件，请勿回复）</p>"
            f"</div>"
        )
        sent, err = notifier.send_email(user.email, f"【每日汇总】今日 {len(records)} 条预警更新", html)
        for record in records:
            record.status = "sent" if sent else "failed"
            if err:
                record.content = {**(record.content or {}), "error": err}
        db.commit()
        if sent:
            sent_count += 1
    return sent_count


def create_or_merge_alert(db: Session, plot_id: int, alert_type: str, case_key: str,
                          title: str, content: dict[str, Any], level: str = "warning",
                          task_id: Optional[int] = None) -> Alert:
    """创建预警或合并到同 case_key 的活跃预警（核心聚合入口）。

    合并逻辑：同 case_key 存在 active 预警 → occurrence_count+1、
    content 更新最新数据并向 updates 时间线追加事件、按规则升级 level；
    升级时补一条 instant 推送记录（病情加重即时提醒）。
    不存在 → 新建 active 预警 + instant 推送记录。

    Args:
        db: 数据库会话（本函数 commit）。
        plot_id: 地块ID。
        alert_type: 类型 pest/env/weather/device_offline。
        case_key: 聚合去重键，如 plot:1:pest:早疫病。
        title: 标题。
        content: 详情 JSON（含最新照片/数值/建议）。
        level: 本次触发级别，默认 warning。
        task_id: 关联诊断任务ID（pest 类）。

    Returns:
        Alert: 新建或合并后的预警 ORM 实例。

    Raises:
        Exception: 数据库写入冲突（uk_active_case 唯一约束并发）时抛出，由调用方重试或忽略。
    """
    active = (
        db.query(Alert)
        .filter(Alert.case_key == case_key, Alert.status == "active")
        .first()
    )
    current_time = now()
    if active is not None:
        # 合并：次数+1，content 追加时间线
        active.occurrence_count += 1
        merged_content = dict(active.content or {})
        updates = merged_content.get("updates", [])
        updates.append(
            {
                "time": current_time.isoformat(),
                "event": "再次触发",
                "content": content,
            }
        )
        merged_content["updates"] = updates
        # 用最新数据覆盖顶层展示字段（保留历史于 updates）
        merged_content.update({k: v for k, v in content.items() if k != "updates"})
        active.content = merged_content
        new_level = _next_level(active.level, level, active.occurrence_count)
        if new_level != active.level:
            active.level = new_level
            # 病情加重：升级即时推送（instant，digest_date 为空不占用每日汇总位）
            _create_push_records(db, active, "instant", None)
        db.commit()
        # 未升级的重复触发：并入当日汇总（每日一条，uk_digest 幂等兜底，含最新照片与病情变化）
        create_daily_digest_push(db, active, current_time.date())
        logger.info("预警合并: case_key=%s occurrence=%s level=%s", case_key, active.occurrence_count, active.level)
        return active

    # 新建：content 统一带 updates 时间线初始事件（快照不含 updates，避免自引用循环）
    content = dict(content)
    snapshot = {k: v for k, v in content.items() if k != "updates"}
    updates = content.get("updates", [])
    updates.append({"time": current_time.isoformat(), "event": "首次触发", "content": snapshot})
    content["updates"] = updates
    alert = Alert(
        type=alert_type,
        level=level,
        plot_id=plot_id,
        task_id=task_id,
        case_key=case_key,
        title=title,
        content=content,
        status="active",
        occurrence_count=1,
        first_triggered_at=current_time,
    )
    db.add(alert)
    db.flush()
    _create_push_records(db, alert, "instant", None)
    db.commit()
    logger.info("预警新建: case_key=%s level=%s", case_key, level)
    return alert


def create_daily_digest_push(db: Session, alert: Alert, digest_date: date) -> bool:
    """写入每日汇总推送记录（uk_digest 唯一约束兜底每日一条）。

    Args:
        db: 数据库会话（本函数 commit）。
        alert: 预警实例。
        digest_date: 汇总归属日期。

    Returns:
        bool: 写入成功 True；当日已存在汇总记录（唯一约束冲突）返回 False。
    """
    exists = (
        db.query(AlertPushRecord.id)
        .filter(
            AlertPushRecord.alert_id == alert.id,
            AlertPushRecord.push_type == "daily_digest",
            AlertPushRecord.digest_date == digest_date,
        )
        .first()
    )
    if exists is not None:
        return False
    try:
        _create_push_records(db, alert, "daily_digest", digest_date)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
