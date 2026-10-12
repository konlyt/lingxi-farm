"""本地向量存储模块（RAG 用）。

以 JSON 文件（app/data/vectors.json）实现轻量向量库：
知识文档切片 → 智谱 Embedding-3 向量化 → 余弦相似度 top-k 检索。
不引入 Milvus；接口抽象保持可替换（后续可平滑切换向量数据库）。

文件结构：
{"chunks": [{"doc_id", "title", "category", "text", "vector"}]}
"""
import json
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.agents.llm.clients import embed_texts
from app.core.config import BASE_DIR

logger = logging.getLogger("farm_vector")

# 向量存储文件路径
VECTOR_FILE = BASE_DIR / "app" / "data" / "vectors.json"
# 切片长度（字符）与重叠
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
# 检索默认 top-k 与低相似度阈值
DEFAULT_TOP_K = 3
LOW_SIMILARITY_THRESHOLD = 0.35

# 文件读写锁（多线程定时任务与请求并发保护）
_lock = threading.Lock()


def _split_text(text: str) -> list[str]:
    """将长文本按固定窗口切片（带重叠）。

    Args:
        text: 原始文档正文。

    Returns:
        list[str]: 切片列表，每片长度约 CHUNK_SIZE 字符。
    """
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def _load_file() -> dict[str, Any]:
    """读取向量存储文件。

    Returns:
        dict: {"chunks": [...]}；文件不存在返回空结构。
    """
    if not VECTOR_FILE.exists():
        return {"chunks": []}
    try:
        return json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("vectors.json 损坏，重建空向量库")
        return {"chunks": []}


def _save_file(data: dict[str, Any]) -> None:
    """写回向量存储文件。

    Args:
        data: 完整向量库结构。
    """
    VECTOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    VECTOR_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _cosine_top_k(query_vec: list[float], chunks: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """计算查询向量与全部切片的余弦相似度并返回 top-k。

    Args:
        query_vec: 查询向量。
        chunks: 切片列表（含 vector 字段）。
        top_k: 返回条数。

    Returns:
        list[dict]: [{chunk, similarity}] 按相似度倒序。
    """
    if not chunks:
        return []
    matrix = np.array([chunk["vector"] for chunk in chunks], dtype=np.float32)
    query = np.array(query_vec, dtype=np.float32)
    # 归一化后点积即余弦相似度
    matrix_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
    query_norm = query / (np.linalg.norm(query) + 1e-9)
    sims = matrix_norm @ query_norm
    order = np.argsort(sims)[::-1][:top_k]
    return [{"chunk": chunks[i], "similarity": float(sims[i])} for i in order]


def add_document(doc_id: int, title: str, category: str, content: str) -> int:
    """将一篇知识文档切片并向量化追加进向量库。

    Args:
        doc_id: knowledge_document 主键（用于关联溯源）。
        title: 文档标题。
        category: 文档分类。
        content: 文档正文。

    Returns:
        int: 实际入库切片数量。

    Raises:
        Exception: 向量化 API 失败时抛出（调用方置 embed_status=failed）。
    """
    chunks = _split_text(content)
    if not chunks:
        return 0
    vectors = embed_texts(chunks)
    with _lock:
        data = _load_file()
        # 幂等：先移除同文档旧切片
        data["chunks"] = [c for c in data["chunks"] if c.get("doc_id") != doc_id]
        for text, vector in zip(chunks, vectors):
            data["chunks"].append(
                {"doc_id": doc_id, "title": title, "category": category, "text": text, "vector": vector}
            )
        _save_file(data)
    return len(chunks)


def remove_document(doc_id: int) -> None:
    """从向量库移除指定文档的全部切片。

    Args:
        doc_id: 文档ID。
    """
    with _lock:
        data = _load_file()
        data["chunks"] = [c for c in data["chunks"] if c.get("doc_id") != doc_id]
        _save_file(data)


def search(query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """向量检索：返回与查询最相关的知识片段。

    Args:
        query: 查询文本。
        top_k: 返回条数，默认 3。

    Returns:
        list[dict]: [{doc_id, title, category, text, similarity}]；
                    向量化失败或向量库为空时返回空列表（调用方降级）。
    """
    try:
        query_vec = embed_texts([query])[0]
    except Exception as exc:  # noqa: BLE001 检索失败降级为空结果
        logger.warning("查询向量化失败，检索降级为空: %s", exc)
        return []
    with _lock:
        data = _load_file()
        chunks = data.get("chunks", [])
    ranked = _cosine_top_k(query_vec, chunks, top_k)
    return [
        {
            "doc_id": item["chunk"]["doc_id"],
            "title": item["chunk"]["title"],
            "category": item["chunk"]["category"],
            "text": item["chunk"]["text"],
            "similarity": round(item["similarity"], 4),
        }
        for item in ranked
    ]


def ensure_index_built(documents: list[dict[str, Any]]) -> int:
    """启动时确保向量索引存在：vectors.json 缺失时对全部文档建索引。

    Args:
        documents: [{id, title, category, content}] 文档列表
                   （content 从文件或数据库读取后的正文）。

    Returns:
        int: 本次新索引的切片总数（已有索引时返回 0）。
    """
    if VECTOR_FILE.exists():
        return 0
    with _lock:
        if VECTOR_FILE.exists():  # 双重检查
            return 0
        total = 0
        data: dict[str, Any] = {"chunks": []}
        for doc in documents:
            try:
                chunks = _split_text(doc["content"])
                if not chunks:
                    continue
                vectors = embed_texts(chunks)
                for text, vector in zip(chunks, vectors):
                    data["chunks"].append(
                        {
                            "doc_id": doc["id"],
                            "title": doc["title"],
                            "category": doc["category"],
                            "text": text,
                            "vector": vector,
                        }
                    )
                total += len(chunks)
            except Exception as exc:  # noqa: BLE001 单篇失败不阻塞其他文档
                logger.warning("文档 %s 向量化失败: %s", doc.get("title"), exc)
        _save_file(data)
    return total
