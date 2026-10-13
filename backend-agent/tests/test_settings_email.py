"""推送邮箱绑定 API 集成测试（GET/PUT /api/settings/email，mock send_email）。

验证内容：
1. PUT 非法邮箱格式（不符合简易正则）被 422 拒绝，且 sys_user.email 未被写入；
2. 该邮箱已被其他用户绑定时 PUT 返回 400「该邮箱已被其他用户绑定」；
3. member 成功绑定/修改自己的邮箱：响应含 email/email_bind_status=1/bind_mail_sent=True，
   GET 回读一致，send_email 以绑定邮箱为收件人发出绑定成功通知；
4. owner 绑定成功后 email_bind_status=1（响应与数据库双重校验）。

邮箱绑定会写种子账号（owner/member）的 email 字段，guard 夹具先行备份原值、
用例结束后完整还原，不污染演示数据；send_email 全程经 monkeypatch 替换，
绝不发起真实 SMTP 请求。
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import SysUser
from app.services import notifier

# 邮箱绑定接口路径
EMAIL_URL = "/api/settings/email"


def _patch_send_success(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """将 notifier.send_email 替换为恒成功的记录型测试替身。

    Args:
        monkeypatch: pytest monkeypatch 夹具。

    Returns:
        list[dict]: 调用记录 [{to, subject, html}]。
    """
    calls: list[dict] = []

    def fake_send(to: str, subject: str, html: str) -> tuple[bool, None]:
        """记录单次发送调用（恒成功）。

        Args:
            to: 收件人邮箱。
            subject: 邮件主题。
            html: 邮件 HTML 正文。

        Returns:
            tuple[bool, None]: 恒 (True, None)。
        """
        calls.append({"to": to, "subject": subject, "html": html})
        return True, None

    monkeypatch.setattr(notifier, "send_email", fake_send)
    return calls


def _unique_email(prefix: str) -> str:
    """生成 pytest 专用唯一邮箱地址。

    Args:
        prefix: 地址本地段前缀。

    Returns:
        str: 形如 pytest_{prefix}_{hex}@test.local 的唯一邮箱。
    """
    return f"pytest_{prefix}_{uuid.uuid4().hex[:10]}@test.local"


@pytest.fixture()
def seed_email_guard(db: Session):
    """备份种子账号（owner/member）email 字段原值，用例结束后完整还原。

    Args:
        db: 数据库会话。

    Yields:
        dict: {用户ID: (原 email, 原 email_bind_status)} 备份映射。
    """
    db.rollback()
    rows = db.query(SysUser).filter(SysUser.username.in_(["owner", "member"])).all()
    original = {row.id: (row.email, row.email_bind_status) for row in rows}
    yield original
    db.rollback()
    rows = db.query(SysUser).filter(SysUser.id.in_(list(original.keys()))).all()
    for row in rows:
        email, status = original[row.id]
        row.email = email
        row.email_bind_status = status
    db.commit()
    db.expire_all()


class TestEmailBindApi:
    """推送邮箱绑定 GET/PUT 接口测试。"""

    def test_put_invalid_format_rejected(
        self, client: TestClient, owner_headers: dict, db: Session, seed_email_guard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PUT 非法格式邮箱返回 422，且用户 email 字段未被写库。"""
        # 兜底替换发送点（非法请求在参数校验层即被拦截，不应触达发送）
        calls = _patch_send_success(monkeypatch)

        for bad_email in ("pytest@invalid", "pytest user@test.local"):
            resp = client.put(EMAIL_URL, json={"email": bad_email}, headers=owner_headers)
            assert resp.status_code == 422, resp.text
            assert resp.json()["code"] == 422

        assert calls == []
        db.rollback()
        owner = db.query(SysUser).filter(SysUser.username == "owner").first()
        assert owner is not None
        assert (owner.email, owner.email_bind_status) == seed_email_guard[owner.id]

    def test_put_email_conflict_with_other_user(
        self, client: TestClient, owner_headers: dict, member_headers: dict, seed_email_guard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """邮箱已被其他用户绑定时 PUT 返回 400，提示「该邮箱已被其他用户绑定」。"""
        _patch_send_success(monkeypatch)
        email = _unique_email("conflict")

        member_put = client.put(EMAIL_URL, json={"email": email}, headers=member_headers)
        assert member_put.status_code == 200, member_put.text
        assert member_put.json()["data"]["email"] == email

        owner_put = client.put(EMAIL_URL, json={"email": email}, headers=owner_headers)
        assert owner_put.status_code == 400
        assert "其他用户" in owner_put.json()["message"]

    def test_member_bind_self_and_readback(
        self, client: TestClient, member_headers: dict, seed_email_guard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """member 绑定自己的邮箱成功：响应字段齐备，GET 回读一致，通知邮件收件人正确。"""
        calls = _patch_send_success(monkeypatch)
        email = _unique_email("member")

        put_resp = client.put(EMAIL_URL, json={"email": email}, headers=member_headers)
        assert put_resp.status_code == 200, put_resp.text
        data = put_resp.json()["data"]
        assert data["email"] == email
        assert data["email_bind_status"] == 1
        assert data["bind_mail_sent"] is True

        get_resp = client.get(EMAIL_URL, headers=member_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["data"] == {"email": email, "email_bind_status": 1}

        assert len(calls) == 1
        assert calls[0]["to"] == email
        assert "绑定成功" in calls[0]["subject"]

    def test_owner_bind_sets_bind_status(
        self, client: TestClient, owner_headers: dict, db: Session, seed_email_guard,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """owner 绑定成功后 email_bind_status=1（接口响应与数据库双重校验）。"""
        _patch_send_success(monkeypatch)
        email = _unique_email("owner")

        put_resp = client.put(EMAIL_URL, json={"email": email}, headers=owner_headers)
        assert put_resp.status_code == 200, put_resp.text
        assert put_resp.json()["data"]["email_bind_status"] == 1

        get_resp = client.get(EMAIL_URL, headers=owner_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["email"] == email
        assert get_resp.json()["data"]["email_bind_status"] == 1

        # 数据库层回读（结束当前事务快照后读取 API 会话已提交的数据）
        db.rollback()
        db.expire_all()
        owner = db.query(SysUser).filter(SysUser.username == "owner").first()
        assert owner is not None
        assert owner.email == email
        assert owner.email_bind_status == 1
