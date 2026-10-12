/**
 * 文件说明：认证模块 API 封装。
 * 包含登录、获取当前用户、修改密码接口。
 */
import { get, post, put } from './request'
import type { User } from '@/types/farm'

/** 登录响应结构 */
export interface LoginResult {
  /** 访问令牌 */
  token: string
  /** 用户信息 */
  user: User
}

/**
 * 账号密码登录。
 * @param username 用户名
 * @param password 密码
 * @returns 登录结果（token 与用户信息）
 * @throws 凭证错误或服务不可用时抛出异常
 */
export function login(username: string, password: string): Promise<LoginResult> {
  return post<LoginResult>('/auth/login', { username, password }, { skipErrorMessage: true })
}

/**
 * 获取当前登录用户信息。
 * @returns 用户信息
 * @throws 未登录或 token 失效时抛出异常
 */
export function fetchMe(): Promise<User> {
  return get<User>('/auth/me')
}

/**
 * 修改当前账号密码。
 * @param oldPassword 旧密码
 * @param newPassword 新密码
 * @returns 空数据
 * @throws 旧密码错误时抛出异常
 */
export function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  return put<void>('/auth/password', { old_password: oldPassword, new_password: newPassword })
}
