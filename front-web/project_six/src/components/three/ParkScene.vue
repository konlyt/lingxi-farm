<script setup lang="ts">
/**
 * 文件说明：三维园区沙盘 Vue 组件壳。
 * 挂载 useParkScene 引擎，接收地块数据驱动场景，处理点击详情卡与 WebGL 降级
 * （初始化失败时向父组件发出 failed 事件，由父组件回退经典 2D 视图）。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useParkScene } from '@/composables/useParkScene'
import type { ParkPlotInput, PlotVisualState } from '@/three/scene/park'

/** 地块数据（由父组件从大屏聚合数据推导） */
const props = defineProps<{ plots: ParkPlotInput[] }>()

/** 初始化失败（WebGL 不可用） */
const emit = defineEmits<{ failed: [] }>()

/** 路由（单棚孪生跳转用） */
const router = useRouter()

/** 画布与容器引用 */
const canvasRef = ref<HTMLCanvasElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)

/** 引擎句柄 */
const handle = useParkScene()

/** 初始化是否成功（失败时显示降级提示） */
const ready = ref(false)

/** 当前选中的地块（详情卡） */
const selected = ref<ParkPlotInput | null>(null)

/** 状态中文名映射 */
const STATE_TEXT: Record<PlotVisualState, string> = { ok: '正常', warn: '预警', alert: '严重' }

watch(
  () => props.plots,
  (plots) => {
    handle.setPlots(plots)
    // 选中项被移除时同步关闭详情卡
    if (selected.value && !plots.some((p) => p.plotId === selected.value?.plotId)) {
      selected.value = null
    }
  },
  { deep: true, immediate: true },
)

onMounted(() => {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return
  ready.value = handle.init(canvas, container)
  if (!ready.value) {
    emit('failed')
    return
  }
  // 初始化后立即应用当前数据（watch immediate 触发时场景尚未建立）
  handle.setPlots(props.plots)
  handle.onSelect((plotId) => {
    const hit = props.plots.find((p) => p.plotId === plotId) ?? null
    if (hit && selected.value?.plotId !== plotId) {
      selected.value = hit
      handle.focusPlot(plotId)
    }
  })
})

/** 数据刷新时同步选中对象内容（保持详情面板与最新数据一致） */
watch(
  () => props.plots.find((p) => p.plotId === selected.value?.plotId),
  (latest) => {
    if (latest) selected.value = latest
  },
)

/**
 * 关闭详情卡并退出聚焦（镜头回到总览机位）。
 */
function closeCard(): void {
  selected.value = null
  handle.exitFocus()
}

/**
 * 跳转单棚数字孪生页。
 * @param plotId 地块 ID
 */
function goTwin(plotId: number): void {
  void router.push({ path: '/greenhouse-twin', query: { plot: String(plotId) } })
}

onUnmounted(() => {
  handle.dispose()
})
</script>

<template>
  <div ref="containerRef" class="park-scene">
    <canvas ref="canvasRef" class="park-canvas" />
    <!-- 状态图例 -->
    <div class="scene-legend">
      <span class="lg-item"><i class="lg-dot ok" />正常</span>
      <span class="lg-item"><i class="lg-dot warn" />预警</span>
      <span class="lg-item"><i class="lg-dot alert" />严重</span>
      <span class="lg-hint">拖拽旋转 · 滚轮缩放 · 点击地块查看详情</span>
    </div>
    <!-- 地块详情面板 -->
    <div v-if="selected" class="scene-card" :class="selected.state">
      <div class="card-head">
        <span class="card-name">{{ selected.name }}</span>
        <span class="card-state">{{ STATE_TEXT[selected.state] }}</span>
        <button class="card-close" type="button" aria-label="关闭" @click="closeCard">×</button>
      </div>
      <div class="card-meta">
        <span v-if="selected.type === 'greenhouse'" class="card-tag">大棚</span>
        <span v-else class="card-tag">露天</span>
        <span v-if="selected.tempText" class="card-val">温度 {{ selected.tempText }}</span>
        <span v-if="selected.humText" class="card-val">湿度 {{ selected.humText }}</span>
      </div>
      <div class="card-meta">
        <span class="card-val dim">墒情 {{ selected.soilMoisture ?? '-' }}%</span>
        <span class="card-val dim">活跃虫情预警 {{ selected.pestAlertCount ?? 0 }}</span>
      </div>
      <ul v-if="selected.alertTitles && selected.alertTitles.length > 0" class="card-alerts">
        <li v-for="t in selected.alertTitles" :key="t" class="card-alert">{{ t }}</li>
      </ul>
      <button
        v-if="selected.type === 'greenhouse'"
        class="card-link"
        type="button"
        @click="goTwin(selected.plotId)"
      >进入单棚孪生 →</button>
      <button class="card-back" type="button" @click="closeCard">返回总览</button>
    </div>
  </div>
</template>

<style scoped>
.park-scene {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.park-canvas {
  display: block;
  width: 100%;
  height: 100%;
  touch-action: none;
  cursor: grab;
}

.park-canvas:active {
  cursor: grabbing;
}

.scene-legend {
  position: absolute;
  right: 12px;
  bottom: 10px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 5px 12px;
  background: rgba(8, 24, 42, 0.72);
  border: 1px solid rgba(78, 166, 255, 0.22);
  border-radius: 4px;
  z-index: 3;
}

.lg-item {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #a9cbe8;
  font-size: 13px;
}

.lg-hint {
  color: #6d95bd;
  font-size: 12px;
  margin-left: 4px;
}

.lg-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.lg-dot.ok {
  background: #35d0ba;
}

.lg-dot.warn {
  background: #fac775;
}

.lg-dot.alert {
  background: #f0655f;
}

.scene-card {
  position: absolute;
  left: 12px;
  bottom: 10px;
  min-width: 220px;
  max-width: 320px;
  background: rgba(8, 24, 42, 0.9);
  border: 1px solid rgba(78, 166, 255, 0.35);
  border-radius: 6px;
  padding: 10px 12px;
  z-index: 4;
}

.scene-card.warn {
  border-color: rgba(250, 199, 117, 0.55);
}

.scene-card.alert {
  border-color: rgba(240, 101, 95, 0.65);
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-name {
  color: #d7ecff;
  font-size: 15px;
  font-weight: 600;
}

.card-state {
  font-size: 12px;
  color: #35d0ba;
}

.scene-card.warn .card-state {
  color: #fac775;
}

.scene-card.alert .card-state {
  color: #f0655f;
}

.card-close {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #6d95bd;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
}

.card-close:hover {
  color: #d7ecff;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
}

.card-tag {
  padding: 0 6px;
  border: 1px solid rgba(53, 208, 186, 0.5);
  border-radius: 3px;
  color: #35d0ba;
  font-size: 11px;
  line-height: 16px;
}

.card-val {
  color: #35d0ba;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.card-val {
  color: #35d0ba;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.card-val.dim {
  color: #9fc4e8;
}

.card-alerts {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-alert {
  color: #f0958f;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 280px;
}

.card-back {
  margin-top: 8px;
  width: 100%;
  padding: 4px 0;
  background: rgba(78, 166, 255, 0.12);
  border: 1px solid rgba(78, 166, 255, 0.4);
  border-radius: 4px;
  color: #9fc4e8;
  font-size: 12px;
  cursor: pointer;
}

.card-back:hover {
  color: #d7ecff;
  border-color: rgba(78, 166, 255, 0.7);
}

.card-link {
  margin-top: 8px;
  width: 100%;
  padding: 5px 0;
  background: rgba(53, 208, 186, 0.14);
  border: 1px solid rgba(53, 208, 186, 0.55);
  border-radius: 4px;
  color: #7fe8d8;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.card-link:hover {
  background: rgba(53, 208, 186, 0.26);
  color: #fff;
}
</style>
