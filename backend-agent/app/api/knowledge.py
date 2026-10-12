"""知识库接口路由。

提供知识文档列表查询与入库接口（切片 → Embedding-3 向量化 → 本地向量库）。
入库接口仅 owner 可用。
"""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import BusinessException, ok
from app.core.security import require_owner
from app.models.knowledge import KnowledgeDocument
from app.services import vector_store
from app.utils.time_utils import now

router = APIRouter(prefix="/api/knowledge", tags=["知识库"], dependencies=[Depends(require_owner)])

# 文档分类合法清单
VALID_CATEGORIES = {"disease_map": "病虫害图谱", "treatment": "防治方案库", "pesticide_regulation": "禁限用农药名录"}


class KnowledgeDocCreateRequest(BaseModel):
    """知识文档入库请求体。

    Attributes:
        title: 文档标题。
        category: 分类 disease_map/treatment/pesticide_regulation。
        content: 文档纯文本正文。
    """

    title: str = Field(..., min_length=1, max_length=255, description="文档标题")
    category: str = Field(..., description="分类")
    content: str = Field(..., min_length=10, description="文档正文（纯文本）")


@router.get("/documents", summary="知识文档列表")
def list_documents(db: Session = Depends(get_db)) -> dict:
    """查询全部知识文档元数据。

    Args:
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为文档数组。
    """
    rows = db.query(KnowledgeDocument).order_by(KnowledgeDocument.id.asc()).all()
    return ok(
        [
            {
                "id": doc.id,
                "title": doc.title,
                "category": doc.category,
                "category_display": VALID_CATEGORIES.get(doc.category, doc.category),
                "file_url": doc.file_url,
                "chunk_count": doc.chunk_count,
                "embed_status": doc.embed_status,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in rows
        ]
    )


@router.post("/documents", summary="知识文档入库（切片+向量化）")
def create_document(body: KnowledgeDocCreateRequest, db: Session = Depends(get_db)) -> dict:
    """知识文档入库：正文落盘 → 切片 → 智谱 Embedding-3 向量化 → vectors.json 追加。

    Args:
        body: 文档入库请求体。
        db: 数据库会话。

    Returns:
        dict: 统一响应，data 为 {id, title, chunk_count, embed_status}。

    Raises:
        BusinessException: 400 分类非法；502 向量化失败（embed_status=failed，
                           文档保留待重试）。
    """
    if body.category not in VALID_CATEGORIES:
        raise BusinessException(400, f"category 仅支持 {'/'.join(VALID_CATEGORIES.keys())}")

    # 正文落盘（uploads/knowledge/{safe_name}.txt）
    from pathlib import Path
    import re as _re

    from app.core.config import BASE_DIR

    safe_name = _re.sub(r"[^\w\u4e00-\u9fff-]", "_", body.title)[:60] or "doc"
    knowledge_dir = BASE_DIR / "uploads" / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{safe_name}_{now().strftime('%Y%m%d%H%M%S')}.txt"
    (knowledge_dir / file_name).write_text(body.content, encoding="utf-8")

    doc = KnowledgeDocument(
        title=body.title,
        category=body.category,
        file_url=f"/uploads/knowledge/{file_name}",
        milvus_collection="knowledge_docs",
        chunk_count=0,
        embed_status="pending",
    )
    db.add(doc)
    db.commit()

    # 切片向量化（失败置 failed 保留记录）
    try:
        chunk_count = vector_store.add_document(doc.id, doc.title, doc.category, body.content)
        doc.chunk_count = chunk_count
        doc.embed_status = "done"
        db.commit()
    except Exception as exc:  # noqa: BLE001 向量化失败不阻塞文档保留
        doc.embed_status = "failed"
        db.commit()
        raise BusinessException(502, f"文档已入库但向量化失败（可重试）：{exc}")

    result: dict[str, Any] = {
        "id": doc.id,
        "title": doc.title,
        "chunk_count": doc.chunk_count,
        "embed_status": doc.embed_status,
    }
    return ok(result)
