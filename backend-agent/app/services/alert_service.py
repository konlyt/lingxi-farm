"""预警聚合去重业务服务模块。

实现 create_or_merge_alert：同 case_key 未解决期间合并（occurrence_count+1、
时间线追加），病情加重时升级 level 并补即时推送记录；新预警落库并即时推送。
推送仅落 alert_push_record 表（status=sent），不调用真实微信 API；
uk_digest(alert_id, push_type, digest_date) 唯一约束兜底每日汇总一条。
"""
import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertPushRecord
from app.models.user import SysUser
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


def _create_push_records(db: Session, alert: Alert, push_type: str, digest_date: Optional[date]) -> None:
    """为预警写入推送记录（所有启用用户，channel=wechat_sa，status=sent）。

    Args:
        db: 数据库会话（由调用方 commit）。
        alert: 预警实例。
        push_type: 推送类型 instant/daily_digest。
        digest_date: 汇总日期（daily_digest 必填，instant 传 None）。
    """
    users = db.query(SysUser).filter(SysUser.status == 1).all()
    for user in users:
        record = AlertPushRecord(
            alert_id=alert.id,
            push_type=push_type,
            digest_date=digest_date,
            channel="wechat_sa",
            receiver_user_id=user.id,
            content={
                "title": alert.title,
                "level": alert.level,
                "occurrence_count": alert.occurrence_count,
            },
            status="sent",
            sent_at=now(),
        )
        db.add(record)


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
