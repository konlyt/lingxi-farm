/**
 * 文件说明：通用异步数据加载组合式函数。
 * 封装「加载中 / 失败 / 成功」三态与手动重试，配合 StateWrap 组件实现全局状态规范。
 */
import { ref } from 'vue'
import type { Ref } from 'vue'

/**
 * 创建异步数据加载状态。
 * @param loader 数据加载函数（返回业务数据）
 * @param immediate 是否在创建时立即加载，默认 true
 * @returns loading 失败标记、数据与手动加载方法
 */
export function useAsyncData<T>(loader: () => Promise<T>, immediate = true) {
  /** 是否加载中 */
  const loading = ref(false)
  /** 是否加载失败 */
  const failed = ref(false)
  /** 业务数据（未加载/失败时为 null） */
  const data: Ref<T | null> = ref(null)
  /** 最近一次失败的信息（拦截器 reject 的 Error.message，供页面区分错误类型） */
  const errorMessage = ref('')

  /**
   * 执行数据加载（可作重试入口）。
   * 失败时不弹出全局提示（拦截器已处理），仅标记 failed 并记录 errorMessage。
   */
  async function load(): Promise<void> {
    loading.value = true
    failed.value = false
    errorMessage.value = ''
    try {
      data.value = await loader()
    } catch (error) {
      failed.value = true
      errorMessage.value = error instanceof Error ? error.message : String(error)
    } finally {
      loading.value = false
    }
  }

  if (immediate) {
    void load()
  }

  return { loading, failed, data, errorMessage, load }
}
