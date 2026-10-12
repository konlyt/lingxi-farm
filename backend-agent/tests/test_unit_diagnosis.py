"""诊断置信度判定与安全间隔期单元测试。

验证内容：
1. _get_threshold 按 confidence_threshold_config 分病种匹配阈值
   （种子配置 common=0.85 / default=0.90 / rare=0.95），未知分类 fallback 至 default，
   default 也缺失时 fallback 至硬编码 0.90；
2. 通过 monkeypatch 替换全部外部大模型客户端后执行真实 LangGraph 图：
   - 高置信度（≥病种阈值）→ 生成防治方案卡，banned 药剂 is_forbidden_blocked=1，
     banned 药剂不生成采收禁令，allowed 药剂自动生成
     harvest_restriction（ban_until = applied_at + safety_interval_days）；
   - 低置信度（<阈值）→ 标注「建议咨询农技专家」并存待确认案例库（status=pending）。

全程不真实调用 DeepSeek/豆包 VLM/智谱接口；任务与结果数据挂在 pytest_ 前缀
测试地块上，用例结束自动清理。
"""
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.agents.graph import _get_threshold
from app.models.advice import ConfidenceThresholdConfig
from app.models.alert import Alert
from app.models.case import CaseLibrary
from app.models.diagnosis import DiagnosisTask, PreventionPlan
from app.models.knowledge import HarvestRestriction
from app.services import diagnosis_service
from app.services.image_service import save_upload_image
from conftest import make_png_bytes

# pytest 模拟病害名（含于 VLM mock 返回值，用于聚合键与案例名断言）
DISEASE_HIGH = f"pytest灰霉病{uuid.uuid4().hex[:6]}"
DISEASE_LOW = f"pytest疑似病{uuid.uuid4().hex[:6]}"


def _patch_llm_clients(monkeypatch: pytest.MonkeyPatch, vlm_result: dict, plan_card: dict | None = None) -> None:
    """替换全部外部大模型调用点（图执行所需的最小 mock 集合）。

    Args:
        monkeypatch: pytest monkeypatch 夹具。
        vlm_result: 豆包 VLM 识别结果的固定返回值。
        plan_card: 防治方案卡固定返回值（None 表示不应被调用）。
    """
    from app.agents.llm import clients
    from app.services import vector_store

    monkeypatch.setattr(
        clients, "diagnose_image_with_vlm",
        lambda image_path, crop_name, growth_stage: dict(vlm_result),
    )
    # RAG 检索片段：文本中包含「多菌灵」(allowed) 与「克百威」(banned)，
    # 触发 knowledge_node 的用药合规校验与禁用药拦截路径
    monkeypatch.setattr(
        vector_store, "search",
        lambda query, top_k=3: [
            {"title": "pytest知识片段", "text": "灰霉病防治可选用 多菌灵 喷雾；严禁使用 克百威 等禁用农药", "similarity": 0.92},
        ],
    )
    if plan_card is not None:
        monkeypatch.setattr(
            clients, "generate_plan_with_llm",
            lambda disease_name, crop_name, growth_stage, contexts, compliance_notes: dict(plan_card),
        )


def _create_task_with_image(db: Session, test_plot, source: str = "manual") -> DiagnosisTask:
    """为测试地块上传一张图像并创建诊断任务（pending）。

    Args:
        db: 数据库会话。
        test_plot: 测试地块实例。
        source: 图像来源标记。

    Returns:
        DiagnosisTask: 已落库的诊断任务实例。
    """
    item = save_upload_image(
        db=db,
        file_bytes=make_png_bytes(seed=1),
        filename=f"pytest_{uuid.uuid4().hex[:8]}.png",
        plot_id=test_plot.id,
        source=source,
        device_id=None,
        uploaded_by=None,
    )
    return diagnosis_service.create_task(
        db, plot_id=test_plot.id, growth_stage="结果期", image_ids=[item["id"]], source=source
    )


class TestThresholdLookup:
    """置信度阈值查询（confidence_threshold_config 匹配与 fallback）测试。"""

    @pytest.mark.parametrize(
        "category, expected",
        [("common", 0.85), ("default", 0.90), ("rare", 0.95)],
        ids=["常见病0.85", "默认0.90", "罕见病0.95"],
    )
    def test_threshold_by_seed_category(self, db: Session, category: str, expected: float) -> None:
        """按种子配置分病种匹配：common=0.85 / default=0.90 / rare=0.95。"""
        row = (
            db.query(ConfidenceThresholdConfig)
            .filter(ConfidenceThresholdConfig.disease_category == category)
            .first()
        )
        assert row is not None, f"种子配置缺少分类 {category}"
        assert float(row.threshold) == pytest.approx(expected)
        assert _get_threshold(db, category) == pytest.approx(expected)

    def test_unknown_category_falls_back_to_default(self, db: Session) -> None:
        """未知病种分类回退到 default 配置（0.90）而非硬编码值。"""
        assert _get_threshold(db, "pytest_unknown_category") == pytest.approx(0.90)

    def test_missing_all_config_falls_back_to_hardcoded(self) -> None:
        """分类与 default 配置均缺失时回退硬编码 0.90（mock 数据库会话，不触碰真实数据）。"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert _get_threshold(mock_db, "rare") == pytest.approx(0.90)


class TestDiagnosisChain:
    """诊断链路置信度分流测试（mock LLM，执行真实 LangGraph 图与状态流转）。"""

    def test_high_confidence_generates_plan_and_restriction(self, db: Session, test_plot, monkeypatch) -> None:
        """高置信度流：common 阈值 0.85，confidence 0.97 → 方案生成 + 禁用药拦截 + 禁令计算。"""
        plan_card = {
            "summary": "pytest 模拟防治方案",
            "pesticides": [
                {"name": "80%多菌灵可湿性粉剂", "dosage": "800倍液", "method": "喷雾"},
                {"name": "克百威颗粒剂", "dosage": "-", "method": "-"},
            ],
            "precautions": "pytest 注意事项",
        }
        _patch_llm_clients(
            monkeypatch,
            vlm_result={
                "disease_name": DISEASE_HIGH,
                "disease_category": "常见病",  # 中文别名，应归一化为 common（0.85）
                "confidence": 0.97,
                "description": "pytest 模拟识别结果",
            },
            plan_card=plan_card,
        )
        task = _create_task_with_image(db, test_plot)
        # 同步执行后台诊断（LLM 已被 mock，不发起外部请求）
        diagnosis_service.run_task(task.id)

        # 结束当前事务快照并清空 identity map 缓存，
        # 确保 run_task 独立会话的落库结果对本会话可见（否则读到对象缓存的旧状态）
        db.rollback()
        db.expire_all()
        task = db.query(DiagnosisTask).filter(DiagnosisTask.id == task.id).first()
        assert task.status == "done"
        assert task.result_level == "high"
        # fused_confidence 为 DECIMAL(5,4)，读回为 Decimal，转 float 后比较
        assert float(task.fused_confidence) == pytest.approx(0.97, abs=1e-4)

        plan = db.query(PreventionPlan).filter(PreventionPlan.task_id == task.id).first()
        assert plan is not None
        # 方案中出现 banned 药剂「克百威」→ 拦截标记置 1 且校验结论含 banned 名单
        assert plan.is_forbidden_blocked == 1
        assert "克百威" in (plan.compliance_result or {}).get("banned", [])

        # banned 药剂不建禁令；allowed「多菌灵」（安全间隔期 14 天）自动生成禁令
        restrictions = (
            db.query(HarvestRestriction).filter(HarvestRestriction.plot_id == test_plot.id).all()
        )
        assert len(restrictions) == 1
        restriction = restrictions[0]
        expected_ban_until = restriction.applied_at.fromordinal(
            restriction.applied_at.toordinal() + 14
        )
        assert restriction.ban_until == expected_ban_until
        assert restriction.status == "active"

        # 确诊非健康病害 → pest 预警聚合生成
        alert = (
            db.query(Alert)
            .filter(Alert.case_key == f"plot:{test_plot.id}:pest:{DISEASE_HIGH}")
            .first()
        )
        assert alert is not None
        assert alert.status == "active"

    def test_low_confidence_saves_pending_case(self, db: Session, test_plot, monkeypatch) -> None:
        """低置信度流：default 阈值 0.90，confidence 0.50 → 任务 low + 待确认案例，不出方案。"""
        _patch_llm_clients(
            monkeypatch,
            vlm_result={
                "disease_name": DISEASE_LOW,
                "disease_category": "default",
                "confidence": 0.50,
                "description": "pytest 病斑模糊疑似病害",
            },
        )
        task = _create_task_with_image(db, test_plot)
        diagnosis_service.run_task(task.id)

        db.rollback()
        db.expire_all()
        task = db.query(DiagnosisTask).filter(DiagnosisTask.id == task.id).first()
        assert task.status == "done"
        assert task.result_level == "low"

        case = db.query(CaseLibrary).filter(CaseLibrary.task_id == task.id).first()
        assert case is not None
        assert case.status == "pending"
        assert case.ai_disease_name == DISEASE_LOW

        # 低置信度不生成防治方案与采收禁令
        assert db.query(PreventionPlan).filter(PreventionPlan.task_id == task.id).first() is None
        assert db.query(HarvestRestriction).filter(HarvestRestriction.plot_id == test_plot.id).count() == 0
