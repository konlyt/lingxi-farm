<script setup lang="ts">
/**
 * 文件说明：ECharts 图表包装组件。
 * 负责初始化、option 响应式更新与容器尺寸自适应（ResizeObserver）。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

const props = defineProps<{
  /** 图表配置项 */
  option: EChartsOption
  /** 图表高度，默认 300px */
  height?: string
}>()

/** 容器 DOM 引用 */
const el = ref<HTMLDivElement | null>(null)
/** 图表实例 */
let chart: echarts.ECharts | null = null
/** 尺寸观察器 */
let resizeObserver: ResizeObserver | null = null

/**
 * 渲染/更新图表配置。
 */
function render(): void {
  if (chart && props.option) {
    chart.setOption(props.option, true)
  }
}

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value)
  // 注入农业绿默认调色板，未显式指定 color 的图表自动统一色调
  chart.setOption({
    color: ['#2e7d4f', '#f59e0b', '#d9534f', '#7fb594', '#4a9a6b', '#9fc4b0'],
    textStyle: { color: '#3d4a42' },
  })
  render()
  resizeObserver = new ResizeObserver(() => {
    chart?.resize()
  })
  resizeObserver.observe(el.value)
})

watch(() => props.option, render, { deep: true })

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" class="echart-box" :style="{ height: height ?? '300px' }" />
</template>

<style scoped>
.echart-box {
  width: 100%;
}
</style>
