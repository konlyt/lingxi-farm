/**
 * 文件说明：交互确认工具。
 * 封装 ElMessageBox 确认框，取消时返回 false 而不抛出未处理异常。
 */
import { ElMessageBox } from 'element-plus'

/**
 * 弹出确认对话框。
 * @param message 确认内容
 * @param title 对话框标题，默认「提示」
 * @returns 用户点击确定返回 true；取消或关闭返回 false
 */
export async function confirmAction(message: string, title = '提示'): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
}
