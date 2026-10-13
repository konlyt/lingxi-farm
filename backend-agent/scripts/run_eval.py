# -*- coding: utf-8 -*-
"""诊断链路端到端评测脚本：对合成评测集逐条走完整诊断流程并统计指标。

支持两种模式：
- --mock：monkeypatch LLM 客户端（按图像类别规则返回固定病名+置信度，
  healthy 类返回健康），同时 patch 掉邮件发送等外部副作用，
  走通 LangGraph 全流程（诊断→落库→条件路由→知识/方案/预警），无 LLM 成本；
- 真实模式（默认）：不 patch，直接调用 diagnosis_service.run_task 走真实
  VLM/DeepSeek/智谱链路（不经 HTTP，依赖服务未启动也可运行）。

评测口径与诊断链路一致：病名取 fused 路径 DiagnosisResult.disease_name、
融合置信度取 DiagnosisTask.fused_confidence、result_level 取任务级标注。

统计指标：
- Top-1 准确率（含 healthy 类）与分病种准确率；
- 低置信度召回：误判样本中 result_level=low 的兜底标注比例；
- 平均时延（ms/条，端到端含 LLM 与落库）；
- RAG 检索评测：内置标准问句集（番茄早疫病/晚疫病/白粉病各 2 问），
  调 vector_store 真实检索，命中判定 top3 含目标病种关键词。

数据自造自清：临时地块（名称前缀 __eval_）、图像、诊断任务、结果、方案、
禁令、预警、推送记录、LangGraph 检查点在上报后统一删除；
uploads/__eval/ 下临时图像文件同步清理。

报告输出 backend-agent/tests/eval/eval_report.json（首跑标记 baseline: true，
供后续模型/Prompt 变更回归对比），并打印中文摘要表格。

用法：
    python scripts/run_eval.py [--mock]
"""
import argparse
import json
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 保证可从任意工作目录导入 app 包
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.graph import HEALTHY_NAMES
from app.agents.llm import clients
from app.core.database import SessionLocal
from app.models.alert import Alert, AlertPushRecord
from app.models.case import CaseImage, CaseLibrary
from app.models.diagnosis import DiagnosisResult, DiagnosisTask, DiagnosisTaskImage, PreventionPlan
from app.models.image import CollectedImage
from app.models.knowledge import HarvestRestriction
from app.models.misc import LanggraphCheckpoint
from app.models.plot import Plot
from app.services import notifier
from app.services import vector_store
from app.services.diagnosis_service import create_task, run_task
from app.utils.time_utils import now

# 评测产物目录与报告路径
EVAL_DIR = BACKEND_DIR / "tests" / "eval"
EVAL_SET_PATH = EVAL_DIR / "eval_set.json"
REPORT_PATH = EVAL_DIR / "eval_report.json"
# 评测临时图像落盘目录（诊断链路经 cos_url=/uploads/__eval/xxx 读取）
UPLOAD_EVAL_DIR = BACKEND_DIR / "uploads" / "__eval"
# 评测临时地块名称前缀（清理依据）
EVAL_PLOT_PREFIX = "__eval_"

# mock 模式 VLM 规则表：图像类别 → 固定识别结果（置信度均高于 common 阈值 0.85）
MOCK_RULES: dict[str, dict[str, Any]] = {
    "early_blight": {
        "disease_name": "番茄早疫病", "disease_category": "common", "confidence": 0.88,
        "description": "[mock] 褐色同心轮纹病斑，周围黄晕圈",
    },
    "late_blight": {
        "disease_name": "番茄晚疫病", "disease_category": "common", "confidence": 0.87,
        "description": "[mock] 水渍状边缘不整齐大型病斑",
    },
    "powdery_mildew": {
        "disease_name": "白粉病", "disease_category": "common", "confidence": 0.86,
        "description": "[mock] 叶面白色粉状霉层",
    },
    "healthy": {
        "disease_name": "健康", "disease_category": "common", "confidence": 0.97,
        "description": "[mock] 叶面绿色无病斑",
    },
}
# mock 未匹配类别时的兜底返回（低置信度）
MOCK_UNKNOWN = {
    "disease_name": "unknown", "disease_category": "default", "confidence": 0.30,
    "description": "[mock] 未匹配评测类别",
}
# mock 防治方案卡（pesticides 置空避免生成采收禁令）
MOCK_PLAN = {
    "summary": "[mock] 按常规防治执行，注意通风降湿",
    "pesticides": [],
    "precautions": "[mock] 用药前核对安全间隔期",
}

# RAG 标准问句集：(目标病种, 标准问句, 命中关键词列表)
# 病种取自知识库已有文档（番茄早疫病/晚疫病/白粉病均有收录）
RAG_QUESTIONS: list[tuple[str, str, list[str]]] = [
    ("番茄早疫病", "番茄早疫病用什么药防治？", ["早疫病"]),
    ("番茄早疫病", "番茄叶片出现褐色同心轮纹病斑是什么病？", ["早疫病"]),
    ("番茄晚疫病", "番茄晚疫病如何识别与防治？", ["晚疫病"]),
    ("番茄晚疫病", "番茄叶背出现白色霉层和水渍状大斑怎么办？", ["晚疫病"]),
    ("番茄白粉病", "番茄白粉病用什么药？", ["白粉病"]),
    ("番茄白粉病", "番茄叶面上有白色粉状霉层怎么治？", ["白粉病"]),
]


def _class_from_image_path(image_path: str) -> str:
    """从图像文件路径解析评测类别（文件名形如 early_blight_001.jpg）。

    Args:
        image_path: 图像路径（mock VLM 收到的本地路径）。

    Returns:
        str: 评测类别键（MOCK_RULES 的 key），未匹配返回 "unknown"。
    """
    stem = Path(image_path).stem
    for key in MOCK_RULES:
        if stem == key or stem.startswith(key + "_"):
            return key
    return "unknown"


def _apply_mock_patches() -> dict[str, Any]:
    """注入 mock：替换 LLM 客户端函数与邮件发送，屏蔽外部副作用。

    覆盖点：VLM 识别（按类别规则返回）、DeepSeek 兜底、方案生成、
    意图识别、问答生成，以及 notifier.send_email / is_email_configured。
    vector_store 检索保持真实调用（RAG 评测需真实命中率）。

    Returns:
        dict: 被替换的原函数字典（键为 "模块对象.函数名"），供恢复使用。
    """
    saved: dict[str, Any] = {}

    def mock_vlm(image_path: str, crop_name: str, growth_stage: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """mock VLM：按图像文件名解析类别并返回固定识别结果。

        使用可变参数签名以兼容诊断链路的签名演进（如新增 temperature）。

        Args:
            image_path: 本地图像路径。
            crop_name: 作物名称（mock 忽略）。
            growth_stage: 生育期（mock 忽略）。
            *args: 链路附加位置参数（mock 忽略）。
            **kwargs: 链附加关键字参数（mock 忽略）。

        Returns:
            dict: 与真实 VLM 同构结果 {disease_name, disease_category,
                  confidence, description}。
        """
        rule = MOCK_RULES.get(_class_from_image_path(image_path), MOCK_UNKNOWN)
        return dict(rule)

    def mock_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """mock 方案生成：返回固定方案卡（签名兼容链路演进）。

        Args:
            *args: 链路位置参数（mock 忽略）。
            **kwargs: 链路关键字参数（mock 忽略）。

        Returns:
            dict: 固定方案卡 {summary, pesticides: [], precautions}。
        """
        return dict(MOCK_PLAN)

    def mock_fallback(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """mock VLM 降级函数：返回低置信 unknown（正常 mock 流程不触发）。

        Args:
            *args: 链路位置参数（最后一项为 VLM 失败原因）。
            **kwargs: 链路关键字参数（mock 忽略）。

        Returns:
            dict: 低置信度降级结果。
        """
        return {
            "disease_name": "unknown", "disease_category": "default",
            "confidence": 0.30, "description": "[mock fallback] VLM 不可用",
        }

    def mock_chat(*args: Any, **kwargs: Any) -> str:
        """mock DeepSeek 文本调用：返回占位回答（正常 mock 流程不触发）。

        Args:
            *args: 链路位置参数（mock 忽略）。
            **kwargs: 链路关键字参数（mock 忽略）。

        Returns:
            str: 占位回答文本。
        """
        return "[mock] 占位回答"

    def mock_intent(*args: Any, **kwargs: Any) -> str:
        """mock 意图识别：固定返回 diagnosis（评测流已显式指定，兜底用）。

        Args:
            *args: 链路位置参数（mock 忽略）。
            **kwargs: 链路关键字参数（mock 忽略）。

        Returns:
            str: 意图标签 "diagnosis"。
        """
        return "diagnosis"

    def mock_context_chat(*args: Any, **kwargs: Any) -> str:
        """mock 知识问答生成：返回占位回答（诊断流不触发）。

        Args:
            *args: 链路位置参数（mock 忽略）。
            **kwargs: 链路关键字参数（mock 忽略）。

        Returns:
            str: 占位回答文本。
        """
        return "[mock] 占位回答"

    def mock_send_email(*args: Any, **kwargs: Any) -> tuple[bool, Optional[str]]:
        """mock 邮件发送：直接返回成功，避免评测产生真实邮件。

        Args:
            *args: 链路位置参数（收件人/主题/正文等，mock 忽略）。
            **kwargs: 链路关键字参数（mock 忽略）。

        Returns:
            tuple[bool, Optional[str]]: (True, None) 表示发送成功。
        """
        return True, None

    def mock_configured() -> bool:
        """mock 邮箱配置检查：返回 False 使 alert_service 跳过推送分支。

        Returns:
            bool: 恒为 False。
        """
        return False

    targets = [
        (clients, "diagnose_image_with_vlm", mock_vlm),
        (clients, "generate_plan_with_llm", mock_plan),
        (clients, "vlm_fallback_description", mock_fallback),
        (clients, "chat_deepseek", mock_chat),
        (clients, "recognize_intent", mock_intent),
        (clients, "chat_with_context", mock_context_chat),
        (notifier, "send_email", mock_send_email),
        (notifier, "is_email_configured", mock_configured),
    ]
    for module, name, replacement in targets:
        saved[f"{id(module)}.{name}"] = (module, name, getattr(module, name))
        setattr(module, name, replacement)
    return saved


def _restore_mock_patches(saved: dict[str, Any]) -> None:
    """恢复被 mock 替换的模块函数。

    Args:
        saved: _apply_mock_patches 返回的原函数字典。

    Returns:
        None: 原地恢复模块属性。
    """
    for _key, (module, name, original) in saved.items():
        setattr(module, name, original)


def _is_healthy_name(name: Optional[str]) -> bool:
    """判断病名是否属于健康类别（与诊断链路 HEALTHY_NAMES 口径一致）。

    Args:
        name: 待判断的病名（可空）。

    Returns:
        bool: 属于健康名称集合时为 True。
    """
    return bool(name) and name.strip().lower() in HEALTHY_NAMES


def _normalize_disease_name(name: Optional[str]) -> str:
    """病名归一化：去空白、去作物前缀后小写（用于 Top-1 等价判分）。

    诊断链路的候选约束会把 VLM 输出对齐到知识库候选名（如「白粉病」
    →「番茄白粉病」），与评测集标签指同一病种，判分须语义等价。

    Args:
        name: 待归一化的病名（可空）。

    Returns:
        str: 归一化后的病名键（空输入返回空串）。
    """
    if not name:
        return ""
    result = name.strip().lower()
    for prefix in ("番茄", "黄瓜", "辣椒", "玉米"):
        if result.startswith(prefix):
            result = result[len(prefix):]
            break
    return result


def _load_eval_set() -> list[dict[str, Any]]:
    """读取评测集清单。

    Returns:
        list[dict]: 评测集条目列表。

    Raises:
        SystemExit: eval_set.json 不存在时提示先运行构建脚本并退出。
    """
    if not EVAL_SET_PATH.exists():
        print(f"[错误] 评测集不存在：{EVAL_SET_PATH}\n请先运行 scripts/build_eval_set.py 构建")
        sys.exit(1)
    return json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))


def _create_eval_plots(db: Any, entries: list[dict[str, Any]]) -> dict[str, int]:
    """按 plot_type_hint 创建评测临时地块（名称带 __eval_ 前缀与唯一后缀）。

    Args:
        db: 数据库会话。
        entries: 评测集条目列表（取 plot_type_hint 分组）。

    Returns:
        dict: hint → 新建地块ID 映射。

    Raises:
        Exception: 数据库写入失败时向上抛出（由调用方回滚清理）。
    """
    plots: dict[str, int] = {}
    for hint in sorted({entry["plot_type_hint"] for entry in entries}):
        plot = Plot(
            name=f"{EVAL_PLOT_PREFIX}评测_{hint}_{uuid.uuid4().hex[:8]}",
            type=hint,
            crop_name="番茄",
            growth_stage="结果期",
            status=1,
        )
        db.add(plot)
        db.commit()
        plots[hint] = plot.id
    return plots


def _run_single(db: Any, plot_id: int, entry: dict[str, Any]) -> dict[str, Any]:
    """执行单条评测：图像入库 → 建任务 → 跑诊断链路 → 读回结果。

    Args:
        db: 数据库会话。
        plot_id: 评测地块ID。
        entry: 评测集条目。

    Returns:
        dict: 单条明细 {id, label, predicted, confidence, result_level,
              status, correct, low_marked, latency_ms, error}。
    """
    detail: dict[str, Any] = {
        "id": entry["id"], "label": entry["label_disease"], "predicted": None,
        "confidence": None, "result_level": None, "status": "failed",
        "correct": False, "low_marked": False, "latency_ms": None, "error": None,
    }
    try:
        # 复制评测图到 uploads/__eval/（诊断链路按 cos_url 读本地文件）
        UPLOAD_EVAL_DIR.mkdir(parents=True, exist_ok=True)
        file_name = f"{entry['id']}.jpg"
        shutil.copyfile(EVAL_DIR / entry["image_path"], UPLOAD_EVAL_DIR / file_name)
        image = CollectedImage(
            plot_id=plot_id,
            device_id=None,
            source="manual",
            cos_url=f"/uploads/__eval/{file_name}",
            thumb_url=None,
            quality_status="pass",
            dedup_hash=uuid.uuid4().hex,
            uploaded_by=None,
            captured_at=now(),
        )
        db.add(image)
        db.commit()

        task = create_task(db, plot_id, None, [image.id], "manual")
        start = time.perf_counter()
        run_task(task.id)
        detail["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)

        # run_task 使用独立数据库会话提交结果，须过期本会话身份映射缓存
        # 后重读（否则读到 create_task 时的旧快照：status=pending）
        db.expire_all()
        # run_task 使用独立会话，此处重新查询读回最终状态
        task_row = db.query(DiagnosisTask).filter(DiagnosisTask.id == task.id).first()
        detail["status"] = task_row.status
        detail["result_level"] = task_row.result_level
        detail["confidence"] = float(task_row.fused_confidence) if task_row.fused_confidence is not None else None
        fused = (
            db.query(DiagnosisResult)
            .filter(DiagnosisResult.task_id == task.id, DiagnosisResult.model_path == "fused")
            .order_by(DiagnosisResult.id.desc())
            .first()
        )
        detail["predicted"] = fused.disease_name if fused is not None else None
        detail["low_marked"] = task_row.result_level == "low"

        label = entry["label_disease"]
        predicted = detail["predicted"]
        if detail["status"] == "done" and predicted is not None:
            detail["correct"] = _normalize_disease_name(predicted) == _normalize_disease_name(label) or (
                _is_healthy_name(predicted) and label == "健康"
            )
    except Exception as exc:  # noqa: BLE001 单条失败不中断整批评测
        db.rollback()
        detail["error"] = str(exc)[:200]
    return detail


def _run_rag_eval() -> dict[str, Any]:
    """执行 RAG 检索评测：标准问句逐条调 vector_store 检索并判定命中。

    命中判定：top3 结果的 title 或 text 含目标病种关键词即算命中。

    Returns:
        dict: {hit_rate, hit, total, details:[{target, question, hit,
              top_titles, top_similarity}]}。
    """
    details: list[dict[str, Any]] = []
    hit_count = 0
    for target, question, keywords in RAG_QUESTIONS:
        hits = vector_store.search(question, top_k=3)
        hit_flag = any(
            any(kw in hit["title"] or kw in hit["text"] for kw in keywords)
            for hit in hits
        )
        hit_count += 1 if hit_flag else 0
        details.append(
            {
                "target": target,
                "question": question,
                "hit": hit_flag,
                "top_titles": [hit["title"] for hit in hits],
                "top_similarity": hits[0]["similarity"] if hits else 0.0,
            }
        )
    total = len(RAG_QUESTIONS)
    return {"hit_rate": round(hit_count / total, 4), "hit": hit_count, "total": total, "details": details}


def _cleanup(db: Any, plot_ids: list[int]) -> None:
    """清理评测期间创建的全部临时数据（按外键依赖顺序删除）。

    覆盖：推送记录→预警→案例图像→案例→采收禁令→防治方案→诊断结果→
    任务图像关联→诊断任务→图像记录→LangGraph 检查点→地块，
    并删除 uploads/__eval/ 临时图像目录。

    Args:
        db: 数据库会话。
        plot_ids: 评测临时地块ID列表。

    Returns:
        None: 清理结果直接落库。

    Raises:
        Exception: 数据库删除失败时向上抛出（调用方记录警告，不阻塞报告输出）。
    """
    if not plot_ids:
        return
    task_ids = [row[0] for row in db.query(DiagnosisTask.id).filter(DiagnosisTask.plot_id.in_(plot_ids)).all()]
    plan_ids = [row[0] for row in db.query(PreventionPlan.id).filter(PreventionPlan.task_id.in_(task_ids)).all()] if task_ids else []
    case_ids = [row[0] for row in db.query(CaseLibrary.id).filter(CaseLibrary.task_id.in_(task_ids)).all()] if task_ids else []
    thread_ids = [row[0] for row in db.query(DiagnosisTask.thread_id).filter(DiagnosisTask.plot_id.in_(plot_ids)).all()]
    alert_ids = [row[0] for row in db.query(Alert.id).filter(Alert.plot_id.in_(plot_ids)).all()]

    if alert_ids:
        db.query(AlertPushRecord).filter(AlertPushRecord.alert_id.in_(alert_ids)).delete(synchronize_session=False)
        db.query(Alert).filter(Alert.id.in_(alert_ids)).delete(synchronize_session=False)
    if case_ids:
        db.query(CaseImage).filter(CaseImage.case_id.in_(case_ids)).delete(synchronize_session=False)
        db.query(CaseLibrary).filter(CaseLibrary.id.in_(case_ids)).delete(synchronize_session=False)
    if plan_ids:
        db.query(HarvestRestriction).filter(HarvestRestriction.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(PreventionPlan).filter(PreventionPlan.id.in_(plan_ids)).delete(synchronize_session=False)
    if task_ids:
        db.query(DiagnosisResult).filter(DiagnosisResult.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(DiagnosisTaskImage).filter(DiagnosisTaskImage.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(DiagnosisTask).filter(DiagnosisTask.id.in_(task_ids)).delete(synchronize_session=False)
    if thread_ids:
        db.query(LanggraphCheckpoint).filter(LanggraphCheckpoint.thread_id.in_(thread_ids)).delete(synchronize_session=False)
    db.query(CollectedImage).filter(CollectedImage.plot_id.in_(plot_ids)).delete(synchronize_session=False)
    db.query(Plot).filter(Plot.id.in_(plot_ids)).delete(synchronize_session=False)
    db.commit()

    if UPLOAD_EVAL_DIR.exists():
        shutil.rmtree(UPLOAD_EVAL_DIR, ignore_errors=True)


def _accuracy(correct: int, total: int) -> float:
    """计算准确率（保留四位小数）。

    Args:
        correct: 正确条数。
        total: 总条数。

    Returns:
        float: 正确/总数；总数为 0 时返回 0.0。
    """
    return round(correct / total, 4) if total else 0.0


def run_eval(mock: bool) -> dict[str, Any]:
    """执行完整评测主流程：临时地块 → 逐条诊断 → 指标统计 → RAG 评测。

    Args:
        mock: True 为 mock 模式（patch LLM 与邮件）；False 为真实模式。

    Returns:
        dict: 评测报告结构 {run_at, mode, total, top1_accuracy, per_class,
              low_conf_recall, avg_latency_ms, rag, baseline, baseline_note,
              details}。

    Raises:
        Exception: 数据库连接失败等致命错误时向上抛出（清理后退出）。
    """
    entries = _load_eval_set()
    saved_patches: dict[str, Any] = {}
    if mock:
        saved_patches = _apply_mock_patches()

    db = SessionLocal()
    plot_ids: list[int] = []
    details: list[dict[str, Any]] = []
    try:
        plot_map = _create_eval_plots(db, entries)
        plot_ids = list(plot_map.values())
        for entry in entries:
            detail = _run_single(db, plot_map[entry["plot_type_hint"]], entry)
            details.append(detail)
    finally:
        if mock:
            _restore_mock_patches(saved_patches)

        # 指标统计
        total = len(details)
        correct_total = sum(1 for d in details if d["correct"])
        wrong_items = [d for d in details if not d["correct"]]
        low_marked_wrong = sum(1 for d in wrong_items if d["low_marked"])
        latencies = [d["latency_ms"] for d in details if d["latency_ms"] is not None]

        class_keys = list(MOCK_RULES.keys())
        per_class: dict[str, Any] = {}
        for class_key in class_keys:
            items = [d for d in details if d["id"].startswith(class_key + "_")]
            correct_n = sum(1 for d in items if d["correct"])
            per_class[class_key] = {
                "label": MOCK_RULES[class_key]["disease_name"],
                "total": len(items),
                "correct": correct_n,
                "accuracy": _accuracy(correct_n, len(items)),
            }

        rag_result = _run_rag_eval()

        first_run = not REPORT_PATH.exists()
        report = {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "mock" if mock else "real",
            "total": total,
            "top1_accuracy": _accuracy(correct_total, total),
            "per_class": per_class,
            "low_conf_recall": (round(low_marked_wrong / len(wrong_items), 4) if wrong_items else None),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "rag": rag_result,
            "baseline": first_run,
            "baseline_note": (
                "首次运行结果作为评测基线，后续模型/Prompt 变更后重跑对比"
                if first_run
                else "与历史基线对比：关注 top1_accuracy/per_class/low_conf_recall 变化"
            ),
            "details": details,
        }

        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        # 数据自造自清：删除临时地块与全部关联记录
        try:
            _cleanup(db, plot_ids)
        except Exception as exc:  # noqa: BLE001 清理失败不阻塞报告输出
            print(f"[警告] 评测临时数据清理失败（可按名称前缀 {EVAL_PLOT_PREFIX} 手动清理）: {exc}")
        finally:
            db.close()

    return report


def print_summary(report: dict[str, Any]) -> None:
    """打印中文摘要表格到控制台。

    Args:
        report: run_eval 返回的报告结构。

    Returns:
        None: 仅打印。
    """
    print()
    print(f"========== 诊断评测摘要（{report['mode']} 模式）==========")
    print(f"总样本数    : {report['total']}")
    print(f"Top-1 准确率: {report['top1_accuracy'] * 100:.2f}%")
    low_recall = report["low_conf_recall"]
    avg_latency = report["avg_latency_ms"]
    print(f"低置信召回  : {'-' if low_recall is None else f'{low_recall * 100:.2f}%'}（误判样本被标注 low 的比例）")
    print(f"平均时延    : {'-' if avg_latency is None else f'{avg_latency} ms/条'}")
    print(f"基线标记    : baseline={report['baseline']}（{report['baseline_note']}）")
    print("-------- 分病种准确率 --------")
    for class_key, item in report["per_class"].items():
        print(f"  {item['label']:<8} {item['correct']}/{item['total']}  {item['accuracy'] * 100:.2f}%")
    print("-------- RAG 检索评测 --------")
    print(f"  命中率: {report['rag']['hit']}/{report['rag']['total']}（{report['rag']['hit_rate'] * 100:.2f}%）")
    for item in report["rag"]["details"]:
        mark = "✓" if item["hit"] else "✗"
        print(f"  {mark} [{item['target']}] {item['question']}")
    print(f"报告已写入: {REPORT_PATH}")
    wrong = [d for d in report["details"] if not d["correct"]]
    if wrong:
        print("-------- 误判明细 --------")
        for d in wrong:
            print(f"  {d['id']}: 标签={d['label']} 预测={d['predicted']} 级别={d['result_level']}")


def main() -> None:
    """命令行入口：解析 --mock 参数并执行评测，失败时以非零码退出。

    Raises:
        SystemExit: 评测执行异常时退出码 1。
    """
    parser = argparse.ArgumentParser(description="病虫害诊断链路端到端评测")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="mock 模式：patch LLM 客户端按规则返回固定结果（无 LLM 成本，用于回归自检）",
    )
    args = parser.parse_args()
    try:
        report = run_eval(mock=args.mock)
    except Exception as exc:  # noqa: BLE001 评测执行失败统一提示退出
        print(f"[错误] 评测执行失败: {exc}")
        sys.exit(1)
    print_summary(report)


if __name__ == "__main__":
    main()
