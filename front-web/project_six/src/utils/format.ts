/**
 * 文件说明：通用展示格式化工具。
 * 集中提供日期、置信度、枚举中文标签与标签类型映射，保证各页面文案一致。
 */
import dayjs from 'dayjs'

/** Element Plus 标签类型 */
export type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

/** 标签展示配置（文案 + 类型） */
export interface TagDisplay {
  /** 标签文案 */
  text: string
  /** 标签类型 */
  type: TagType
}

/**
 * 格式化日期时间为 YYYY-MM-DD HH:mm。
 * @param value 时间字符串
 * @returns 格式化结果；空值返回 '-'
 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  return dayjs(value).format('YYYY-MM-DD HH:mm')
}

/**
 * 格式化日期为 YYYY-MM-DD。
 * @param value 时间字符串
 * @returns 格式化结果；空值返回 '-'
 */
export function formatDate(value?: string | null): string {
  if (!value) return '-'
  return dayjs(value).format('YYYY-MM-DD')
}

/**
 * 格式化为中文月日（M月D日），用于采收禁令角标。
 * @param value 时间字符串
 * @returns 格式化结果；空值返回 '-'
 */
export function formatMonthDay(value?: string | null): string {
  if (!value) return '-'
  return dayjs(value).format('M月D日')
}

/**
 * 置信度格式化为百分比文本（保留一位小数）。
 * @param value 0-1 的置信度
 * @returns 如「92.5%」；空值返回 '-'
 */
export function formatConfidence(value?: number | null): string {
  if (value === null || value === undefined) return '-'
  return `${(value * 100).toFixed(1)}%`
}

/** 环境指标键名 → 中文标签映射 */
export const METRIC_LABELS: Record<string, string> = {
  temp: '温度',
  humidity: '湿度',
  light: '光照',
  soil_moisture: '土壤墒情',
}

/**
 * 指标键名转中文标签。
 * @param key 指标键名
 * @returns 中文标签；未知键名原样返回
 */
export function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key
}

/**
 * 地块类型转中文标签。
 * @param type greenhouse 大棚 / open_field 露天（后端字符串枚举）
 * @returns 中文标签
 */
export function plotTypeLabel(type?: string | null): string {
  if (type === 'greenhouse') return '大棚'
  if (type === 'open_field') return '露天'
  return type ?? '-'
}

/**
 * 诊断/案例来源转中文标签。
 * @param source device/manual
 * @returns 中文标签
 */
export function sourceLabel(source?: string | null): string {
  if (source === 'device') return '设备采集'
  if (source === 'manual') return '手动上传'
  return source ?? '-'
}

/**
 * 诊断任务/案例状态转标签配置。
 * 诊断任务状态机：pending → running → done/failed；案例状态：pending/confirmed/corrected。
 * @param status 状态字符串
 * @returns 标签文案与类型
 */
export function statusTag(status?: string | null): TagDisplay {
  switch (status) {
    case 'pending':
      return { text: '待确认', type: 'warning' }
    case 'running':
    case 'processing':
      return { text: '识别中', type: 'primary' }
    case 'done':
    case 'success':
    case 'completed':
      return { text: '已完成', type: 'success' }
    case 'failed':
    case 'error':
      return { text: '失败', type: 'danger' }
    case 'confirmed':
      return { text: '已确认', type: 'success' }
    case 'corrected':
      return { text: '已纠正', type: 'warning' }
    default:
      return { text: status ?? '-', type: 'info' }
  }
}

/**
 * 预警等级转标签配置。
 * 后端等级枚举：info/warning/critical（兼容旧 high/medium/low）。
 * @param level 等级字符串
 * @returns 标签文案与类型
 */
export function alertLevelTag(level?: string | null): TagDisplay {
  switch (level) {
    case 'critical':
    case 'high':
      return { text: '高', type: 'danger' }
    case 'warning':
    case 'medium':
      return { text: '中', type: 'warning' }
    case 'info':
    case 'low':
      return { text: '低', type: 'info' }
    default:
      return { text: level ?? '-', type: 'info' }
  }
}

/**
 * 设备状态转标签配置。
 * @param status online/offline
 * @returns 标签文案与类型
 */
export function deviceStatusTag(status?: string | null): TagDisplay {
  if (status === 'online') return { text: '在线', type: 'success' }
  if (status === 'offline') return { text: '离线', type: 'danger' }
  return { text: status ?? '未知', type: 'info' }
}

/**
 * 服务号绑定状态转标签配置。
 * 后端 wx_bind_status 为数字：1 已绑定 / 0 未绑定（兼容字符串 'bound'）。
 * @param status 绑定状态（数字或字符串）
 * @returns 标签文案与类型
 */
export function wxBindTag(status?: number | string | null): TagDisplay {
  if (status === 1 || status === 'bound' || status === '已绑定') return { text: '已绑定', type: 'success' }
  return { text: '未绑定', type: 'info' }
}
