<script setup lang="ts">
/**
 * 文件说明：诊断详情/防治方案卡页（07）。
 * 原图放大、结论卡、低置信度黄色横幅、防治方案卡（含禁用药拦截与免责声明）、
 * 采收禁令提示、确认/纠正操作（member 隐藏）、失败态原因 + 重试；识别中自动轮询。
 */
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getDiagnosisTask, retryDiagnosisTask } from '@/api/diagnosis'
import { confirmCase, correctCase } from '@/api/cases'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import { useAuthStore } from '@/stores/auth'
import { confirmAction } from '@/utils/confirm'
import { formatConfidence, formatDateTime, sourceLabel, statusTag } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/** 任务 ID（路由参数） */
const taskId = Number(route.params.id)

/** 任务详情异步状态（errorMessage 用于区分「记录不存在」与网络异常，缺陷 D-11） */
const { loading, failed, data: task, errorMessage: loadError, load } = useAsyncData(() => getDiagnosisTask(taskId))

/** 失败态展示文案：记录不存在时给出明确提示 */
const failedText = computed(() =>
  loadError.value.includes('不存在') ? '诊断记录不存在或已删除' : '',
)

/** 轮询定时器句柄 */
let pollTimer: number | undefined

/** 重试中 */
const retrying = ref(false)

/** 主识别结果（取第一个模型结果） */
const primaryResult = computed(() => task.value?.results?.[0])

/** 是否低置信度 */
const isLowConfidence = computed(() => task.value?.result_level === 'low')

/** scheme_json 键名 → 中文标签映射 */
const SCHEME_KEY_LABELS: Record<string, string> = {
  crop: '作物',
  stage: '生育期',
  summary: '防治总结',
  pesticides: '推荐药剂',
  precautions: '注意事项',
  disease_name: '病害名称',
  dosage: '用量',
  method: '施用方法',
  name: '药剂名',
}

/**
 * 将 scheme_json 值转为可读文本（数组对象逐条提取，避免整段 JSON 堆叠）。
 * @param value 任意 JSON 值
 * @returns 展示文本
 */
function schemeValueText(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (item && typeof item === 'object') {
          return Object.entries(item as Record<string, unknown>)
            .map(([k, v]) => `${SCHEME_KEY_LABELS[k] ?? k}：${String(v)}`)
            .join('；')
        }
        return String(item)
      })
      .join('\n')
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${SCHEME_KEY_LABELS[k] ?? k}：${Array.isArray(v) ? v.map(String).join('、') : String(v)}`)
      .join('；')
  }
  return String(value)
}

/** 方案 JSON 的键值对展示列表 */
const schemeEntries = computed<Array<{ key: string; value: string }>>(() => {
  const scheme = task.value?.plan?.scheme_json
  if (!scheme) return []
  return Object.entries(scheme)
    .filter(([key]) => key !== 'rag_references')
    .map(([key, value]) => ({
      key: SCHEME_KEY_LABELS[key] ?? key,
      value: schemeValueText(value),
    }))
})

/**
 * 合规校验结果转可读文本（后端为 {notes, banned, mentioned} 对象或字符串）。
 * @returns 展示文本；无内容返回空串
 */
const complianceText = computed<string>(() => {
  const result = task.value?.plan?.compliance_result
  if (!result) return ''
  if (typeof result === 'string') return result
  const parts: string[] = []
  if (result.notes) parts.push(result.notes)
  if (result.banned && result.banned.length > 0) parts.push(`命中禁限用药：${result.banned.map((b) => (typeof b === 'object' ? JSON.stringify(b) : String(b))).join('、')}`)
  return parts.join('；')
})

/** 是否可执行确认/纠正（owner + 存在待确认案例 ID） */
const canOperate = computed(
  () => auth.isOwner && !!task.value?.case?.id && task.value?.case?.status === 'pending',
)

/** 纠正弹窗 */
const correctDialog = reactive({ visible: false, name: '', note: '' })
/** 纠正提交中 */
const correcting = ref(false)

/**
 * 启动轮询（识别中每 5 秒刷新任务详情）。
 */
function startPolling(): void {
  stopPolling()
  pollTimer = window.setInterval(() => {
    void load()
  }, 5000)
}

/**
 * 停止轮询。
 */
function stopPolling(): void {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

// 任务状态变化控制轮询启停（后端状态机 pending → running → done/failed）
watch(
  () => task.value?.status,
  (status) => {
    if (status === 'pending' || status === 'running' || status === 'processing') {
      if (pollTimer === undefined) startPolling()
    } else {
      stopPolling()
    }
  },
  { immediate: true },
)

/**
 * 重试失败任务。
 */
async function handleRetry(): Promise<void> {
  retrying.value = true
  try {
    await retryDiagnosisTask(taskId)
    ElMessage.success('已重新发起诊断')
    await load()
  } finally {
    retrying.value = false
  }
}

/**
 * 确认诊断正确（回流案例库）。
 */
async function handleConfirm(): Promise<void> {
  const caseId = task.value?.case?.id
  if (!caseId) return
  const ok = await confirmAction('确认本次诊断结果正确？确认后回流案例库。')
  if (!ok) return
  await confirmCase(caseId)
  ElMessage.success('已确认')
  await load()
}

/**
 * 打开纠正弹窗。
 */
function openCorrect(): void {
  correctDialog.name = ''
  correctDialog.note = ''
  correctDialog.visible = true
}

/**
 * 提交纠正（输入正确病名）。
 * @throws 病名为空或后端报错时提示
 */
async function submitCorrect(): Promise<void> {
  const caseId = task.value?.case?.id
  if (!caseId) return
  if (correctDialog.name.trim() === '') {
    ElMessage.warning('请输入正确病名')
    return
  }
  correcting.value = true
  try {
    await correctCase(caseId, { final_disease_name: correctDialog.name.trim(), note: correctDialog.note })
    ElMessage.success('已纠正')
    correctDialog.visible = false
    await load()
  } finally {
    correcting.value = false
  }
}

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="page">
    <StateWrap :loading="loading" :failed="failed" :failed-text="failedText" :rows="8" @retry="load()">
      <template v-if="task">
        <!-- 识别中提示 -->
        <div v-if="task.status === 'pending' || task.status === 'running' || task.status === 'processing'" class="page-card recognizing">
          <el-icon class="spin" :size="24" color="#409eff"><Loading /></el-icon>
          <span>AI 正在识别，约需 1–3 分钟…</span>
        </div>

        <!-- 失败态：原因 + 重试 -->
        <div v-else-if="task.status === 'failed' || task.status === 'error'" class="page-card">
          <h3 class="page-card-title">诊断失败</h3>
          <div class="state-failed">
            <el-alert :title="task.failure_reason ?? '诊断失败（模型超时降级）'" type="error" show-icon :closable="false" />
            <span class="text-muted">可稍后在诊断记录中查看，或立即重试</span>
            <el-button type="primary" :loading="retrying" @click="handleRetry">重试诊断</el-button>
          </div>
        </div>

        <template v-else>
          <!-- 原始图像 + 结论卡 -->
          <div class="detail-row">
            <div class="page-card">
              <h3 class="page-card-title">原始图像</h3>
              <div class="img-grid">
                <el-image
                  v-for="img in task.images"
                  :key="img.id"
                  :src="img.url"
                  fit="cover"
                  class="detail-img"
                  :preview-src-list="task.images.map((i) => i.url)"
                  preview-teleported
                />
              </div>
            </div>

            <div class="page-card">
              <h3 class="page-card-title">诊断结论</h3>
              <div class="conclusion">
                <div class="conclusion-name">{{ primaryResult?.disease_name ?? task.results[0]?.disease_name ?? '未知' }}</div>
                <div class="conclusion-meta">
                  <span>置信度：<b>{{ formatConfidence(task.fused_confidence) }}</b></span>
                  <span>时间：{{ formatDateTime(task.finished_at ?? task.created_at) }}</span>
                  <el-tag size="small" :type="task.source === 'device' ? 'primary' : 'success'">
                    {{ sourceLabel(task.source) }}
                  </el-tag>
                  <el-tag size="small" :type="statusTag(task.status).type">{{ statusTag(task.status).text }}</el-tag>
                </div>
                <div v-if="task.results.length > 1" class="sub-results">
                  <div v-for="(r, idx) in task.results" :key="idx" class="sub-result">
                    <span>{{ r.disease_name }}</span>
                    <span class="text-muted">{{ r.model_path }} · {{ formatConfidence(r.confidence) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 低置信度黄色横幅 -->
          <el-alert
            v-if="isLowConfidence"
            title="置信度不足，建议咨询农技专家"
            type="warning"
            show-icon
            :closable="false"
            class="low-banner"
          />

          <!-- 防治方案卡 -->
          <div v-if="task.plan" class="page-card">
            <h3 class="page-card-title">防治方案</h3>
            <!-- 禁用药拦截红色展示 -->
            <el-alert
              v-if="task.plan.is_forbidden_blocked === 1"
              title="方案中的禁限用药物已被系统拦截，请勿自行购买使用"
              type="error"
              show-icon
              :closable="false"
              class="forbidden-banner"
            />
            <div v-if="schemeEntries.length > 0" class="scheme-list">
              <div v-for="entry in schemeEntries" :key="entry.key" class="scheme-item">
                <span class="scheme-key">{{ entry.key }}</span>
                <span class="scheme-value">{{ entry.value }}</span>
              </div>
            </div>
            <div v-if="complianceText" class="compliance">
              <el-tag size="small" type="success">合规校验</el-tag>
              <span>{{ complianceText }}</span>
            </div>
            <p class="text-muted disclaimer">{{ task.plan.disclaimer ?? '本方案由 AI 生成，仅供参考，请结合实际情况谨慎用药。' }}</p>
            <el-alert
              title="用药后请遵守安全间隔期，采收禁令以地块角标为准"
              type="info"
              show-icon
              :closable="false"
              class="harvest-tip"
            />
          </div>

          <!-- 确认/纠正操作区（member 隐藏） -->
          <div v-if="canOperate" class="page-card action-card">
            <el-button type="success" @click="handleConfirm">确认正确</el-button>
            <el-button type="warning" plain @click="openCorrect">纠正为…</el-button>
          </div>
          <div v-else-if="task.case" class="page-card action-card">
            <el-tag :type="statusTag(task.case.status).type">{{ statusTag(task.case.status).text }}</el-tag>
            <span class="text-muted" style="margin-left: 8px">本诊断已进入案例库（{{ statusTag(task.case.status).text }}）</span>
          </div>
        </template>
      </template>
    </StateWrap>

    <!-- 纠正弹窗 -->
    <el-dialog v-model="correctDialog.visible" title="纠正诊断结果" width="420px">
      <el-form label-width="90px">
        <el-form-item label="正确病名" required>
          <el-input v-model="correctDialog.name" placeholder="请输入正确病名" maxlength="30" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="correctDialog.note" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="correctDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="correcting" @click="submitCorrect">提交纠正</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.detail-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.img-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
}

.detail-img {
  width: 100%;
  height: 140px;
  border-radius: 8px;
  display: block;
  cursor: pointer;
}

.conclusion-name {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  margin-bottom: 10px;
}

.conclusion-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
  color: #606266;
}

.sub-results {
  margin-top: 12px;
  border-top: 1px dashed #ebeef5;
  padding-top: 8px;
}

.sub-result {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 4px 0;
  color: #606266;
}

.low-banner {
  margin-bottom: 16px;
}

.forbidden-banner {
  margin-bottom: 12px;
}

.scheme-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.scheme-item {
  display: flex;
  gap: 10px;
  font-size: 13px;
  padding: 8px 10px;
  background: #f5f7fa;
  border-radius: 6px;
}

.scheme-key {
  color: #909399;
  flex-shrink: 0;
  min-width: 90px;
}

.compliance {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 13px;
}

.disclaimer {
  margin-top: 10px;
}

.harvest-tip {
  margin-top: 8px;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 10px;
}

.recognizing {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #409eff;
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

@media (max-width: 767px) {
  .detail-row {
    grid-template-columns: 1fr;
  }
}
</style>
