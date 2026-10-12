/**
 * 文件说明：农场总览与监测大屏模块 API 封装。
 * 分别对应总览聚合接口与大屏统计聚合接口。
 */
import { get } from './request'
import type { DashboardStats, FarmOverview } from '@/types/farm'

/**
 * 查询农场总览聚合数据（禁令角标/地块卡片/待办/预警/天气）。
 * @returns 总览数据
 * @throws 请求失败时抛出异常
 */
export function getOverview(): Promise<FarmOverview> {
  return get<FarmOverview>('/overview')
}

/**
 * 查询监测大屏聚合统计。
 * @returns 大屏统计数据
 * @throws 请求失败时抛出异常
 */
export function getDashboardStats(): Promise<DashboardStats> {
  return get<DashboardStats>('/dashboard/stats')
}
