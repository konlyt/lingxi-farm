<script setup lang="ts">
/**
 * 文件说明：自用监测大屏页（16，仅 owner）。
 * 科技风三段式布局（1920×1080 设计稿，transform scale 等比适配）：
 * 左列 环境实况 KPI + 地块虫情密度与墒情；中央 园区主视觉（热点标注）+ 设备指标翻牌 + 实时预警跑马灯；
 * 右列 诊断趋势 + 病虫害类型分布。各面板独立加载/失败重试；60 秒定时刷新。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'

dayjs.locale('zh-cn')
import { getDashboardStats } from '@/api/overview'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import EChart from '@/components/EChart.vue'
import TechPanel from '@/components/TechPanel.vue'
import { formatDateTime } from '@/utils/format'
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

/** 科技风主色板 */
const palette = ['#4ea6ff', '#35d0ba', '#fac775', '#f0655f', '#9a6fe0', '#36cfc9'] as const

/** 轴文字统一色 */
const AXIS_TEXT = '#7fa8cf' as const

/** 分隔线统一色 */
const SPLIT_LINE = 'rgba(126, 180, 235, 0.12)' as const

/* ================= 等比缩放适配 ================= */

/** 视口容器引用 */
const viewport = ref<HTMLDivElement | null>(null)

/** 当前横纵缩放比例（各自拉伸铺满视口，不留黑边） */
const scaleXY = ref({ x: 1, y: 1 })

/**
 * 依据视口尺寸计算 1920×1080 设计稿的横纵缩放比例。
 */
function updateScale(): void {
  const el = viewport.value
  if (!el) return
  scaleXY.value = { x: el.clientWidth / 1920, y: el.clientHeight / 1080 }
}

/* ================= 顶栏时钟 ================= */

/** 时钟文本 */
const clockText = ref(dayjs().format('YYYY-MM-DD HH:mm:ss dddd'))

/** 时钟定时器句柄 */
let clockTimer: number | undefined

/* ================= 图表配置 ================= */

/**
 * 构建诊断趋势渐变面积折线图（后端 diagnosis_trend 为 [{date, count}] 数组）。
 * @returns ECharts 配置
 */
const trendOption = computed<EChartsOption>(() => {
  const rows = trendPanel.data.value?.diagnosis_trend ?? []
  return {
    color: [palette[0]],
    tooltip: { trigger: 'axis' },
    grid: { left: 44, right: 20, top: 34, bottom: 30 },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r.date.slice(5)),
      boundaryGap: false,
      axisLine: { lineStyle: { color: 'rgba(126,180,235,0.3)' } },
      axisLabel: { color: AXIS_TEXT },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: AXIS_TEXT },
      splitLine: { lineStyle: { color: SPLIT_LINE } },
    },
    series: [
      {
        name: '诊断次数',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2 },
        areaStyle: { color: 'rgba(78, 166, 255, 0.22)' },
        data: rows.map((r) => r.count),
      },
    ],
  }
})

/**
 * 构建病虫害类型分布环形图（图例右置）。
 * @returns ECharts 配置
 */
const pieOption = computed<EChartsOption>(() => ({
  color: [...palette],
  tooltip: { trigger: 'item' },
  legend: {
    orient: 'vertical',
    right: 8,
    top: 'middle',
    icon: 'circle',
    itemWidth: 8,
    textStyle: { color: '#a9cbe8', fontSize: 12 },
  },
  series: [
    {
      name: '病虫害类型',
      type: 'pie',
      radius: ['48%', '72%'],
      center: ['36%', '50%'],
      itemStyle: { borderColor: '#0a1a2f', borderWidth: 2 },
      label: { show: false },
      data:
        piePanel.data.value?.disease_distribution.map((d) => ({ name: d.disease_name, value: d.count })) ?? [],
    },
  ],
}))

/**
 * 构建地块虫情密度与墒情组合图（柱 + 双轴折线）。
 * @returns ECharts 配置
 */
const densityOption = computed<EChartsOption>(() => {
  const rows = densityPanel.data.value?.plot_pest_density ?? []
  return {
    color: [palette[3], palette[1]],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: '#a9cbe8' } },
    grid: { left: 44, right: 44, top: 36, bottom: 30 },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r.plot_name),
      axisLine: { lineStyle: { color: 'rgba(126,180,235,0.3)' } },
      axisLabel: { color: AXIS_TEXT },
    },
    yAxis: [
      {
        type: 'value',
        name: '虫情密度',
        nameTextStyle: { color: AXIS_TEXT },
        axisLabel: { color: AXIS_TEXT },
        splitLine: { lineStyle: { color: SPLIT_LINE } },
      },
      {
        type: 'value',
        name: '墒情',
        nameTextStyle: { color: AXIS_TEXT },
        axisLabel: { color: AXIS_TEXT },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '虫情预警',
        type: 'bar',
        barWidth: 18,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        data: rows.map((r) => r.pest_alert_count),
      },
      {
        name: '土壤墒情',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2 },
        data: rows.map((r) => r.soil_moisture),
      },
    ],
  }
})

/* ================= 环境实况 / 设备指标 ================= */

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

/** 设备健康数据 */
const deviceHealth = computed(() => devicePanel.data.value?.device_health)

/** 设备与预警指标翻牌卡 */
const kpiCards = computed(() => {
  const health = deviceHealth.value
  return [
    { label: '总设备', value: health?.total ?? 0, tone: 'cyan' },
    { label: '在线', value: health?.online ?? 0, tone: 'green' },
    { label: '离线', value: health?.offline ?? 0, tone: 'red' },
    { label: '活跃预警', value: alertRows.value.length, tone: 'amber' },
  ]
})

/* ================= 中央主视觉热点 ================= */

/** 热点状态 */
type HotspotState = 'ok' | 'warn' | 'alert'

/** 单个热点 */
interface Hotspot {
  /** 地块名 */
  plotName: string
  /** 温度文本 */
  tempText: string
  /** 湿度文本 */
  humText: string
  /** 状态 */
  state: HotspotState
  /** 关联预警标题（无则空） */
  alertTitle: string
  /** 横向位置（%） */
  x: number
  /** 纵向位置（%） */
  y: number
}

/** 预置热点坐标（按地块顺序轮转，落在插画的大棚/田垄区域） */
const HOTSPOT_POS: ReadonlyArray<{ x: number; y: number }> = [
  { x: 16, y: 62 },
  { x: 47, y: 55 },
  { x: 80, y: 66 },
  { x: 32, y: 76 },
  { x: 63, y: 78 },
  { x: 12, y: 48 },
]

/**
 * 取第 i 个预置坐标（越界时轮转并兜底）。
 * @param i 序号
 * @returns 百分比坐标
 */
function hotspotPos(i: number): { x: number; y: number } {
  return HOTSPOT_POS[i % HOTSPOT_POS.length] ?? { x: 50, y: 50 }
}

/** 主视觉热点列表（环境实况 × 活跃预警叠加） */
const hotspots = computed<Hotspot[]>(() => {
  const rows = envRows.value
  const alerts = alertRows.value
  return rows.map((row, idx) => {
    const plotAlerts = alerts.filter(
      (a) => a.plot_id === row.plot_id || (a.plot_name !== undefined && a.plot_name === row.plot_name),
    )
    const critical = plotAlerts.some((a) => a.level === 'critical')
    const state: HotspotState = critical ? 'alert' : plotAlerts.length > 0 ? 'warn' : 'ok'
    const pos = hotspotPos(idx)
    return {
      plotName: row.plot_name,
      tempText: envText(row.temp, '℃'),
      humText: envText(row.humidity, '%'),
      state,
      alertTitle: plotAlerts[0]?.title ?? '',
      x: pos.x,
      y: pos.y,
    }
  })
})

/* ================= 预警跑马灯 ================= */

/** 预警流行 */
const alertRows = computed(() => alertPanel.data.value?.recent_alerts ?? [])

/** 跑马灯滚动行（两份拼接实现无缝循环） */
const marqueeRows = computed(() => [...alertRows.value, ...alertRows.value])

/**
 * 跑马灯单轮时长（按条数伸缩，保证可读速度）。
 * @returns CSS animation-duration 文本
 */
const marqueeDuration = computed(() => `${Math.max(alertRows.value.length * 5, 12)}s`)

/* ================= 生命周期 ================= */

onMounted(() => {
  updateScale()
  window.addEventListener('resize', updateScale)
  // 每秒更新时钟
  clockTimer = window.setInterval(() => {
    clockText.value = dayjs().format('YYYY-MM-DD HH:mm:ss dddd')
  }, 1000)
  // 60 秒定时刷新全部面板
  refreshTimer = window.setInterval(() => {
    for (const panel of allPanels) {
      if (!panel.loading.value) void panel.load()
    }
  }, 60000)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateScale)
  if (clockTimer !== undefined) window.clearInterval(clockTimer)
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div ref="viewport" class="bigscreen-viewport">
    <div class="bigscreen" :style="{ transform: `translate(-50%, -50%) scale(${scaleXY.x}, ${scaleXY.y})` }">
      <!-- 顶栏 -->
      <header class="top-bar">
        <div class="top-side left">DATA · 60s 自动刷新</div>
        <div class="top-title">
          <span class="title-line" />
          <h1>农场智能管护 · 监测大屏</h1>
          <span class="title-line right" />
        </div>
        <div class="top-side right">{{ clockText }}</div>
      </header>

      <!-- 主体三段式 -->
      <div class="layout">
        <!-- 左列 -->
        <div class="col">
          <TechPanel title="环境实况" class="h-env">
            <StateWrap :loading="envPanel.loading.value" :failed="envPanel.failed.value" :rows="4" @retry="envPanel.load()">
              <div v-if="envRows.length > 0" class="env-grid">
                <div v-for="row in envRows" :key="row.plot_id" class="env-card">
                  <div class="env-name">
                    {{ row.plot_name }}
                    <span class="env-type">{{ row.type === 'greenhouse' ? '大棚' : '露天' }}</span>
                  </div>
                  <div class="env-val">
                    <span class="label">温度</span>
                    <span class="num">{{ envText(row.temp, '℃') }}</span>
                  </div>
                  <div class="env-val">
                    <span class="label">湿度</span>
                    <span class="num">{{ envText(row.humidity, '%') }}</span>
                  </div>
                </div>
              </div>
              <el-empty v-else description="暂无数据" :image-size="50" />
            </StateWrap>
          </TechPanel>

          <TechPanel title="地块虫情密度与墒情" class="h-fill">
            <StateWrap :loading="densityPanel.loading.value" :failed="densityPanel.failed.value" :rows="4" @retry="densityPanel.load()">
              <EChart v-if="densityPanel.data.value" :option="densityOption" height="100%" class="chart-fill" />
              <el-empty v-else description="暂无数据" :image-size="50" />
            </StateWrap>
          </TechPanel>
        </div>

        <!-- 中央列 -->
        <div class="col center">
          <TechPanel title="园区监测总览" class="h-fill">
            <div class="stage">
              <!-- 2.5D 园区插画底图 -->
              <svg class="stage-bg" viewBox="0 0 800 340" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
                <rect x="0" y="0" width="800" height="340" fill="#12283f" />
                <path d="M0 120 Q140 70 300 108 T800 96 L800 0 L0 0 Z" fill="#16324e" />
                <path d="M0 150 Q200 112 420 140 T800 132 L800 340 L0 340 Z" fill="#17324a" />
                <rect x="0" y="176" width="800" height="164" fill="#1c3a2f" />
                <!-- 露天田垄 -->
                <g stroke="#26513c" stroke-width="6" opacity="0.85">
                  <line x1="560" y1="216" x2="790" y2="204" />
                  <line x1="560" y1="240" x2="790" y2="228" />
                  <line x1="560" y1="264" x2="790" y2="252" />
                  <line x1="560" y1="288" x2="790" y2="276" />
                  <line x1="560" y1="312" x2="790" y2="300" />
                </g>
                <!-- 大棚 1 -->
                <g>
                  <polygon points="60,236 150,196 240,236 240,296 60,296" fill="#0f2c44" />
                  <polygon points="60,236 150,196 240,236" fill="rgba(78,166,255,0.35)" />
                  <line x1="150" y1="196" x2="150" y2="296" stroke="rgba(78,166,255,0.4)" stroke-width="1.5" />
                  <line x1="105" y1="216" x2="105" y2="296" stroke="rgba(78,166,255,0.25)" stroke-width="1" />
                  <line x1="195" y1="216" x2="195" y2="296" stroke="rgba(78,166,255,0.25)" stroke-width="1" />
                </g>
                <!-- 大棚 2 -->
                <g>
                  <polygon points="270,226 380,178 490,226 490,298 270,298" fill="#0f2c44" />
                  <polygon points="270,226 380,178 490,226" fill="rgba(78,166,255,0.35)" />
                  <line x1="380" y1="178" x2="380" y2="298" stroke="rgba(78,166,255,0.4)" stroke-width="1.5" />
                  <line x1="325" y1="202" x2="325" y2="298" stroke="rgba(78,166,255,0.25)" stroke-width="1" />
                  <line x1="435" y1="202" x2="435" y2="298" stroke="rgba(78,166,255,0.25)" stroke-width="1" />
                </g>
                <!-- 大棚 3 -->
                <g>
                  <polygon points="520,244 610,204 700,244 700,300 520,300" fill="#0f2c44" />
                  <polygon points="520,244 610,204 700,244" fill="rgba(78,166,255,0.35)" />
                  <line x1="610" y1="204" x2="610" y2="300" stroke="rgba(78,166,255,0.4)" stroke-width="1.5" />
                  <line x1="565" y1="224" x2="565" y2="300" stroke="rgba(78,166,255,0.25)" stroke-width="1" />
                  <line x1="655" y1="224" x2="655" y2="300" stroke="rgba(78,166,255,0.25)" stroke-width="1" />
                </g>
                <!-- 道路 -->
                <path d="M0 316 L800 300 L800 322 L0 340 Z" fill="#122438" />
              </svg>

              <!-- 数据热点标注 -->
              <div
                v-for="(spot, idx) in hotspots"
                :key="idx"
                class="hotspot"
                :class="spot.state"
                :style="{ left: `${spot.x}%`, top: `${spot.y}%` }"
              >
                <span class="hs-dot" />
                <div class="hs-card">
                  <div class="hs-name">{{ spot.plotName }}</div>
                  <div class="hs-vals">
                    <span>{{ spot.tempText }}</span>
                    <span>{{ spot.humText }}</span>
                  </div>
                  <div v-if="spot.alertTitle" class="hs-alert">{{ spot.alertTitle }}</div>
                </div>
              </div>

              <!-- 图例 -->
              <div class="stage-legend">
                <span class="lg-item"><i class="lg-dot ok" />正常</span>
                <span class="lg-item"><i class="lg-dot warn" />预警</span>
                <span class="lg-item"><i class="lg-dot alert" />严重</span>
              </div>
            </div>
          </TechPanel>

          <!-- 设备与预警指标翻牌 -->
          <div class="kpi-row">
            <div v-for="card in kpiCards" :key="card.label" class="kpi-card" :class="card.tone">
              <div class="kpi-value">{{ card.value }}</div>
              <div class="kpi-label">{{ card.label }}</div>
            </div>
          </div>

          <!-- 实时预警跑马灯 -->
          <TechPanel title="实时预警流" class="h-marquee">
            <StateWrap :loading="alertPanel.loading.value" :failed="alertPanel.failed.value" :rows="2" @retry="alertPanel.load()">
              <div v-if="alertRows.length > 0" class="marquee">
                <div class="marquee-track" :style="{ animationDuration: marqueeDuration }">
                  <div v-for="(a, i) in marqueeRows" :key="`${a.id}-${i}`" class="marquee-item">
                    <span class="m-dot" :class="a.level" />
                    <span class="m-title">{{ a.title }}</span>
                    <span class="m-time">{{ formatDateTime(a.first_triggered_at) }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="marquee-empty">当前无活跃预警</div>
            </StateWrap>
          </TechPanel>
        </div>

        <!-- 右列 -->
        <div class="col">
          <TechPanel title="诊断趋势（近 14 天）" class="h-env">
            <StateWrap :loading="trendPanel.loading.value" :failed="trendPanel.failed.value" :rows="4" @retry="trendPanel.load()">
              <EChart v-if="trendPanel.data.value" :option="trendOption" height="100%" class="chart-fill" />
              <el-empty v-else description="暂无数据" :image-size="50" />
            </StateWrap>
          </TechPanel>

          <TechPanel title="病虫害类型分布" class="h-fill">
            <StateWrap :loading="piePanel.loading.value" :failed="piePanel.failed.value" :rows="4" @retry="piePanel.load()">
              <EChart v-if="piePanel.data.value" :option="pieOption" height="100%" class="chart-fill" />
              <el-empty v-else description="暂无数据" :image-size="50" />
            </StateWrap>
          </TechPanel>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ===== 视口与等比缩放画布 ===== */
.bigscreen-viewport {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #060f1c;
}

.bigscreen {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 1920px;
  height: 1080px;
  padding: 14px 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background:
    radial-gradient(ellipse at 50% -10%, rgba(30, 82, 138, 0.5) 0%, rgba(8, 22, 40, 0) 55%),
    radial-gradient(ellipse at bottom, #0c2036 0%, #081526 60%, #060f1c 100%);
  transform-origin: center center;
}

/* ===== 顶栏 ===== */
.top-bar {
  display: flex;
  align-items: center;
  height: 52px;
  flex: none;
}

.top-title {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 18px;
  justify-content: center;
}

.top-title h1 {
  margin: 0;
  color: #e6f3ff;
  font-size: 26px;
  font-weight: 600;
  letter-spacing: 6px;
  text-shadow: 0 0 18px rgba(78, 166, 255, 0.55);
  white-space: nowrap;
}

.title-line {
  width: 240px;
  height: 8px;
  background:
    linear-gradient(90deg, rgba(53, 208, 186, 0) 0%, #35d0ba 60%, rgba(53, 208, 186, 0) 100%);
  clip-path: polygon(0 40%, 100% 0, 100% 100%, 0 60%);
}

.title-line.right {
  transform: scaleX(-1);
}

.top-side {
  width: 280px;
  color: #6d95bd;
  font-size: 15px;
  letter-spacing: 1px;
}

.top-side.right {
  text-align: right;
  color: #9fc4e8;
  font-variant-numeric: tabular-nums;
}

/* ===== 三段式布局 ===== */
.layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 440px 1fr 440px;
  gap: 14px;
}

/* 面板内三态包装统一撑满，保证 EChart height:100% 有参照 */
.bigscreen :deep(.state-wrap) {
  height: 100%;
}

.h-env :deep(.state-wrap),
.h-marquee :deep(.state-wrap) {
  display: flex;
  flex-direction: column;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  min-width: 0;
}

.h-env {
  flex: none;
  height: 420px;
}

.h-fill {
  flex: 1;
  min-height: 0;
}

.h-marquee {
  flex: none;
  height: 150px;
}

.chart-fill {
  flex: 1;
  min-height: 0;
}

/* ===== 环境实况 KPI ===== */
.env-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: 1fr;
  gap: 12px;
}

.env-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  background: rgba(78, 166, 255, 0.07);
  border: 1px solid rgba(78, 166, 255, 0.15);
  border-radius: 8px;
  padding: 12px 14px;
}

.env-name {
  color: #d7ecff;
  font-size: 15px;
  margin-bottom: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-type {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border: 1px solid rgba(53, 208, 186, 0.5);
  border-radius: 3px;
  color: #35d0ba;
  font-size: 11px;
  line-height: 16px;
  vertical-align: 1px;
}

.env-val {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 2px 0;
}

.env-val .label {
  color: #6d95bd;
  font-size: 13px;
}

.env-val .num {
  color: #35d0ba;
  font-size: 19px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* ===== 中央主视觉 ===== */
.stage {
  position: relative;
  flex: 1;
  min-height: 0;
  border: 1px solid rgba(78, 166, 255, 0.18);
  border-radius: 6px;
  overflow: hidden;
}

.stage-bg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.hotspot {
  position: absolute;
  transform: translate(-50%, -50%);
  z-index: 3;
}

.hs-dot {
  display: block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.85);
  animation: hs-pulse 2s ease-out infinite;
}

.hotspot.ok .hs-dot {
  background: #35d0ba;
}

.hotspot.warn .hs-dot {
  background: #fac775;
}

.hotspot.alert .hs-dot {
  background: #f0655f;
}

@keyframes hs-pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(255, 255, 255, 0.45);
  }
  70% {
    box-shadow: 0 0 0 12px rgba(255, 255, 255, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(255, 255, 255, 0);
  }
}

.hs-card {
  position: absolute;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  min-width: 150px;
  background: rgba(8, 24, 42, 0.88);
  border: 1px solid rgba(78, 166, 255, 0.35);
  border-radius: 5px;
  padding: 8px 10px;
}

.hotspot.warn .hs-card {
  border-color: rgba(250, 199, 117, 0.55);
}

.hotspot.alert .hs-card {
  border-color: rgba(240, 101, 95, 0.65);
}

.hs-name {
  color: #d7ecff;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}

.hs-vals {
  display: flex;
  gap: 12px;
  color: #35d0ba;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.hs-alert {
  margin-top: 4px;
  color: #f0958f;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 190px;
}

.stage-legend {
  position: absolute;
  right: 10px;
  bottom: 8px;
  display: flex;
  gap: 14px;
  padding: 4px 10px;
  background: rgba(8, 24, 42, 0.7);
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

/* ===== 设备指标翻牌 ===== */
.kpi-row {
  flex: none;
  height: 112px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.kpi-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background:
    linear-gradient(180deg, rgba(20, 48, 82, 0.6) 0%, rgba(10, 26, 47, 0.9) 100%);
  border: 1px solid rgba(78, 166, 255, 0.22);
  border-radius: 8px;
}

.kpi-value {
  font-size: 40px;
  font-weight: 600;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.kpi-label {
  color: #6d95bd;
  font-size: 14px;
  letter-spacing: 2px;
}

.kpi-card.cyan .kpi-value {
  color: #4ea6ff;
}

.kpi-card.green .kpi-value {
  color: #35d0ba;
}

.kpi-card.red .kpi-value {
  color: #f0655f;
}

.kpi-card.amber .kpi-value {
  color: #fac775;
}

/* ===== 预警跑马灯 ===== */
.marquee {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  overflow: hidden;
}

.marquee-track {
  display: flex;
  width: max-content;
  animation: marquee-scroll linear infinite;
}

.marquee-item {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-right: 56px;
  white-space: nowrap;
}

.m-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.m-dot.info {
  background: #4ea6ff;
}

.m-dot.warning {
  background: #fac775;
}

.m-dot.critical {
  background: #f0655f;
  animation: hs-pulse 1.6s ease-out infinite;
}

.m-title {
  color: #cfe3f5;
  font-size: 15px;
}

.m-time {
  color: #6d95bd;
  font-size: 13px;
}

@keyframes marquee-scroll {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-50%);
  }
}

.marquee-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6d95bd;
  font-size: 14px;
}
</style>
