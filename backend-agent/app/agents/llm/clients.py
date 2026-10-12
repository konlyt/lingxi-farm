"""LLM 客户端统一封装模块。

基于 openai SDK（OpenAI 兼容协议）封装三家大模型客户端：
- DeepSeek：推理/决策/Supervisor 意图识别/知识问答；
- 豆包 VLM：图像病虫害识别（支持 image_url 多模态消息）；
- 智谱：Embedding-3 文本向量化（RAG 用）。

统一特性：60 秒超时、失败自动重试一次、异常向上抛出由调用方降级。
"""
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger("farm_llm")

# LLM 请求超时（秒）
LLM_TIMEOUT = 60.0
# 失败重试次数（openai SDK 自身 max_retries 之外的业务级重试）
LLM_RETRY = 1


def _build_client(base_url: str, api_key: str) -> OpenAI:
    """构建 OpenAI 兼容客户端实例。

    Args:
        base_url: 服务商 OpenAI 兼容接口地址。
        api_key: API Key。

    Returns:
        OpenAI: 已配置超时与一次 SDK 级重试的客户端。
    """
    return OpenAI(base_url=base_url, api_key=api_key, timeout=LLM_TIMEOUT, max_retries=1)


# 三个全局客户端（懒加载由模块导入时创建，配置缺失时创建也不报错，调用时报错）
deepseek_client = _build_client(settings.deepseek_base_url, settings.deepseek_api_key)
doubao_vlm_client = _build_client(settings.doubao_vlm_base_url, settings.doubao_vlm_api_key)
zhipu_client = _build_client(settings.zhipu_base_url, settings.zhipu_api_key)


def chat_deepseek(prompt: str, system: str = "你是一名经验丰富的农场植保与种植管理专家。", temperature: float = 0.3) -> str:
    """调用 DeepSeek 进行文本推理/生成（带一次业务级重试）。

    Args:
        prompt: 用户提示词。
        system: 系统提示词。
        temperature: 采样温度，决策类任务建议低温。

    Returns:
        str: 模型回复文本。

    Raises:
        Exception: 两次尝试均失败时抛出最后一次异常，由调用方降级。
    """
    last_exc: Exception | None = None
    for _ in range(LLM_RETRY + 1):
        try:
            resp = deepseek_client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 统一降级入口
            last_exc = exc
            logger.warning("DeepSeek 调用失败，准备重试: %s", exc)
    raise last_exc  # type: ignore[misc]


def _image_file_to_data_url(file_path: str) -> str:
    """读取本地图像文件并编码为 base64 data URL。

    Args:
        file_path: 图像文件绝对/相对路径。

    Returns:
        str: data:image/jpeg;base64,... 形式的 data URL。

    Raises:
        FileNotFoundError: 文件不存在时抛出。
    """
    path = Path(file_path)
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    if suffix == "jpg":
        suffix = "jpeg"
    data = path.read_bytes()
    return f"data:image/{suffix};base64,{base64.b64encode(data).decode('utf-8')}"


def diagnose_image_with_vlm(image_path: str, crop_name: str, growth_stage: str) -> dict[str, Any]:
    """调用豆包 VLM 对图像做病虫害识别，输出严格 JSON。

    Args:
        image_path: 本地图像文件路径。
        crop_name: 作物名称（辅助识别）。
        growth_stage: 生育期（辅助识别）。

    Returns:
        dict: {disease_name, disease_category, confidence, description}；
              confidence 为 0-1 浮点。

    Raises:
        ValueError: 模型输出无法解析为合法 JSON 时抛出。
        Exception: API 调用两次均失败时抛出。
    """
    system = (
        "你是农作物病虫害识别专家。请严格只输出一个 JSON 对象，不要输出任何其他文字，"
        '格式为：{"disease_name": "病害或虫害中文名称，健康则写 健康", '
        '"disease_category": "常见病/罕见病 二选一", '
        '"confidence": 0到1之间的小数, '
        '"description": "50字以内的识别依据描述"}'
    )
    user_text = f"作物：{crop_name}，生育期：{growth_stage}。请识别图像中的病虫害情况。"
    data_url = _image_file_to_data_url(image_path)
    last_exc: Exception | None = None
    for _ in range(LLM_RETRY + 1):
        try:
            resp = doubao_vlm_client.chat.completions.create(
                model=settings.doubao_vlm_model,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                temperature=0.1,
            )
            content = resp.choices[0].message.content or ""
            return _extract_json(content)
        except ValueError as exc:
            # JSON 解析失败不重试（重试同样输入无意义），直接抛出
            raise exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("豆包 VLM 调用失败，准备重试: %s", exc)
    raise last_exc  # type: ignore[misc]


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出文本中提取第一个 JSON 对象并解析。

    Args:
        text: 模型原始输出（可能含 markdown 代码块或说明文字）。

    Returns:
        dict: 解析后的 JSON 对象。

    Raises:
        ValueError: 文本中不存在可解析的 JSON 对象时抛出。
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError(f"模型输出中未找到 JSON：{text[:120]}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}") from exc


def vlm_fallback_description(crop_name: str, growth_stage: str, image_error: str) -> dict[str, Any]:
    """VLM 失败时降级：调 DeepSeek 纯文本生成低置信度诊断描述。

    Args:
        crop_name: 作物名称。
        growth_stage: 生育期。
        image_error: VLM 失败原因（用于记录）。

    Returns:
        dict: 与 VLM 输出同构的低置信度结果
              {disease_name: "unknown", disease_category: "default",
               confidence: 0.3, description: 降级文本}。

    Raises:
        Exception: DeepSeek 也失败时抛出（调用方置任务 failed）。
    """
    prompt = (
        f"作物：{crop_name}，生育期：{growth_stage}。图像识别服务暂时不可用（原因：{image_error}）。"
        "请基于该作物当前生育期最可能发生的 2-3 种病虫害，给出一段 80 字以内的观察建议文本，"
        "提醒用户拍摄清晰病斑照片重试。只输出建议文本本身。"
    )
    description = chat_deepseek(prompt, temperature=0.5)
    return {
        "disease_name": "unknown",
        "disease_category": "default",
        "confidence": 0.3,
        "description": f"[图像识别降级] {description}",
        "fallback": True,
    }


def embed_texts(texts: list[str]) -> list[list[float]]:
    """调用智谱 Embedding-3 批量向量化文本。

    Args:
        texts: 文本列表（切片后的知识片段）。

    Returns:
        list[list[float]]: 与输入顺序对应的向量列表。

    Raises:
        Exception: API 调用失败时抛出，由调用方标记 embed_status=failed。
    """
    resp = zhipu_client.embeddings.create(model=settings.zhipu_model, input=texts)
    # 兼容返回顺序字段
    data = sorted(resp.data, key=lambda item: item.index)
    return [item.embedding for item in data]


def chat_with_context(question: str, contexts: list[str]) -> str:
    """基于检索片段调用 DeepSeek 生成知识问答回答。

    Args:
        question: 用户问题。
        contexts: RAG 检索到的知识片段列表（可为空）。

    Returns:
        str: 面向用户的中文回答（方案类内容自动附用药合规提示）。
    """
    if contexts:
        context_text = "\n".join(f"[片段{i + 1}] {ctx}" for i, ctx in enumerate(contexts))
        system = (
            "你是农场植保知识助手。请优先依据提供的知识片段回答用户问题；"
            "片段未覆盖的部分可补充通用农技常识但需说明。"
            "若回答包含用药方案，必须在末尾附加合规提示："
            "「⚠️ 用药前请核对禁限用农药名录与安全间隔期，采收前按规定停药。」"
        )
        prompt = f"知识片段：\n{context_text}\n\n用户问题：{question}"
    else:
        system = (
            "你是农场植保知识助手。知识库暂无相关片段，请基于通用农技常识谨慎回答并注明仅供参考。"
            "若包含用药方案，末尾附加合规提示："
            "「⚠️ 用药前请核对禁限用农药名录与安全间隔期。」"
        )
        prompt = question
    return chat_deepseek(prompt, system=system, temperature=0.4)


def generate_plan_with_llm(disease_name: str, crop_name: str, growth_stage: str,
                           contexts: list[str], compliance_notes: str) -> dict[str, Any]:
    """调用 DeepSeek 生成防治方案卡（结合 RAG 片段与用药合规校验结论）。

    Args:
        disease_name: 诊断出的病害名称。
        crop_name: 作物名称。
        growth_stage: 生育期。
        contexts: RAG 检索到的防治知识片段。
        compliance_notes: 对照药剂名录的合规校验说明文本。

    Returns:
        dict: 方案卡结构 {disease_name, crop, stage, summary,
              pesticides:[{name, dosage, method}], precautions}。

    Raises:
        ValueError: 输出无法解析 JSON 时抛出。
        Exception: API 失败时抛出。
    """
    context_text = "\n".join(f"[片段{i + 1}] {ctx}" for i, ctx in enumerate(contexts)) or "（知识库暂无匹配片段，请给通用方案）"
    system = (
        "你是农作物防治方案专家。请严格只输出一个 JSON 对象，格式为："
        '{"summary": "防治要点一句话", '
        '"pesticides": [{"name": "农药名称", "dosage": "稀释倍数或亩用量", "method": "施药方式"}], '
        '"precautions": "安全注意事项"}'
    )
    prompt = (
        f"病害：{disease_name}；作物：{crop_name}；生育期：{growth_stage}。\n"
        f"参考知识：\n{context_text}\n\n用药合规校验结论：{compliance_notes}\n"
        "请生成防治方案。方案中不得出现禁用（banned）农药；限用（restricted）农药需注明谨慎使用。"
    )
    return _extract_json(chat_deepseek(prompt, system=system, temperature=0.2))


def recognize_intent(question: str) -> str:
    """调用 DeepSeek 识别用户问题意图。

    Args:
        question: 用户输入的问题/指令。

    Returns:
        str: 意图标签 diagnosis/advice/monitor/knowledge 之一；
             识别失败时降级返回 knowledge。
    """
    system = (
        "你是意图识别器。只输出以下四个标签之一，不要输出其他任何内容："
        "diagnosis（涉及图像/病虫害诊断）、advice（水肥/种植决策建议）、"
        "monitor（农情/环境监测汇总）、knowledge（知识问答）。"
    )
    try:
        result = chat_deepseek(question, system=system, temperature=0.0).strip().lower()
    except Exception:
        return "knowledge"
    for tag in ("diagnosis", "advice", "monitor", "knowledge"):
        if tag in result:
            return tag
    return "knowledge"


def decide_water_fertilizer(plot_info: dict[str, Any], env_values: dict[str, Any],
                            weather_items: list[dict[str, Any]]) -> dict[str, Any]:
    """调用 DeepSeek 生成未来 7 天水肥建议卡（严格 JSON）。

    Args:
        plot_info: 地块档案摘要 {name, crop_name, crop_variety, growth_stage, type, soil_type}。
        env_values: 最新环境值 {temp, humidity, soil_moisture, observed_at}（可为空值）。
        weather_items: 天气缓存逐日列表 [{date, condition, temp_high, temp_low, precipitation_mm}]。

    Returns:
        dict: {summary, items:[{date, irrigate, fertilize}], risk_notes}。

    Raises:
        ValueError: 输出无法解析 JSON 时抛出。
        Exception: API 失败时抛出。
    """
    system = (
        "你是水肥管理专家。请严格只输出一个 JSON 对象，格式为："
        '{"summary": "未来7天水肥总体策略一句话", '
        '"items": [{"date": "YYYY-MM-DD", "irrigate": "浇水建议（含时机与量）", "fertilize": "施肥建议或 无"}], '
        '"risk_notes": "风险与不确定性说明"}'
    )
    prompt = (
        f"地块：{plot_info}\n最新墒情与环境：{env_values}\n"
        f"未来7天天气：{weather_items}\n"
        "请结合作物生育期需水需肥特点给出未来 7 天逐日浇水/施肥建议。"
    )
    return _extract_json(chat_deepseek(prompt, system=system, temperature=0.3))


def decide_environment_control(plot_info: dict[str, Any], env_values: dict[str, Any],
                               weather_now: dict[str, Any] | None) -> dict[str, Any]:
    """调用 DeepSeek 生成未来 12 小时大棚环境调控建议（严格 JSON）。

    Args:
        plot_info: 地块档案摘要。
        env_values: 最新环境值。
        weather_now: 今日天气（可空）。

    Returns:
        dict: {items:[{time_range, action, reason}]}。

    Raises:
        ValueError: 输出无法解析 JSON 时抛出。
        Exception: API 失败时抛出。
    """
    system = (
        "你是大棚环境调控专家。建议仅提示操作不控制设备。请严格只输出一个 JSON 对象，格式为："
        '{"items": [{"time_range": "如 12:00-15:00", "action": "通风/保温/降湿等操作", "reason": "依据"}]}'
    )
    prompt = (
        f"大棚：{plot_info}\n当前环境：{env_values}\n今日天气：{weather_now or '无数据'}\n"
        "请给出未来 12 小时分时段的通风/保温/降湿操作建议（2-4 条）。"
    )
    return _extract_json(chat_deepseek(prompt, system=system, temperature=0.3))
