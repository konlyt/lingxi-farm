/**
 * 文件说明：案例库模块 API 封装。
 * 包含统计、分页列表、单条确认、纠正与批量确认接口。
 */
import { get, post } from './request'
import type { Paged } from '@/types/api'
import type { CaseItem, CaseStats } from '@/types/farm'

/**
 * 查询案例统计（总数/待确认/已确认/已纠正/病种样本量）。
 * @returns 统计数据
 * @throws 请求失败时抛出异常
 */
export function getCaseStats(): Promise<CaseStats> {
  return get<CaseStats>('/cases/stats')
}

/**
 * 分页查询案例列表。
 * @param params 筛选与分页参数（status：pending/confirmed/corrected）
 * @returns 分页案例列表
 * @throws 请求失败时抛出异常
 */
export function getCases(params?: {
  status?: string
  category?: string
  page?: number
  page_size?: number
}): Promise<Paged<CaseItem>> {
  return get<Paged<CaseItem>>('/cases', params)
}

/**
 * 确认案例正确（final = ai_disease_name）。
 * @param id 案例 ID
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function confirmCase(id: number): Promise<void> {
  return post<void>(`/cases/${id}/confirm`)
}

/**
 * 纠正案例病名（final = 输入病名）。
 * @param id 案例 ID
 * @param data 正确病名与备注
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function correctCase(id: number, data: { final_disease_name: string; note?: string }): Promise<void> {
  return post<void>(`/cases/${id}/correct`, data)
}

/**
 * 批量确认待确认案例。
 * @param ids 案例 ID 列表
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function batchConfirmCases(ids: number[]): Promise<void> {
  return post<void>('/cases/batch-confirm', { ids })
}
