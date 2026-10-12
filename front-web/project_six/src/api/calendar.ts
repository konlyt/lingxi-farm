/**
 * 文件说明：农事日历模块 API 封装。
 * 包含按地块/月份的农事事件与 upcoming 提醒接口。
 * 契约说明：后端返回 {events: [...]} / {reminders: [...]}，此处统一解包为数组。
 */
import { get } from './request'
import type { CalendarEvent, CalendarReminder } from '@/types/farm'

/**
 * 查询农事日历事件（按地块作物生育期推算，解包 events 字段）。
 * @param params 查询参数（plot_id 地块、month 月份 YYYY-MM）
 * @returns 事件列表
 * @throws 请求失败时抛出异常
 */
export async function getCalendarEvents(params?: {
  plot_id?: number
  month?: string
}): Promise<CalendarEvent[]> {
  const res = await get<{ events: CalendarEvent[] }>('/calendar', params)
  return res.events
}

/**
 * 查询即将到来的农事提醒列表（解包 reminders 字段）。
 * @param params 查询参数（plot_id 可选）
 * @returns 提醒列表（含 days_until 剩余天数）
 * @throws 请求失败时抛出异常
 */
export async function getCalendarReminders(params?: { plot_id?: number }): Promise<CalendarReminder[]> {
  const res = await get<{ reminders: CalendarReminder[] }>('/calendar/reminders', params)
  return res.reminders
}
