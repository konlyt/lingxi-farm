/**
 * 文件说明：axios 实例与拦截器封装。
 * 统一注入 Bearer token、剥离统一响应包装（只回传 data）、处理 401 跳登录与统一错误提示。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import type { AxiosRequestConfig } from 'axios'
import router from '@/router'

/** axios 模块扩充：允许调用方跳过统一错误提示（如登录页需要行内红字） */
declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 为 true 时拦截器不弹出 ElMessage 错误提示，由调用方自行处理 */
    skipErrorMessage?: boolean
  }
}

/** token 本地存储键名 */
export const TOKEN_KEY = 'farm_token'

/** 全局 axios 实例（经 Vite 代理转发 /api 前缀） */
const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：注入 Authorization 头
http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一业务码处理，成功时只回传 data
http.interceptors.response.use(
  (response) => {
    const body = response.data as { code?: number; message?: string; data?: unknown }
    // 非标准包装结构（如文件流）直接放行
    if (!body || typeof body.code !== 'number') {
      return response.data
    }
    if (body.code !== 0) {
      if (!response.config.skipErrorMessage) {
        ElMessage.error(body.message || '请求失败')
      }
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return body.data
  },
  (error) => {
    const status: number | undefined = error.response?.status
    const config = error.config as AxiosRequestConfig | undefined
    // 优先使用后端统一响应体中的中文错误信息（如「用户名或密码错误」）
    const serverMsg: string | undefined = error.response?.data?.message
    const fallbackMsg = status ? `请求失败（${status}）` : '网络异常，请稍后再试'
    const errMsg = serverMsg || fallbackMsg
    if (status === 401) {
      // 登录页自身的 401 属于账号或密码错误，行内提示即可，不做登出跳转
      if (router.currentRoute.value.path === '/login') {
        return Promise.reject(new Error(serverMsg || '账号或密码错误'))
      }
      localStorage.removeItem(TOKEN_KEY)
      ElMessage.error('登录已过期，请重新登录')
      const current = router.currentRoute.value.fullPath
      const redirect = current.startsWith('/login') ? {} : { redirect: current }
      void router.push({ path: '/login', query: redirect })
    } else if (!config?.skipErrorMessage) {
      ElMessage.error(errMsg)
    }
    return Promise.reject(new Error(errMsg))
  },
)

/**
 * 发起 GET 请求并返回业务数据。
 * 说明：响应拦截器已剥离统一包装并只回传 data，故此处以受控类型断言返回业务数据。
 * @param url 请求路径（不含 /api 前缀）
 * @param params 查询参数（undefined 值会被 axios 忽略）
 * @param config 额外 axios 配置
 * @returns 业务数据
 */
export function get<T>(url: string, params?: object, config?: AxiosRequestConfig): Promise<T> {
  return http.get(url, { params, ...config }) as unknown as Promise<T>
}

/**
 * 发起 POST 请求并返回业务数据。
 * @param url 请求路径
 * @param data 请求体
 * @param config 额外 axios 配置
 * @returns 业务数据
 */
export function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return http.post(url, data, config) as unknown as Promise<T>
}

/**
 * 发起 PUT 请求并返回业务数据。
 * @param url 请求路径
 * @param data 请求体
 * @param config 额外 axios 配置
 * @returns 业务数据
 */
export function put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return http.put(url, data, config) as unknown as Promise<T>
}

/**
 * 发起 PATCH 请求并返回业务数据。
 * @param url 请求路径
 * @param data 请求体
 * @param config 额外 axios 配置
 * @returns 业务数据
 */
export function patch<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return http.patch(url, data, config) as unknown as Promise<T>
}

/**
 * 发起 DELETE 请求并返回业务数据。
 * @param url 请求路径
 * @param config 额外 axios 配置
 * @returns 业务数据
 */
export function del<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return http.delete(url, config) as unknown as Promise<T>
}

export default http
