"""系统设置接口集成测试：置信度阈值配置与环境报警阈值校验。

覆盖内容：
1. GET /api/settings/confidence-thresholds 返回种子配置（common/default/rare）；
2. PUT 编辑置信度阈值：非法值（>1）被参数校验拒绝（400/422），
   合法值更新即时生效，测后恢复原值（不破坏演示数据）；
3. member 调用配置写接口 403；
4. POST /api/environment/thresholds：min >= max 返回 400、上下限同时缺失返回 400；
5. 合法环境阈值创建后经 DELETE 清理（自造自清）。
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.advice import ConfidenceThresholdConfig

# 置信度阈值 PUT 接口路径
THRESHOLD_URL = "/api/settings/confidence-thresholds"


def _get_default_config(db: Session) -> ConfidenceThresholdConfig:
    """查询 default 分类的置信度配置行。

    Args:
        db: 数据库会话。

    Returns:
        ConfidenceThresholdConfig: default 配置 ORM 实例。

    Raises:
        AssertionError: 种子配置缺失时失败。
    """
    row = (
        db.query(ConfidenceThresholdConfig)
        .filter(ConfidenceThresholdConfig.disease_category == "default")
        .first()
    )
    assert row is not None, "种子配置缺少 default 分类"
    return row


class TestConfidenceThresholdSettings:
    """置信度阈值配置 GET/PUT 接口测试。"""

    def test_get_thresholds_returns_seed_config(self, client: TestClient, owner_headers: dict) -> None:
        """GET 返回 200，包含 common/default/rare 三类种子配置。"""
        resp = client.get(THRESHOLD_URL, headers=owner_headers)
        assert resp.status_code == 200, resp.text
        items = {item["disease_category"]: item for item in resp.json()["data"]}
        assert {"common", "default", "rare"} <= set(items.keys())
        assert items["common"]["threshold"] == pytest.approx(0.85)
        assert items["default"]["threshold"] == pytest.approx(0.90)
        assert items["rare"]["threshold"] == pytest.approx(0.95)

    def test_put_threshold_invalid_value_rejected(self, client: TestClient, owner_headers: dict, db: Session) -> None:
        """PUT 非法阈值（>1）被 400/422 拒绝，且库中配置未被修改。"""
        config = _get_default_config(db)
        original = float(config.threshold)
        resp = client.put(
            THRESHOLD_URL,
            json={"items": [{"id": config.id, "threshold": 1.5}]},
            headers=owner_headers,
        )
        assert resp.status_code in (400, 422)
        db.rollback()  # 读取最新库值校验未被写入
        config = _get_default_config(db)
        assert float(config.threshold) == pytest.approx(original)

    def test_put_threshold_valid_update_takes_effect(self, client: TestClient, owner_headers: dict, db: Session) -> None:
        """PUT 合法阈值（0.91）更新即时生效，测毕恢复原值 0.90。"""
        config = _get_default_config(db)
        original = float(config.threshold)
        try:
            resp = client.put(
                THRESHOLD_URL,
                json={"items": [{"id": config.id, "threshold": 0.91}]},
                headers=owner_headers,
            )
            assert resp.status_code == 200, resp.text
            updated = {item["disease_category"]: item for item in resp.json()["data"]}
            assert updated["default"]["threshold"] == pytest.approx(0.91)
            # 再次 GET 验证已持久化生效
            reget = client.get(THRESHOLD_URL, headers=owner_headers).json()["data"]
            assert any(item["threshold"] == pytest.approx(0.91) for item in reget)
        finally:
            # 恢复种子原值，保证演示数据不被破坏
            restore = client.put(
                THRESHOLD_URL,
                json={"items": [{"id": config.id, "threshold": original}]},
                headers=owner_headers,
            )
            assert restore.status_code == 200
        db.rollback()
        assert float(_get_default_config(db).threshold) == pytest.approx(original)

    def test_member_cannot_update_threshold(self, client: TestClient, member_headers: dict, db: Session) -> None:
        """member 调用配置编辑接口返回 403（只读角色拦截）。"""
        config = _get_default_config(db)
        resp = client.put(
            THRESHOLD_URL,
            json={"items": [{"id": config.id, "threshold": 0.5}]},
            headers=member_headers,
        )
        assert resp.status_code == 403


class TestEnvironmentThresholdValidation:
    """环境报警阈值上下限校验测试（POST /api/environment/thresholds）。"""

    def _payload(self, **overrides) -> dict:
        """构造合法阈值请求体（默认模板形态），支持字段覆盖。

        Args:
            **overrides: 覆盖默认字段的键值对。

        Returns:
            dict: 请求体字典。
        """
        payload = {
            "plot_id": None,
            "crop_name": f"pytest作物{uuid.uuid4().hex[:6]}",
            "growth_stage": "pytest期",
            "metric": "temp",
            "max_value": 35.0,
            "min_value": 10.0,
            "is_default_template": 1,
            "enabled": 1,
        }
        payload.update(overrides)
        return payload

    def test_min_ge_max_rejected(self, client: TestClient, owner_headers: dict) -> None:
        """min >= max 请求返回 400（下限必须小于上限）。"""
        resp = client.post(
            "/api/environment/thresholds",
            json=self._payload(min_value=40.0, max_value=35.0),
            headers=owner_headers,
        )
        assert resp.status_code == 400
        assert "下限" in resp.json()["message"]

        equal_resp = client.post(
            "/api/environment/thresholds",
            json=self._payload(min_value=35.0, max_value=35.0),
            headers=owner_headers,
        )
        assert equal_resp.status_code == 400

    def test_missing_bounds_rejected(self, client: TestClient, owner_headers: dict) -> None:
        """上下限同时缺失返回 400（至少填写一项）。"""
        resp = client.post(
            "/api/environment/thresholds",
            json=self._payload(min_value=None, max_value=None),
            headers=owner_headers,
        )
        assert resp.status_code == 400

    def test_valid_threshold_create_and_delete(self, client: TestClient, owner_headers: dict, db: Session) -> None:
        """合法模板创建成功后经 DELETE 清理，列表中不再出现（自造自清）。"""
        crop_name = f"pytest作物{uuid.uuid4().hex[:6]}"
        create_resp = client.post(
            "/api/environment/thresholds",
            json=self._payload(crop_name=crop_name),
            headers=owner_headers,
        )
        assert create_resp.status_code == 200, create_resp.text
        config_id = create_resp.json()["data"]["id"]

        delete_resp = client.delete(f"/api/environment/thresholds/{config_id}", headers=owner_headers)
        assert delete_resp.status_code == 200
        assert delete_resp.json()["data"]["deleted"] is True

        db.rollback()
        remaining = client.get(
            "/api/environment/thresholds", headers=owner_headers
        ).json()["data"]["templates"]
        assert all(item["id"] != config_id for item in remaining)
