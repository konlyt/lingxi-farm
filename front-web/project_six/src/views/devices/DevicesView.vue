<script setup lang="ts">
/**
 * 文件说明：设备管理页（14）。
 * 统计头（总/在线/离线）、设备表格（离线>24h 红色标识）、详情抽屉（心跳历史/采集计划/远程配置）、
 * 新增设备四步向导（类型→接入方式→参数→连接测试模拟 2 秒成功）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createDevice, getDeviceDetail, getDeviceStats, getDevices, sendDeviceConfig } from '@/api/devices'
import { getPlots } from '@/api/plots'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import { useAuthStore } from '@/stores/auth'
import dayjs from 'dayjs'
import { deviceStatusTag, formatDateTime, plotTypeLabel } from '@/utils/format'
import type { Device, DeviceDetail } from '@/types/farm'

const router = useRouter()
const auth = useAuthStore()

/** 设备统计异步状态 */
const { data: stats, load: loadStats } = useAsyncData(getDeviceStats)
/** 设备列表异步状态 */
const { loading, failed, data: devices, load } = useAsyncData(() => getDevices())
/** 地块列表（用于名称映射与向导选择） */
const { data: plots, load: loadPlots } = useAsyncData(() => getPlots())

/** 详情抽屉可见性 */
const drawerVisible = ref(false)
/** 抽屉加载中 */
const drawerLoading = ref(false)
/** 抽屉设备详情（含心跳历史） */
const drawerDevice = ref<DeviceDetail | null>(null)
/** 远程配置 JSON 文本 */
const configText = ref('{"interval_minutes": 30}')
/** 配置下发中 */
const sendingConfig = ref(false)

/** 新增向导 */
const wizard = reactive({ visible: false, step: 0, testing: false })
/** 向导表单（type/protocol 与后端枚举对齐，collect_schedule 传输 JSON 对象） */
const wizardForm = reactive({
  type: 'camera',
  protocol: 'MQTT',
  device_no: '',
  name: '',
  plot_id: undefined as number | undefined,
  vendor: '',
  collect_schedule: '每日 3 次（早/中/晚）+ 事件触发',
})
/** 向导参数步骤表单引用 */
const wizardFormRef = ref<FormInstance | null>(null)
/** 向导提交中 */
const wizardSubmitting = ref(false)
/** 向导参数步骤校验规则（name 与 plot_id 为后端必填） */
const wizardRules: FormRules = {
  device_no: [{ required: true, message: '请输入设备编号', trigger: 'blur' }],
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }],
  plot_id: [{ required: true, message: '请选择所属地块', trigger: 'change' }],
}

/** 设备类型选项（后端枚举 camera/pest_light/spore_trap/env_sensor） */
const deviceTypeOptions = [
  { value: 'camera', label: '摄像头' },
  { value: 'pest_light', label: '测报灯' },
  { value: 'spore_trap', label: '孢子捕捉仪' },
  { value: 'env_sensor', label: '环境传感器' },
]

/** 接入协议选项（后端枚举大写 MQTT/RTSP/vendor_api） */
const protocolOptions = [
  { value: 'MQTT', label: 'MQTT' },
  { value: 'RTSP', label: 'RTSP' },
  { value: 'vendor_api', label: '厂商开放 API' },
]

/** 采集计划预设（展示文本 → JSON 对象，后端 collect_schedule 为 dict） */
const schedulePresets: Array<{ label: string; text: string; schedule: Record<string, unknown> }> = [
  { label: '摄像头：每日 3 次 + 事件触发', text: '每日 3 次（早/中/晚）+ 事件触发', schedule: { times_per_day: 3, trigger: 'event' } },
  { label: '测报灯：每日 1 次', text: '每日 1 次', schedule: { times_per_day: 1 } },
  { label: '环境传感器：每 30 分钟', text: '每 30 分钟', schedule: { interval_minutes: 30 } },
]

/** 设备行列表 */
const deviceRows = computed<Device[]>(() => devices.value ?? [])

/** 地块名称映射 */
const plotNameMap = computed<Record<number, string>>(() => {
  const map: Record<number, string> = {}
  for (const p of plots.value ?? []) {
    map[p.id] = p.name
  }
  return map
})

/**
 * 设备类型转中文标签。
 * @param type 类型键名
 * @returns 中文标签
 */
function deviceTypeLabel(type: string): string {
  return deviceTypeOptions.find((t) => t.value === type)?.label ?? type
}

/**
 * 采集计划 JSON 对象转展示文本（键值拼接；空值显示未设置）。
 * @param schedule 采集计划 JSON 对象
 * @returns 展示文本
 */
function formatSchedule(schedule?: Record<string, unknown> | null): string {
  if (!schedule || Object.keys(schedule).length === 0) return '未设置'
  return Object.entries(schedule)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join('、') : String(value)}`)
    .join('；')
}

/**
 * 判断设备是否离线超过 24 小时（红色标识）。
 * @param row 设备行
 * @returns 超过 24h 返回 true
 */
function isOfflineOver24h(row: Device): boolean {
  if (row.status !== 'offline' || !row.last_heartbeat_at) return false
  return dayjs().diff(dayjs(row.last_heartbeat_at), 'hour') > 24
}

/**
 * 打开设备详情抽屉（加载心跳历史）。
 * @param row 设备行
 */
async function openDrawer(row: Device): Promise<void> {
  drawerVisible.value = true
  drawerLoading.value = true
  try {
    drawerDevice.value = await getDeviceDetail(row.id)
  } catch {
    drawerDevice.value = row
  } finally {
    drawerLoading.value = false
  }
}

/**
 * 下发远程配置（JSON 校验）。
 * @throws JSON 格式错误时提示
 */
async function sendConfig(): Promise<void> {
  if (!drawerDevice.value) return
  let config: Record<string, unknown>
  try {
    config = JSON.parse(configText.value) as Record<string, unknown>
  } catch {
    ElMessage.error('配置必须是合法 JSON')
    return
  }
  sendingConfig.value = true
  try {
    await sendDeviceConfig(drawerDevice.value.id, config)
    ElMessage.success('配置已下发，等待设备生效')
  } finally {
    sendingConfig.value = false
  }
}

/**
 * 打开新增向导并重置表单。
 */
function openWizard(): void {
  wizard.step = 0
  Object.assign(wizardForm, {
    type: 'camera',
    protocol: 'MQTT',
    device_no: '',
    name: '',
    plot_id: undefined,
    vendor: '',
    collect_schedule: '每日 3 次（早/中/晚）+ 事件触发',
  })
  wizard.visible = true
}

/**
 * 向导下一步（参数步骤先做表单校验）。
 * @throws 校验失败时提示
 */
async function wizardNext(): Promise<void> {
  if (wizard.step === 2) {
    const valid = await wizardFormRef.value
      ?.validate()
      .then(() => true)
      .catch(() => false)
    if (!valid) return
  }
  wizard.step += 1
}

/**
 * 向导上一步。
 */
function wizardPrev(): void {
  wizard.step -= 1
}

/**
 * 连接测试（模拟 2 秒 loading 后成功）。
 */
async function testConnection(): Promise<void> {
  wizard.testing = true
  await new Promise((resolve) => setTimeout(resolve, 2000))
  wizard.testing = false
  ElMessage.success('连接测试通过')
}

/**
 * 提交向导完成设备接入（采集计划文本映射为 JSON 对象传输）。
 * @throws 编号重复或校验失败时提示
 */
async function submitWizard(): Promise<void> {
  if (!wizardForm.plot_id) {
    ElMessage.warning('请选择所属地块')
    wizard.step = 2
    return
  }
  wizardSubmitting.value = true
  try {
    const preset = schedulePresets.find((p) => p.text === wizardForm.collect_schedule)
    await createDevice({
      device_no: wizardForm.device_no,
      name: wizardForm.name || wizardForm.device_no,
      type: wizardForm.type,
      plot_id: wizardForm.plot_id,
      protocol: wizardForm.protocol,
      vendor: wizardForm.vendor === '' ? null : wizardForm.vendor,
      collect_schedule: preset?.schedule ?? { description: wizardForm.collect_schedule },
    })
    ElMessage.success('设备已接入')
    wizard.visible = false
    await Promise.all([load(), loadStats()])
  } finally {
    wizardSubmitting.value = false
  }
}

onMounted(() => {
  void loadPlots()
})
</script>

<template>
  <div class="page">
    <!-- 统计头 -->
    <div class="page-card stat-bar">
      <div class="stat-item">
        <span class="stat-num">{{ stats?.total ?? 0 }}</span>
        <span class="stat-label">设备总数</span>
      </div>
      <div class="stat-item">
        <span class="stat-num ok">{{ stats?.online ?? 0 }}</span>
        <span class="stat-label">在线</span>
      </div>
      <div class="stat-item">
        <span class="stat-num" :class="{ bad: (stats?.offline ?? 0) > 0 }">{{ stats?.offline ?? 0 }}</span>
        <span class="stat-label">离线</span>
      </div>
      <div class="stat-note text-muted">系统在无设备状态下可完全使用手动上传通道</div>
    </div>

    <div class="page-card">
      <div class="head-row">
        <h3 class="page-card-title" style="margin: 0">设备列表</h3>
        <el-button v-if="auth.isOwner" type="primary" @click="openWizard">
          <el-icon><Plus /></el-icon>&nbsp;新增设备
        </el-button>
      </div>

      <StateWrap :loading="loading" :failed="failed" :rows="6" @retry="load()">
        <el-empty v-if="deviceRows.length === 0" description="暂无设备——可完全使用手动上传通道完成诊断">
          <el-button type="primary" @click="router.push('/diagnosis/upload')">去手动上传</el-button>
        </el-empty>
        <el-table v-else :data="deviceRows" stripe :row-class-name="(r: { row: Device }) => (isOfflineOver24h(r.row) ? 'row-danger' : '')">
          <el-table-column prop="device_no" label="设备编号" width="140" />
          <el-table-column label="名称" width="130">
            <template #default="{ row }">{{ row.name || '-' }}</template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">{{ deviceTypeLabel(row.type) }}</template>
          </el-table-column>
          <el-table-column label="所属地块" width="120">
            <template #default="{ row }">{{ row.plot_id ? (plotNameMap[row.plot_id] ?? '-') : '-' }}</template>
          </el-table-column>
          <el-table-column prop="protocol" label="协议" width="110">
            <template #default="{ row }">{{ protocolOptions.find((p) => p.value === row.protocol)?.label ?? row.protocol }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="deviceStatusTag(row.status).type">{{ deviceStatusTag(row.status).text }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近心跳" min-width="150">
            <template #default="{ row }">
              <span :class="{ 'heartbeat-danger': isOfflineOver24h(row as Device) }">
                {{ formatDateTime(row.last_heartbeat_at) }}
                <template v-if="isOfflineOver24h(row as Device)">（离线超 24h，已产生预警）</template>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openDrawer(row as Device)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </StateWrap>
    </div>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" title="设备详情" size="420px">
      <StateWrap :loading="drawerLoading" :failed="false" :rows="5">
        <template v-if="drawerDevice">
          <h4 class="drawer-subtitle">基本信息</h4>
          <div class="info-line"><span class="info-key">编号</span>{{ drawerDevice.device_no }}</div>
          <div class="info-line"><span class="info-key">类型</span>{{ deviceTypeLabel(drawerDevice.type) }}</div>
          <div class="info-line">
            <span class="info-key">所属地块</span>
            {{ drawerDevice.plot_id ? (plotNameMap[drawerDevice.plot_id] ?? '-') : '-' }}
            <el-tag v-if="drawerDevice.plot_id" size="small" style="margin-left: 6px">
              {{ plotTypeLabel(plots?.find((p) => p.id === drawerDevice?.plot_id)?.type) }}
            </el-tag>
          </div>
          <div class="info-line">
            <span class="info-key">状态</span>
            <el-tag size="small" :type="deviceStatusTag(drawerDevice.status).type">
              {{ deviceStatusTag(drawerDevice.status).text }}
            </el-tag>
          </div>
          <h4 class="drawer-subtitle">采集计划</h4>
          <div class="info-line">{{ formatSchedule(drawerDevice.collect_schedule) }}</div>
          <h4 class="drawer-subtitle">心跳历史</h4>
          <el-empty
            v-if="!drawerDevice.recent_heartbeats || drawerDevice.recent_heartbeats.length === 0"
            description="暂无心跳记录"
            :image-size="50"
          />
          <el-timeline v-else class="heartbeat-timeline">
            <el-timeline-item
              v-for="(h, idx) in drawerDevice.recent_heartbeats"
              :key="idx"
              :timestamp="formatDateTime(h)"
            >
              心跳正常
            </el-timeline-item>
          </el-timeline>
          <template v-if="auth.isOwner">
            <h4 class="drawer-subtitle">远程配置</h4>
            <el-input v-model="configText" type="textarea" :rows="4" placeholder="JSON 格式配置" />
            <el-button type="primary" class="config-btn" :loading="sendingConfig" @click="sendConfig">下发配置</el-button>
          </template>
        </template>
      </StateWrap>
    </el-drawer>

    <!-- 新增向导 -->
    <el-dialog v-model="wizard.visible" title="新增设备向导" width="560px" :close-on-click-modal="false">
      <el-steps :active="wizard.step" align-center finish-status="success" class="wizard-steps">
        <el-step title="选择类型" />
        <el-step title="接入方式" />
        <el-step title="参数填写" />
        <el-step title="连接测试" />
      </el-steps>

      <!-- 步骤 1：类型 -->
      <div v-if="wizard.step === 0" class="wizard-body">
        <el-radio-group v-model="wizardForm.type" size="large">
          <el-radio-button v-for="t in deviceTypeOptions" :key="t.value" :value="t.value">
            {{ t.label }}
          </el-radio-button>
        </el-radio-group>
      </div>

      <!-- 步骤 2：接入方式 -->
      <div v-else-if="wizard.step === 1" class="wizard-body">
        <el-radio-group v-model="wizardForm.protocol">
          <el-radio v-for="p in protocolOptions" :key="p.value" :value="p.value" border>{{ p.label }}</el-radio>
        </el-radio-group>
      </div>

      <!-- 步骤 3：参数 -->
      <div v-else-if="wizard.step === 2" class="wizard-body">
        <el-form ref="wizardFormRef" :model="wizardForm" :rules="wizardRules" label-width="90px">
          <el-form-item label="设备编号" prop="device_no">
            <el-input v-model="wizardForm.device_no" placeholder="唯一编号，如 CAM-001" />
          </el-form-item>
          <el-form-item label="名称" prop="name">
            <el-input v-model="wizardForm.name" placeholder="设备显示名称" />
          </el-form-item>
          <el-form-item label="所属地块" prop="plot_id">
            <el-select v-model="wizardForm.plot_id" placeholder="选择地块" style="width: 100%">
              <el-option v-for="p in plots ?? []" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="厂商">
            <el-input v-model="wizardForm.vendor" placeholder="选填" />
          </el-form-item>
          <el-form-item label="采集计划">
            <el-select v-model="wizardForm.collect_schedule" style="width: 100%">
              <el-option v-for="p in schedulePresets" :key="p.text" :label="p.label" :value="p.text" />
            </el-select>
          </el-form-item>
        </el-form>
      </div>

      <!-- 步骤 4：连接测试 -->
      <div v-else class="wizard-body">
        <div class="test-zone">
          <el-button type="primary" size="large" :loading="wizard.testing" @click="testConnection">
            {{ wizard.testing ? '正在连接测试…' : '开始连接测试' }}
          </el-button>
          <p class="text-muted">测试通过后点击「完成接入」保存设备</p>
        </div>
      </div>

      <template #footer>
        <el-button v-if="wizard.step > 0" @click="wizardPrev">上一步</el-button>
        <el-button v-if="wizard.step < 3" type="primary" @click="wizardNext">下一步</el-button>
        <el-button v-else type="success" :loading="wizardSubmitting" @click="submitWizard">完成接入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stat-bar {
  display: flex;
  align-items: center;
  gap: 40px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.stat-num {
  font-size: 24px;
  font-weight: 700;
}

.stat-num.ok {
  color: #67c23a;
}

.stat-num.bad {
  color: #f56c6c;
}

.stat-label {
  font-size: 12px;
  color: #909399;
}

.stat-note {
  margin-left: auto;
}

.head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

:deep(.row-danger) {
  color: #f56c6c;
}

.heartbeat-danger {
  color: #f56c6c;
  font-weight: 600;
}

.drawer-subtitle {
  margin: 14px 0 8px;
  font-size: 14px;
}

.info-line {
  font-size: 13px;
  padding: 4px 0;
  color: #303133;
}

.info-key {
  color: #909399;
  display: inline-block;
  width: 70px;
}

.heartbeat-timeline {
  padding-left: 4px;
  max-height: 260px;
  overflow-y: auto;
}

.config-btn {
  margin-top: 10px;
  width: 100%;
}

.wizard-steps {
  margin-bottom: 20px;
}

.wizard-body {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.test-zone {
  text-align: center;
}
</style>
