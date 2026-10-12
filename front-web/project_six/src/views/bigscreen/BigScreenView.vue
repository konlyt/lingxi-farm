<script setup lang="ts">
/**
 * 文件说明：自用监测大屏页（16，仅 owner）。
 * 全屏深色风格，ECharts 六面板：诊断趋势折线、病虫害类型分布饼图、地块虫情密度与墒情组合图、
 * 设备健康度环图、实时预警流、环境实况卡片；各面板独立加载/失败重试；60 秒定时刷新。
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { getDashboardStats } from '@/api/overview'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import EChart from '@/components/EChart.vue'
import { alertLevelTag, formatDateTime } from '@/utils/format'
import type { EChartsOption } from 'echarts'

/** 面板统一数据加载器（同一聚合接口，独立实例实现单面板失败独立重试） */
function makePanel() {
  return useAsyncData(getDashboardStats)
}

/** 诊断趋势面板 */
const trendPanel = makePanel()
/** 类型分布面板 */
const piePanel = makePanel()
/** 虫情密度面板 */
const densityPanel = makePanel()
/** 设备健康面板 */
const devicePanel = makePanel()
/** 预警流面板 */
const alertPanel = makePanel()
/** 环境实况面板 */
const envPanel = makePanel()

/** 全部面板加载器（定时刷新用） */
const allPanels = [trendPanel, piePanel, densityPanel, devicePanel, alertPanel, envPanel]

/** 刷新定时器句柄 */
let refreshTimer: number | undefined

/** 大屏主色板 */
const palette = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#9a6fe0', '#36cfc9'] as const

/**
 * 构建诊断趋势折线配置（后端 diagnosis_trend 为 [{date, count}] 数组）。
 * @returns ECharts 配置
 */
const trendOption = computed<EChartsOption>(() => {
  const rows = trendPanel.data.value?.diagnosis_trend ?? []
  return {
    color: [palette[0]],
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 30, bottom: 26 },
    xAxis: { type: 'category', data: rows.map((r) => r.date), axisLabel: { color: '#8fb3d9' } },
    yAxis: { type: 'value', axisLabel: { color: '#8fb3d9' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } } },
    series: [
      {
        name: '诊断次数',
        type: 'line',
        smooth: true,
        areaStyle: { opacity: 0.25 },
        data: rows.map((r) => r.count),
      },
    ],
  }
})

/**
 * 构建病虫害类型分布饼图配置。
 * @returns ECharts 配置
 */
const pieOption = computed<EChartsOption>(() => ({
  color: [...palette],
  tooltip: { trigger: 'item' },
  legend: { bottom: 0, textStyle: { color: '#8fb3d9', fontSize: 11 } },
  series: [
    {
      name: '病虫害类型',
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '44%'],
      label: { color: '#cfe3f5', fontSize: 11 },
      data:
        piePanel.data.value?.disease_distribution.map((d) => ({ name: d.disease_name, value: d.count })) ?? [],
    },
  ],
}))

/**
 * 构建地块虫情密度与墒情组合图配置。
 * @returns ECharts 配置
 */
const densityOption = computed<EChartsOption>(() => {
  const rows = densityPanel.data.value?.plot_pest_density ?? []
  return {
    color: [palette[3], palette[1]],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: '#8fb3d9' } },
    grid: { left: 40, right: 40, top: 34, bottom: 26 },
    xAxis: { type: 'category', data: rows.map((r) => r.plot_name), axisLabel: { color: '#8fb3d9' } },
    yAxis: [
      { type: 'value', name: '虫情密度', axisLabel: { color: '#8fb3d9' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } } },
      { type: 'value', name: '墒情', axisLabel: { color: '#8fb3d9' }, splitLine: { show: false } },
    ],
    series: [
      { name: '虫情预警', type: 'bar', data: rows.map((r) => r.pest_alert_count) },
      { name: '土壤墒情', type: 'line', yAxisIndex: 1, smooth: true, data: rows.map((r) => r.soil_moisture) },
    ],
  }
})

/**
 * 构建设备健康度环图配置。
 * @returns ECharts 配置
 */
const deviceOption = computed<EChartsOption>(() => {
  const health = devicePanel.data.value?.device_health
  return {
    color: ['#67c23a', '#f56c6c'],
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: '#8fb3d9' } },
    series: [
      {
        name: '设备健康度',
        type: 'pie',
        radius: ['52%', '74%'],
        center: ['50%', '44%'],
        label: {
          show: true,
          position: 'center',
          formatter: `{a|${health?.total ?? 0}}\n{b|总设备}`,
          rich: {
            a: { color: '#fff', fontSize: 24, fontWeight: 700 },
            b: { color: '#8fb3d9', fontSize: 12, padding: [4, 0, 0, 0] },
          },
        },
        data: [
          { name: '在线', value: health?.online ?? 0 },
          { name: '离线', value: health?.offline ?? 0 },
        ],
      },
    ],
  }
})

/** 环境实况行 */
const envRows = computed(() => envPanel.data.value?.env_realtime ?? [])

/**
 * 环境值格式化（null 显示 '-'）。
 * @param value 数值
 * @param unit 单位
 * @returns 展示文本
 */
function envText(value: number | null | undefined, unit: string): string {
  return value === null || value === undefined ? '-' : `${value}${unit}`
}

/** 预警流行 */
const alertRows = computed(() => alertPanel.data.value?.recent_alerts ?? [])

onMounted(() => {
  // 60 秒定时刷新全部面板
  refreshTimer = window.setInterval(() => {
    for (const panel of allPanels) {
      if (!panel.loading.value) void panel.load()
    }
  }, 60000)
})

onUnmounted(() => {
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="bigscreen">
    <div class="screen-title">农场智能管护 · 监测大屏</div>

    <div class="panel-grid">
      <!-- 诊断趋势 -->
      <div class="panel">
        <div class="panel-title">诊断趋势（近 14 天）</div>
        <StateWrap :loading="trendPanel.loading.value" :failed="trendPanel.failed.value" :rows="4" @retry="trendPanel.load()">
          <EChart v-if="trendPanel.data.value" :option="trendOption" height="220px" />
          <el-empty v-else description="暂无数据" :image-size="50" />
        </StateWrap>
      </div>

      <!-- 病虫害类型分布 -->
      <div class="panel">
        <div class="panel-title">病虫害类型分布</div>
        <StateWrap :loading="piePanel.loading.value" :failed="piePanel.failed.value" :rows="4" @retry="piePanel.load()">
          <EChart v-if="piePanel.data.value" :option="pieOption" height="220px" />
          <el-empty v-else description="暂无数据" :image-size="50" />
        </StateWrap>
      </div>

      <!-- 地块虫情密度与墒情 -->
      <div class="panel">
        <div class="panel-title">地块虫情密度与墒情</div>
        <StateWrap :loading="densityPanel.loading.value" :failed="densityPanel.failed.value" :rows="4" @retry="densityPanel.load()">
          <EChart v-if="densityPanel.data.value" :option="densityOption" height="220px" />
          <el-empty v-else description="暂无数据" :image-size="50" />
        </StateWrap>
      </div>

      <!-- 设备健康度 -->
      <div class="panel">
        <div class="panel-title">设备健康度</div>
        <StateWrap :loading="devicePanel.loading.value" :failed="devicePanel.failed.value" :rows="4" @retry="devicePanel.load()">
          <EChart v-if="devicePanel.data.value" :option="deviceOption" height="220px" />
          <el-empty v-else description="暂无数据" :image-size="50" />
        </StateWrap>
      </div>

      <!-- 实时预警流 -->
      <div class="panel">
        <div class="panel-title">实时预警流</div>
        <StateWrap :loading="alertPanel.loading.value" :failed="alertPanel.failed.value" :rows="4" @retry="alertPanel.load()">
          <div v-if="alertRows.length > 0" class="alert-stream">
            <div v-for="a in alertRows" :key="a.id" class="stream-row">
              <el-tag size="small" :type="alertLevelTag(a.level).type" effect="dark">{{ alertLevelTag(a.level).text }}</el-tag>
              <span class="stream-title">{{ a.title }}</span>
              <span class="stream-time">{{ formatDateTime(a.first_triggered_at) }}</span>
            </div>
          </div>
          <el-empty v-else description="暂无预警" :image-size="50" />
        </StateWrap>
      </div>

      <!-- 环境实况 -->
      <div class="panel">
        <div class="panel-title">环境实况</div>
        <StateWrap :loading="envPanel.loading.value" :failed="envPanel.failed.value" :rows="4" @retry="envPanel.load()">
          <div v-if="envRows.length > 0" class="env-grid">
            <div v-for="(row, idx) in envRows" :key="idx" class="env-card">
              <div class="env-name">{{ row.plot_name }}</div>
              <div class="env-vals">
                <span>温度 {{ envText(row.temp, '℃') }}</span>
                <span>湿度 {{ envText(row.humidity, '%') }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无数据" :image-size="50" />
        </StateWrap>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bigscreen {
  min-height: 100vh;
  background: radial-gradient(ellipse at top, #10314f 0%, #0b1c2c 65%, #081420 100%);
  padding: 16px;
}

.screen-title {
  text-align: center;
  color: #cfe3f5;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 4px;
  margin-bottom: 16px;
}

.panel-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.panel {
  background: rgba(18, 38, 58, 0.85);
  border: 1px solid rgba(64, 158, 255, 0.25);
  border-radius: 10px;
  padding: 12px;
  min-height: 270px;
}

.panel-title {
  color: #9fc8ef;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
}

.alert-stream {
  max-height: 220px;
  overflow-y: auto;
}

.stream-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 4px;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.08);
  color: #cfe3f5;
  font-size: 12px;
}

.stream-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stream-time {
  color: #6d89a8;
  font-size: 11px;
}

.env-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}

.env-card {
  background: rgba(64, 158, 255, 0.08);
  border-radius: 8px;
  padding: 10px;
}

.env-name {
  color: #cfe3f5;
  font-size: 13px;
  margin-bottom: 6px;
}

.env-vals {
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: #67c23a;
  font-size: 12px;
}

/* 深色背景下的骨架与空态适配 */
.panel :deep(.el-skeleton__item) {
  background: rgba(255, 255, 255, 0.08);
}

.panel :deep(.el-empty__description p) {
  color: #6d89a8;
}

@media (max-width: 991px) {
  .panel-grid {
    grid-template-columns: 1fr;
  }
}
</style>
