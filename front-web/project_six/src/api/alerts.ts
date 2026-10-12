/**
 * 文件说明：预警中心模块 API 封装。
 * 包含预警分页列表、详情（含时间线）与确认解决接口。
 */
import { get, post } from './request'
import type { Paged } from '@/types/api'
import type { AlertDetail, AlertItem } from '@/types/farm'

/**
 * 分页查询预警列表。
 * @param params 查询参数（status：active 未解决 / resolved 已解决；type：预警类型）
 * @returns 分页预警列表
 * @throws 请求失败时抛出异常
 */
export function getAlerts(params?: {
  status?: 'active' | 'resolved'
  type?: string
  page?: number
  page_size?: number
}): Promise<Paged<AlertItem>> {
  return get<Paged<AlertItem>>('/alerts', params)
}

/**
 * 查询预警详情（含病情时间线、现场照片、关联诊断）。
 * @param id 预警 ID
 * @returns 预警详情
 * @throws 预警不存在时抛出异常
 */
export function getAlertDetail(id: number): Promise<AlertDetail> {
  return get<AlertDetail>(`/alerts/${id}`)
}

/**
 * 确认解决预警（关闭聚合窗口）。
 * @param id 预警 ID
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function resolveAlert(id: number): Promise<void> {
  return post<void>(`/alerts/${id}/resolve`)
}
