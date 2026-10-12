"""知识问答接口路由。

提供会话管理（列表/创建/历史消息）与提问接口：
user 消息落库 → Supervisor 意图识别 → knowledge 意图走 RAG 回答 → assistant 消息落库。
"""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.graph import build_farm_graph
from app.agents.llm import clients as llm_clients
from app.core.database import get_db
from app.core.response import BusinessException, ok
from app.core.security import get_current_user
from app.models.chat import ChatMessage, ChatSession
from app.models.user import SysUser
from app.utils.time_utils import fmt_datetime, now

router = APIRouter(prefix="/api/chat", tags=["知识问答"], dependencies=[Depends(get_current_user)])


class ChatSessionCreateRequest(BaseModel):
    """创建会话请求体。

    Attributes:
        title: 会话标题（可空，默认「新会话」）。
    """

    title: str | None = Field(None, max_length=128, description="会话标题")


class ChatQueryRequest(BaseModel):
    """知识问答提问请求体。

    Attributes:
        session_id: 会话ID。
        question: 用户问题。
    """

    session_id: int = Field(..., gt=0, description="会话ID")
    question: str = Field(..., min_length=1, max_length=1000, description="问题")


@router.get("/sessions", summary="会话列表")
def list_sessions(db: Session = Depends(get_db), user: SysUser = Depends(get_current_user)) -> dict:
    """查询当前用户的问答会话列表。

    Args:
        db: 数据库会话。
        user: 当前用户。

    Returns:
        dict: 统一响应，data 为会话数组。
    """
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.id.desc())
        .all()
    )
    return ok(
        [
            {
                "id": session.id,
                "title": session.title or "新会话",
                "created_at": fmt_datetime(session.created_at),
            }
            for session in rows
        ]
    )


@router.post("/sessions", summary="创建会话")
def create_session(body: ChatSessionCreateRequest | None = None, db: Session = Depends(get_db),
                   user: SysUser = Depends(get_current_user)) -> dict:
    """创建知识问答会话（请求体可省略，默认标题「新会话」）。

    Args:
        body: 创建请求体（可选）。
        db: 数据库会话。
        user: 当前用户。

    Returns:
        dict: 统一响应，data 为 {id, title}。
    """
    title = (body.title if body is not None else None) or "新会话"
    session = ChatSession(user_id=user.id, title=title)
    db.add(session)
    db.commit()
    return ok({"id": session.id, "title": session.title})


@router.get("/sessions/{session_id}/messages", summary="会话历史消息")
def list_messages(session_id: int, db: Session = Depends(get_db),
                  user: SysUser = Depends(get_current_user)) -> dict:
    """查询会话历史消息（时间正序）。

    Args:
        session_id: 会话ID。
        db: 数据库会话。
        user: 当前用户。

    Returns:
        dict: 统一响应，data 为消息数组。

    Raises:
        BusinessException: 404 会话不存在或不属于当前用户。
    """
    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == user.id).first()
    if session is None:
        raise BusinessException(404, "会话不存在")
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return ok(
        [
            {
                "id": msg.id,
                "role": msg.role,
                "content_type": msg.content_type,
                "content": msg.content,
                "created_at": fmt_datetime(msg.created_at),
            }
            for msg in rows
        ]
    )


@router.post("/queries", summary="知识问答（Supervisor 意图识别 + RAG 回答）")
def chat_query(body: ChatQueryRequest, db: Session = Depends(get_db),
               user: SysUser = Depends(get_current_user)) -> dict:
    """知识问答：意图识别 → RAG 检索 → DeepSeek 回答 → 消息落库。

    Args:
        body: 提问请求体 {session_id, question}。
        db: 数据库会话。
        user: 当前用户。

    Returns:
        dict: 统一响应，data 为 {session_id, answer, low_confidence}。

    Raises:
        BusinessException: 404 会话不存在或不属于当前用户。
    """
    session = db.query(ChatSession).filter(ChatSession.id == body.session_id, ChatSession.user_id == user.id).first()
    if session is None:
        raise BusinessException(404, "会话不存在")

    # user 消息落库
    db.add(ChatMessage(session_id=session.id, user_id=user.id, role="user", content_type="text", content=body.question))
    db.commit()

    # Supervisor 意图识别（结果随响应返回；问答通道统一经 knowledge 节点产出文本回答）
    intent = llm_clients.recognize_intent(body.question)
    graph = build_farm_graph(db)
    try:
        state = graph.invoke(
            {
                "intent": "knowledge",
                "thread_id": f"chat-{session.id}-{now().strftime('%Y%m%d%H%M%S')}",
                "question": body.question,
            }
        )
    except Exception as exc:  # noqa: BLE001 智能体失败降级为固定提示
        state = {
            "answer": f"知识问答服务暂时不可用，请稍后重试。（原因：{exc}）",
            "low_confidence": True,
        }
    answer = state.get("answer", "")
    low_confidence = bool(state.get("low_confidence", False))

    # assistant 消息落库
    db.add(
        ChatMessage(
            session_id=session.id,
            user_id=user.id,
            role="assistant",
            content_type="text",
            content=answer,
        )
    )
    # 首次提问把问题设为会话标题
    if session.title in (None, "新会话"):
        session.title = body.question[:50]
    db.commit()

    result: dict[str, Any] = {
        "session_id": session.id,
        "answer": answer,
        "low_confidence": low_confidence,
        "intent": intent,
    }
    return ok(result)
