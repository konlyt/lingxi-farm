/**
 * 文件说明：知识问答模块 API 封装。
 * 包含会话管理、会话消息历史与提问接口。
 */
import { get, post } from './request'
import type { ChatAnswer, ChatMessage, ChatSession } from '@/types/farm'

/**
 * 查询历史会话列表。
 * @returns 会话列表
 * @throws 请求失败时抛出异常
 */
export function listChatSessions(): Promise<ChatSession[]> {
  return get<ChatSession[]>('/chat/sessions')
}

/**
 * 创建新会话。
 * @returns 新会话（含 ID）
 * @throws 请求失败时抛出异常
 */
export function createChatSession(): Promise<{ id: number }> {
  return post<{ id: number }>('/chat/sessions')
}

/**
 * 查询会话消息历史。
 * @param sessionId 会话 ID
 * @returns 消息列表（按时间升序）
 * @throws 会话不存在时抛出异常
 */
export function listChatMessages(sessionId: number): Promise<ChatMessage[]> {
  return get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`)
}

/**
 * 发送提问并获取 AI 回答（Supervisor → 知识检索智能体 RAG）。
 * @param sessionId 会话 ID
 * @param question 问题文本
 * @returns 回答内容与低置信度标记
 * @throws 模型超时或服务异常时抛出异常
 */
export function askQuestion(sessionId: number, question: string): Promise<ChatAnswer> {
  return post<ChatAnswer>('/chat/queries', { session_id: sessionId, question })
}
