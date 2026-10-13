"""VLM 置信度增强（三次采样投票融合）单元与集成测试（全程 mock LLM）。

验证内容：
1. _vote_fuse 纯函数融合规则：
   - 3/3 同病名 → 一致样本均值 ×1.05 上浮（封顶 0.99）；
   - 2/3 同病名 → 一致样本均值（剔除不一致样本）不上浮；
   - 全不一致 → 回落首轮病名，融合置信度 = 首轮 ×0.8，描述注明「不一致」；
2. 识别节点两段式链路（真实 LangGraph 图，diagnosis_service.run_task 驱动）：
   - VLM_ENHANCE_ENABLED=false：不调 vlm_diagnose_multi、不触发 RAG 检索，首轮单次直通；
   - 首轮判定 healthy：不进入增强分支；
   - 3/3 一致端到端：fused_confidence = 均值×1.05，raw_output 记录 samples 与 vote 明细，
     增强提示词注入封闭候选集；
   - 全不一致端到端：置信度 ×0.8 判低置信并存待确认案例。

外部大模型（首轮 VLM/三次采样/方案生成）与向量检索全部经 monkeypatch 替换，
绝不发起真实请求；诊断任务与产出挂在 pytest_ 前缀测试地块上，用例结束自动清理。
"""
import uuid
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.agents.graph import _vote_fuse
from app.core.config import settings
from app.models.alert import Alert
from app.models.case import CaseLibrary
from app.models.diagnosis import DiagnosisResult, DiagnosisTask, PreventionPlan
from app.services import diagnosis_service
from app.services.image_service import save_upload_image
from conftest import make_png_bytes

# pytest 模拟病名（uuid 唯一，避免与库中演示数据冲突）
DISEASE_CONSENSUS = f"pytest早疫病{uuid.uuid4().hex[:6]}"
DISEASE_INCONSISTENT = f"pytest软腐病{uuid.uuid4().hex[:6]}"


def _sample(name: str, confidence: float, category: str = "常见病") -> dict[str, Any]:
    """构造单条 VLM 采样结果明细。

    Args:
        name: 采样判定的病名。
        confidence: 采样置信度（0-1）。
        category: 病种分类（默认「常见病」）。

    Returns:
        dict: {disease_name, disease_category, confidence, description}。
    """
    return {
        "disease_name": name,
        "disease_category": category,
        "confidence": confidence,
        "description": f"pytest 采样描述·{name}",
    }


class TestVoteFuse:
    """_vote_fuse 三次采样投票融合规则纯函数测试。"""

    def test_unanimous_mean_uplift(self) -> None:
        """3/3 一致：融合置信度 = 一致样本均值 ×1.05（0.86×1.05≈0.903）。"""
        samples = [_sample("pytest灰霉病", 0.85), _sample("pytest灰霉病", 0.87), _sample("pytest灰霉病", 0.86)]
        vote = _vote_fuse(samples, "pytest首轮病名", "common", 0.90)
        assert vote["consistent_count"] == 3
        assert vote["final_disease"] == "pytest灰霉病"
        assert vote["fused_confidence"] == pytest.approx(0.903, abs=1e-4)
        assert vote["rule"] == "3/3_consensus_mean_x1.05"

    def test_unanimous_capped_at_099(self) -> None:
        """3/3 一致且均值上浮后超过 1：融合置信度封顶 0.99。"""
        samples = [_sample("pytest白粉病", 0.99), _sample("pytest白粉病", 0.99), _sample("pytest白粉病", 0.99)]
        vote = _vote_fuse(samples, "pytest首轮病名", "common", 0.99)
        assert vote["consistent_count"] == 3
        assert vote["fused_confidence"] == pytest.approx(0.99, abs=1e-4)

    def test_two_thirds_majority_mean_no_uplift(self) -> None:
        """2/3 一致：融合置信度 = 一致样本均值（剔除不一致样本），不上浮。"""
        samples = [
            _sample("pytest灰霉病", 0.80),
            _sample("pytest灰霉病", 0.82),
            _sample("pytest白粉病", 0.95),
        ]
        vote = _vote_fuse(samples, "pytest首轮病名", "common", 0.90)
        assert vote["consistent_count"] == 2
        assert vote["final_disease"] == "pytest灰霉病"
        assert vote["fused_confidence"] == pytest.approx(0.81, abs=1e-4)
        assert vote["rule"] == "2/3_majority_mean_no_uplift"

    def test_all_inconsistent_fallback_first_x08(self) -> None:
        """全不一致：回落首轮病名，融合置信度 = 首轮×0.8，描述注明不一致。"""
        samples = [_sample("pytest甲病", 0.90), _sample("pytest乙病", 0.90), _sample("pytest丙病", 0.90)]
        vote = _vote_fuse(samples, "pytest首轮病名", "common", 0.90)
        assert vote["consistent_count"] == 0
        assert vote["final_disease"] == "pytest首轮病名"
        assert vote["fused_confidence"] == pytest.approx(0.72, abs=1e-4)
        assert vote["rule"] == "0/3_inconsistent_first_x0.8"
        assert "不一致" in vote["final_description"]


def _patch_enhanced_llm(monkeypatch: pytest.MonkeyPatch, first_result: dict[str, Any],
                        samples: list[dict[str, Any]]) -> tuple[list[dict], list[str]]:
    """替换首轮 VLM、三次采样、RAG 检索与方案生成全部调用点（记录调用）。

    Args:
        monkeypatch: pytest monkeypatch 夹具。
        first_result: 首轮单次调用识别结果。
        samples: vlm_diagnose_multi 固定返回（三次采样明细）。

    Returns:
        tuple[list[dict], list[str]]: (采样调用记录 [{n, prompt}], 检索查询记录)。
    """
    from app.agents.llm import clients
    from app.services import vector_store

    multi_calls: list[dict] = []
    search_calls: list[str] = []

    def fake_first(image_path: str, crop_name: str, growth_stage: str) -> dict[str, Any]:
        """首轮识别测试替身（返回固定结果）。

        Args:
            image_path: 图像文件路径。
            crop_name: 作物名称。
            growth_stage: 生育期。

        Returns:
            dict: 固定识别结果副本。
        """
        return dict(first_result)

    def fake_multi(image_paths: list[str], prompt: str, n: int = 3) -> list[dict[str, Any]]:
        """三次采样测试替身（记录调用参数并返回固定样本）。

        Args:
            image_paths: 图像路径列表。
            prompt: 增强用户提示词。
            n: 采样次数。

        Returns:
            list[dict]: 固定采样明细副本列表。
        """
        multi_calls.append({"n": n, "prompt": prompt})
        return [dict(item) for item in samples]

    def fake_search(query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """RAG 检索测试替身（记录查询文本，返回空命中）。

        Args:
            query: 检索查询文本。
            top_k: 命中条数上限。

        Returns:
            list[dict]: 恒为空列表。
        """
        search_calls.append(query)
        return []

    def fake_plan(disease_name: str, crop_name: str, growth_stage: str,
                  contexts: list[str], compliance_notes: str) -> dict[str, Any]:
        """方案生成测试替身（返回最小方案卡，不含药剂）。

        Args:
            disease_name: 病名。
            crop_name: 作物。
            growth_stage: 生育期。
            contexts: 检索片段。
            compliance_notes: 合规校验说明。

        Returns:
            dict: 最小方案卡 {summary, pesticides, precautions}。
        """
        return {"summary": "pytest 模拟防治方案", "pesticides": [], "precautions": "pytest 注意事项"}

    monkeypatch.setattr(clients, "diagnose_image_with_vlm", fake_first)
    monkeypatch.setattr(clients, "vlm_diagnose_multi", fake_multi)
    monkeypatch.setattr(vector_store, "search", fake_search)
    monkeypatch.setattr(clients, "generate_plan_with_llm", fake_plan)
    return multi_calls, search_calls


def _create_task_with_image(db: Session, test_plot) -> DiagnosisTask:
    """为测试地块上传一张图像并创建诊断任务（pending）。

    Args:
        db: 数据库会话。
        test_plot: 测试地块实例。

    Returns:
        DiagnosisTask: 已落库的诊断任务实例。
    """
    item = save_upload_image(
        db=db,
        file_bytes=make_png_bytes(seed=3),
        filename=f"pytest_vlm_{uuid.uuid4().hex[:8]}.png",
        plot_id=test_plot.id,
        source="manual",
        device_id=None,
        uploaded_by=None,
    )
    return diagnosis_service.create_task(
        db, plot_id=test_plot.id, growth_stage="结果期", image_ids=[item["id"]], source="manual"
    )


class TestEnhanceFlow:
    """识别节点两段式链路测试（真实图执行，LLM 全 mock）。"""

    def test_unanimous_vote_fused_confidence_end_to_end(
        self, db: Session, test_plot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """3/3 一致端到端：融合置信度 = 均值×1.05，raw_output 记录采样与投票明细。"""
        first = {
            "disease_name": DISEASE_CONSENSUS,
            "disease_category": "常见病",
            "confidence": 0.90,
            "description": "pytest 首轮判定",
        }
        samples = [
            _sample(DISEASE_CONSENSUS, 0.85),
            _sample(DISEASE_CONSENSUS, 0.87),
            _sample(DISEASE_CONSENSUS, 0.86),
        ]
        multi_calls, _ = _patch_enhanced_llm(monkeypatch, first, samples)
        task = _create_task_with_image(db, test_plot)
        diagnosis_service.run_task(task.id)

        db.rollback()
        db.expire_all()
        task = db.query(DiagnosisTask).filter(DiagnosisTask.id == task.id).first()
        assert task is not None
        assert task.status == "done"
        assert task.result_level == "high"
        # 融合置信度 = (0.85+0.87+0.86)/3 ×1.05 ≈ 0.903（≥ common 阈值 0.85 判高置信）
        assert float(task.fused_confidence) == pytest.approx(0.903, abs=1e-4)

        # 增强分支恰好执行一轮采样（3 次），提示词注入封闭候选集
        assert len(multi_calls) == 1
        assert multi_calls[0]["n"] == 3
        assert "从以下候选中选择" in multi_calls[0]["prompt"]

        # vlm 路径 raw_output 记录三次采样明细与投票结论（溯源）
        vlm_result = (
            db.query(DiagnosisResult)
            .filter(DiagnosisResult.task_id == task.id, DiagnosisResult.model_path == "vlm")
            .first()
        )
        assert vlm_result is not None
        raw = vlm_result.raw_output or {}
        assert len(raw["samples"]) == 3
        assert raw["vote"]["rule"] == "3/3_consensus_mean_x1.05"
        assert raw["vote"]["fused_confidence"] == pytest.approx(0.903, abs=1e-4)

    def test_enhance_disabled_single_round(
        self, db: Session, test_plot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VLM_ENHANCE_ENABLED=false：不调采样与检索，首轮单次结果直通。"""
        first = {
            "disease_name": DISEASE_INCONSISTENT,
            "disease_category": "default",
            "confidence": 0.95,
            "description": "pytest 首轮判定",
        }
        multi_calls, search_calls = _patch_enhanced_llm(monkeypatch, first, [_sample("pytest不应出现", 0.5)])
        monkeypatch.setattr(settings, "vlm_enhance_enabled", False)
        task = _create_task_with_image(db, test_plot)
        diagnosis_service.run_task(task.id)

        db.rollback()
        db.expire_all()
        task = db.query(DiagnosisTask).filter(DiagnosisTask.id == task.id).first()
        assert task is not None
        assert task.status == "done"
        assert task.result_level == "high"
        assert float(task.fused_confidence) == pytest.approx(0.95, abs=1e-4)
        # 三次采样从未发起；检索仅发生在后续 knowledge 方案节点（0.95 高置信正常路由），
        # 不含增强分支特有的「症状 识别」查询
        assert multi_calls == []
        assert all("症状 识别" not in query for query in search_calls)

    def test_healthy_first_round_skips_enhance(
        self, db: Session, test_plot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """首轮判定 healthy：不进入增强分支，且不生成方案/预警（诊断后直接结束）。"""
        first = {
            "disease_name": "健康",
            "disease_category": "常见病",
            "confidence": 0.98,
            "description": "pytest 叶片健康无病斑",
        }
        multi_calls, search_calls = _patch_enhanced_llm(monkeypatch, first, [])
        task = _create_task_with_image(db, test_plot)
        diagnosis_service.run_task(task.id)

        db.rollback()
        db.expire_all()
        task = db.query(DiagnosisTask).filter(DiagnosisTask.id == task.id).first()
        assert task is not None
        assert task.status == "done"
        assert task.result_level == "high"
        assert float(task.fused_confidence) == pytest.approx(0.98, abs=1e-4)
        assert multi_calls == []
        assert search_calls == []
        assert db.query(PreventionPlan).filter(PreventionPlan.task_id == task.id).first() is None
        assert db.query(Alert).filter(Alert.plot_id == test_plot.id).count() == 0

    def test_all_inconsistent_fallback_low_confidence(
        self, db: Session, test_plot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全不一致端到端：融合置信度 = 首轮×0.8 判低置信，回落首轮病名并存待确认案例。"""
        first = {
            "disease_name": DISEASE_INCONSISTENT,
            "disease_category": "常见病",
            "confidence": 0.90,
            "description": "pytest 首轮判定",
        }
        samples = [
            _sample("pytest甲病", 0.90),
            _sample("pytest乙病", 0.90),
            _sample("pytest丙病", 0.90),
        ]
        _patch_enhanced_llm(monkeypatch, first, samples)
        task = _create_task_with_image(db, test_plot)
        diagnosis_service.run_task(task.id)

        db.rollback()
        db.expire_all()
        task = db.query(DiagnosisTask).filter(DiagnosisTask.id == task.id).first()
        assert task is not None
        assert task.status == "done"
        assert task.result_level == "low"
        # 融合置信度 = 0.90×0.8 = 0.72（< common 阈值 0.85 判低置信）
        assert float(task.fused_confidence) == pytest.approx(0.72, abs=1e-4)

        vlm_result = (
            db.query(DiagnosisResult)
            .filter(DiagnosisResult.task_id == task.id, DiagnosisResult.model_path == "vlm")
            .first()
        )
        assert vlm_result is not None
        raw = vlm_result.raw_output or {}
        assert raw["vote"]["rule"] == "0/3_inconsistent_first_x0.8"
        assert vlm_result.disease_name == DISEASE_INCONSISTENT

        # fused 路径描述注明三次采样不一致
        fused_result = (
            db.query(DiagnosisResult)
            .filter(DiagnosisResult.task_id == task.id, DiagnosisResult.model_path == "fused")
            .first()
        )
        assert fused_result is not None
        assert "不一致" in (fused_result.raw_output or {}).get("description", "")

        # 低置信度 → 待确认案例库（status=pending）
        case = db.query(CaseLibrary).filter(CaseLibrary.task_id == task.id).first()
        assert case is not None
        assert case.status == "pending"
        assert case.ai_disease_name == DISEASE_INCONSISTENT
