/**
 * 文件说明：知识库文档模块 API 封装。
 * 包含知识文档列表与入库接口（切片 + 向量化由后端完成）。
 */
import { get, post } from './request'
import type { KnowledgeDocument } from '@/types/farm'

/**
 * 查询知识文档列表。
 * @returns 文档列表
 * @throws 请求失败时抛出异常
 */
export function listKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  return get<KnowledgeDocument[]>('/knowledge/documents')
}

/**
 * 新增知识文档（后端自动切片并向量化入库）。
 * @param data 文档标题、分类与正文
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function createKnowledgeDocument(data: {
  title: string
  category: string
  content: string
}): Promise<void> {
  return post<void>('/knowledge/documents', data)
}
