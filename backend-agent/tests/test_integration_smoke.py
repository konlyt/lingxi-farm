"""API 集成冒烟测试（FastAPI TestClient in-process，不占用 8000 端口）。

覆盖端到端关键流程：
1. owner 登录签发 JWT，GET /api/plots 地块列表；
2. POST 创建 pytest_ 前缀唯一名测试地块并出现在列表；
3. PUT 编辑地块档案（仅更新传入字段）；
4. member 登录后调用写接口 POST /api/plots 断言 403（角色只读拦截）；
5. PATCH 停用地块；
6. POST /api/images 上传 Pillow 现场生成的 PNG（BytesIO），重复上传命中去重；
7. monkeypatch 掉 graph 执行函数后 POST /api/diagnosis/tasks，
   断言任务创建成功且 status 为 pending/running（不等待真实诊断）；
8. 用例结束清理全部测试数据（预警/诊断/图像/文件/地块）。

全程直连真实 MySQL；不 mock 数据库、不真实调用外部大模型。
"""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services import diagnosis_service
from app.services.image_service import save_upload_image
from conftest import cleanup_plot_data, make_png_bytes

# 测试地块名称前缀（便于库中辨识与清理兜底检索）
PLOT_PREFIX = "pytest_smoke"


def test_owner_login_and_list_plots(client: TestClient, owner_headers: dict) -> None:
    """owner 登录后查询地块列表：200 且返回标准分页结构。"""
    resp = client.get("/api/plots", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert isinstance(data["items"], list)
    assert {"items", "total", "page", "page_size"} <= set(data.keys())


def test_plot_create_update_status_and_member_forbidden(
    client: TestClient, db: Session, owner_headers: dict, member_headers: dict
) -> None:
    """地块档案冒烟：创建→列表可见→编辑→member 写操作 403→PATCH 停用。

    Args:
        client: 测试客户端。
        db: 数据库会话（finally 清理 API 自建地块）。
        owner_headers: owner 认证头。
        member_headers: member 认证头。
    """
    # 1) owner 创建测试地块（唯一名 + pytest_ 前缀）
    plot_name = f"{PLOT_PREFIX}_{uuid.uuid4().hex[:10]}"
    create_resp = client.post(
        "/api/plots",
        json={"name": plot_name, "type": "greenhouse", "crop_name": "黄瓜", "growth_stage": "苗期"},
        headers=owner_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    plot_id = create_resp.json()["data"]["id"]

    try:
        # 2) 创建后出现在列表中
        list_resp = client.get("/api/plots", headers=owner_headers, params={"page_size": 100})
        names = [item["name"] for item in list_resp.json()["data"]["items"]]
        assert plot_name in names

        # 3) PUT 编辑（仅更新传入字段）
        update_resp = client.put(
            f"/api/plots/{plot_id}",
            json={"crop_variety": "pytest品种", "remark": "pytest 冒烟编辑"},
            headers=owner_headers,
        )
        assert update_resp.status_code == 200, update_resp.text
        detail_resp = client.get(f"/api/plots/{plot_id}", headers=owner_headers)
        detail = detail_resp.json()["data"]
        assert detail["crop_variety"] == "pytest品种"
        assert detail["crop_name"] == "黄瓜"  # 未传字段保持不变

        # 4) member 调用写接口 → 403 只读拦截
        member_create_resp = client.post(
            "/api/plots",
            json={"name": f"{PLOT_PREFIX}_member_{uuid.uuid4().hex[:8]}", "type": "greenhouse",
                  "crop_name": "黄瓜", "growth_stage": "苗期"},
            headers=member_headers,
        )
        assert member_create_resp.status_code == 403
        assert "只读" in member_create_resp.json()["message"] or "权限" in member_create_resp.json()["message"]

        # 5) member 读接口放行（GET 类）
        member_list_resp = client.get("/api/plots", headers=member_headers)
        assert member_list_resp.status_code == 200

        # 6) PATCH 停用地块
        patch_resp = client.patch(
            f"/api/plots/{plot_id}/status", json={"status": 0}, headers=owner_headers
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["data"]["status"] == 0
    finally:
        # API 无 DELETE 接口，测试自建地块经数据库清理（含关联数据与上传文件）
        cleanup_plot_data(db, plot_id)


def test_image_upload_and_duplicate(client: TestClient, owner_headers: dict, test_plot) -> None:
    """图像上传冒烟：Pillow 生成 PNG 上传入库，重复上传命中感知哈希去重。"""
    png_bytes = make_png_bytes(seed=8)
    upload_resp = client.post(
        "/api/images",
        files=[("files", ("pytest_smoke.png", png_bytes, "image/png"))],
        data={"plot_id": str(test_plot.id), "source": "manual"},
        headers=owner_headers,
    )
    assert upload_resp.status_code == 200, upload_resp.text
    items = upload_resp.json()["data"]
    assert len(items) == 1
    assert items[0]["duplicate"] is False
    assert items[0]["url"].startswith("/uploads/")

    duplicate_resp = client.post(
        "/api/images",
        files=[("files", ("pytest_smoke_again.png", png_bytes, "image/png"))],
        data={"plot_id": str(test_plot.id), "source": "manual"},
        headers=owner_headers,
    )
    assert duplicate_resp.status_code == 200
    dup_items = duplicate_resp.json()["data"]
    assert dup_items[0]["duplicate"] is True
    assert dup_items[0]["id"] == items[0]["id"]


def test_diagnosis_task_creation_mocked_graph(
    client: TestClient, db: Session, owner_headers: dict, test_plot, monkeypatch
) -> None:
    """诊断任务创建冒烟：mock 掉 graph 执行函数，断言任务创建成功且状态为 pending/running。"""
    # mock 后台图执行：任务保持创建时状态，绝不真实调用大模型
    monkeypatch.setattr(diagnosis_service, "run_task", lambda task_id: None)

    item = save_upload_image(
        db=db, file_bytes=make_png_bytes(seed=9), filename="pytest_diag.png",
        plot_id=test_plot.id, source="manual", device_id=None, uploaded_by=None,
    )
    create_resp = client.post(
        "/api/diagnosis/tasks",
        json={"plot_id": test_plot.id, "growth_stage": "结果期", "image_ids": [item["id"]]},
        headers=owner_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    data = create_resp.json()["data"]
    assert data["task_id"] > 0
    assert data["thread_id"]
    assert data["status"] in ("pending", "running")

    # 轮询详情接口：任务可查且状态一致
    detail_resp = client.get(f"/api/diagnosis/tasks/{data['task_id']}", headers=owner_headers)
    assert detail_resp.status_code == 200
    assert detail_resp.json()["data"]["status"] in ("pending", "running")


def test_diagnosis_task_validation_errors(
    client: TestClient, db: Session, owner_headers: dict, test_plot, monkeypatch
) -> None:
    """诊断任务创建校验：图像数量越界 422、无效图像ID 400。"""
    monkeypatch.setattr(diagnosis_service, "run_task", lambda task_id: None)

    empty_resp = client.post(
        "/api/diagnosis/tasks",
        json={"plot_id": test_plot.id, "image_ids": []},
        headers=owner_headers,
    )
    assert empty_resp.status_code == 422

    invalid_resp = client.post(
        "/api/diagnosis/tasks",
        json={"plot_id": test_plot.id, "image_ids": [999999999]},
        headers=owner_headers,
    )
    assert invalid_resp.status_code == 400
