/**
 * 文件说明：地块/棚室档案模块 API 封装。
 * 包含列表、详情、新增、编辑、停用/启用接口。
 * 契约说明：后端 GET /plots 返回分页结构 {items, total, page, page_size}，
 * type 为字符串枚举 greenhouse/open_field；此处解包 items 并以大页容量拉取全量。
 */
import { get, patch, post, put } from './request'
import type { Plot, PlotDetail } from '@/types/farm'

/** 地块新增/编辑载荷（type 与后端 PlotCreateRequest 对齐） */
export interface PlotPayload {
  /** 名称（唯一） */
  name: string
  /** 类型：greenhouse 大棚 / open_field 露天 */
  type: 'greenhouse' | 'open_field'
  /** 经度（露天地块必填） */
  lng?: number | null
  /** 纬度（露天地块必填） */
  lat?: number | null
  /** 面积（亩） */
  area_mu?: number | null
  /** 土壤类型 */
  soil_type?: string | null
  /** 作物名称（后端必填） */
  crop_name?: string | null
  /** 作物品种 */
  crop_variety?: string | null
  /** 生育期（后端必填） */
  growth_stage?: string | null
  /** 定植日期 YYYY-MM-DD（空串需转为 null） */
  planted_at?: string | null
  /** 备注 */
  remark?: string | null
}

/** 地块列表分页返回结构 */
interface PlotPage {
  /** 当前页地块列表 */
  items: Plot[]
  /** 总条数 */
  total: number
  /** 当前页码 */
  page: number
  /** 每页条数 */
  page_size: number
}

/**
 * 查询地块列表（解包后端分页结构，仅回传 items）。
 * @param params 查询参数（status：1 在种 / 0 停用）
 * @returns 地块列表
 * @throws 请求失败时抛出异常
 */
export async function getPlots(params?: { status?: number }): Promise<Plot[]> {
  const res = await get<PlotPage>('/plots', { page_size: 100, ...params })
  return res.items
}

/**
 * 查询地块详情（含最新环境快照与采收禁令 harvest_restrictions）。
 * @param id 地块 ID
 * @returns 地块详情
 * @throws 地块不存在时抛出异常
 */
export function getPlot(id: number): Promise<PlotDetail> {
  return get<PlotDetail>(`/plots/${id}`)
}

/**
 * 新增地块档案。
 * @param data 地块表单数据
 * @returns 新建的地块 {id, name}
 * @throws 名称重复或校验失败时抛出异常
 */
export function createPlot(data: PlotPayload): Promise<{ id: number; name: string }> {
  return post<{ id: number; name: string }>('/plots', data)
}

/**
 * 编辑地块档案。
 * @param id 地块 ID
 * @param data 地块表单数据
 * @returns 更新后的基本信息 {id, name, status}
 * @throws 名称重复或校验失败时抛出异常
 */
export function updatePlot(id: number, data: PlotPayload): Promise<{ id: number; name: string; status: number }> {
  return put<{ id: number; name: string; status: number }>(`/plots/${id}`, data)
}

/**
 * 停用/启用地块（软删除）。
 * @param id 地块 ID
 * @param status 1 在种 / 0 停用
 * @returns 空数据
 * @throws 请求失败时抛出异常
 */
export function updatePlotStatus(id: number, status: 0 | 1): Promise<void> {
  return patch<void>(`/plots/${id}/status`, { status })
}
