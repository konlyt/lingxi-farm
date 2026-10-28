"""向量存储统一门面（RAG 用）。

按 settings.retrieval_backend 在两套实现间分发：
- local : app/services/vector_local.py  —— vectors.json + numpy 余弦（零依赖兜底）
- milvus: app/services/vector_milvus.py —— Milvus 2.4+ / pymilvus，HNSW + COSINE

接口（模块级函数）自单农场 v0.1 起保持稳定，调用方（graph.py / knowledge.py /
main.py / scripts）不感知后端差异；backend=milvus 但服务不可达时自动降级 local。

常量与文件路径向后兼容导出：VECTOR_FILE、LOW_SIMILARITY_THRESHOLD、
CHUNK_SIZE、CHUNK_OVERLAP、DEFAULT_TOP_K。
"""
import logging
from typing import Any

from app.core.config import settings
from app.services import vector_local, vector_milvus
from app.services.vector_local import VECTOR_FILE  # noqa: F401 兼容导出（迁移/预热脚本引用）

logger = logging.getLogger("farm_vector")

# 切片长度（字符）与重叠
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
# 检索默认 top-k 与低相似度阈值
DEFAULT_TOP_K = 3
LOW_SIMILARITY_THRESHOLD = 0.35

# Milvus 连通性缓存（None=未探测；启动后首次检索探测一次，失败降级 local）
_milvus_available: bool | None = None


def backend_name() -> str:
    """返回当前生效的检索后端名（milvus 不可达时实际返回 local）。

    Returns:
        str: "local" 或 "milvus"。
    """
    return "milvus" if _use_milvus() else "local"


def _use_milvus() -> bool:
    """判断本次调用是否走 Milvus（含连通性探测与缓存）。

    Returns:
        bool: True 走 Milvus；False 走本地实现。
    """
    global _milvus_available
    if settings.retrieval_backend != "milvus":
        return False
    if _milvus_available is None:
        _milvus_available = vector_milvus.ping()
        if _milvus_available:
            logger.info("RAG 检索后端: Milvus (%s:%s/%s)", settings.milvus_host, settings.milvus_port, settings.milvus_collection)
        else:
            logger.warning("Milvus 不可达，RAG 检索自动降级为本地 vectors.json 实现")
    return _milvus_available


def add_document(doc_id: int, title: str, category: str, content: str) -> int:
    """将一篇知识文档切片并向量化追加进当前后端向量库。

    Args:
        doc_id: knowledge_document 主键（用于关联溯源）。
        title: 文档标题。
        category: 文档分类。
        content: 文档正文。

    Returns:
        int: 实际入库切片数量。

    Raises:
        Exception: 向量化 API 或后端写入失败时抛出（调用方置 embed_status=failed）。
    """
    if _use_milvus():
        return vector_milvus.add_document(doc_id, title, category, content)
    return vector_local.add_document(doc_id, title, category, content)


def remove_document(doc_id: int) -> None:
    """从当前后端移除指定文档的全部切片。

    Args:
        doc_id: 文档ID。
    """
    if _use_milvus():
        vector_milvus.remove_document(doc_id)
    else:
        vector_local.remove_document(doc_id)


def search(query: str, top_k: int = DEFAULT_TOP_K, category: str | None = None) -> list[dict[str, Any]]:
    """向量检索：返回与查询最相关的知识片段。

    Args:
        query: 查询文本。
        top_k: 返回条数，默认 3。
        category: 可选分类过滤（仅 Milvus 后端生效；local 忽略）。

    Returns:
        list[dict]: [{doc_id, title, category, text, similarity}]；
                    检索失败或向量库为空时返回空列表（调用方降级）。
    """
    if not _use_milvus():
        return vector_local.search(query, top_k)
    try:
        return vector_milvus.search(query, top_k, category=category)
    except Exception as exc:  # noqa: BLE001 运行期 Milvus 故障兜底切回本地
        logger.warning("Milvus 检索失败，本次降级本地实现: %s", exc)
        return vector_local.search(query, top_k)


def get_chunk_counts() -> dict[int, int]:
    """统计当前后端中各文档的切片数（启动元数据同步用）。

    Returns:
        dict: {doc_id: chunk_count}。
    """
    if _use_milvus():
        try:
            return vector_milvus.get_chunk_counts()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Milvus 统计切片数失败: %s", exc)
            return {}
    return vector_local.get_chunk_counts()


def ensure_index_built(documents: list[dict[str, Any]]) -> int:
    """启动时确保向量索引存在：索引缺失时对全部文档切片建索引。

    Args:
        documents: [{id, title, category, content}] 文档列表
                   （content 从文件或数据库读取后的正文）。

    Returns:
        int: 本次新索引的切片总数（索引已存在时返回 0）。
    """
    if _use_milvus():
        return vector_milvus.ensure_index_built(documents)
    return vector_local.ensure_index_built(documents)
