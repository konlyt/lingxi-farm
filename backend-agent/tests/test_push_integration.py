"""预警邮件推送真实化集成测试（mock send_email，绝不发起真实 SMTP）。

验证内容：
1. 设备上报环境数据越限触发 env 预警后，逐启用用户落 alert_push_record：
   已绑定邮箱用户 status=sent、channel=email 且 send_email 以其邮箱为收件人被调用；
   未绑定用户 status=failed 且 content.error='接收人未绑定邮箱'；
2. send_email 恒失败路径：已绑定用户 status=failed 且 content.error 为非空错误信息；
3. 同 case_key 二次触发（合并）后写每日汇总：uk_digest 兜底每用户当日仅一条
   daily_digest 记录，第二次写入返回 False。

预警与推送记录挂在 pytest_ 前缀测试地块上（test_plot 夹具自动清理）；
邮箱通道配置经 monkeypatch 置为已配置、send_email 恒为记录型测试替身；
设备/阈值配置/测试用户/传感器读数在夹具 teardown 中删除（先删推送记录再删用户，
遵循外键依赖），不污染库中演示数据。
"""
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.advice import EnvironmentThresholdConfig
from app.models.alert import Alert, AlertPushRecord
from app.models.device import Device
from app.models.sensor import SensorReading
from app.models.user import SysUser
from app.services import notifier
from app.services.alert_service import create_daily_digest_push

# 测试用 SMTP 登录账号（使 is_email_configured 判定为已配置）
SMTP_TEST_USER = "pytest_sender@test.local"


def _patch_email_channel(monkeypatch: pytest.MonkeyPatch,
                         send_result: tuple[bool, str | None] = (True, None)) -> list[dict]:
    """将邮箱通道置为「已配置」并把 notifier.send_email 替换为记录型测试替身。

    Args:
        monkeypatch: pytest monkeypatch 夹具。
        send_result: 测试替身固定返回值 (是否发送成功, 失败原因)。

    Returns:
        list[dict]: 调用记录 [{to, subject, html}]，按调用顺序追加。
    """
    monkeypatch.setattr(settings, "email_user", SMTP_TEST_USER)
    monkeypatch.setattr(settings, "email_password", "pytest_auth_code")
    calls: list[dict] = []

    def fake_send(to: str, subject: str, html: str) -> tuple[bool, str | None]:
        """记录单次发送调用并返回预设结果。

        Args:
            to: 收件人邮箱。
            subject: 邮件主题。
            html: 邮件 HTML 正文。

        Returns:
            tuple[bool, str | None]: 预设的 (sent, err)。
        """
        calls.append({"to": to, "subject": subject, "html": html})
        return send_result

    monkeypatch.setattr(notifier, "send_email", fake_send)
    return calls


@pytest.fixture()
def push_scene(db: Session, test_plot, client: TestClient, owner_headers: dict) -> dict:
    """搭建推送集成场景：已绑定/未绑定测试用户 + 地块级温度阈值 + env 传感器设备。

    设备经 API 创建（绑定测试地块），阈值配置 max=30/min=10 直接落库；
    teardown 按「推送记录 → 传感器读数 → 设备 → 阈值 → 用户」顺序清理，
    预警与剩余推送记录由 test_plot 夹具随后清理。

    Args:
        db: 数据库会话。
        test_plot: 测试地块夹具。
        client: FastAPI 测试客户端。
        owner_headers: owner 认证头。

    Yields:
        dict: 场景数据 {device_id, threshold_id, bound, unbound}。
    """
    device_no = f"pytest_dev_{uuid.uuid4().hex[:12]}"
    create_resp = client.post(
        "/api/devices",
        json={
            "device_no": device_no,
            "name": "pytest 温湿度传感器",
            "type": "env_sensor",
            "plot_id": test_plot.id,
            "protocol": "MQTT",
        },
        headers=owner_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    device_id = create_resp.json()["data"]["id"]

    threshold = EnvironmentThresholdConfig(
        plot_id=test_plot.id,
        crop_name="番茄",
        growth_stage="结果期",
        metric="temp",
        max_value=30.0,
        min_value=10.0,
        is_default_template=0,
        enabled=1,
    )
    bound = SysUser(
        username=f"pytest_bound_{uuid.uuid4().hex[:10]}",
        password_hash="pytest-placeholder-hash",
        nickname="pytest 已绑定用户",
        role="member",
        status=1,
        email=f"pytest_bound_{uuid.uuid4().hex[:8]}@test.local",
        email_bind_status=1,
    )
    unbound = SysUser(
        username=f"pytest_unbound_{uuid.uuid4().hex[:10]}",
        password_hash="pytest-placeholder-hash",
        nickname="pytest 未绑定用户",
        role="member",
        status=1,
        email=None,
        email_bind_status=0,
    )
    db.add_all([threshold, bound, unbound])
    db.commit()
    db.refresh(threshold)
    db.refresh(bound)
    db.refresh(unbound)
    scene = {"device_id": device_id, "threshold_id": threshold.id, "bound": bound, "unbound": unbound}
    try:
        yield scene
    finally:
        db.rollback()
        db.query(AlertPushRecord).filter(
            AlertPushRecord.receiver_user_id.in_([bound.id, unbound.id])
        ).delete(synchronize_session=False)
        db.query(SensorReading).filter(SensorReading.plot_id == test_plot.id).delete(synchronize_session=False)
        db.query(Device).filter(Device.id == device_id).delete(synchronize_session=False)
        db.query(EnvironmentThresholdConfig).filter(
            EnvironmentThresholdConfig.id == threshold.id
        ).delete(synchronize_session=False)
        db.query(SysUser).filter(SysUser.id.in_([bound.id, unbound.id])).delete(synchronize_session=False)
        db.commit()


def _report_over_limit(client: TestClient, device_id: int, owner_headers: dict, value: float) -> dict:
    """触发一次越限环境上报（temp 超上限 30）。

    Args:
        client: 测试客户端。
        device_id: 传感器设备ID。
        owner_headers: owner 认证头。
        value: 上报温度值（>30 即越限）。

    Returns:
        dict: 响应 data（含逐条判定结果 results）。
    """
    resp = client.post(
        f"/api/devices/{device_id}/report",
        json={"readings": [{"metric": "temp", "value": value}]},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


class TestEnvAlertPushIntegration:
    """env 预警触发 → 推送记录落库 → 邮件真实发送（mock）集成测试。"""

    def test_bound_user_sent_and_unbound_failed(
        self, db: Session, test_plot, push_scene: dict, monkeypatch: pytest.MonkeyPatch,
        client: TestClient, owner_headers: dict,
    ) -> None:
        """发送成功路径：绑定用户 sent（收件人正确、无 error），未绑定用户 failed。"""
        calls = _patch_email_channel(monkeypatch)
        data = _report_over_limit(client, push_scene["device_id"], owner_headers, 35.0)
        assert data["results"][0]["exceeded"] is True

        # 结束当前事务快照，读取 API 独立会话已提交的预警与推送记录
        db.rollback()
        db.expire_all()
        alert = db.query(Alert).filter(Alert.case_key == f"plot:{test_plot.id}:env:temp").first()
        assert alert is not None
        assert alert.status == "active"
        assert alert.content.get("metric") == "temp"
        assert alert.content.get("direction") == "high"

        bound = push_scene["bound"]
        unbound = push_scene["unbound"]
        bound_rec = (
            db.query(AlertPushRecord)
            .filter(
                AlertPushRecord.alert_id == alert.id,
                AlertPushRecord.push_type == "instant",
                AlertPushRecord.receiver_user_id == bound.id,
            )
            .first()
        )
        assert bound_rec is not None
        assert bound_rec.channel == "email"
        assert bound_rec.status == "sent"
        assert (bound_rec.content or {}).get("error") is None

        unbound_rec = (
            db.query(AlertPushRecord)
            .filter(
                AlertPushRecord.alert_id == alert.id,
                AlertPushRecord.push_type == "instant",
                AlertPushRecord.receiver_user_id == unbound.id,
            )
            .first()
        )
        assert unbound_rec is not None
        assert unbound_rec.status == "failed"
        assert (unbound_rec.content or {}).get("error") == "接收人未绑定邮箱"

        # 真实发送仅面向已绑定邮箱用户，收件人与主题正确
        recipients = [item["to"] for item in calls]
        assert bound.email in recipients
        assert all(item["to"] for item in calls)
        assert calls[0]["subject"].startswith("【农情预警】")

    def test_send_failure_marks_failed_with_error(
        self, db: Session, test_plot, push_scene: dict, monkeypatch: pytest.MonkeyPatch,
        client: TestClient, owner_headers: dict,
    ) -> None:
        """发送失败路径：绑定用户 failed 且 content.error 为非空错误信息（含重试语义）。"""
        error_message = "SMTPConnectError: pytest SMTP 连接失败"
        _patch_email_channel(monkeypatch, send_result=(False, error_message))
        _report_over_limit(client, push_scene["device_id"], owner_headers, 35.0)

        db.rollback()
        db.expire_all()
        alert = db.query(Alert).filter(Alert.case_key == f"plot:{test_plot.id}:env:temp").first()
        assert alert is not None

        bound = push_scene["bound"]
        bound_rec = (
            db.query(AlertPushRecord)
            .filter(
                AlertPushRecord.alert_id == alert.id,
                AlertPushRecord.push_type == "instant",
                AlertPushRecord.receiver_user_id == bound.id,
            )
            .first()
        )
        assert bound_rec is not None
        assert bound_rec.status == "failed"
        assert (bound_rec.content or {}).get("error") == error_message
        assert (bound_rec.content or {}).get("error")

        unbound_rec = (
            db.query(AlertPushRecord)
            .filter(
                AlertPushRecord.alert_id == alert.id,
                AlertPushRecord.push_type == "instant",
                AlertPushRecord.receiver_user_id == push_scene["unbound"].id,
            )
            .first()
        )
        assert unbound_rec is not None
        assert unbound_rec.status == "failed"
        assert (unbound_rec.content or {}).get("error") == "接收人未绑定邮箱"

    def test_daily_digest_push_unique_per_day(
        self, db: Session, test_plot, push_scene: dict, monkeypatch: pytest.MonkeyPatch,
        client: TestClient, owner_headers: dict,
    ) -> None:
        """同 case_key 二次触发合并即触发当日汇总，uk_digest 每用户仅一条，重复写入 False。"""
        _patch_email_channel(monkeypatch)
        # 首次触发（新建）+ 二次触发（同 case_key 合并，occurrence+1，合并路径自动创建当日汇总）
        _report_over_limit(client, push_scene["device_id"], owner_headers, 35.0)
        _report_over_limit(client, push_scene["device_id"], owner_headers, 36.0)

        db.rollback()
        db.expire_all()
        alert = db.query(Alert).filter(Alert.case_key == f"plot:{test_plot.id}:env:temp").first()
        assert alert is not None
        assert alert.occurrence_count == 2

        # 合并路径已自动写入当日汇总，再次调用应被 uk_digest/查重拦截返回 False
        again_ok = create_daily_digest_push(db, alert, date.today())
        assert again_ok is False

        for user in (push_scene["bound"], push_scene["unbound"]):
            digest_count = (
                db.query(AlertPushRecord)
                .filter(
                    AlertPushRecord.alert_id == alert.id,
                    AlertPushRecord.push_type == "daily_digest",
                    AlertPushRecord.digest_date == date.today(),
                    AlertPushRecord.receiver_user_id == user.id,
                )
                .count()
            )
            assert digest_count == 1
