"""pytest 全局夹具与测试数据清理模块。

提供：
- client：FastAPI TestClient（in-process，不占用 8000 端口，不触发 lifespan/定时任务）；
- owner_headers / member_headers：种子账号登录后的认证头（会话级复用）；
- test_plot：函数级测试地块夹具（pytest_ 前缀唯一名，用后自动清理全部关联数据）；
- make_png_bytes：现场生成测试用 PNG 图像字节流（Pillow）；
- cleanup_plot_data：地块关联数据彻底清理（预警/推送/诊断/案例/禁令/图像/检查点/上传文件）。

测试直连真实 MySQL（localhost:3306/Ai_Farm_Manage），禁止 mock 数据库；
外部大模型（DeepSeek/豆包 VLM/智谱）一律通过 monkeypatch 替换，绝不真实调用。
"""
import io
import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.main import app
from app.models.alert import Alert, AlertPushRecord
from app.models.case import CaseImage, CaseLibrary
from app.models.diagnosis import DiagnosisResult, DiagnosisTask, DiagnosisTaskImage, PreventionPlan
from app.models.image import CollectedImage
from app.models.knowledge import HarvestRestriction
from app.models.misc import LanggraphCheckpoint
from app.models.plot import Plot
from app.services.image_service import UPLOAD_DIR

# 种子账号（初始化脚本写入，owner/123456 与 member/123456）
OWNER_ACCOUNT = {"username": "owner", "password": "123456"}
MEMBER_ACCOUNT = {"username": "member", "password": "123456"}


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI 测试客户端夹具（会话级复用）。

    注意：不使用 with 上下文，避免触发 lifespan（不启动 APScheduler 定时任务、
    不重复建表），且全程 in-process 请求，不监听任何端口。

    Returns:
        TestClient: 已注册全部路由的测试客户端实例。
    """
    return TestClient(app)


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """数据库会话夹具（函数级，用后关闭）。

    Returns:
        Session: SQLAlchemy 会话实例。

    Raises:
        Exception: 数据库连接失败时抛出，测试标记为错误。
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _login(client: TestClient, account: dict) -> dict[str, str]:
    """使用种子账号登录并组装 Bearer 认证头。

    Args:
        client: FastAPI 测试客户端。
        account: 登录账号 {username, password}。

    Returns:
        dict[str, str]: {Authorization: Bearer <token>} 请求头。

    Raises:
        AssertionError: 登录接口返回非 200 或 code 非 0 时失败。
    """
    resp = client.post("/api/auth/login", json=account)
    assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["code"] == 0, f"登录业务失败: {body}"
    return {"Authorization": f"Bearer {body['data']['token']}"}


@pytest.fixture(scope="session")
def owner_headers(client: TestClient) -> dict[str, str]:
    """owner 角色认证头夹具（全权限农场主）。

    Args:
        client: 测试客户端。

    Returns:
        dict[str, str]: Bearer 认证请求头。
    """
    return _login(client, OWNER_ACCOUNT)


@pytest.fixture(scope="session")
def member_headers(client: TestClient) -> dict[str, str]:
    """member 角色认证头夹具（只读家庭成员）。

    Args:
        client: 测试客户端。

    Returns:
        dict[str, str]: Bearer 认证请求头。
    """
    return _login(client, MEMBER_ACCOUNT)


def _delete_uploaded_file(cos_url: str | None) -> None:
    """按图像记录的 cos_url 删除 uploads 目录下的物理文件（防路径穿越）。

    Args:
        cos_url: 形如 /uploads/2026_10/xxx.png 的存储相对路径（可空）。
    """
    if not cos_url:
        return
    relative = cos_url.removeprefix("/uploads/")
    upload_root = UPLOAD_DIR.resolve()
    target = (UPLOAD_DIR / relative).resolve()
    if str(target).startswith(str(upload_root)) and target.is_file():
        target.unlink()


def cleanup_plot_data(db: Session, plot_id: int) -> None:
    """删除地块及其全部关联测试数据（含上传文件与 LangGraph 检查点）。

    删除顺序遵循外键依赖：检查点/案例 → 禁令/方案/结果/任务图像 → 任务 →
    推送记录/预警 → 图像 → 地块。先 rollback 结束当前事务快照，
    保证能读到其他会话（TestClient 请求 / 后台任务）已提交的数据。

    Args:
        db: 数据库会话（清理完成后 commit）。
        plot_id: 待清理的测试地块ID。
    """
    db.rollback()
    task_ids = [row[0] for row in db.query(DiagnosisTask.id).filter(DiagnosisTask.plot_id == plot_id).all()]
    if task_ids:
        thread_ids = [
            row[0] for row in db.query(DiagnosisTask.thread_id).filter(DiagnosisTask.id.in_(task_ids)).all()
        ]
        if thread_ids:
            db.query(LanggraphCheckpoint).filter(
                LanggraphCheckpoint.thread_id.in_(thread_ids)
            ).delete(synchronize_session=False)
        case_ids = [row[0] for row in db.query(CaseLibrary.id).filter(CaseLibrary.task_id.in_(task_ids)).all()]
        if case_ids:
            db.query(CaseImage).filter(CaseImage.case_id.in_(case_ids)).delete(synchronize_session=False)
            db.query(CaseLibrary).filter(CaseLibrary.id.in_(case_ids)).delete(synchronize_session=False)
        plan_ids = [row[0] for row in db.query(PreventionPlan.id).filter(PreventionPlan.task_id.in_(task_ids)).all()]
        if plan_ids:
            db.query(HarvestRestriction).filter(
                HarvestRestriction.plan_id.in_(plan_ids)
            ).delete(synchronize_session=False)
            db.query(PreventionPlan).filter(PreventionPlan.id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(DiagnosisResult).filter(DiagnosisResult.task_id.in_(task_ids)).delete(synchronize_session=False)
        # 预警 task_id 外键引用 diagnosis_task，必须先于任务删除
        alert_ids = [row[0] for row in db.query(Alert.id).filter(Alert.plot_id == plot_id).all()]
        if alert_ids:
            db.query(AlertPushRecord).filter(AlertPushRecord.alert_id.in_(alert_ids)).delete(synchronize_session=False)
            db.query(Alert).filter(Alert.plot_id == plot_id).delete(synchronize_session=False)
        db.query(DiagnosisTaskImage).filter(DiagnosisTaskImage.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(DiagnosisTask).filter(DiagnosisTask.plot_id == plot_id).delete(synchronize_session=False)
    else:
        alert_ids = [row[0] for row in db.query(Alert.id).filter(Alert.plot_id == plot_id).all()]
        if alert_ids:
            db.query(AlertPushRecord).filter(AlertPushRecord.alert_id.in_(alert_ids)).delete(synchronize_session=False)
            db.query(Alert).filter(Alert.plot_id == plot_id).delete(synchronize_session=False)

    for image in db.query(CollectedImage).filter(CollectedImage.plot_id == plot_id).all():
        _delete_uploaded_file(image.cos_url)
    db.query(CollectedImage).filter(CollectedImage.plot_id == plot_id).delete(synchronize_session=False)

    db.query(Plot).filter(Plot.id == plot_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture(scope="function")
def test_plot(db: Session) -> Generator[Plot, None, None]:
    """函数级测试地块夹具：创建 pytest_ 前缀唯一名地块，用例结束自动清理。

    Args:
        db: 数据库会话。

    Yields:
        Plot: 已入库的测试地块 ORM 实例（含自增ID）。
    """
    plot = Plot(
        name=f"pytest_地块_{uuid.uuid4().hex[:10]}",
        type="greenhouse",
        crop_name="番茄",
        growth_stage="结果期",
        status=1,
    )
    db.add(plot)
    db.commit()
    db.refresh(plot)
    try:
        yield plot
    finally:
        cleanup_plot_data(db, plot.id)


def make_png_bytes(width: int = 64, height: int = 64, seed: int = 0) -> bytes:
    """现场生成测试用 PNG 图像字节流（渐变纹理，dhash 可区分不同 seed）。

    Args:
        width: 图像宽度（像素）。
        height: 图像高度（像素）。
        seed: 渐变相位偏移，不同 seed 生成像素排布不同的图像。

    Returns:
        bytes: PNG 编码的图像完整字节流。
    """
    image = Image.new("RGB", (width, height))
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), ((x * 4 + seed * 37) % 256, (y * 4) % 256, (128 + seed * 53) % 256))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
