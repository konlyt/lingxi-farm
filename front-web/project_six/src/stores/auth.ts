/**
 * 文件说明：认证状态 store。
 * 管理 token 与当前用户信息，并持久化到 localStorage；供路由守卫与页面权限判断使用。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchMe, login as loginApi } from '@/api/auth'
import { TOKEN_KEY } from '@/api/request'
import type { User } from '@/types/farm'

/** 用户信息本地存储键名 */
const USER_KEY = 'farm_user'

/**
 * 读取本地缓存的用户信息。
 * @returns 用户对象；解析失败返回 null
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
   * 账号密码登录。
   * @param username 用户名
   * @param password 密码
   * @throws 凭证错误或服务不可用时抛出异常（调用方展示行内错误）
   */
  async function login(username: string, password: string): Promise<void> {
    const result = await loginApi(username, password)
    token.value = result.token
    user.value = result.user
    localStorage.setItem(TOKEN_KEY, result.token)
    localStorage.setItem(USER_KEY, JSON.stringify(result.user))
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

  return { token, user, isOwner, isLoggedIn, login, refreshUser, logout }
})
