/**
 * 文件说明：数据导出模块 API 封装。
 * 包含导出任务创建、任务列表查询；文件下载使用任务返回的 file_url 直链。
 * 契约说明：导出类型枚举为 diagnosis_cases/env_data；状态机为 pending → done/failed；
 * 列表接口直接返回数组；创建接口返回 {export_id, status}。
 */
import { get, post } from './request'
import type { ExportTask } from '@/types/farm'

/**
 * 创建异步导出任务（诊断案例/环境数据 CSV）。
 * @param data 导出类型（diagnosis_cases/env_data）与时间范围
 * @returns 任务 ID（export_id）与初始状态
 * @throws member 角色调用返回 403
 */
export function createExportTask(data: {
  export_type: 'diagnosis_cases' | 'env_data'
  start: string
  end: string
}): Promise<{ export_id: number; status: string }> {
  return post<{ export_id: number; status: string }>('/exports', data)
}

/**
 * 查询导出任务列表（后端直接返回数组，统一包装为 {items} 便于页面消费）。
 * @returns 任务列表（含状态与文件地址）
 * @throws 请求失败时抛出异常
 */
export async function listExportTasks(): Promise<{ items: ExportTask[] }> {
  const items = await get<ExportTask[]>('/exports')
  return { items }
}
