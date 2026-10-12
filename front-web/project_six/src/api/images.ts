/**
 * 文件说明：图像上传模块 API 封装。
 * 手动通道与设备通道共用统一上传接口（multipart/form-data）。
 */
import { post } from './request'
import type { ImageUploadResult } from '@/types/farm'

/**
 * 上传图像（1–4 张，multipart/form-data）。
 * @param files 原始图片文件数组
 * @param plotId 地块 ID
 * @param source 来源标记，默认 manual（手动上传）
 * @returns 上传结果列表（含重复标记）
 * @throws 数量超限或上传失败时抛出异常
 */
export function uploadImages(files: File[], plotId: number, source = 'manual'): Promise<ImageUploadResult[]> {
  const formData = new FormData()
  files.forEach((file) => {
    formData.append('files', file)
  })
  formData.append('plot_id', String(plotId))
  formData.append('source', source)
  return post<ImageUploadResult[]>('/images', formData)
}
