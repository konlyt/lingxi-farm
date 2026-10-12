<script setup lang="ts">
/**
 * 文件说明：智能诊断·手动上传页（05）。
 * 拍照引导（示例图 + 三要点）、1–4 张上传（本地 canvas 亮度/清晰度预检并标红）、
 * 地块选择联动生育期、提交后显示识别动画并每 5 秒轮询任务状态，成功跳详情。
 */
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Camera, Plus } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'
import { getPlots } from '@/api/plots'
import { uploadImages } from '@/api/images'
import { createDiagnosisTask, getDiagnosisTask } from '@/api/diagnosis'
import { useAsyncData } from '@/composables/useAsyncData'

const router = useRouter()

/** 已选图片项（自管理列表，规避 el-upload 文件类型约束） */
interface PickedImage {
  /** 自增标识 */
  id: number
  /** 本地预览地址 */
  url: string
  /** 原始文件 */
  raw: File
  /** 质量预检提示（空串表示合格） */
  tip: string
}

/** 拍照要点提示 */
const tips = ['对准病斑拍摄，突出受害部位', '使用自然光，避免逆光与阴影', '距离约 15cm，保持手机稳定']

/** 地块列表异步状态 */
const { data: plots, load: loadPlots } = useAsyncData(() => getPlots())

/** 表单数据 */
const form = reactive({ plot_id: undefined as number | undefined, growth_stage: '' })

/** 已选图片列表 */
const pickedImages = ref<PickedImage[]>([])
/** 图片自增 ID */
let nextImageId = 1

/** 提交中 */
const submitting = ref(false)
/** 轮询中的任务 ID */
const pollingTaskId = ref<number | null>(null)
/** 任务失败/超时提示 */
const taskError = ref('')
/** 轮询次数（用于超时判断） */
let pollCount = 0
/** 轮询定时器句柄 */
let pollTimer: number | undefined

/** 提交按钮禁用：未选图、未选地块或提交中 */
const submitDisabled = computed(() => pickedImages.value.length === 0 || !form.plot_id || submitting.value)

/** 是否存在不合格图片 */
const hasBadImage = computed(() => pickedImages.value.some((item) => item.tip !== ''))

/**
 * 监听地块选择变化，自动带出当前生育期（可手动修改）。
 */
watch(
  () => form.plot_id,
  (id) => {
    const plot = plots.value?.find((p) => p.id === id)
    if (plot) form.growth_stage = plot.growth_stage ?? ''
  },
)

/**
 * 对单张图片做本地亮度/清晰度简易预检（canvas 采样灰度均值与方差）。
 * @param file 原始图片文件
 * @returns 质量提示文本；空串表示合格
 */
function analyzeImage(file: File): Promise<string> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        const w = Math.min(img.width, 200)
        canvas.width = w
        canvas.height = Math.max(1, Math.round((img.height / img.width) * w))
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          resolve('')
          return
        }
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
        const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height)
        let sum = 0
        let sumSq = 0
        const count = data.length / 4
        for (let i = 0; i < data.length; i += 4) {
          const r = data[i] ?? 0
          const g = data[i + 1] ?? 0
          const b = data[i + 2] ?? 0
          const gray = 0.299 * r + 0.587 * g + 0.114 * b
          sum += gray
          sumSq += gray * gray
        }
        const mean = sum / count
        const variance = sumSq / count - mean * mean
        let tip = ''
        if (mean < 45) tip = '画面过暗，建议重拍'
        else if (mean > 215) tip = '画面过曝，建议重拍'
        else if (variance < 100) tip = '画面可能模糊，建议重拍'
        resolve(tip)
      } finally {
        URL.revokeObjectURL(url)
      }
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      resolve('图片读取失败，建议重拍')
    }
    img.src = url
  })
}

/**
 * el-upload 文件选择回调：限制数量、加入自管理列表并执行本地预检。
 * @param file 变化的文件对象
 */
async function onFileChange(file: UploadFile): Promise<void> {
  if (pickedImages.value.length >= 4) {
    ElMessage.warning('最多上传 4 张图片')
    return
  }
  const raw = file.raw
  if (!raw) return
  const item: PickedImage = { id: nextImageId++, url: URL.createObjectURL(raw), raw, tip: '' }
  pickedImages.value.push(item)
  item.tip = await analyzeImage(raw)
}

/**
 * 移除指定图片并释放预览地址。
 * @param id 图片标识
 */
function removeImage(id: number): void {
  const item = pickedImages.value.find((i) => i.id === id)
  if (item) URL.revokeObjectURL(item.url)
  pickedImages.value = pickedImages.value.filter((i) => i.id !== id)
}

/**
 * 停止任务状态轮询。
 */
function stopPolling(): void {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

/**
 * 启动任务状态轮询（每 5 秒一次；后端状态机 pending→running→done/failed，
 * done 跳详情，失败展示原因，5 分钟超时提示）。
 * @param taskId 诊断任务 ID
 */
function startPolling(taskId: number): void {
  stopPolling()
  pollCount = 0
  pollingTaskId.value = taskId
  pollTimer = window.setInterval(async () => {
    pollCount += 1
    if (pollCount > 60) {
      stopPolling()
      taskError.value = '诊断耗时较长，请稍后在诊断记录中查看结果'
      return
    }
    try {
      const task = await getDiagnosisTask(taskId)
      if (task.status === 'done' || task.status === 'success' || task.status === 'completed') {
        stopPolling()
        ElMessage.success('诊断完成')
        await router.push(`/diagnosis/${taskId}`)
      } else if (task.status === 'failed' || task.status === 'error') {
        stopPolling()
        taskError.value = task.failure_reason ?? '诊断失败'
      }
    } catch {
      /* 轮询失败忽略，等待下一次 */
    }
  }, 5000)
}

/**
 * 提交诊断：上传图片（去重提示）→ 创建任务 → 启动轮询。
 * @throws 上传或任务创建失败时展示错误提示
 */
async function handleSubmit(): Promise<void> {
  if (!form.plot_id) return
  submitting.value = true
  taskError.value = ''
  try {
    const files = pickedImages.value.map((item) => item.raw)
    if (files.length === 0) {
      ElMessage.warning('请先选择图片')
      return
    }
    const uploaded = await uploadImages(files, form.plot_id)
    const dupCount = uploaded.filter((u) => u.duplicate).length
    if (dupCount > 0) {
      ElMessage.warning(`其中 ${dupCount} 张与已有图像重复，已去重处理`)
    }
    const fresh = uploaded.filter((u) => !u.duplicate)
    const imageIds = (fresh.length > 0 ? fresh : uploaded).map((u) => u.id)
    const task = await createDiagnosisTask({
      plot_id: form.plot_id,
      growth_stage: form.growth_stage,
      image_ids: imageIds,
    })
    startPolling(task.task_id)
  } catch (err) {
    taskError.value = err instanceof Error && err.message ? err.message : '提交失败，请稍后再试'
  } finally {
    submitting.value = false
  }
}

onUnmounted(() => {
  stopPolling()
  for (const item of pickedImages.value) {
    URL.revokeObjectURL(item.url)
  }
})

// 进入页面加载地块选项
void loadPlots()
</script>

<template>
  <div class="page">
    <!-- 拍照引导区 -->
    <div class="page-card guide-card">
      <div class="guide-example">
        <div class="example-box">
          <el-icon :size="34" color="#c0c4cc"><Camera /></el-icon>
          <span>示例图占位</span>
        </div>
      </div>
      <div class="guide-tips">
        <h3 class="page-card-title">拍照引导</h3>
        <ul class="tip-list">
          <li v-for="(tip, idx) in tips" :key="idx" class="tip-item">{{ tip }}</li>
        </ul>
      </div>
    </div>

    <!-- 上传与表单区 -->
    <div class="page-card">
      <h3 class="page-card-title">上传照片（1–4 张）</h3>

      <!-- 地块与生育期 -->
      <el-form label-width="90px" class="upload-form">
        <el-form-item label="地块" required>
          <el-select v-model="form.plot_id" placeholder="请选择地块/棚室" style="width: 280px">
            <el-option
              v-for="p in plots ?? []"
              :key="p.id"
              :label="p.name"
              :value="p.id"
              :disabled="p.status === 0"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="生育期">
          <el-input v-model="form.growth_stage" placeholder="选择地块后自动带出，可修改" style="width: 280px" />
        </el-form-item>
      </el-form>

      <!-- 自定义缩略图网格 -->
      <div class="thumb-grid">
        <div v-for="item in pickedImages" :key="item.id" class="thumb" :class="{ bad: item.tip !== '' }">
          <el-image :src="item.url" fit="cover" class="thumb-img" />
          <el-button class="thumb-del" type="danger" circle size="small" @click="removeImage(item.id)">
            <el-icon><Close /></el-icon>
          </el-button>
          <div v-if="item.tip !== ''" class="thumb-tip">{{ item.tip }}</div>
        </div>
        <el-upload
          v-if="pickedImages.length < 4"
          accept="image/*"
          multiple
          :auto-upload="false"
          :show-file-list="false"
          :on-change="onFileChange"
        >
          <div class="thumb add-box">
            <el-icon :size="24"><Plus /></el-icon>
            <span>添加图片</span>
          </div>
        </el-upload>
      </div>

      <!-- 预检提示 -->
      <el-alert
        v-if="hasBadImage"
        title="存在不合格图片（已标红），建议删除后重拍，以免影响识别准确率"
        type="warning"
        show-icon
        :closable="false"
        class="precheck-tip"
      />

      <!-- 提交区 -->
      <div class="submit-zone">
        <el-button type="primary" size="large" :disabled="submitDisabled" @click="handleSubmit">
          提交诊断
        </el-button>
        <span class="text-muted">提交后 AI 正在识别，约需 1–3 分钟</span>
      </div>

      <!-- 诊断中动画 -->
      <div v-if="pollingTaskId" class="recognizing">
        <el-icon class="spin" :size="28" color="#409eff"><Loading /></el-icon>
        <span>AI 正在识别，约需 1–3 分钟，请勿关闭页面…</span>
      </div>

      <!-- 失败提示 + 重试 -->
      <div v-if="taskError" class="state-failed" style="margin-top: 12px">
        <el-alert :title="taskError" type="error" show-icon :closable="false" />
        <el-button type="primary" plain size="small" @click="handleSubmit">重试</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.guide-card {
  display: flex;
  gap: 20px;
  align-items: center;
}

.example-box {
  width: 200px;
  height: 140px;
  border: 1px dashed #dcdfe6;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #c0c4cc;
  font-size: 12px;
  background: #fafafa;
}

.tip-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.tip-item {
  font-size: 13px;
  color: #606266;
  padding: 4px 0;
}

.tip-item::before {
  content: '✓';
  color: #67c23a;
  margin-right: 8px;
}

.upload-form {
  max-width: 400px;
}

.thumb-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.thumb {
  position: relative;
  width: 120px;
  height: 120px;
  border-radius: 8px;
  overflow: hidden;
}

.thumb.bad {
  outline: 2px solid #f56c6c;
}

.thumb-img {
  width: 100%;
  height: 100%;
  display: block;
}

.thumb-del {
  position: absolute;
  top: 4px;
  right: 4px;
}

.thumb-tip {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(245, 108, 108, 0.9);
  color: #fff;
  font-size: 11px;
  padding: 3px 6px;
}

.add-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px dashed #dcdfe6;
  color: #909399;
  font-size: 12px;
  background: #fafafa;
  cursor: pointer;
}

.precheck-tip {
  margin-top: 12px;
}

.submit-zone {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.recognizing {
  margin-top: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: #409eff;
  font-size: 14px;
  padding: 14px;
  background: #ecf5ff;
  border-radius: 8px;
}

.spin {
  animation: rotate 1.2s linear infinite;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
