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

  /**
   * 执行数据加载（可作重试入口）。
   * 失败时不弹出全局提示（拦截器已处理），仅标记 failed。
   */
  async function load(): Promise<void> {
    loading.value = true
    failed.value = false
    try {
      data.value = await loader()
    } catch {
      failed.value = true
    } finally {
      loading.value = false
    }
  }

  if (immediate) {
    void load()
  }

  return { loading, failed, data, load }
}
