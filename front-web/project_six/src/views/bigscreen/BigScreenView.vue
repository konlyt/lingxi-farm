<script setup lang="ts">
/**
 * 文件说明：监测大屏 · 3D 数字孪生页（完全重构版，仅 owner）。
 * 参考智慧大棚孪生中控风格：全屏三维场景打底（完整大棚/露天地块建模，360° 自由视角），
 * 左侧环境调控中枢面板（环境实时数据/设备监控/时间轴/群体健康总览），右侧巡检 Agent。
 * 数据源：getDashboardStats（60s 轮询）+ getDevices（按地块），地块下拉切换（大棚 ↔ 露天自动换建模）。
 * 原三段式 2D 大屏保留为「经典视图」，路由 ?view=2d 直达，WebGL 失败自动回退。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGreenhouseScene } from '@/composables/useGreenhouseScene'
import { getDashboardStats } from '@/api/overview'
import { getDevices } from '@/api/devices'
import { useAsyncData } from '@/composables/useAsyncData'
import ClassicDashboard from '@/views/bigscreen/ClassicDashboard.vue'
import type { Device } from '@/types/farm'
import type { TwinSceneKind } from '@/three/scene/greenhouse'

const route = useRoute()
const router = useRouter()

/** 画布与容器引用 */
const canvasRef = ref<HTMLCanvasElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)

/** 引擎句柄 */
const handle = useGreenhouseScene()

/** WebGL 初始化失败标记（失败后锁定经典视图） */
const sceneFailed = ref(false)

/** 视图模式（路由 ?view=2d 时默认经典视图，否则默认 3D 孪生） */
const view3d = ref((route.query.view as string | undefined) !== '2d')

/* ================= 数据加载 ================= */

/** 大屏聚合数据（60s 轮询） */
const stats = useAsyncData(getDashboardStats)

/** 轮询定时器句柄 */
let refreshTimer: number | undefined

/** 地块选项（来自环境实况：含类型） */
const plotOptions = computed(() =>
  (stats.data.value?.env_realtime ?? []).map((r) => ({
    id: r.plot_id,
    name: r.plot_name,
    type: r.type,
  })),
)

/** 当前选中地块 ID */
const plotId = ref<number | null>(null)

/** 设备列表（按地块过滤） */
const devices = ref<Device[]>([])
/** 设备加载中 */
const devicesLoading = ref(false)
/** 设备加载失败 */
const devicesFailed = ref(false)

/**
 * 加载当前地块设备列表。
 */
async function loadDevices(): Promise<void> {
  if (plotId.value === null) {
    devices.value = []
    return
  }
  devicesLoading.value = true
  devicesFailed.value = false
  try {
    devices.value = await getDevices({ plot_id: plotId.value })
  } catch {
    devicesFailed.value = true
  } finally {
    devicesLoading.value = false
  }
}

/** 首次拿到地块列表后初始化默认选中（优先路由参数，其次第一个大棚，再次第一个地块） */
let plotInitialized = false
watch(
  plotOptions,
  (opts) => {
    if (plotInitialized || opts.length === 0) return
    plotInitialized = true
    const fromQuery = Number(route.query.plot ?? 0)
    const matched = opts.find((o) => o.id === fromQuery)
    if (matched) {
      plotId.value = matched.id
    } else {
      const fallback = opts.find((o) => o.type === 'greenhouse') ?? opts[0]
      plotId.value = fallback?.id ?? null
    }
  },
  { immediate: true },
)

/** 地块切换 → 同步路由 + 重载设备 */
watch(plotId, (id) => {
  if (id !== null) {
    void router.replace({ query: { ...route.query, plot: String(id), view: view3d.value ? '3d' : '2d' } })
  }
  void loadDevices()
})

/* ================= 面板数据推导 ================= */

/** 当前地块信息 */
const currentPlot = computed(() => plotOptions.value.find((o) => o.id === plotId.value) ?? null)

/** 当前地块是否大棚 */
const isGreenhouse = computed(() => currentPlot.value?.type === 'greenhouse')

/** 孪生场景标签数据 */
const twinData = computed(() => {
  const env = stats.data.value?.env_realtime.find((r) => r.plot_id === plotId.value)
  const density = stats.data.value?.plot_pest_density.find((d) => d.plot_id === plotId.value)
  const alerts = (stats.data.value?.recent_alerts ?? []).filter(
    (a) => a.plot_id === plotId.value && a.status === 'active',
  )
  return {
    name: env?.plot_name ?? '数字孪生场景',
    tempText: env?.temp === null || env?.temp === undefined ? undefined : `${env.temp}℃`,
    humText: env?.humidity === null || env?.humidity === undefined ? undefined : `${env.humidity}%`,
    soilMoisture: density?.soil_moisture ?? null,
    pestAlertCount: density?.pest_alert_count ?? 0,
    alertTitles: alerts.slice(0, 3).map((a) => a.title),
  }
})

/** 环境实时数据行 */
const envItems = computed(() => {
  const d = twinData.value
  return [
    { label: '空气温度', value: d.tempText ?? '--', state: '适宜' },
    { label: '空气湿度', value: d.humText ?? '--', state: '适宜' },
    {
      label: isGreenhouse.value ? '基质含水率' : '土壤墒情',
      value: d.soilMoisture === null || d.soilMoisture === undefined ? '--' : `${d.soilMoisture} %`,
      state: '适宜',
    },
    {
      label: '活跃预警',
      value: `${d.pestAlertCount} 项`,
      state: d.pestAlertCount > 0 ? '告警' : '适宜',
    },
  ]
})

/** 群体健康预警标题 */
const alertTitles = computed(() => twinData.value.alertTitles)

/** 设备健康统计 */
const deviceHealth = computed(() => stats.data.value?.device_health)

/** 设备类型中文映射 */
const DEVICE_TYPE_LABEL: Record<string, string> = {
  camera: '监控摄像头',
  pest_light: '虫情测报灯',
  spore_trap: '孢子捕捉仪',
  env_sensor: '环境传感器',
}

/**
 * 设备展示名（无名称时回退类型标签）。
 * @param d 设备
 * @returns 展示名
 */
function deviceName(d: Device): string {
  return d.name || DEVICE_TYPE_LABEL[d.type] || '监测设备'
}

/** 设备卡展示行（最多 6 个） */
const deviceCards = computed(() =>
  devices.value.slice(0, 6).map((d) => ({
    id: d.id,
    name: deviceName(d),
    no: d.device_no,
    online: d.status === 'online',
  })),
)

/* ================= 场景交互 ================= */

/** 巡检状态（自主环绕开关） */
const patrolling = ref(false)

/** 时间轴（0-24 小时） */
const hour = ref(9.5)

/** 时间显示文本（HH:mm） */
const hourText = computed(() => {
  const h = Math.floor(hour.value)
  const m = Math.round((hour.value - h) * 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
})

/** 时间轴拖动 → 引擎光照联动 */
watch(hour, (h) => handle.setTimeOfDay(h))

/** 巡检开关 → 相机自动环绕 */
watch(patrolling, (on) => handle.setAutoRotate(on))

/** 数据刷新 → 场景标签重绘 */
watch(
  twinData,
  (d) => {
    handle.setData(d)
  },
  { deep: true },
)

/** 地块类型变化 → 切换大棚/露天地块建模（init 完成后才生效） */
watch(
  isGreenhouse,
  (gh) => {
    handle.setScene(gh ? 'greenhouse' : 'open_field')
  },
)

/**
 * 切换 3D/经典视图并同步路由参数。
 * @param to3d 是否切到 3D 孪生视图
 */
function switchView(to3d: boolean): void {
  view3d.value = to3d
  void router.replace({ query: { ...route.query, view: to3d ? '3d' : '2d' } })
}

onMounted(() => {
  void stats.load()
  // 60 秒定时刷新聚合数据
  refreshTimer = window.setInterval(() => {
    if (!stats.loading.value) void stats.load()
  }, 60000)

  // 3D 视图初始化场景
  if (view3d.value) {
    initScene()
  }
})

/**
 * 初始化 3D 场景（失败则回退经典视图）。
 */
function initScene(): void {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return
  const ok = handle.init(canvas, container)
  if (!ok) {
    sceneFailed.value = true
    view3d.value = false
    return
  }
  handle.setTimeOfDay(hour.value)
  handle.setData(twinData.value)
  /* 初始主体按当前地块类型（默认建的是大棚，露天则换） */
  if (isGreenhouse.value === false) {
    handle.setScene('open_field')
  }
}

/** 视图切换联动：切回 3D 重新初始化场景，切到经典视图暂停渲染并释放资源 */
watch(view3d, (to3d) => {
  if (to3d && !sceneFailed.value) {
    void Promise.resolve().then(() => initScene())
  } else if (!to3d) {
    handle.stop()
  }
})

onUnmounted(() => {
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
  handle.dispose()
})
</script>

<template>
  <div class="twin-root">
    <!-- 3D 孪生视图 -->
    <div v-if="view3d && !sceneFailed" ref="containerRef" class="twin-page">
      <canvas ref="canvasRef" class="twin-canvas" />

      <!-- 顶栏：标题 + 地块切换 + 视图切换 -->
      <header class="top-bar">
        <div class="title-block">
          <h1>{{ isGreenhouse ? '3D 大棚' : '3D 地块' }}</h1>
          <div class="title-sub">{{ twinData.name }} · 数字孪生场景</div>
        </div>
        <div class="top-actions">
          <div class="source-switch">
            <span class="sw-label">数据源切换</span>
            <el-select
              v-model="plotId"
              size="small"
              placeholder="选择地块"
              class="sw-select"
              :teleported="false"
            >
              <el-option
                v-for="o in plotOptions"
                :key="o.id"
                :value="o.id"
                :label="`${o.name}（${o.type === 'greenhouse' ? '大棚' : '露天'}）`"
              />
            </el-select>
          </div>
          <button class="ghost-btn" type="button" @click="switchView(false)">经典视图</button>
        </div>
      </header>

      <!-- 左侧：环境调控中枢 -->
      <aside class="panel left">
        <div class="p-title">
          <span class="p-tick" />
          <div>
            <div class="p-main">{{ isGreenhouse ? '智慧大棚' : '智慧地块' }} · 环境调控中枢</div>
            <div class="p-sub">{{ twinData.name }} · 数字孪生场景</div>
          </div>
        </div>

        <div class="sec-title">环境实时数据</div>
        <div class="env-list">
          <div v-for="item in envItems" :key="item.label" class="env-row">
            <span class="env-label">{{ item.label }}</span>
            <span class="env-value">{{ item.value }}</span>
            <span class="env-state" :class="{ alert: item.state === '告警' }">{{ item.state }}</span>
          </div>
        </div>

        <div class="sec-title">设备监控（本地块）</div>
        <div v-if="devicesLoading" class="dev-empty">设备加载中…</div>
        <div v-else-if="devicesFailed" class="dev-empty dev-error">设备加载失败</div>
        <div v-else-if="deviceCards.length === 0" class="dev-empty">本地块暂无接入设备</div>
        <div v-else class="dev-grid">
          <div v-for="d in deviceCards" :key="d.id" class="dev-card">
            <div class="dev-name">{{ d.name }}</div>
            <div class="dev-state">
              <i class="dot" :class="d.online ? 'on' : 'off'" />{{ d.no }} · {{ d.online ? '在线' : '离线' }}
            </div>
          </div>
        </div>

        <div class="sec-title">时间轴（昼夜光照联动）</div>
        <div class="time-row">
          <el-slider v-model="hour" :min="0" :max="24" :step="0.25" />
          <span class="time-text">{{ hourText }}</span>
        </div>

        <div class="sec-title">群体健康总览</div>
        <div class="health-card">
          <div class="health-line">本地块病虫害活跃预警 {{ alertTitles.length }} 组</div>
          <div v-for="t in alertTitles" :key="t" class="health-alert">{{ t }}</div>
          <div v-if="alertTitles.length === 0" class="health-ok">当前无活跃预警，植株状态良好</div>
        </div>
      </aside>

      <!-- 右侧：巡检 Agent + 设备健康 -->
      <aside class="panel right">
        <div class="p-title">
          <span class="p-tick" />
          <div>
            <div class="p-main">巡检 Agent</div>
            <div class="p-sub">{{ patrolling ? '自主巡检中' : '待命中' }}</div>
          </div>
        </div>
        <div class="agent-status">
          {{ patrolling ? '相机正自动环绕孪生主体巡检，拖拽画面可随时接管。' : '当前未开始任务，点击下方按钮可下发自主巡检指令。' }}
        </div>
        <button class="agent-btn" :class="{ active: patrolling }" type="button" @click="patrolling = !patrolling">
          {{ patrolling ? '停止巡检' : '自主巡检' }}
        </button>

        <div class="sec-title">设备健康（全场）</div>
        <div class="kpi-mini">
          <div class="kpi-item">
            <div class="kpi-num cyan">{{ deviceHealth?.total ?? '--' }}</div>
            <div class="kpi-cap">总数</div>
          </div>
          <div class="kpi-item">
            <div class="kpi-num green">{{ deviceHealth?.online ?? '--' }}</div>
            <div class="kpi-cap">在线</div>
          </div>
          <div class="kpi-item">
            <div class="kpi-num red">{{ deviceHealth?.offline ?? '--' }}</div>
            <div class="kpi-cap">离线</div>
          </div>
        </div>
        <div class="agent-hint">数据 60s 自动刷新 · 来源于农场监测平台</div>
      </aside>

      <!-- 操作提示 -->
      <div class="hint-bar">左键旋转 · 右键平移 · 滚轮缩放 · 时间轴联动昼夜光照</div>
    </div>

    <!-- 经典视图 / WebGL 回退 -->
    <ClassicDashboard v-else @back-3d="switchView(true)" />
  </div>
</template>

<style scoped>
.twin-root {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

/* ===== 3D 孪生页 ===== */
.twin-page {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #0a1428;
  font-family: 'Microsoft YaHei', sans-serif;
}

.twin-canvas {
  display: block;
  width: 100%;
  height: 100%;
  touch-action: none;
  cursor: grab;
}

.twin-canvas:active {
  cursor: grabbing;
}

/* ===== 顶栏 ===== */
.top-bar {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  z-index: 6;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 12px 16px 0;
  pointer-events: none;
}

.top-bar > * {
  pointer-events: auto;
}

.title-block h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: #eafff8;
  letter-spacing: 2px;
  text-shadow: 0 0 14px rgba(53, 208, 186, 0.45);
}

.title-sub {
  margin-top: 2px;
  font-size: 12px;
  color: #8fb5a8;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.source-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  background: rgba(8, 20, 18, 0.82);
  border: 1px solid rgba(53, 208, 186, 0.35);
  border-radius: 6px;
}

.sw-label {
  font-size: 12px;
  color: #8fb5a8;
  white-space: nowrap;
}

.sw-select {
  width: 190px;
}

.sw-select :deep(.el-input__wrapper) {
  background: rgba(53, 208, 186, 0.08);
  box-shadow: 0 0 0 1px rgba(53, 208, 186, 0.35) inset;
}

.sw-select :deep(.el-input__inner) {
  color: #d7ece4;
}

.ghost-btn {
  padding: 6px 14px;
  background: rgba(8, 20, 18, 0.82);
  border: 1px solid rgba(53, 208, 186, 0.45);
  border-radius: 6px;
  color: #7fe8d8;
  font-size: 13px;
  cursor: pointer;
}

.ghost-btn:hover {
  color: #fff;
  border-color: rgba(53, 208, 186, 0.8);
}

/* ===== 悬浮玻璃面板 ===== */
.panel {
  position: absolute;
  top: 76px;
  z-index: 5;
  width: 296px;
  max-height: calc(100% - 120px);
  overflow-y: auto;
  background: rgba(8, 20, 18, 0.85);
  border: 1px solid rgba(53, 208, 186, 0.3);
  border-radius: 10px;
  padding: 14px 16px;
  backdrop-filter: blur(6px);
  color: #d7ece4;
}

.panel.left {
  left: 16px;
}

.panel.right {
  right: 16px;
  width: 252px;
}

.p-title {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.p-tick {
  width: 4px;
  align-self: stretch;
  background: #35d0ba;
  border-radius: 2px;
  flex: none;
}

.p-main {
  font-size: 15px;
  font-weight: 600;
  color: #eafff8;
}

.p-sub {
  margin-top: 2px;
  font-size: 12px;
  color: #8fb5a8;
}

.sec-title {
  margin: 12px 0 6px;
  font-size: 12px;
  letter-spacing: 1px;
  color: #35d0ba;
}

.env-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.env-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: rgba(53, 208, 186, 0.06);
  border-radius: 5px;
  font-size: 13px;
}

.env-label {
  color: #9fc4b5;
  flex: 1;
}

.env-value {
  color: #eafff8;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.env-state {
  font-size: 11px;
  color: #35d0ba;
  border: 1px solid rgba(53, 208, 186, 0.45);
  border-radius: 3px;
  padding: 0 5px;
  line-height: 16px;
}

.env-state.alert {
  color: #f0958f;
  border-color: rgba(240, 101, 95, 0.55);
}

/* ===== 设备监控 ===== */
.dev-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.dev-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  padding: 8px 10px;
}

.dev-name {
  font-size: 13px;
  font-weight: 600;
  color: #eafff8;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dev-state {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #8fb5a8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dev-empty {
  padding: 10px 8px;
  font-size: 12px;
  color: #6d8f82;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  text-align: center;
}

.dev-error {
  color: #f0958f;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}

.dot.on {
  background: #35d0ba;
  box-shadow: 0 0 5px rgba(53, 208, 186, 0.9);
}

.dot.off {
  background: #5a6f66;
}

/* ===== 时间轴 ===== */
.time-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.time-row :deep(.el-slider__runway) {
  background: rgba(255, 255, 255, 0.12);
}

.time-text {
  flex: none;
  width: 46px;
  text-align: right;
  color: #35d0ba;
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* ===== 群体健康 ===== */
.health-card {
  background: rgba(53, 208, 186, 0.05);
  border: 1px solid rgba(53, 208, 186, 0.18);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12px;
}

.health-line {
  color: #9fc4b5;
  margin-bottom: 4px;
}

.health-alert {
  color: #f0958f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.health-ok {
  color: #7fe8d8;
}

/* ===== 右侧 Agent ===== */
.agent-status {
  font-size: 12px;
  color: #8fb5a8;
  line-height: 1.6;
  margin-bottom: 10px;
}

.agent-btn {
  width: 100%;
  padding: 8px 0;
  background: rgba(53, 208, 186, 0.14);
  border: 1px solid rgba(53, 208, 186, 0.55);
  border-radius: 6px;
  color: #7fe8d8;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.agent-btn:hover {
  background: rgba(53, 208, 186, 0.24);
}

.agent-btn.active {
  background: rgba(240, 101, 95, 0.16);
  border-color: rgba(240, 101, 95, 0.6);
  color: #f0958f;
}

.kpi-mini {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.kpi-item {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  padding: 8px 0;
  text-align: center;
}

.kpi-num {
  font-size: 22px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.kpi-num.cyan {
  color: #4ea6ff;
}

.kpi-num.green {
  color: #35d0ba;
}

.kpi-num.red {
  color: #f0655f;
}

.kpi-cap {
  margin-top: 2px;
  font-size: 11px;
  color: #8fb5a8;
}

.agent-hint {
  margin-top: 10px;
  font-size: 11px;
  color: #6d8f82;
  line-height: 1.5;
}

/* ===== 底部操作提示 ===== */
.hint-bar {
  position: absolute;
  left: 50%;
  bottom: 14px;
  transform: translateX(-50%);
  z-index: 5;
  padding: 5px 16px;
  background: rgba(8, 20, 18, 0.72);
  border: 1px solid rgba(53, 208, 186, 0.25);
  border-radius: 5px;
  color: #8fb5a8;
  font-size: 12px;
  white-space: nowrap;
}
</style>
