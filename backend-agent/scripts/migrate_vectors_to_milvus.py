"""存量向量数据迁移脚本：vectors.json → Milvus。

直接复用 vectors.json 中现成的 2048 维向量批量写入 Milvus，
全程不调用智谱 Embedding API（零 API 成本、秒级完成）。
写入前按 doc_id 清理同文档旧切片，脚本可重复执行（幂等）。

运行方式（在 backend-agent 目录下）：
    .venv/Scripts/python.exe scripts/migrate_vectors_to_milvus.py

前置条件：
- Milvus 服务已启动（默认 127.0.0.1:19530，见 .env MILVUS_* 配置）；
- pymilvus 已安装（pip install pymilvus）。

迁移完成后可运行 scripts/run_eval.py 验证检索命中率，
或对比两后端 top-k 结果一致性（见项目文档）。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.core.config import settings  # noqa: E402
from app.services import vector_milvus  # noqa: E402
from app.services.vector_local import VECTOR_FILE  # noqa: E402


def main() -> None:
    """读取 vectors.json 全部切片并写入 Milvus collection。"""
    if not VECTOR_FILE.exists():
        print(f"未找到本地向量库：{VECTOR_FILE}")
        sys.exit(1)
    import json

    chunks = json.loads(VECTOR_FILE.read_text(encoding="utf-8")).get("chunks", [])
    if not chunks:
        print("本地向量库为空，无需迁移")
        return

    print(f"本地切片数: {len(chunks)}，目标: {settings.milvus_host}:{settings.milvus_port}/{settings.milvus_collection}")
    if not vector_milvus.ping():
        print("Milvus 服务不可达：请先启动 Milvus（docker compose -f docker-compose.milvus.yml up -d 或启动已有容器）")
        sys.exit(1)

    written = vector_milvus.insert_chunks(chunks)
    counts = vector_milvus.get_chunk_counts()
    print(f"\n迁移完成：写入 {written} 个切片，覆盖 {len(counts)} 篇文档")
    print("collection 内切片分布：")
    for doc_id, count in sorted(counts.items()):
        print(f"  doc_id={doc_id}: {count} 片")


if __name__ == "__main__":
    main()
