/**
 * 文件说明：大棚环境监控模块 API 封装。
 * 包含实时环境、趋势、越限报警记录与阈值配置（模板 + 地块覆盖）接口。
 */
import { del, get, post, put } from './request'
import type {
  AlarmRecord,
  EnvTrend,
  RealtimeEnv,
  ThresholdPayload,
  ThresholdSettings,
} from '@/types/farm'

/**
 * 查询地块实时环境值（越限标记即时返回）。
 * @param params 查询参数（plot_id 必填）
 * @returns 实时环境数据
 * @throws 请求失败时抛出异常
 */
export function getRealtimeEnv(params: { plot_id: number }): Promise<RealtimeEnv> {
  return get<RealtimeEnv>('/environment/realtime', params)
}

/**
 * 查询环境趋势数据。
 * @param params 查询参数（plot_id、range：24h/7d）
 * @returns 趋势数据（时间轴与各指标序列）
 * @throws 请求失败时抛出异常
 */
export function getEnvTrend(params: { plot_id: number; range: '24h' | '7d' }): Promise<EnvTrend> {
  return get<EnvTrend>('/environment/trend', params)
}

/**
 * 查询环境越限报警记录（后端 plot_id 必填，直接返回数组）。
 * @param params 查询参数（plot_id 必填）
 * @returns 报警记录列表
 * @throws 请求失败时抛出异常
 */
export function getAlarmRecords(params: { plot_id: number }): Promise<AlarmRecord[]> {
  return get<AlarmRecord[]>('/environment/alarm-records', params)
}

/**
 * 查询阈值配置（默认模板 + 地块覆盖）。
 * @param params 查询参数（plot_id 可选，按地块过滤覆盖配置）
 * @returns 阈值配置集合
 * @throws 请求失败时抛出异常
 */
export function getThresholds(params?: { plot_id?: number }): Promise<ThresholdSettings> {
  return get<ThresholdSettings>('/environment/thresholds', params)
}

/**
 * 新建地块级阈值覆盖配置（enabled 转换为 0/1 传输，对齐后端 int 约束）。
 * @param data 配置数据（plot_id 必填）
 * @returns 空数据
 * @throws 下限不小于上限或 member 角色调用时抛出异常
 */
export function createThreshold(data: ThresholdPayload): Promise<void> {
  return post<void>('/environment/thresholds', { ...data, enabled: data.enabled ? 1 : 0 })
}

/**
 * 编辑地块级阈值覆盖配置（enabled 转换为 0/1 传输）。
 * @param id 配置 ID
 * @param data 配置数据
 * @returns 空数据
 * @throws 下限不小于上限或 member 角色调用时抛出异常
 */
export function updateThreshold(id: number, data: ThresholdPayload): Promise<void> {
  return put<void>(`/environment/thresholds/${id}`, { ...data, enabled: data.enabled ? 1 : 0 })
}

/**
 * 删除地块级阈值覆盖配置。
 * @param id 配置 ID
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function deleteThreshold(id: number): Promise<void> {
  return del<void>(`/environment/thresholds/${id}`)
}
