"""邮件通知服务模块。

基于 smtplib + SMTP_SSL(465) 发送 HTML 邮件，配置读取 .env 的
EMAIL_HOST/EMAIL_PORT/EMAIL_USER/EMAIL_PASSWORD/EMAIL_SENDR 五项；
提供预警/每日汇总/农情简报/绑定通知/诊断失败告警五类 HTML 模板渲染函数。

关键约定：
- EMAIL_USER/EMAIL_PASSWORD 留空视为「邮箱通道未配置」：send_email 直接返回
  (False, '邮箱未配置')，不抛异常，保证未配置时系统其余链路正常运转；
- 发送失败自动重试 1 次（间隔 2 秒），两次均失败返回最后一次错误信息；
- 诊断失败告警 notify_owner_task_failure 使用模块级时间戳做 1 小时节流。
"""
import logging
import smtplib
import time
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.utils.time_utils import fmt_datetime

logger = logging.getLogger("farm_notifier")

# 统一 HTML 邮件基础样式（中文字体内联，兼容 QQ 邮箱等客户端不加载外部 CSS）
_BASE_STYLE = (
    "font-family:'Microsoft YaHei','PingFang SC','Hiragino Sans GB',sans-serif;"
    "font-size:14px;color:#333;line-height:1.7;"
)
# 卡片容器样式
_CARD_STYLE = (
    "max-width:560px;margin:16px auto;padding:24px 28px;"
    "border:1px solid #e4e7ed;border-radius:8px;background:#ffffff;"
)
# 标题样式
_TITLE_STYLE = "margin:0 0 12px;font-size:18px;color:#1f2d3d;"
# 键值行样式
_ROW_STYLE = "margin:4px 0;"
# 强调色文字（等级/越限值）
_CRITICAL_COLOR = "#c0392b"
_WARNING_COLOR = "#b8860b"

# 诊断失败告警上次发送时间戳（模块级，进程内 1 小时节流）
_last_failure_alert_ts: float = 0.0
# 失败告警最小发送间隔（秒）：1 小时
_FAILURE_ALERT_INTERVAL_SECONDS = 3600


def is_email_configured() -> bool:
    """判断邮箱发送通道是否已配置。

    以 EMAIL_USER 与 EMAIL_PASSWORD 是否同时非空为准（占位空即未配置）。

    Returns:
        bool: 已配置返回 True，未配置返回 False。
    """
    return bool(settings.email_user and settings.email_password)


def _build_message(to_list: list[str], subject: str, html: str) -> MIMEMultipart:
    """构造 HTML MIME 邮件消息体。

    Args:
        to_list: 收件人邮箱地址列表。
        subject: 邮件主题。
        html: HTML 正文。

    Returns:
        MIMEMultipart: 可直接 sendmail 的邮件对象（Subject/From/To 齐备）。
    """
    sender = settings.email_sender or settings.email_user
    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("农场智能管护系统", "utf-8")), sender))
    msg["To"] = ", ".join(to_list)
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def send_email(to: str | list[str], subject: str, html: str) -> tuple[bool, Optional[str]]:
    """发送 HTML 邮件（SMTP_SSL 465 端口，失败重试 1 次）。

    流程：SMTP_SSL 连接(超时 15s) → login → sendmail → quit；
    任何一步异常均捕获，重试 1 次（间隔 2 秒），两次均失败返回最后一次错误。
    邮箱通道未配置（EMAIL_USER/PASSWORD 为空）时直接返回 (False, '邮箱未配置')。

    Args:
        to: 收件人，单个邮箱字符串或邮箱列表。
        subject: 邮件主题。
        html: HTML 正文（内联样式）。

    Returns:
        tuple[bool, str|None]: (是否发送成功, 失败原因)；成功时错误信息为 None。

    Raises:
        None: 不向外抛出任何异常，所有失败均以 (False, 错误信息) 返回。
    """
    if not is_email_configured():
        logger.info("邮箱通道未配置（EMAIL_USER/EMAIL_PASSWORD 为空），跳过发送: subject=%s", subject)
        return False, "邮箱未配置"
    recipients = [to] if isinstance(to, str) else list(to)
    sender = settings.email_sender or settings.email_user
    last_error: Optional[str] = None
    for attempt in (1, 2):
        smtp: Optional[smtplib.SMTP_SSL] = None
        try:
            smtp = smtplib.SMTP_SSL(settings.email_host, settings.email_port, timeout=15)
            smtp.login(settings.email_user, settings.email_password)
            smtp.sendmail(sender, recipients, _build_message(recipients, subject, html).as_string())
            smtp.quit()
            logger.info("邮件发送成功: to=%s subject=%s attempt=%s", recipients, subject, attempt)
            return True, None
        except Exception as exc:  # noqa: BLE001 网络异常/认证失败等一律捕获重试
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("邮件发送失败(第 %s 次): to=%s subject=%s err=%s", attempt, recipients, subject, last_error)
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:  # noqa: BLE001 连接已断开时忽略
                    pass
        if attempt == 1:
            time.sleep(2)  # 重试间隔 2 秒
    return False, last_error


def _render_html(title: str, rows: list[tuple[str, str]], footer: str = "") -> str:
    """按统一卡片模板渲染 HTML 邮件正文。

    Args:
        title: 卡片标题（如预警标题/简报标题）。
        rows: 键值对行列表 [(标签, 值)]，值可为含内联样式的 HTML 片段。
        footer: 底部补充说明（可空）。

    Returns:
        str: 完整 HTML 文本。
    """
    row_html = "".join(
        f'<p style="{_ROW_STYLE}"><strong>{label}：</strong>{value}</p>' for label, value in rows
    )
    footer_html = f'<p style="{_ROW_STYLE}color:#909399;font-size:12px;">{footer}</p>' if footer else ""
    return (
        f'<div style="{_CARD_STYLE}">'
        f'<h2 style="{_TITLE_STYLE}">{title}</h2>'
        f'{row_html}'
        f'{footer_html}'
        f'<p style="{_ROW_STYLE}color:#909399;font-size:12px;">—— 农场智能管护系统（自动邮件，请勿回复）</p>'
        f'</div>'
    )


def _level_display(level: str) -> str:
    """将预警级别码转换为带颜色的中文展示片段。

    Args:
        level: 级别码 info/warning/critical。

    Returns:
        str: 带内联颜色的 HTML 片段（如 <span style="...">紧急</span>）。
    """
    mapping = {
        "info": ("提示", "#67c23a"),
        "warning": ("警告", _WARNING_COLOR),
        "critical": ("紧急", _CRITICAL_COLOR),
    }
    text, color = mapping.get(level, (level, "#333"))
    return f'<span style="color:{color};font-weight:bold;">{text}</span>'


def _alert_summary_rows(alert: Any) -> list[tuple[str, str]]:
    """从预警 content JSON 提取通用摘要行（兼容 env/pest/weather/device_offline）。

    Args:
        alert: 预警 ORM 实例（含 content JSON）。

    Returns:
        list[tuple[str, str]]: 摘要行列表，键值已转 HTML 安全文本。
    """
    import html as html_lib

    def esc(value: Any) -> str:
        """对值做 HTML 转义。

        Args:
            value: 任意标量值。

        Returns:
            str: 转义后的字符串（None 转为 '-'）。
        """
        return html_lib.escape(str(value)) if value is not None else "-"

    content = alert.content or {}
    rows: list[tuple[str, str]] = [("预警类型", esc(content.get("metric") and "环境越限" or _type_display(alert.type)))]
    if content.get("metric"):
        direction = "高于上限" if content.get("direction") == "high" else "低于下限"
        threshold = content.get("threshold") or {}
        bound = threshold.get("max") if content.get("direction") == "high" else threshold.get("min")
        rows.append(("越限详情", f'<span style="color:{_CRITICAL_COLOR};font-weight:bold;">'
                                f'{esc(content.get("value"))}{esc(content.get("unit"))}'
                                f'（{direction} {esc(bound)}）</span>'))
    if content.get("disease_name"):
        rows.append(("识别病害", esc(content.get("disease_name"))))
    if content.get("confidence") is not None:
        rows.append(("置信度", esc(round(float(content["confidence"]), 4))))
    if content.get("description"):
        rows.append(("内容摘要", esc(content["description"])))
    if content.get("latest_image_url"):
        rows.append(("最新照片", f'<a href="{esc(content["latest_image_url"])}">{esc(content["latest_image_url"])}</a>'))
    if content.get("device_no"):
        rows.append(("设备编号", esc(content["device_no"])))
    rows.append(("累计触发", f'{esc(alert.occurrence_count)} 次'))
    rows.append(("触发时间", esc(fmt_datetime(alert.first_triggered_at))))
    return rows


def _type_display(alert_type: str) -> str:
    """将预警类型码转换为中文名称。

    Args:
        alert_type: 类型码 pest/env/weather/device_offline。

    Returns:
        str: 中文名称（病虫害/环境/气象/设备离线），未知类型原样返回。
    """
    mapping = {"pest": "病虫害", "env": "环境", "weather": "气象", "device_offline": "设备离线"}
    return mapping.get(alert_type, alert_type)


def render_alert_email(alert: Any, plot_name: str) -> str:
    """渲染预警即时通知邮件 HTML（首次触发/病情升级）。

    Args:
        alert: 预警 ORM 实例。
        plot_name: 归属地块名称。

    Returns:
        str: HTML 邮件正文（标题/等级/地块/摘要/时间，中文字体内联）。
    """
    rows = [
        ("预警等级", _level_display(alert.level)),
        ("所属地块", plot_name or "-"),
        *_alert_summary_rows(alert),
    ]
    return _render_html(f"【农情预警】{alert.title}", rows, footer="请及时前往预警详情页处理。")


def render_daily_digest_email(alert: Any, plot_name: str) -> str:
    """渲染预警每日汇总邮件 HTML（同预警当日合并为一条，含病情变化）。

    Args:
        alert: 预警 ORM 实例（content.updates 时间线含病情变化）。
        plot_name: 归属地块名称。

    Returns:
        str: HTML 邮件正文。
    """
    import html as html_lib

    rows = [
        ("预警等级", _level_display(alert.level)),
        ("所属地块", plot_name or "-"),
        *_alert_summary_rows(alert),
    ]
    # 时间线变化：取最近 3 条更新事件
    updates = (alert.content or {}).get("updates", [])[-3:]
    timeline = "".join(
        f'<li>{html_lib.escape(str(item.get("time", "")))} {html_lib.escape(str(item.get("event", "")))}</li>'
        for item in updates
    )
    if timeline:
        rows.append(("病情变化", f'<ul style="margin:4px 0;padding-left:18px;">{timeline}</ul>'))
    return _render_html(f"【每日汇总】{alert.title}", rows, footer="本邮件按每日一条合并汇总，详情请登录系统查看。")


def render_brief_email(brief: Any) -> str:
    """渲染每日农情简报邮件 HTML（07:00 生成后推送）。

    Args:
        brief: DailyBrief ORM 实例（content JSON 含 plot_summaries/today_todos/weather_reminders）。

    Returns:
        str: HTML 邮件正文。
    """
    import html as html_lib

    def esc(value: Any) -> str:
        """对值做 HTML 转义。

        Args:
            value: 任意标量值。

        Returns:
            str: 转义后的字符串（None 转为 '-'）。
        """
        return html_lib.escape(str(value)) if value is not None else "-"

    content = brief.content or {}
    rows: list[tuple[str, str]] = []
    # 各地块实况摘要
    for summary in content.get("plot_summaries", []):
        env = summary.get("env") or {}
        env_text = "、".join(f"{k} {v}" for k, v in env.items()) if env else "暂无数据"
        rows.append((f"地块实况 · {esc(summary.get('plot_name'))}",
                     f"{esc(summary.get('crop'))}；{html_lib.escape(env_text)}；"
                     f"活跃预警 {esc(summary.get('active_alerts', 0))} 条"))
    # 今日待办
    todos = content.get("today_todos", [])
    if todos:
        todo_text = "<br/>".join(
            f"{esc(item.get('plot_name'))}：灌溉 {esc(item.get('irrigate') or '—')}；施肥 {esc(item.get('fertilize') or '—')}"
            for item in todos
        )
        rows.append(("今日待办", todo_text))
    # 天气提醒
    reminders = content.get("weather_reminders", [])
    if reminders:
        rows.append(("天气提醒", "<br/>".join(esc(item) for item in reminders)))
    if not rows:
        rows.append(("今日概况", "暂无地块数据"))
    return _render_html(f"【每日农情简报】{brief.brief_date.isoformat()}", rows, footer="祝您农事顺利。")


def render_bind_email(email: str) -> str:
    """渲染邮箱绑定成功通知邮件 HTML。

    Args:
        email: 新绑定的邮箱地址。

    Returns:
        str: HTML 邮件正文。
    """
    import html as html_lib

    rows = [
        ("绑定邮箱", html_lib.escape(email)),
        ("生效状态", '<span style="color:#67c23a;font-weight:bold;">已绑定（保存即生效）</span>'),
        ("接收内容", "农情预警、病情升级、每日汇总与每日农情简报"),
    ]
    return _render_html("【绑定成功】推送邮箱已生效", rows, footer="如非本人操作，请立即登录系统修改绑定邮箱。")


def render_failure_alert_email(task_id: int, reason: str) -> str:
    """渲染诊断任务失败告警邮件 HTML（发给 owner，1 小时节流）。

    Args:
        task_id: 失败的诊断任务ID。
        reason: 失败原因（异常信息摘要）。

    Returns:
        str: HTML 邮件正文。
    """
    import html as html_lib

    rows = [
        ("任务ID", f'#{task_id}'),
        ("失败原因", f'<span style="color:{_CRITICAL_COLOR};">{html_lib.escape(reason or "未知错误")}</span>'),
        ("处理建议", "可在「诊断记录」页对该任务发起重试；若持续失败请检查模型服务配置。"),
    ]
    return _render_html("【系统告警】诊断任务执行失败", rows, footer="本告警 1 小时内最多发送一次，防止轰炸。")


def notify_owner_task_failure(db: Session, task_id: int, reason: str) -> None:
    """诊断任务失败时向 owner 发送告警邮件（1 小时节流，未绑定邮箱跳过）。

    使用模块级时间戳做节流：距上次实际发送不足 1 小时直接跳过；
    owner 未绑定邮箱或邮箱通道未配置时同样跳过，均不抛异常。

    Args:
        db: 数据库会话（只读查询 owner 用户，由调用方管理事务）。
        task_id: 失败的诊断任务ID。
        reason: 失败原因。

    Returns:
        None: 发送结果仅记录日志。

    Raises:
        None: 不向外抛出任何异常，失败仅记日志，保证失败处理链路不受影响。
    """
    global _last_failure_alert_ts
    current_ts = time.time()
    if current_ts - _last_failure_alert_ts < _FAILURE_ALERT_INTERVAL_SECONDS:
        logger.info("诊断失败告警 1 小时节流命中，跳过发送: task_id=%s", task_id)
        return
    from app.models.user import SysUser

    owner = (
        db.query(SysUser)
        .filter(SysUser.role == "owner", SysUser.status == 1, SysUser.email_bind_status == 1)
        .first()
    )
    if owner is None or not owner.email:
        logger.info("owner 未绑定邮箱，跳过诊断失败告警邮件: task_id=%s", task_id)
        return
    html = render_failure_alert_email(task_id, reason)
    sent, err = send_email(owner.email, f"【系统告警】诊断任务 #{task_id} 执行失败", html)
    if sent:
        _last_failure_alert_ts = current_ts
        logger.info("诊断失败告警邮件已发送: task_id=%s to=%s", task_id, owner.email)
    else:
        logger.warning("诊断失败告警邮件发送失败: task_id=%s err=%s", task_id, err)
