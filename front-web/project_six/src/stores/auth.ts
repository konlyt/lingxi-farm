/**
 * 文件说明：认证状态 store。
 * 管理 token 与当前用户信息，并持久化到 localStorage；供路由守卫与页面权限判断使用。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  fetchMe,
  loginByCode,
  loginByPhone,
  register as registerApi,
} from '@/api/auth'
import { TOKEN_KEY } from '@/api/request'
import type { User } from '@/types/farm'

/** 用户信息本地存储键名 */
const USER_KEY = 'farm_user'

/**
 * 读取本地缓存的用户信息。
 */
function readLocalUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

/** 认证 store：token、用户、角色判断与登录/登出动作 */
export const useAuthStore = defineStore('auth', () => {
  /** 访问令牌 */
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) ?? '')
  /** 当前登录用户 */
  const user = ref<User | null>(readLocalUser())
  /** 是否农场主（拥有全部写操作权限） */
  const isOwner = computed(() => user.value?.role === 'owner')
  /** 是否已登录 */
  const isLoggedIn = computed(() => token.value !== '')

  /**
   * 用登录响应结果填充 store 与本地缓存。
   */
  function applyLoginResult(result: { token: string; user: User }): void {
    token.value = result.token
    user.value = result.user
    localStorage.setItem(TOKEN_KEY, result.token)
    localStorage.setItem(USER_KEY, JSON.stringify(result.user))
  }

  /**
   * 手机号+密码登录。
   * @param phone 手机号
   * @param password 密码
   */
  async function loginWithPhone(phone: string, password: string): Promise<void> {
    applyLoginResult(await loginByPhone(phone, password))
  }

  /**
   * 手机号+验证码登录。
   * @param phone 手机号
   * @param code 短信验证码
   */
  async function loginWithCode(phone: string, code: string): Promise<void> {
    applyLoginResult(await loginByCode(phone, code))
  }

  /**
   * 手机号注册（成功后自动登录）。
   */
  async function register(phone: string, password: string, code: string, nickname?: string): Promise<void> {
    applyLoginResult(await registerApi(phone, password, code, nickname))
  }

  /**
   * 拉取并刷新当前用户信息（静默失败，保留本地缓存）。
   */
  async function refreshUser(): Promise<void> {
    if (!token.value) return
    try {
      const me = await fetchMe()
      user.value = me
      localStorage.setItem(USER_KEY, JSON.stringify(me))
    } catch {
      /* 静默失败 */
    }
  }

  /**
   * 退出登录并清理本地状态。
   */
  function logout(): void {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return {
    token,
    user,
    isOwner,
    isLoggedIn,
    loginWithPhone,
    loginWithCode,
    register,
    refreshUser,
    logout,
  }
})
