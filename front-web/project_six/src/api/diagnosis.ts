/**
 * 文件说明：智能诊断模块 API 封装。
 * 包含任务创建、任务详情轮询、诊断记录分页查询与失败重试接口。
 */
import { get, post } from './request'
import type { Paged } from '@/types/api'
import type { DiagnosisRecord, DiagnosisTaskDetail } from '@/types/farm'

/** 诊断任务创建载荷 */
export interface DiagnosisTaskPayload {
  /** 地块 ID */
  plot_id: number
  /** 生育期 */
  growth_stage?: string | null
  /** 图像 ID 列表 */
  image_ids: number[]
}

/** 诊断任务创建响应 */
export interface DiagnosisTaskCreated {
  /** 任务 ID */
  task_id: number
  /** 任务状态 */
  status: string
}

/** 诊断记录查询参数 */
export interface DiagnosisRecordQuery {
  /** 地块 ID */
  plot_id?: number
  /** 来源：device/manual */
  source?: string
  /** 开始日期 YYYY-MM-DD */
  start?: string
  /** 结束日期 YYYY-MM-DD */
  end?: string
  /** 置信度档位：high/low */
  level?: string
  /** 页码 */
  page?: number
  /** 每页条数 */
  page_size?: number
}

/**
 * 创建诊断任务（异步执行，前端轮询任务详情）。
 * @param data 任务参数（地块、生育期、图像 ID）
 * @returns 任务 ID 与初始状态
 * @throws 图像不存在或参数校验失败时抛出异常
 */
export function createDiagnosisTask(data: DiagnosisTaskPayload): Promise<DiagnosisTaskCreated> {
  return post<DiagnosisTaskCreated>('/diagnosis/tasks', data)
}

/**
 * 查询诊断任务详情。
 * @param id 任务 ID
 * @returns 任务详情（含识别结果、方案卡、关联案例）
 * @throws 任务不存在时抛出异常
 */
export function getDiagnosisTask(id: number): Promise<DiagnosisTaskDetail> {
  return get<DiagnosisTaskDetail>(`/diagnosis/tasks/${id}`)
}

/**
 * 分页查询诊断记录。
 * @param params 筛选与分页参数
 * @returns 分页记录列表
 * @throws 请求失败时抛出异常
 */
export function listDiagnosisRecords(params: DiagnosisRecordQuery): Promise<Paged<DiagnosisRecord>> {
  return get<Paged<DiagnosisRecord>>('/diagnosis/records', params)
}

/**
 * 重试失败的诊断任务。
 * @param id 任务 ID
 * @returns 空数据
 * @throws 任务状态不允许重试时抛出异常
 */
export function retryDiagnosisTask(id: number): Promise<void> {
  return post<void>(`/diagnosis/tasks/${id}/retry`)
}
