/**
 * 文件说明：认证模块 API 封装。
 * 包含：账号密码登录（兼容）、手机号+密码登录、手机号+验证码登录、
 * 发送短信验证码、手机号是否已注册、注册、获取当前用户、修改密码。
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

/** 发送验证码响应 */
export interface SendCodeResult {
  /** 是否已发送 */
  sent: boolean
  /** dev_mode 下后端直接返回的验证码（便于联调） */
  dev_code?: string | null
}

/**
 * 账号密码登录（保留兼容，前端主入口已切到手机号登录）。
 * @param username 用户名
 * @param password 密码
 */
export function login(username: string, password: string): Promise<LoginResult> {
  return post<LoginResult>('/auth/login', { username, password }, { skipErrorMessage: true })
}

/**
 * 手机号+密码登录。
 * @param phone 11 位手机号
 * @param password 密码
 */
export function loginByPhone(phone: string, password: string): Promise<LoginResult> {
  return post<LoginResult>(
    '/auth/login/phone',
    { phone, password },
    { skipErrorMessage: true },
  )
}

/**
 * 手机号+短信验证码登录。
 * @param phone 11 位手机号
 * @param code 6 位验证码
 */
export function loginByCode(phone: string, code: string): Promise<LoginResult> {
  return post<LoginResult>(
    '/auth/login/code',
    { phone, code },
    { skipErrorMessage: true },
  )
}

/**
 * 发送短信验证码。
 * @param phone 11 位手机号
 * @param scene 场景：login 登录 / register 注册
 */
export function sendSmsCode(phone: string, scene: 'login' | 'register'): Promise<SendCodeResult> {
  return post<SendCodeResult>('/auth/send-code', { phone, scene }, { skipErrorMessage: true })
}

/**
 * 查询手机号是否已注册。
 * @param phone 11 位手机号
 */
export function checkPhoneExists(phone: string): Promise<{ exists: boolean }> {
  return get<{ exists: boolean }>('/auth/check-phone', { phone }, { skipErrorMessage: true })
}

/**
 * 手机号注册。
 * @param phone 11 位手机号
 * @param password 密码（至少 6 位）
 * @param code 短信验证码
 * @param nickname 可选昵称
 */
export function register(
  phone: string,
  password: string,
  code: string,
  nickname?: string,
): Promise<LoginResult> {
  return post<LoginResult>(
    '/auth/register',
    { phone, password, code, nickname: nickname || null },
    { skipErrorMessage: true },
  )
}

/**
 * 获取当前登录用户信息。
 */
export function fetchMe(): Promise<User> {
  return get<User>('/auth/me')
}

/**
 * 修改当前账号密码。
 * @param oldPassword 旧密码
 * @param newPassword 新密码
 */
export function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  return put<void>('/auth/password', { old_password: oldPassword, new_password: newPassword })
}
