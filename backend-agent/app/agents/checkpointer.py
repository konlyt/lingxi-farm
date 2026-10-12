"""简化版 LangGraph MySQL Checkpointer 模块。

基于已建三张 langgraph_* 表实现 JSON 序列化的状态持久化：
- langgraph_checkpoints：检查点主表（最新/历史状态快照）；
- langgraph_checkpoint_blobs / langgraph_checkpoint_writes：本简化实现不强制使用，
  预留给后续按 LangGraph 官方协议扩展。

只需支持 save(thread_id, state) / load(thread_id) 两个能力，
不实现 LangGraph 官方 BaseCheckpointSaver 全协议。
"""
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.misc import LanggraphCheckpoint


class SimpleMySQLCheckpointer:
    """简化版 MySQL 检查点保存器。

    以 JSON 序列化方式将图执行状态快照存入 langgraph_checkpoints 表，
    load 返回最新一条快照，支撑全流程持久化与回放。
    """

    def save(self, db: Session, thread_id: str, state: dict[str, Any], node_name: str = "") -> int:
        """保存一次状态快照。

        Args:
            db: 数据库会话（由调用方管理事务，本方法不 commit）。
            thread_id: 线程ID（诊断任务为 diagnosis_task.thread_id）。
            state: 图状态字典（须已剔除不可序列化对象）。
            node_name: 产生该快照的节点名（记录进 metadata）。

        Returns:
            int: 新增检查点记录ID。

        Raises:
            Exception: 序列化失败或数据库写入失败时抛出。
        """
        record = LanggraphCheckpoint(
            thread_id=thread_id,
            checkpoint_ns="",
            checkpoint_id=uuid.uuid4().hex,
            metadata={"node": node_name, "saved_at": datetime.now().isoformat()},
            channel_values=json.dumps(state, ensure_ascii=False, default=str),
            channel_versions={},
        )
        db.add(record)
        db.flush()
        return record.id

    def load(self, db: Session, thread_id: str) -> Optional[dict[str, Any]]:
        """加载指定线程最新一条状态快照。

        Args:
            db: 数据库会话。
            thread_id: 线程ID。

        Returns:
            dict | None: 反序列化后的状态字典；无线程记录返回 None。

        Raises:
            Exception: 数据库查询失败时抛出。
        """
        record = (
            db.query(LanggraphCheckpoint)
            .filter(LanggraphCheckpoint.thread_id == thread_id)
            .order_by(LanggraphCheckpoint.id.desc())
            .first()
        )
        if record is None or not record.channel_values:
            return None
        return json.loads(record.channel_values)

    def list_threads(self, db: Session, limit: int = 100) -> list[str]:
        """列出最近有快照的线程ID（调试/回放用）。

        Args:
            db: 数据库会话。
            limit: 返回上限，默认 100。

        Returns:
            list[str]: 线程ID列表（按最近快照倒序）。
        """
        rows = (
            db.query(LanggraphCheckpoint.thread_id)
            .order_by(LanggraphCheckpoint.id.desc())
            .limit(limit)
            .all()
        )
        return [row[0] for row in rows]


# 全局单例
checkpointer = SimpleMySQLCheckpointer()
