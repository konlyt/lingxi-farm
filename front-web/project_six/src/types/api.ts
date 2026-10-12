/**
 * 文件说明：通用 API 类型定义。
 * 声明后端统一响应包装结构与分页数据结构，供各 API 模块与页面共用。
 */

/** 后端统一响应包装结构 */
export interface ApiResponse<T = unknown> {
  /** 业务状态码，0 表示成功 */
  code: number
  /** 提示消息 */
  message: string
  /** 业务数据（拦截器只回传该字段） */
  data: T
}

/** 通用分页数据结构 */
export interface Paged<T> {
  /** 当前页数据列表 */
  items: T[]
  /** 数据总条数 */
  total: number
  /** 当前页码（可选） */
  page?: number
  /** 每页条数（可选） */
  page_size?: number
}
