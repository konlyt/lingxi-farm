"""邮件通知服务（notifier）单元测试（mock smtplib，绝不发起真实网络请求）。

验证内容：
1. send_email 配置齐全（SMTP_SSL 465 / timeout 15s）：发送成功返回 (True, None)，
   且 SMTP 主机/端口/超时、login 账号、sendmail 的 from/to 与报文头均正确；
2. SMTP 异常路径：自动重试 1 次（SMTP_SSL 共实例化 2 次），两次均失败返回
   (False, 含异常类型与信息的错误串)；
3. EMAIL_USER 为空（邮箱通道未配置）：直接返回 (False, '邮箱未配置')，
   全程不建立 SMTP 连接；
4. notify_owner_task_failure 1 小时节流：窗口内连续两次调用仅实际发送一封，
   重置模块级时间戳（模拟窗口过期）后可再次发送。

发送行为经 monkeypatch 替换 smtplib.SMTP_SSL 全程拦截；节流时间戳经
monkeypatch 设置并在用例后自动还原，保证可重复执行（幂等）。
"""
import smtplib
import uuid
from typing import Generator

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import SysUser
from app.services import notifier


class FakeSMTP:
    """smtplib.SMTP_SSL 测试替身：记录构造/login/sendmail/quit 调用，支持故障注入。

    Attributes:
        instances: 全部实例化记录（用于断言重试次数）。
        behavior: 行为模式，"success" 正常发送 / "fail" sendmail 恒抛异常。
    """

    instances: list["FakeSMTP"] = []
    behavior: str = "success"

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        """记录连接参数并登记实例。

        Args:
            host: SMTP 主机。
            port: SMTP 端口。
            timeout: 连接超时秒数。
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.login_calls: list[tuple[str, str]] = []
        self.sendmail_calls: list[tuple[str, list[str], str]] = []
        self.quit_calls = 0
        FakeSMTP.instances.append(self)

    def login(self, user: str, password: str) -> None:
        """记录登录调用（模拟登录恒成功）。

        Args:
            user: 登录账号。
            password: 登录密码/授权码。
        """
        self.login_calls.append((user, password))

    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
        """记录或拒绝发送（按 behavior 注入故障）。

        Args:
            from_addr: 发件人地址。
            to_addrs: 收件人地址列表。
            msg: 完整邮件报文。

        Raises:
            RuntimeError: behavior 为 "fail" 时模拟网络/服务异常。
        """
        if FakeSMTP.behavior == "fail":
            raise RuntimeError("pytest smtp down")
        self.sendmail_calls.append((from_addr, list(to_addrs), msg))

    def quit(self) -> None:
        """记录连接关闭次数（可重复调用，模拟真实语义宽松）。"""
        self.quit_calls += 1


@pytest.fixture()
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    """以测试替身替换 smtplib.SMTP_SSL 并隔离外部影响（sleep/邮箱配置）。

    同时将 settings 的邮箱五项配置替换为 pytest 专用值，保证断言确定性；
    全部替换在用例结束后由 monkeypatch 自动还原。

    Args:
        monkeypatch: pytest monkeypatch 夹具。

    Returns:
        type[FakeSMTP]: 测试替身类（读取 instances/behavior 做断言）。
    """
    FakeSMTP.instances = []
    FakeSMTP.behavior = "success"
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    # 重试间隔 sleep 置空，避免失败路径用例真实等待 2 秒
    monkeypatch.setattr(notifier.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(settings, "email_host", "smtp.pytest.local")
    monkeypatch.setattr(settings, "email_port", 465)
    monkeypatch.setattr(settings, "email_user", "pytest_sender@test.local")
    monkeypatch.setattr(settings, "email_password", "pytest_auth_code")
    monkeypatch.setattr(settings, "email_sender", "")
    return FakeSMTP


class TestSendEmail:
    """send_email 发送/重试/未配置三条路径测试。"""

    def test_send_success_returns_true_with_correct_params(self, fake_smtp: type[FakeSMTP]) -> None:
        """配置齐全时发送成功：返回 (True, None)，SSL/主机/端口/超时/from/to 参数正确。"""
        sent, err = notifier.send_email(
            "pytest_receiver@test.local", "pytest 邮件主题", "<p>pytest 正文</p>"
        )
        assert sent is True
        assert err is None
        assert len(fake_smtp.instances) == 1
        smtp = fake_smtp.instances[0]
        # SMTP_SSL(host, port, timeout=15)：SSL 连接与超时参数
        assert smtp.host == "smtp.pytest.local"
        assert smtp.port == 465
        assert smtp.timeout == 15
        # login 使用 EMAIL_USER/EMAIL_PASSWORD
        assert smtp.login_calls == [("pytest_sender@test.local", "pytest_auth_code")]
        # sendmail from=发件人（email_sender 为空回落 email_user），to=收件人列表，报文含 Subject/From/To
        assert len(smtp.sendmail_calls) == 1
        from_addr, to_addrs, msg = smtp.sendmail_calls[0]
        assert from_addr == "pytest_sender@test.local"
        assert to_addrs == ["pytest_receiver@test.local"]
        assert "Subject:" in msg
        assert "From:" in msg
        assert "pytest_receiver@test.local" in msg
        assert smtp.quit_calls >= 1

    def test_send_failure_retries_once_and_returns_error(self, fake_smtp: type[FakeSMTP]) -> None:
        """SMTP 异常时重试 1 次（共 2 次连接），两次均失败返回含错误信息的 (False, err)。"""
        fake_smtp.behavior = "fail"
        sent, err = notifier.send_email(
            "pytest_receiver@test.local", "pytest 失败主题", "<p>pytest 正文</p>"
        )
        assert sent is False
        assert err is not None
        assert "RuntimeError" in err
        assert "pytest smtp down" in err
        assert len(fake_smtp.instances) == 2

    def test_email_not_configured_skips_smtp(self, fake_smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch) -> None:
        """EMAIL_USER 为空（通道未配置）直接返回 (False, '邮箱未配置')，不建立任何 SMTP 连接。"""
        monkeypatch.setattr(settings, "email_user", "")
        monkeypatch.setattr(settings, "email_password", "")
        sent, err = notifier.send_email(
            "pytest_receiver@test.local", "pytest 未配置主题", "<p>pytest 正文</p>"
        )
        assert (sent, err) == (False, "邮箱未配置")
        assert fake_smtp.instances == []


@pytest.fixture()
def pytest_owner_user(db: Session) -> Generator[SysUser, None, None]:
    """创建一个已绑定邮箱的 pytest_ 前缀 owner 测试用户，用例结束后删除。

    Args:
        db: 数据库会话。

    Yields:
        SysUser: 已入库的 owner 用户 ORM 实例（含自增ID）。
    """
    user = SysUser(
        username=f"pytest_owner_{uuid.uuid4().hex[:10]}",
        password_hash="pytest-placeholder-hash",
        nickname="pytest 告警接收人",
        role="owner",
        status=1,
        email=f"pytest_owner_{uuid.uuid4().hex[:8]}@test.local",
        email_bind_status=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    try:
        yield user
    finally:
        db.rollback()
        db.query(SysUser).filter(SysUser.id == user.id).delete(synchronize_session=False)
        db.commit()


class TestNotifyOwnerTaskFailure:
    """notify_owner_task_failure 诊断失败告警 1 小时节流测试。"""

    def test_throttle_only_one_send_within_one_hour(
        self, db: Session, pytest_owner_user, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1 小时窗口内连续两次失败告警仅实际发送一封邮件。"""
        calls: list[tuple[str, str]] = []

        def fake_send(to: str, subject: str, html: str) -> tuple[bool, None]:
            """记录发送调用的测试替身（恒成功）。

            Args:
                to: 收件人邮箱。
                subject: 邮件主题。
                html: 邮件正文。

            Returns:
                tuple[bool, None]: 恒 (True, None)。
            """
            calls.append((to, subject))
            return True, None

        # 重置模块级节流时间戳（monkeypatch 自动还原，保证幂等）
        monkeypatch.setattr(notifier, "send_email", fake_send)
        monkeypatch.setattr(notifier, "_last_failure_alert_ts", 0.0)

        notifier.notify_owner_task_failure(db, 9001, "pytest 失败原因一")
        notifier.notify_owner_task_failure(db, 9002, "pytest 失败原因二")

        assert len(calls) == 1
        assert calls[0][1].startswith("【系统告警】")

    def test_reset_timestamp_allows_send_again(
        self, db: Session, pytest_owner_user, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """重置模块级时间戳（模拟 1 小时窗口过期）后可再次发送（累计两封）。"""
        calls: list[tuple[str, str]] = []

        def fake_send(to: str, subject: str, html: str) -> tuple[bool, None]:
            """记录发送调用的测试替身（恒成功）。

            Args:
                to: 收件人邮箱。
                subject: 邮件主题。
                html: 邮件正文。

            Returns:
                tuple[bool, None]: 恒 (True, None)。
            """
            calls.append((to, subject))
            return True, None

        monkeypatch.setattr(notifier, "send_email", fake_send)
        monkeypatch.setattr(notifier, "_last_failure_alert_ts", 0.0)

        notifier.notify_owner_task_failure(db, 9001, "pytest 失败原因")
        assert len(calls) == 1

        # 直接重置模块级时间戳，模拟第二个节流窗口
        notifier._last_failure_alert_ts = 0.0
        notifier.notify_owner_task_failure(db, 9002, "pytest 失败原因")
        assert len(calls) == 2
