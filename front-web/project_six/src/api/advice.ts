/**
 * 文件说明：决策建议模块 API 封装。
 * 包含水肥建议查询/生成、大棚环境调控建议、每日农情简报接口。
 */
import { get, post } from './request'
import type { DailyBrief, EnvironmentAdvice, WaterFertilizerAdvice } from '@/types/farm'

/**
 * 查询地块未来 7 天水肥建议（后端 plot_id 必填，返回双层 data 包装结构）。
 * @param params 查询参数（plot_id 必填、date 日期，默认当日）
 * @returns 水肥建议数据
 * @throws 请求失败时抛出异常
 */
export function getWaterFertilizerAdvice(params: { plot_id: number; date?: string }): Promise<WaterFertilizerAdvice> {
  return get<WaterFertilizerAdvice>('/advice/water-fertilizer', params)
}

/**
 * 手动触发生成水肥建议（定时任务外补充）。
 * @param data 参数（plot_id 缺省时为全部地块）
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function generateWaterFertilizerAdvice(data?: { plot_id?: number }): Promise<void> {
  return post<void>('/advice/water-fertilizer/generate', data)
}

/**
 * 查询大棚未来 12 小时通风/保温/降湿调控建议。
 * @param params 查询参数（plot_id 必填）
 * @returns 调控建议数据
 * @throws 请求失败时抛出异常
 */
export function getEnvironmentAdvice(params: { plot_id: number }): Promise<EnvironmentAdvice> {
  return get<EnvironmentAdvice>('/advice/environment', params)
}

/**
 * 查询每日农情简报。
 * @param params 查询参数（date 默认当日）
 * @returns 简报数据
 * @throws 请求失败时抛出异常
 */
export function getDailyBrief(params?: { date?: string }): Promise<DailyBrief> {
  return get<DailyBrief>('/advice/daily-brief', params)
}
