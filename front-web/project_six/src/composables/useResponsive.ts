/**
 * 文件说明：响应式断点组合式函数。
 * 以 992px 为界区分桌面端（左侧导航）与移动端（底部 Tab）布局形态。
 */
import { onUnmounted, ref } from 'vue'

/** 桌面/移动端断点（像素） */
const BREAKPOINT = 992

/**
 * 创建响应式断点状态（窗口宽度 < 992 视为移动端）。
 * @returns isMobile 响应式标记
 */
export function useResponsive() {
  /** 是否移动端布局 */
  const isMobile = ref(window.innerWidth < BREAKPOINT)

  /**
   * 窗口尺寸变化回调：更新断点标记。
   */
  function onResize(): void {
    isMobile.value = window.innerWidth < BREAKPOINT
  }

  window.addEventListener('resize', onResize)
  onUnmounted(() => {
    window.removeEventListener('resize', onResize)
  })

  return { isMobile }
}
