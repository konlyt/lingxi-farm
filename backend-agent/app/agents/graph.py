"""LangGraph 多智能体编排模块（Supervisor 模式）。

构建农场业务 StateGraph：
- supervisor：意图识别（diagnosis/advice/monitor/knowledge，已有 intent 则直接路由）；
- diagnosis：病虫害识别（豆包 VLM，失败降级 DeepSeek 纯文本），按病种阈值判定置信度；
- pending_case：低置信度标注并存待确认案例库；
- knowledge：双模式节点——诊断模式做 RAG 检索 + 药剂名录合规校验 + 生成防治方案；
  问答模式做 RAG 回答（低相似度标注建议咨询专家）；
- plan：防治方案落库 + 采收禁令自动创建 + pest 预警聚合；
- advice：种植决策（水肥/调控建议，DeepSeek 严格 JSON）；
- monitor：农情监测汇总（供定时任务/每日简报）。

全过程通过简化版 MySQL Checkpointer 保存状态快照。
"""
import logging
import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents.checkpointer import checkpointer
from app.agents.llm import clients
from app.models.advice import (
    ConfidenceThresholdConfig,
    WaterFertilizerAdvice,
    WeatherForecastCache,
)
from app.models.diagnosis import DiagnosisResult, PreventionPlan
from app.models.image import CollectedImage
from app.models.knowledge import HarvestRestriction, Pesticide
from app.models.plot import Plot
from app.services import vector_store
from app.services.alert_service import create_or_merge_alert
from app.services.image_service import UPLOAD_DIR
from app.services.plot_service import get_latest_env
from app.utils.time_utils import fmt_date, now, today

logger = logging.getLogger("farm_graph")

# 病名归一化：这些名称视为无需处理
HEALTHY_NAMES = {"健康", "healthy", "正常", "无病虫害"}

# 病种分类别名映射（VLM 可能输出中文分类，配置表以英文键存储）
_CATEGORY_ALIASES = {"常见病": "common", "罕见病": "rare", "默认": "default", "default病": "default"}


def _normalize_category(category: str | None) -> str | None:
    """归一化病种分类（中文别名 → 配置表英文键）。

    Args:
        category: 模型输出的病种分类（可空）。

    Returns:
        str | None: 归一化后的分类键。
    """
    if not category:
        return None
    return _CATEGORY_ALIASES.get(category.strip(), category.strip())


class FarmState(TypedDict, total=False):
    """图全局状态定义。

    Attributes:
        intent: 意图标签 diagnosis/advice/monitor/knowledge。
        thread_id: 线程ID（诊断任务为 diagnosis_task.thread_id）。
        task_id: 诊断任务ID（诊断流必传）。
        plot_id: 地块ID。
        source: 诊断来源 device/manual。
        growth_stage: 生育期。
        image_ids: 参与诊断的图像ID列表。
        question: 用户问题（问答流）。
        diagnosis: 诊断结果字典。
        low_confidence: 是否低置信度。
        plan: 防治方案字典（知识节点产出）。
        answer: 知识问答回答文本。
        advice_kind: 建议类型 water_fertilizer/environment_control。
        advice_result: 建议产出字典。
        monitor_result: 农情监测汇总结果。
        error: 节点执行错误信息。
    """

    intent: str
    thread_id: str
    task_id: int
    plot_id: int
    source: str
    growth_stage: str
    image_ids: list[int]
    question: str
    diagnosis: dict[str, Any]
    low_confidence: bool
    plan: dict[str, Any]
    answer: str
    advice_kind: str
    advice_result: dict[str, Any]
    monitor_result: dict[str, Any]
    error: str


# 需要持久化到 checkpointer 的状态白名单（剔除不可序列化对象）
_PERSIST_KEYS = (
    "intent", "thread_id", "task_id", "plot_id", "source", "growth_stage",
    "image_ids", "question", "diagnosis", "low_confidence", "plan",
    "answer", "advice_kind", "advice_result", "monitor_result", "error",
)


def _persist(db: Session, state: dict[str, Any], node_name: str) -> None:
    """按白名单保存当前状态快照到检查点表。

    Args:
        db: 数据库会话。
        state: 当前图状态。
        node_name: 产生快照的节点名。
    """
    thread_id = state.get("thread_id")
    if not thread_id:
        return
    snapshot = {key: state.get(key) for key in _PERSIST_KEYS if key in state}
    checkpointer.save(db, thread_id, snapshot, node_name=node_name)


def _get_threshold(db: Session, category: str | None) -> float:
    """按病种分类查询生效置信度阈值（无匹配用 default 配置，再无则 0.90）。

    Args:
        db: 数据库会话。
        category: 病种分类（常见病 common/罕见病 rare 等，可空）。

    Returns:
        float: 生效阈值（0-1）。
    """
    if category:
        row = (
            db.query(ConfidenceThresholdConfig)
            .filter(ConfidenceThresholdConfig.disease_category == category, ConfidenceThresholdConfig.enabled == 1)
            .first()
        )
        if row is not None:
            return float(row.threshold)
    default_row = (
        db.query(ConfidenceThresholdConfig)
        .filter(ConfidenceThresholdConfig.disease_category == "default", ConfidenceThresholdConfig.enabled == 1)
        .first()
    )
    return float(default_row.threshold) if default_row is not None else 0.90


def build_farm_graph(db: Session):
    """构建并编译农场业务 StateGraph（闭包绑定数据库会话）。

    Args:
        db: 数据库会话（由调用方创建并管理生命周期）。

    Returns:
        CompiledStateGraph: 可 invoke 的编译图。
    """

    # ---------- 节点实现 ----------

    def supervisor_node(state: FarmState) -> dict[str, Any]:
        """Supervisor 节点：意图识别与路由决策。

        Args:
            state: 当前图状态。

        Returns:
            dict: {intent}（已指定 intent 时原样透传，否则调 DeepSeek 识别，
                  识别失败降级 knowledge）。
        """
        if state.get("intent"):
            return {"intent": state["intent"]}
        intent = clients.recognize_intent(state.get("question", ""))
        return {"intent": intent}

    def diagnosis_node(state: FarmState) -> dict[str, Any]:
        """病虫害识别节点：VLM 识别 → 阈值判定 → 双路结果落库。

        Args:
            state: 当前图状态（需含 image_ids/task_id/plot_id）。

        Returns:
            dict: {diagnosis, low_confidence}；识别彻底失败时 {error}。

        Raises:
            Exception: VLM 与 DeepSeek 降级均失败时向上抛出（外层置任务 failed）。
        """
        image_ids: list[int] = state.get("image_ids", [])
        plot_id = state["plot_id"]
        crop_name = "作物"
        plot = db.query(Plot).filter(Plot.id == plot_id).first()
        if plot is not None:
            crop_name = plot.crop_name
        growth_stage = state.get("growth_stage") or (plot.growth_stage if plot else "未知")

        # 取第一张图像文件作为识别主图
        image = (
            db.query(CollectedImage)
            .filter(CollectedImage.id.in_(image_ids))
            .order_by(CollectedImage.id.asc())
            .first()
        )
        # 解析本地文件路径（cos_url 形如 /uploads/2026_10/xx.jpg）
        relative = (image.cos_url or "").removeprefix("/uploads/")
        image_path = UPLOAD_DIR / relative

        raw_output: dict[str, Any] = {}
        fallback_used = False
        try:
            vlm_result = clients.diagnose_image_with_vlm(str(image_path), crop_name, growth_stage)
            raw_output = {"source": "vlm", "raw": vlm_result}
        except Exception as vlm_exc:
            logger.warning("VLM 识别失败，降级 DeepSeek 文本诊断: %s", vlm_exc)
            fallback_used = True
            vlm_result = clients.vlm_fallback_description(crop_name, growth_stage, str(vlm_exc))
            raw_output = {"source": "deepseek_fallback", "vlm_error": str(vlm_exc), "raw": vlm_result}

        disease_name = str(vlm_result.get("disease_name") or "unknown").strip()
        disease_category = _normalize_category(str(vlm_result.get("disease_category") or "default"))
        confidence = max(0.0, min(1.0, float(vlm_result.get("confidence") or 0.0)))
        description = str(vlm_result.get("description") or "")
        threshold = _get_threshold(db, disease_category)
        is_healthy = disease_name.lower() in HEALTHY_NAMES

        diagnosis = {
            "disease_name": disease_name,
            "disease_category": disease_category,
            "confidence": round(confidence, 4),
            "description": description,
            "threshold": threshold,
            "model_name": "deepseek-fallback" if fallback_used else "doubao-vlm",
            "fallback": fallback_used,
            "healthy": is_healthy,
            "low_confidence": confidence < threshold and not is_healthy,
        }
        raw_output["threshold"] = threshold

        # 双路结果落库：vlm 路径 + fused 路径（本实现 fused 即 VLM/降级结果）
        task_id = state.get("task_id")
        if task_id:
            db.add_all(
                [
                    DiagnosisResult(
                        task_id=task_id,
                        model_path="vlm",
                        model_name=diagnosis["model_name"],
                        disease_name=disease_name,
                        disease_category=disease_category,
                        confidence=confidence,
                        raw_output=raw_output,
                    ),
                    DiagnosisResult(
                        task_id=task_id,
                        model_path="fused",
                        model_name=diagnosis["model_name"],
                        disease_name=disease_name,
                        disease_category=disease_category,
                        confidence=confidence,
                        raw_output={"fused_note": "单路 VLM 结果直通融合", "description": description},
                    ),
                ]
            )
            db.commit()
        _persist(db, {**state, "diagnosis": diagnosis}, "diagnosis")
        return {"diagnosis": diagnosis, "low_confidence": diagnosis["low_confidence"]}

    def pending_case_node(state: FarmState) -> dict[str, Any]:
        """低置信度处理节点：标注「建议咨询农技专家」并存待确认案例库。

        Args:
            state: 当前图状态（需含 task_id/diagnosis）。

        Returns:
            dict: {low_confidence: True}。
        """
        from app.models.case import CaseLibrary  # 局部导入避免循环依赖

        task_id = state.get("task_id")
        diagnosis = state.get("diagnosis", {})
        if task_id:
            exists = db.query(CaseLibrary.id).filter(CaseLibrary.task_id == task_id).first()
            if exists is None:
                db.add(
                    CaseLibrary(
                        task_id=task_id,
                        ai_disease_name=diagnosis.get("disease_name", "unknown"),
                        status="pending",
                        source=state.get("source", "manual"),
                        disease_category=diagnosis.get("disease_category"),
                    )
                )
                db.commit()
        _persist(db, {**state, "low_confidence": True}, "pending_case")
        return {"low_confidence": True}

    def knowledge_node(state: FarmState) -> dict[str, Any]:
        """知识检索节点（双模式）。

        诊断模式：RAG 检索病害知识 + 对照 pesticide 名录合规校验 + LLM 生成防治方案；
        问答模式：RAG 检索 + DeepSeek 回答，相似度低时标注建议咨询专家。

        Args:
            state: 当前图状态。

        Returns:
            dict: 诊断模式返回 {plan}；问答模式返回 {answer, low_confidence}。
        """
        if state.get("image_ids"):
            # ---------- 诊断模式：检索 + 合规校验 + 方案生成 ----------
            diagnosis = state.get("diagnosis", {})
            disease_name = diagnosis.get("disease_name", "unknown")
            plot = db.query(Plot).filter(Plot.id == state["plot_id"]).first()
            crop_name = plot.crop_name if plot else "作物"
            growth_stage = state.get("growth_stage") or (plot.growth_stage if plot else "")

            hits = vector_store.search(f"{crop_name} {disease_name} 防治方法 用药", top_k=3)
            contexts = [hit["text"] for hit in hits]

            # 用药合规校验：检索片段中出现的药剂名逐一对照 pesticide 名录
            all_pesticides = db.query(Pesticide).all()
            name_to_row = {}
            for row in all_pesticides:
                name_to_row[row.name] = row
                name_to_row[row.active_ingredient] = row
            mentioned = [name for name in name_to_row if name in "".join(contexts)]
            compliance_notes = "；".join(
                f"{name}:{name_to_row[name].forbidden_flag}(安全间隔期{name_to_row[name].safety_interval_days}天)"
                for name in mentioned
            ) or "检索片段未提及具体药剂，按常规用药规范执行"
            banned_names = [
                name for name in mentioned
                if name_to_row[name].forbidden_flag == "banned"
            ]
            is_forbidden_blocked = len(banned_names) > 0
            if banned_names:
                compliance_notes += f"。⚠️ 检出禁用农药 {('、'.join(banned_names))}，已拦截，严禁使用"

            try:
                plan_card = clients.generate_plan_with_llm(disease_name, crop_name, growth_stage, contexts, compliance_notes)
            except Exception as exc:  # 方案生成失败降级为检索片段拼装
                logger.warning("方案生成失败，降级为片段拼装: %s", exc)
                plan_card = {
                    "summary": (contexts[0][:80] if contexts else f"{disease_name} 防治建议请咨询农技专家"),
                    "pesticides": [],
                    "precautions": compliance_notes,
                }
            plan = {
                "scheme_json": {
                    "disease_name": disease_name,
                    "crop": crop_name,
                    "stage": growth_stage,
                    **plan_card,
                    "rag_references": [{"title": h["title"], "similarity": h["similarity"]} for h in hits],
                },
                "compliance_result": {"notes": compliance_notes, "mentioned": mentioned, "banned": banned_names},
                "is_forbidden_blocked": 1 if is_forbidden_blocked else 0,
                "disclaimer": "方案仅供参考，实际用药请遵产品标签与当地农技部门指导",
            }
            _persist(db, {**state, "plan": plan}, "knowledge")
            return {"plan": plan}

        # ---------- 问答模式：RAG 回答 ----------
        question = state.get("question", "")
        hits = vector_store.search(question, top_k=3)
        contexts = [hit["text"] for hit in hits]
        top_similarity = hits[0]["similarity"] if hits else 0.0
        answer = clients.chat_with_context(question, contexts)
        low_confidence = top_similarity < vector_store.LOW_SIMILARITY_THRESHOLD
        if low_confidence:
            answer += "\n\n💡 建议咨询农技专家获取更准确的指导。"
        _persist(db, {**state, "answer": answer, "low_confidence": low_confidence}, "knowledge")
        return {"answer": answer, "low_confidence": low_confidence}

    def plan_node(state: FarmState) -> dict[str, Any]:
        """方案落库节点：prevention_plan + 采收禁令自动创建 + pest 预警聚合。

        Args:
            state: 当前图状态（需含 task_id/plan/plot_id）。

        Returns:
            dict: {plan}(补充落库产物 plan_id/restrictions/alert_id)。
        """
        plan = state.get("plan", {})
        task_id = state["task_id"]
        plot_id = state["plot_id"]
        scheme = plan.get("scheme_json", {})

        prevention = PreventionPlan(
            task_id=task_id,
            scheme_json=scheme,
            compliance_result=plan.get("compliance_result", {}),
            is_forbidden_blocked=plan.get("is_forbidden_blocked", 0),
            disclaimer=plan.get("disclaimer"),
        )
        db.add(prevention)
        db.flush()

        # 按方案推荐药剂（allowed/restricted）自动创建采收禁令
        # 药剂名称采用双向包含模糊匹配（方案名常带剂型前缀，如「250g/L嘧菌酯悬浮剂」↔「嘧菌酯」）
        all_pesticide_rows = db.query(Pesticide).all()
        restrictions: list[dict[str, Any]] = []
        applied_day = today()
        for item in scheme.get("pesticides", []):
            pesticide_name = str(item.get("name", "")).strip()
            row = None
            for candidate in all_pesticide_rows:
                if not pesticide_name or not candidate.name:
                    continue
                if candidate.name in pesticide_name or pesticide_name in candidate.name:
                    row = candidate
                    break
            if row is None or row.forbidden_flag == "banned":
                continue  # 禁用药不建禁令（方案已拦截），名录外药剂无法计算间隔期
            restriction = HarvestRestriction(
                plot_id=plot_id,
                plan_id=prevention.id,
                pesticide_id=row.id,
                applied_at=applied_day,
                ban_until=applied_day.fromordinal(applied_day.toordinal() + row.safety_interval_days),
                status="active",
            )
            db.add(restriction)
            restrictions.append({"pesticide": row.name, "ban_until": fmt_date(restriction.ban_until)})
        db.flush()

        # 确诊病虫害（非健康）→ pest 预警聚合
        diagnosis = state.get("diagnosis", {})
        disease_name = diagnosis.get("disease_name", "unknown")
        alert_id = None
        if disease_name.lower() not in HEALTHY_NAMES:
            plot = db.query(Plot).filter(Plot.id == plot_id).first()
            image_ids = state.get("image_ids", [])
            first_image = (
                db.query(CollectedImage).filter(CollectedImage.id.in_(image_ids)).first() if image_ids else None
            )
            alert = create_or_merge_alert(
                db=db,
                plot_id=plot_id,
                alert_type="pest",
                case_key=f"plot:{plot_id}:pest:{disease_name}",
                title=f"{plot.name if plot else plot_id} 发现{disease_name}",
                content={
                    "disease_name": disease_name,
                    "confidence": diagnosis.get("confidence"),
                    "description": diagnosis.get("description"),
                    "latest_image_url": first_image.cos_url if first_image else None,
                    "plan_id": prevention.id,
                },
                level="warning",
                task_id=task_id,
            )
            alert_id = alert.id

        db.commit()
        plan = {**plan, "plan_id": prevention.id, "restrictions": restrictions, "alert_id": alert_id}
        _persist(db, {**state, "plan": plan}, "plan")
        return {"plan": plan}

    def advice_node(state: FarmState) -> dict[str, Any]:
        """种植决策节点：水肥建议（落库）或环境调控建议。

        Args:
            state: 当前图状态（需含 plot_id/advice_kind）。

        Returns:
            dict: {advice_result}。

        Raises:
            Exception: LLM 失败时抛出（调用方返回错误响应）。
        """
        plot = db.query(Plot).filter(Plot.id == state["plot_id"]).first()
        if plot is None:
            return {"error": "地块不存在"}
        plot_info = {
            "name": plot.name,
            "type": plot.type,
            "crop_name": plot.crop_name,
            "crop_variety": plot.crop_variety,
            "growth_stage": plot.growth_stage,
            "soil_type": plot.soil_type,
        }
        env_latest = get_latest_env(db, plot.id)
        env_payload = {**env_latest}

        kind = state.get("advice_kind", "water_fertilizer")
        if kind == "environment_control":
            weather_today = (
                db.query(WeatherForecastCache)
                .filter(
                    WeatherForecastCache.plot_id == plot.id,
                    WeatherForecastCache.data_type == "weather_forecast",
                    WeatherForecastCache.forecast_date == today(),
                )
                .first()
            )
            result = clients.decide_environment_control(plot_info, env_payload, weather_today.data_json if weather_today else None)
            return {"advice_result": result}

        # 水肥建议：无墒情数据时降级标注
        fallback_flag = 0
        if all(value is None for value in env_latest.values()):
            fallback_flag = 1
            env_payload["observed_at"] = None
            env_payload["note"] = "传感器数据缺失，建议基于历史经验与天气生成"
        weather_rows = (
            db.query(WeatherForecastCache)
            .filter(
                WeatherForecastCache.plot_id == plot.id,
                WeatherForecastCache.data_type == "weather_forecast",
                WeatherForecastCache.forecast_date >= today(),
            )
            .order_by(WeatherForecastCache.forecast_date.asc())
            .limit(7)
            .all()
        )
        weather_items = [
            {"date": fmt_date(row.forecast_date), **(row.data_json or {})} for row in weather_rows
        ]
        result = clients.decide_water_fertilizer(plot_info, env_payload, weather_items)

        # uk_plot_date 当日记录幂等写入
        current_date = today()
        existing = (
            db.query(WaterFertilizerAdvice)
            .filter(WaterFertilizerAdvice.plot_id == plot.id, WaterFertilizerAdvice.advice_date == current_date)
            .first()
        )
        basis = {
            "env": env_payload,
            "weather": weather_items,
            "weather_fetched_at": fmt_date(weather_rows[0].fetched_at) if weather_rows else None,
        }
        if existing is None:
            db.add(
                WaterFertilizerAdvice(
                    plot_id=plot.id,
                    advice_date=current_date,
                    horizon_days=7,
                    advice_json=result,
                    basis_json=basis,
                    data_fallback_flag=fallback_flag,
                    push_status="sent",
                )
            )
        else:
            existing.advice_json = result
            existing.basis_json = basis
            existing.data_fallback_flag = fallback_flag
        db.commit()
        return {"advice_result": {**result, "data_fallback_flag": fallback_flag}}

    def monitor_node(state: FarmState) -> dict[str, Any]:
        """农情监测节点：汇总各地块实况与异常发现（供定时任务/简报）。

        Args:
            state: 当前图状态。

        Returns:
            dict: {monitor_result: {plots:[...], generated_at}}。
        """
        plots = db.query(Plot).filter(Plot.status == 1).all()
        summaries = []
        for plot in plots:
            env = get_latest_env(db, plot.id)
            summaries.append(
                {
                    "plot_id": plot.id,
                    "plot_name": plot.name,
                    "crop_name": plot.crop_name,
                    "growth_stage": plot.growth_stage,
                    "env": env,
                }
            )
        result = {"plots": summaries, "generated_at": now().isoformat()}
        _persist(db, {**state, "monitor_result": result}, "monitor")
        return {"monitor_result": result}

    # ---------- 路由函数 ----------

    def route_after_supervisor(state: FarmState) -> Literal["diagnosis", "knowledge", "advice", "monitor"]:
        """Supervisor 条件边：按意图路由到对应智能体节点。

        Args:
            state: 当前图状态。

        Returns:
            str: 下一节点名。
        """
        return state.get("intent", "knowledge")  # type: ignore[return-value]

    def route_after_diagnosis(state: FarmState) -> Literal["pending_case", "knowledge", "__end__"]:
        """诊断后条件边：低置信度→待确认案例；健康→结束；高置信度→知识合规。

        Args:
            state: 当前图状态。

        Returns:
            str: 下一节点名。
        """
        diagnosis = state.get("diagnosis", {})
        if state.get("error"):
            return END  # type: ignore[return-value]
        if diagnosis.get("low_confidence"):
            return "pending_case"
        if diagnosis.get("healthy"):
            return END  # type: ignore[return-value]
        return "knowledge"

    def route_after_knowledge(state: FarmState) -> Literal["plan", "__end__"]:
        """知识节点后条件边：诊断流→方案落库；问答流→结束。

        Args:
            state: 当前图状态。

        Returns:
            str: 下一节点名。
        """
        if state.get("image_ids") and state.get("plan"):
            return "plan"
        return END  # type: ignore[return-value]

    # ---------- 组装 StateGraph ----------
    builder = StateGraph(FarmState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("diagnosis", diagnosis_node)
    builder.add_node("pending_case", pending_case_node)
    builder.add_node("knowledge", knowledge_node)
    builder.add_node("plan", plan_node)
    builder.add_node("advice", advice_node)
    builder.add_node("monitor", monitor_node)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"diagnosis": "diagnosis", "knowledge": "knowledge", "advice": "advice", "monitor": "monitor"},
    )
    builder.add_conditional_edges(
        "diagnosis",
        route_after_diagnosis,
        {"pending_case": "pending_case", "knowledge": "knowledge", END: END},
    )
    builder.add_edge("pending_case", END)
    builder.add_conditional_edges(
        "knowledge",
        route_after_knowledge,
        {"plan": "plan", END: END},
    )
    builder.add_edge("plan", END)
    builder.add_edge("advice", END)
    builder.add_edge("monitor", END)

    return builder.compile()
