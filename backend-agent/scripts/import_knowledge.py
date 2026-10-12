"""知识库批量导入脚本。

读取 scripts/knowledge_corpus/ 下的 Markdown 语料文件，
复用 app/api/knowledge.py 相同的入库链路：
正文落盘(uploads/knowledge/) → 切片 → 智谱 Embedding-3 向量化 → vectors.json 追加。

文件命名与分类约定（文件名前缀决定分类）：
- disease_map_*.md  → 病虫害图谱
- treatment_*.md    → 防治方案库
- pesticide_regulation_*.md → 禁限用农药名录

运行方式（在 backend-agent 目录下）：
    .venv/Scripts/python.exe scripts/import_knowledge.py

特性：
- 按标题去重：已入库的同名文档自动跳过；
- 单文档向量化失败不中断整体（该文档置 failed，可重跑本脚本重试）。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.core.database import SessionLocal  # noqa: E402
from app.models.knowledge import KnowledgeDocument  # noqa: E402
from app.services import vector_store  # noqa: E402
from app.utils.time_utils import now  # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parent / "knowledge_corpus"

CATEGORY_BY_PREFIX = {
    "disease_map": "disease_map",
    "treatment": "treatment",
    "pesticide_regulation": "pesticide_regulation",
}


def parse_file(path: Path) -> tuple[str, str, str] | None:
    """解析语料文件为 (title, category, content)。

    首行若为 "# 标题" 则取为文档标题，否则用文件名去前缀。
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    lines = text.splitlines()
    title = path.stem
    for prefix in CATEGORY_BY_PREFIX:
        if title.startswith(f"{prefix}_"):
            title = title[len(prefix) + 1:]
            break
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        content = "\n".join(lines[1:]).strip()
    else:
        content = text
    category = next(
        (cat for prefix, cat in CATEGORY_BY_PREFIX.items() if path.stem.startswith(prefix)),
        None,
    )
    if category is None:
        print(f"[跳过] {path.name}：文件名缺少分类前缀(disease_map_/treatment_/pesticide_regulation_)")
        return None
    return title, category, content


def main() -> None:
    files = sorted(CORPUS_DIR.glob("*.md"))
    if not files:
        print(f"语料目录为空：{CORPUS_DIR}")
        return

    db = SessionLocal()
    existing = {t for (t,) in db.query(KnowledgeDocument.title).all()}

    ok_count, skip_count, fail_count = 0, 0, 0
    for path in files:
        parsed = parse_file(path)
        if parsed is None:
            skip_count += 1
            continue
        title, category, content = parsed
        if title in existing:
            print(f"[跳过] {title}：同名文档已入库")
            skip_count += 1
            continue

        # 正文落盘（与 API 入口保持一致：uploads/knowledge/{safe_name}_{ts}.txt）
        import re

        safe_name = re.sub(r"[^\w\u4e00-\u9fff-]", "_", title)[:60] or "doc"
        knowledge_dir = BASE_DIR / "uploads" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{safe_name}_{now().strftime('%Y%m%d%H%M%S')}.txt"
        (knowledge_dir / file_name).write_text(content, encoding="utf-8")

        doc = KnowledgeDocument(
            title=title,
            category=category,
            file_url=f"/uploads/knowledge/{file_name}",
            milvus_collection="knowledge_docs",
            chunk_count=0,
            embed_status="pending",
        )
        db.add(doc)
        db.commit()

        try:
            chunk_count = vector_store.add_document(doc.id, doc.title, doc.category, content)
            doc.chunk_count = chunk_count
            doc.embed_status = "done"
            db.commit()
            print(f"[完成] {title} → {chunk_count} 个切片")
            ok_count += 1
        except Exception as exc:  # noqa: BLE001
            doc.embed_status = "failed"
            db.commit()
            print(f"[失败] {title}：向量化失败（{exc}），文档已保留可重试")
            fail_count += 1

    db.close()
    total_chunks = sum(c for (c,) in db.query(KnowledgeDocument.chunk_count).all()) if False else None
    print(f"\n导入完成：成功 {ok_count}，跳过 {skip_count}，失败 {fail_count}")


if __name__ == "__main__":
    main()
