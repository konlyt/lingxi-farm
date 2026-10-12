/**
 * 文件说明：设备管理模块 API 封装。
 * 包含统计、列表、详情（含心跳历史）、新增、心跳上报、远程配置接口。
 */
import { get, post } from './request'
import type { Device, DeviceDetail, DeviceStats } from '@/types/farm'

/**
 * 设备新增载荷（与后端 DeviceCreateRequest 对齐）。
 * type 枚举：camera/pest_light/spore_trap/env_sensor；protocol 枚举：MQTT/RTSP/vendor_api；
 * name 与 plot_id 为必填；collect_schedule 传输 JSON 对象。
 */
export interface DevicePayload {
  /** 设备编号（唯一） */
  device_no: string
  /** 设备名称（后端必填） */
  name: string
  /** 类型：camera/pest_light/spore_trap/env_sensor */
  type: string
  /** 所属地块 ID（后端必填） */
  plot_id: number
  /** 接入协议：MQTT/RTSP/vendor_api */
  protocol: string
  /** 厂商 */
  vendor?: string | null
  /** 采集计划 JSON 对象（后端 dict） */
  collect_schedule?: Record<string, unknown> | null
}

/**
 * 查询设备统计（总数/在线/离线）。
 * @returns 统计数据
 * @throws 请求失败时抛出异常
 */
export function getDeviceStats(): Promise<DeviceStats> {
  return get<DeviceStats>('/devices/stats')
}

/**
 * 查询设备列表。
 * @param params 查询参数（plot_id 按地块过滤）
 * @returns 设备列表
 * @throws 请求失败时抛出异常
 */
export function getDevices(params?: { plot_id?: number }): Promise<Device[]> {
  return get<Device[]>('/devices', params)
}

/**
 * 查询设备详情（含心跳历史）。
 * @param id 设备 ID
 * @returns 设备详情
 * @throws 设备不存在时抛出异常
 */
export function getDeviceDetail(id: number): Promise<DeviceDetail> {
  return get<DeviceDetail>(`/devices/${id}`)
}

/**
 * 新增设备（新增向导最终提交）。
 * @param data 设备参数
 * @returns 新建的设备 {id, device_no}
 * @throws 编号重复或校验失败时抛出异常
 */
export function createDevice(data: DevicePayload): Promise<{ id: number; device_no: string }> {
  return post<{ id: number; device_no: string }>('/devices', data)
}

/**
 * 上报设备心跳（设备模拟器/调试用）。
 * @param id 设备 ID
 * @returns 空数据
 * @throws 设备不存在时抛出异常
 */
export function sendHeartbeat(id: number): Promise<void> {
  return post<void>(`/devices/${id}/heartbeat`)
}

/**
 * 下发设备远程配置。
 * @param id 设备 ID
 * @param config 配置对象
 * @returns 空数据
 * @throws 配置校验失败时抛出异常
 */
export function sendDeviceConfig(id: number, config: Record<string, unknown>): Promise<void> {
  return post<void>(`/devices/${id}/config`, { config })
}
