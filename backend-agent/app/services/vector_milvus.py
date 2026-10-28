"""Milvus 向量数据库实现（RAG）。

基于 pymilvus（Milvus 2.4+）实现与本地 vectors.json 同构的检索接口：
- Collection schema：自增主键 + FLOAT_VECTOR(dim=settings.milvus_dim) + 标量字段；
- 索引：HNSW + COSINE 度量（服务端直接算余弦，免去手动归一化）；
- 幂等写入：insert 前按 doc_id 标量字段 delete 旧切片（与本地实现语义一致）；
- 标量过滤：search 支持 category 过滤（expr），是本地实现不具备的能力。

连接失败时由门面层（vector_store.py）探测并降级 local，本模块不做兜底。
"""
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger("farm_vector")

# VarChar 字段长度（Milvus 按 UTF-8 字节数计）：
# 切片约 300 字符（中文最多 900 字节），预留余量取 1024；标题同理由取 1024
_TEXT_MAX_LEN = 1024
_TITLE_MAX_LEN = 1024
_CATEGORY_MAX_LEN = 64

# HNSW 检索参数
_SEARCH_EF = 128

_client: Any = None


def _get_client() -> Any:
    """获取（并懒初始化）Milvus 客户端单例。

    Returns:
        MilvusClient: 已连接的客户端实例。

    Raises:
        Exception: Milvus 服务不可达或 pymilvus 未安装时抛出。
    """
    global _client
    if _client is not None:
        return _client
    from pymilvus import MilvusClient  # 延迟导入：local 后端无需安装 pymilvus

    uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
    _client = MilvusClient(uri=uri)
    return _client


def ping() -> bool:
    """探测 Milvus 服务连通性（门面层降级判断用）。

    Returns:
        bool: 可连通返回 True；任何异常（未装 pymilvus/服务未启动）返回 False。
    """
    try:
        _get_client().list_collections()
        return True
    except Exception as exc:  # noqa: BLE001 连接类异常统一视为不可用
        logger.warning("Milvus 连接失败 (%s:%s): %s", settings.milvus_host, settings.milvus_port, exc)
        return False


def _ensure_collection() -> Any:
    """确保 collection 存在（缺失则按当前模型维度创建并建 HNSW/COSINE 索引）。

    Returns:
        Collection 对象（MilvusClient 模式下返回 collection 名，内部封装）。

    Raises:
        RuntimeError: 存量 collection 维度与配置维度不一致时抛出。
    """
    client = _get_client()
    name = settings.milvus_collection
    if client.has_collection(name):
        desc = client.describe_collection(name)
        dim = next(
            (f.get("params", {}).get("dim") for f in desc.get("fields", []) if f.get("name") == "vector"),
            None,
        )
        if dim is not None and int(dim) != settings.milvus_dim:
            raise RuntimeError(
                f"Milvus collection {name} 向量维度为 {dim}，与配置 milvus_dim={settings.milvus_dim} 不一致，"
                "请删除 collection 后重新迁移"
            )
        return name
    from pymilvus import CollectionSchema, DataType, FieldSchema

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=settings.milvus_dim),
        FieldSchema(name="doc_id", dtype=DataType.INT64),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=_TITLE_MAX_LEN),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=_CATEGORY_MAX_LEN),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=_TEXT_MAX_LEN),
    ]
    schema = CollectionSchema(fields, description="灵犀田园知识库切片")
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 256},
    )
    client.create_collection(
        collection_name=name,
        schema=schema,
        index_params=index_params,
    )
    logger.info("已创建 Milvus collection: %s (dim=%s, HNSW/COSINE)", name, settings.milvus_dim)
    return name


def _insert_rows(name: str, rows: list[dict[str, Any]]) -> None:
    """分批写入切片数据并 flush。

    Args:
        name: collection 名。
        rows: [{vector, doc_id, title, category, text}] 行列表。
    """
    client = _get_client()
    batch = 100
    for start in range(0, len(rows), batch):
        client.insert(collection_name=name, data=rows[start:start + batch])
    client.flush(name)


def _delete_by_doc_id(name: str, doc_id: int) -> None:
    """删除指定文档的全部切片（幂等写入的前置清理）。

    Args:
        name: collection 名。
        doc_id: 文档主键。
    """
    _get_client().delete(collection_name=name, filter=f"doc_id == {int(doc_id)}")


def add_document(doc_id: int, title: str, category: str, content: str) -> int:
    """切片 → 向量化 → 幂等写入 Milvus。

    Args:
        doc_id: knowledge_document 主键。
        title: 文档标题。
        category: 文档分类。
        content: 文档正文。

    Returns:
        int: 实际入库切片数量。

    Raises:
        Exception: 向量化 API 或 Milvus 写入失败时抛出。
    """
    from app.agents.llm.clients import embed_texts
    from app.services.vector_local import split_text

    chunks = split_text(content)
    if not chunks:
        return 0
    vectors = embed_texts(chunks)
    name = _ensure_collection()
    _delete_by_doc_id(name, doc_id)
    rows = [
        {
            "vector": vector,
            "doc_id": doc_id,
            "title": title,
            "category": category,
            "text": text,
        }
        for text, vector in zip(chunks, vectors)
    ]
    _insert_rows(name, rows)
    return len(chunks)


def insert_chunks(chunks: list[dict[str, Any]]) -> int:
    """批量写入现成切片（迁移脚本用，含向量，不再调 Embedding API）。

    Args:
        chunks: [{doc_id, title, category, text, vector}] 切片列表。

    Returns:
        int: 写入切片数量。

    Raises:
        ValueError: 向量维度与 milvus_dim 配置不符时抛出。
    """
    if not chunks:
        return 0
    for chunk in chunks:
        if len(chunk["vector"]) != settings.milvus_dim:
            raise ValueError(
                f"向量维度 {len(chunk['vector'])} 与 milvus_dim={settings.milvus_dim} 不符，请核对配置"
            )
    name = _ensure_collection()
    # 同文档幂等：按 doc_id 去重清理
    for doc_id in {int(c["doc_id"]) for c in chunks}:
        _delete_by_doc_id(name, doc_id)
    rows = [
        {
            "vector": chunk["vector"],
            "doc_id": int(chunk["doc_id"]),
            "title": chunk["title"],
            "category": chunk["category"],
            "text": chunk["text"],
        }
        for chunk in chunks
    ]
    _insert_rows(name, rows)
    return len(rows)


def remove_document(doc_id: int) -> None:
    """从 Milvus 移除指定文档的全部切片。

    Args:
        doc_id: 文档ID。
    """
    name = settings.milvus_collection
    if not _get_client().has_collection(name):
        return
    _delete_by_doc_id(name, doc_id)


def search(query: str, top_k: int = 3, category: str | None = None) -> list[dict[str, Any]]:
    """Milvus 向量检索：返回与查询最相关的知识片段。

    Args:
        query: 查询文本。
        top_k: 返回条数。
        category: 可选标量过滤（如 "treatment" 只查防治方案库）。

    Returns:
        list[dict]: [{doc_id, title, category, text, similarity}]；
                    向量化失败时返回空列表（调用方降级）。

    Raises:
        Exception: Milvus 检索失败时向上抛出（门面层降级 local）。
    """
    from app.agents.llm.clients import embed_texts

    try:
        query_vec = embed_texts([query])[0]
    except Exception as exc:  # noqa: BLE001 查询向量化失败降级为空
        logger.warning("查询向量化失败，检索降级为空: %s", exc)
        return []
    client = _get_client()
    name = _ensure_collection()
    if not client.has_collection(name):
        return []
    client.load_collection(name)
    results = client.search(
        collection_name=name,
        data=[query_vec],
        limit=top_k,
        filter=f"category == '{category}'" if category else "",
        output_fields=["doc_id", "title", "category", "text"],
        search_params={"metric_type": "COSINE", "params": {"ef": _SEARCH_EF}},
    )
    hits = results[0] if results else []
    return [
        {
            "doc_id": hit["entity"]["doc_id"],
            "title": hit["entity"]["title"],
            "category": hit["entity"]["category"],
            "text": hit["entity"]["text"],
            "similarity": round(float(hit["distance"]), 4),
        }
        for hit in hits
    ]


def get_chunk_counts() -> dict[int, int]:
    """统计 Milvus 中各文档的切片数（启动时同步元数据用）。

    Returns:
        dict: {doc_id: chunk_count}；collection 不存在返回空表。
    """
    client = _get_client()
    name = settings.milvus_collection
    if not client.has_collection(name):
        return {}
    client.load_collection(name)
    rows = client.query(
        collection_name=name,
        filter="doc_id >= 0",
        output_fields=["doc_id"],
    )
    counts: dict[int, int] = {}
    for row in rows:
        doc_id = row["doc_id"]
        counts[doc_id] = counts.get(doc_id, 0) + 1
    return counts


def ensure_index_built(documents: list[dict[str, Any]]) -> int:
    """启动时确保 Milvus 索引就绪：collection 缺失或为空时全量建索引。

    Args:
        documents: [{id, title, category, content}] 文档列表。

    Returns:
        int: 本次新索引的切片总数（索引已就绪时返回 0）。

    Raises:
        Exception: 向量化或 Milvus 写入失败时抛出（单篇失败不阻塞其他文档）。
    """
    from app.agents.llm.clients import embed_texts
    from app.services.vector_local import split_text

    name = _ensure_collection()
    client = _get_client()
    client.load_collection(name)
    if client.query(collection_name=name, filter="doc_id >= 0", output_fields=["doc_id"], limit=1):
        return 0
    total = 0
    for doc in documents:
        try:
            chunks = split_text(doc["content"])
            if not chunks:
                continue
            vectors = embed_texts(chunks)
            rows = [
                {
                    "vector": vector,
                    "doc_id": doc["id"],
                    "title": doc["title"],
                    "category": doc["category"],
                    "text": text,
                }
                for text, vector in zip(chunks, vectors)
            ]
            _insert_rows(name, rows)
            total += len(rows)
        except Exception as exc:  # noqa: BLE001 单篇失败不阻塞其他文档
            logger.warning("文档 %s 向量化失败: %s", doc.get("title"), exc)
    return total
