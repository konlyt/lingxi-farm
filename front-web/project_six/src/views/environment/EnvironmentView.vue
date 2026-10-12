<script setup lang="ts">
/**
 * 文件说明：大棚环境监控与调控建议页（12）。
 * 棚室切换、实时环境卡（越限红色高亮）、24h/7d 趋势、越限报警记录表、
 * 12h 调控建议卡（展开依据）与底部「系统暂不直接控制设备」提示。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getPlots } from '@/api/plots'
import { getAlarmRecords, getRealtimeEnv, getEnvTrend } from '@/api/environment'
import { getEnvironmentAdvice } from '@/api/advice'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import EChart from '@/components/EChart.vue'
import { formatDateTime, metricLabel, plotTypeLabel } from '@/utils/format'
import type { EChartsOption } from 'echarts'
import type { EnvTrend } from '@/types/farm'

const router = useRouter()

/** 展示的环境指标键名与顺序 */
const metricKeys = ['temp', 'humidity', 'light', 'soil_moisture'] as const

/** 地块列表异步状态 */
const { loading: plotsLoading, failed: plotsFailed, data: plots, load: loadPlots } = useAsyncData(() => getPlots())

/** 当前棚室 ID */
const activePlotId = ref<number | undefined>(undefined)

/** 仅展示大棚类型地块（无大棚时回退展示全部并提示） */
const greenhousePlots = computed(() => {
  const list = plots.value ?? []
  const gh = list.filter((p) => p.type === 'greenhouse')
  return gh.length > 0 ? gh : list
})

/** 是否使用了露天回退展示 */
const fallbackToAll = computed(() => {
  const list = plots.value ?? []
  return list.length > 0 && !list.some((p) => p.type === 'greenhouse')
})

/** 实时环境异步状态（activePlotId 就绪后由 watch 触发加载） */
const { loading: envLoading, failed: envFailed, data: realtime, load: loadEnv } = useAsyncData(
  () => getRealtimeEnv({ plot_id: activePlotId.value ?? 0 }),
  false,
)

/** 报警记录异步状态（后端 plot_id 必填） */
const { loading: alarmLoading, failed: alarmFailed, data: alarms, load: loadAlarms } = useAsyncData(
  () => getAlarmRecords({ plot_id: activePlotId.value ?? 0 }),
  false,
)

/** 调控建议异步状态 */
const { loading: adviceLoading, failed: adviceFailed, data: envAdvice, load: loadAdvice } = useAsyncData(
  () => getEnvironmentAdvice({ plot_id: activePlotId.value ?? 0 }),
  false,
)

/** 趋势时间范围 */
const range = ref<'24h' | '7d'>('24h')
/** 趋势数据 */
const trend = ref<EnvTrend | null>(null)
/** 趋势加载中 */
const trendLoading = ref(false)
/** 趋势加载失败 */
const trendFailed = ref(false)

/** 最后上报时间（后端在 metrics 各项内，取 temp 项展示） */
const lastReportedAt = computed(() => realtime.value?.metrics?.temp?.last_reported_at ?? null)

/**
 * 构建趋势图配置。
 * @param data 趋势数据
 * @returns ECharts 配置
 */
function buildTrendOption(data: EnvTrend): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['温度', '湿度', '土壤墒情'], top: 0 },
    grid: { left: 48, right: 24, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: data.times },
    yAxis: { type: 'value' },
    series: [
      { name: '温度', type: 'line', smooth: true, showSymbol: false, data: data.series.temp },
      { name: '湿度', type: 'line', smooth: true, showSymbol: false, data: data.series.humidity },
      { name: '土壤墒情', type: 'line', smooth: true, showSymbol: false, data: data.series.soil_moisture },
    ],
  }
}

/** 趋势图配置 */
const trendOption = computed<EChartsOption | null>(() => (trend.value ? buildTrendOption(trend.value) : null))

/**
 * 加载趋势数据。
 */
async function loadTrend(): Promise<void> {
  if (!activePlotId.value) return
  trendLoading.value = true
  trendFailed.value = false
  try {
    trend.value = await getEnvTrend({ plot_id: activePlotId.value, range: range.value })
  } catch {
    trendFailed.value = true
  } finally {
    trendLoading.value = false
  }
}

// 地块列表加载后默认选中第一个棚室
watch(
  greenhousePlots,
  (list) => {
    if (list.length > 0 && activePlotId.value === undefined) {
      activePlotId.value = list[0]?.id
    }
  },
  { immediate: true },
)

// 切换棚室重新加载所有区块
watch(activePlotId, () => {
  void loadEnv()
  void loadAlarms()
  void loadAdvice()
  void loadTrend()
})

// 时间范围切换重载趋势
watch(range, () => {
  void loadTrend()
})

// 进入页面加载地块列表
void loadPlots()
</script>

<template>
  <div class="page">
    <div class="page-card">
      <div class="head-row">
        <h3 class="page-card-title" style="margin: 0">大棚环境监控</h3>
        <el-select v-model="activePlotId" placeholder="选择棚室" style="width: 200px">
          <el-option v-for="p in greenhousePlots" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </div>

      <el-alert
        v-if="fallbackToAll"
        title="暂无大棚类型地块，当前展示全部地块环境数据"
        type="info"
        show-icon
        :closable="false"
        class="fallback-tip"
      />

      <StateWrap :loading="plotsLoading" :failed="plotsFailed" :rows="4" @retry="loadPlots">
        <el-empty
          v-if="greenhousePlots.length === 0"
          description="未接入传感器，请先创建棚室并接入设备"
        >
          <el-button type="primary" @click="router.push('/devices')">前往设备管理</el-button>
        </el-empty>

        <template v-else>
          <!-- 实时环境卡 -->
          <StateWrap :loading="envLoading" :failed="envFailed" :rows="3" @retry="loadEnv">
            <div class="env-grid">
              <div
                v-for="key in metricKeys"
                :key="key"
                class="env-item"
                :class="{ exceeded: realtime?.metrics[key]?.exceeded }"
              >
                <span class="env-label">{{ metricLabel(key) }}</span>
                <span class="env-value">
                  {{ realtime?.metrics[key]?.value != null ? `${realtime?.metrics[key]?.value}${realtime?.metrics[key]?.unit ?? ''}` : '-' }}
                </span>
                <el-tag v-if="realtime?.metrics[key]?.exceeded" type="danger" size="small">越限</el-tag>
              </div>
            </div>
            <div class="text-muted" style="margin-top: 8px">
              最后上报：{{ formatDateTime(lastReportedAt) }}
              <span v-if="lastReportedAt === null">（传感器离线，展示最后有效数据）</span>
            </div>
          </StateWrap>

          <!-- 趋势图 -->
          <div class="trend-block">
            <div class="head-row">
              <h3 class="page-card-title" style="margin: 0">环境趋势</h3>
              <el-radio-group v-model="range" size="small">
                <el-radio-button value="24h">24 小时</el-radio-button>
                <el-radio-button value="7d">7 天</el-radio-button>
              </el-radio-group>
            </div>
            <div v-if="trendLoading" v-loading="true" class="chart-loading" />
            <div v-else-if="trendFailed" class="state-failed">
              <el-alert title="趋势数据加载失败" type="error" show-icon :closable="false" />
              <el-button type="primary" plain size="small" @click="loadTrend">重试</el-button>
            </div>
            <EChart v-else-if="trendOption" :option="trendOption" height="300px" />
            <el-empty v-else description="暂无趋势数据" :image-size="60" />
          </div>

          <!-- 越限报警记录（threshold 为 {max, min} 对象，按 direction 取对应边界） -->
          <StateWrap :loading="alarmLoading" :failed="alarmFailed" :rows="3" @retry="loadAlarms">
            <h3 class="page-card-title">越限报警记录</h3>
            <el-empty v-if="!alarms || alarms.length === 0" description="暂无越限记录" :image-size="60" />
            <el-table v-else :data="alarms" stripe size="small">
              <el-table-column label="指标" width="100">
                <template #default="{ row }">{{ metricLabel(String(row.metric)) }}</template>
              </el-table-column>
              <el-table-column label="越限值 / 阈值" width="150">
                <template #default="{ row }">
                  {{ row.value }}{{ row.unit ?? '' }} / {{ row.direction === 'low' ? row.threshold?.min : row.threshold?.max }}
                </template>
              </el-table-column>
              <el-table-column label="触发时间" width="160">
                <template #default="{ row }">{{ formatDateTime(row.triggered_at) }}</template>
              </el-table-column>
              <el-table-column label="恢复时间">
                <template #default="{ row }">
                  <span v-if="row.recovered_at">{{ formatDateTime(row.recovered_at) }}</span>
                  <el-tag v-else size="small" type="danger">未恢复</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </StateWrap>

          <!-- 调控建议 -->
          <StateWrap :loading="adviceLoading" :failed="adviceFailed" :rows="3" @retry="loadAdvice">
            <h3 class="page-card-title">未来 12 小时调控建议</h3>
            <el-empty v-if="!envAdvice || envAdvice.items.length === 0" description="暂无调控建议" :image-size="60" />
            <div v-else class="advice-list">
              <div v-for="(item, idx) in envAdvice.items" :key="idx" class="advice-card">
                <div class="advice-time">{{ item.time_range }}</div>
                <div class="advice-action">{{ item.action }}</div>
                <el-collapse class="basis-collapse">
                  <el-collapse-item title="依据" :name="String(idx)">
                    <div class="basis-text">{{ item.reason }}</div>
                  </el-collapse-item>
                </el-collapse>
              </div>
            </div>
          </StateWrap>

          <!-- 底部提示条 -->
          <el-alert
            title="建议仅提示操作，系统暂不直接控制设备（通风/保温/降湿请人工执行）"
            type="warning"
            show-icon
            :closable="false"
            class="bottom-tip"
          />
        </template>
      </StateWrap>
    </div>
  </div>
</template>

<style scoped>
.head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}

.fallback-tip {
  margin-bottom: 12px;
}

.env-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.env-item {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.env-item.exceeded {
  background: #fef0f0;
}

.env-label {
  font-size: 12px;
  color: #909399;
}

.env-value {
  font-size: 20px;
  font-weight: 600;
}

.env-item.exceeded .env-value {
  color: #f56c6c;
}

.trend-block {
  margin-top: 20px;
}

.chart-loading {
  height: 300px;
}

.advice-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.advice-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px;
}

.advice-time {
  font-size: 12px;
  color: #909399;
}

.advice-action {
  font-size: 14px;
  font-weight: 600;
  margin: 6px 0;
}

.basis-text {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
}

.bottom-tip {
  margin-top: 16px;
}
</style>
