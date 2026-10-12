/**
 * 文件说明：系统设置模块 API 封装。
 * 包含置信度阈值配置、家庭成员管理与服务号绑定状态接口。
 */
import { get, patch, post, put } from './request'
import type { ConfidenceThreshold, Member, WxBindItem } from '@/types/farm'

/**
 * 查询置信度阈值分病种配置列表。
 * @returns 阈值配置列表
 * @throws 请求失败时抛出异常
 */
export function getConfidenceThresholds(): Promise<ConfidenceThreshold[]> {
  return get<ConfidenceThreshold[]>('/settings/confidence-thresholds')
}

/**
 * 批量保存置信度阈值（修改即时生效于诊断链路）。
 * @param items 阈值编辑项列表（id + 新阈值）
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function updateConfidenceThresholds(items: Array<{ id: number; threshold: number }>): Promise<void> {
  return put<void>('/settings/confidence-thresholds', { items })
}

/**
 * 查询家庭成员列表。
 * @returns 成员列表
 * @throws 请求失败时抛出异常
 */
export function getMembers(): Promise<Member[]> {
  return get<Member[]>('/settings/members')
}

/**
 * 邀请家庭成员（创建只读账号）。
 * @param data 成员账号信息（用户名/昵称/初始密码）
 * @returns 空数据
 * @throws 用户名重复或 member 角色调用时抛出异常
 */
export function createMember(data: { username: string; nickname: string; password: string }): Promise<void> {
  return post<void>('/settings/members', data)
}

/**
 * 启用/停用家庭成员账号。
 * @param id 成员用户 ID
 * @param status 1 启用 / 0 停用
 * @returns 空数据
 * @throws member 角色调用返回 403
 */
export function updateMemberStatus(id: number, status: 0 | 1): Promise<void> {
  return patch<void>(`/settings/members/${id}/status`, { status })
}

/**
 * 查询服务号绑定状态列表。
 * @returns 绑定状态列表
 * @throws 请求失败时抛出异常
 */
export function getWxBind(): Promise<WxBindItem[]> {
  return get<WxBindItem[]>('/settings/wx-bind')
}
