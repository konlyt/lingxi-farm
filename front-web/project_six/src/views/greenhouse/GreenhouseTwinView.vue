<script setup lang="ts">
/**
 * 文件说明：3D 大棚数字孪生全屏页（仅 owner）。
 * 参考智慧大棚孪生中控风格：自由视角环绕单棚、环境实时数据面板、
 * 设备控制卡、时间轴昼夜联动、自主巡检、群体健康总览。
 * 数据复用大屏聚合接口 getDashboardStats，按路由 query.plot 取对应棚。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGreenhouseScene } from '@/composables/useGreenhouseScene'
import { getDashboardStats } from '@/api/overview'
import { useAsyncData } from '@/composables/useAsyncData'
import type { GreenhouseTwinData } from '@/three/scene/greenhouse'

const route = useRoute()
const router = useRouter()

/** 画布与容器引用 */
const canvasRef = ref<HTMLCanvasElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)

/** 引擎句柄 */
const handle = useGreenhouseScene()

/** 初始化失败标记 */
const failed = ref(false)

/** 目标棚 ID（路由参数） */
const plotId = computed(() => Number(route.query.plot ?? 0))

/** 大屏聚合数据 */
const stats = useAsyncData(getDashboardStats)

/** 巡检状态（自主环绕开关） */
const patrolling = ref(false)

/** 时间轴（0-24 小时） */
const hour = ref(10.5)

/** 时间显示文本（HH:mm） */
const hourText = computed(() => {
  const h = Math.floor(hour.value)
  const m = Math.round((hour.value - h) * 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
})

/** 孪生面板数据（场景标签 + 面板展示） */
interface TwinSpec extends GreenhouseTwinData {
  /** 活跃预警数 */
  pestAlertCount: number
  /** 预警标题列表 */
  alertTitles: string[]
}

/** 目标棚数据（聚合接口推导） */
const twinData = computed<TwinSpec>(() => {
  const env = stats.data.value?.env_realtime.find((r) => r.plot_id === plotId.value)
  const density = stats.data.value?.plot_pest_density.find((d) => d.plot_id === plotId.value)
  const alerts = (stats.data.value?.recent_alerts ?? []).filter(
    (a) => a.plot_id === plotId.value && a.status === 'active',
  )
  return {
    name: env?.plot_name ?? '温室大棚',
    tempText: env?.temp === null || env?.temp === undefined ? undefined : `${env.temp}℃`,
    humText: env?.humidity === null || env?.humidity === undefined ? undefined : `${env.humidity}%`,
    soilMoisture: density?.soil_moisture ?? null,
    pestAlertCount: density?.pest_alert_count ?? 0,
    alertTitles: alerts.slice(0, 3).map((a) => a.title),
  }
})

/** 环境数据行（左面板展示） */
const envItems = computed(() => {
  const d = twinData.value
  return [
    { label: '空气温度', value: d.tempText ?? '--', state: '适宜' },
    { label: '空气湿度', value: d.humText ?? '--', state: '适宜' },
    { label: '土壤墒情', value: d.soilMoisture === null || d.soilMoisture === undefined ? '--' : `${d.soilMoisture} %`, state: '适宜' },
    { label: '活跃预警', value: `${d.pestAlertCount} 项`, state: d.pestAlertCount > 0 ? '告警' : '适宜' },
  ]
})

/** 预警列表（群体健康卡片） */
const alertTitles = computed(() => twinData.value.alertTitles)

/** 时间轴拖动 → 引擎光照联动 */
watch(hour, (h) => handle.setTimeOfDay(h))

/** 巡检开关 → 相机自动环绕 */
watch(patrolling, (on) => handle.setAutoRotate(on))

/** 数据刷新 → 标签重绘 */
watch(
  twinData,
  (d) => {
    handle.setData(d)
  },
  { deep: true },
)

onMounted(() => {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return
  const ok = handle.init(canvas, container)
  if (!ok) {
    failed.value = true
    return
  }
  handle.setTimeOfDay(hour.value)
  handle.setData(twinData.value)
})

onUnmounted(() => {
  handle.dispose()
})

/**
 * 返回三维大屏。
 */
function goBack(): void {
  void router.push({ path: '/bigscreen', query: { view: '3d' } })
}
</script>

<template>
  <div ref="containerRef" class="twin-page">
    <canvas ref="canvasRef" class="twin-canvas" />

    <div v-if="failed" class="twin-failed">WebGL 初始化失败，请检查浏览器支持后重试</div>

    <!-- 返回大屏 -->
    <button class="back-btn" type="button" @click="goBack">← 返回大屏</button>

    <!-- 左侧：环境调控中枢 -->
    <aside class="panel left">
      <div class="p-title">
        <span class="p-tick" />
        <div>
          <div class="p-main">智慧大棚 · 环境调控中枢</div>
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

      <div class="sec-title">设备控制</div>
      <div class="dev-grid">
        <div class="dev-card">
          <div class="dev-name">滴灌水泵</div>
          <div class="dev-state"><i class="dot off" />P-102 · 关闭</div>
        </div>
        <div class="dev-card">
          <div class="dev-name">环流风机</div>
          <div class="dev-state"><i class="dot on" />在运行 · 自动</div>
        </div>
        <div class="dev-card">
          <div class="dev-name">LED 补光</div>
          <div class="dev-state"><i class="dot on" />按边界 · 自动</div>
        </div>
        <div class="dev-card">
          <div class="dev-name">天窗开合</div>
          <div class="dev-state"><i class="dot off" />V-401 · 关闭</div>
        </div>
      </div>

      <div class="sec-title">时间轴（太瓦宽度联动）</div>
      <div class="time-row">
        <el-slider v-model="hour" :min="0" :max="24" :step="0.25" />
        <span class="time-text">{{ hourText }}</span>
      </div>

      <div class="sec-title">群体健康总览</div>
      <div class="health-card">
        <div class="health-line">本棚病虫害活跃预警 {{ alertTitles.length }} 组</div>
        <div v-for="t in alertTitles" :key="t" class="health-alert">{{ t }}</div>
        <div v-if="alertTitles.length === 0" class="health-ok">当前无活跃预警，植株状态良好</div>
      </div>
    </aside>

    <!-- 右侧：巡检 Agent -->
    <aside class="panel right">
      <div class="p-title">
        <span class="p-tick" />
        <div>
          <div class="p-main">无风 · 巡检 Agent</div>
          <div class="p-sub">AGV-J101 · 待命中</div>
        </div>
      </div>
      <div class="agent-status">当前未开始任务，点击右侧按钮可开始巡检指令。</div>
      <button class="agent-btn" :class="{ active: patrolling }" type="button" @click="patrolling = !patrolling">
        {{ patrolling ? '停止巡检' : '自主巡检' }}
      </button>
      <div class="agent-hint">开启后相机自动环绕棚体，拖拽画面会暂停巡检</div>
    </aside>

    <!-- 操作提示 -->
    <div class="hint-bar">左键旋转 · 右键平移 · 滚轮缩放 · 时间轴联动昼夜光照</div>
  </div>
</template>

<style scoped>
.twin-page {
  position: relative;
  width: 100vw;
  height: 100vh;
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

.twin-failed {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #f0958f;
  font-size: 15px;
}

.back-btn {
  position: absolute;
  left: 16px;
  top: 14px;
  z-index: 6;
  padding: 6px 14px;
  background: rgba(8, 20, 18, 0.82);
  border: 1px solid rgba(53, 208, 186, 0.45);
  border-radius: 5px;
  color: #7fe8d8;
  font-size: 13px;
  cursor: pointer;
}

.back-btn:hover {
  color: #fff;
  border-color: rgba(53, 208, 186, 0.8);
}

/* ===== 悬浮玻璃面板 ===== */
.panel {
  position: absolute;
  top: 60px;
  z-index: 5;
  width: 296px;
  max-height: calc(100vh - 130px);
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
  width: 250px;
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
}

.dev-state {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #8fb5a8;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.dot.on {
  background: #35d0ba;
  box-shadow: 0 0 5px rgba(53, 208, 186, 0.9);
}

.dot.off {
  background: #5a6f66;
}

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

.agent-hint {
  margin-top: 8px;
  font-size: 11px;
  color: #6d8f82;
  line-height: 1.5;
}

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
