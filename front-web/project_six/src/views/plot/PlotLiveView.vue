<script setup lang="ts">
/**
 * 文件说明：地块/棚室实况详情页（03）。
 * 顶部信息与采收角标、环境卡（越限红色高亮）、趋势图 24h/7d 切换、巡检照片流（AI 标注）、关联入口与水肥建议摘要。
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getPlot } from '@/api/plots'
import { getRealtimeEnv, getEnvTrend } from '@/api/environment'
import { getWaterFertilizerAdvice } from '@/api/advice'
import { listDiagnosisRecords } from '@/api/diagnosis'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import EChart from '@/components/EChart.vue'
import {
  formatConfidence,
  formatDateTime,
  formatMonthDay,
  metricLabel,
  plotTypeLabel,
  sourceLabel,
} from '@/utils/format'
import type { EChartsOption } from 'echarts'
import type { EnvTrend, MetricValue } from '@/types/farm'

const route = useRoute()
const router = useRouter()

/** 地块 ID（来自路由参数） */
const plotId = Number(route.params.id)

/** 展示的环境指标键名与顺序 */
const metricKeys = ['temp', 'humidity', 'light', 'soil_moisture'] as const

/** 地块详情异步状态 */
const { loading, failed, data: plot, load } = useAsyncData(() => getPlot(plotId))
/** 实时环境异步状态 */
const { loading: envLoading, failed: envFailed, data: realtime, load: loadEnv } = useAsyncData(() => getRealtimeEnv({ plot_id: plotId }))
/** 巡检照片流（取该地块最近诊断记录的缩略图） */
const { loading: photosLoading, failed: photosFailed, data: records, load: loadPhotos } = useAsyncData(
  () => listDiagnosisRecords({ plot_id: plotId, page: 1, page_size: 8 }),
)
/** 水肥建议摘要 */
const { loading: adviceLoading, failed: adviceFailed, data: advice, load: loadAdvice } = useAsyncData(
  () => getWaterFertilizerAdvice({ plot_id: plotId }),
)

/** 趋势时间范围：24h / 7d */
const range = ref<'24h' | '7d'>('24h')
/** 趋势数据 */
const trend = ref<EnvTrend | null>(null)
/** 趋势加载中 */
const trendLoading = ref(false)
/** 趋势加载失败 */
const trendFailed = ref(false)

/** 生效中的采收禁令角标（后端字段 harvest_restrictions） */
const banners = computed(() => plot.value?.harvest_restrictions ?? [])

/** 最后上报时间（后端在 metrics 各项内，取 temp 项展示） */
const lastReportedAt = computed(() => realtime.value?.metrics?.temp?.last_reported_at ?? null)

/** 水肥建议数据体（后端双层 data 包装） */
const adviceBody = computed(() => advice.value?.data ?? null)

/**
 * 构建趋势图配置项。
 * @param data 趋势数据
 * @returns ECharts 配置
 */
function buildTrendOption(data: EnvTrend): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['温度', '湿度', '土壤墒情', '光照'], top: 0 },
    grid: { left: 48, right: 56, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: data.times },
    yAxis: [
      { type: 'value', name: '℃ / %' },
      { type: 'value', name: 'klx', position: 'right' },
    ],
    series: [
      { name: '温度', type: 'line', smooth: true, showSymbol: false, data: data.series.temp },
      { name: '湿度', type: 'line', smooth: true, showSymbol: false, data: data.series.humidity },
      { name: '土壤墒情', type: 'line', smooth: true, showSymbol: false, data: data.series.soil_moisture },
      { name: '光照', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 1, data: data.series.light ?? [] },
    ],
  }
}

/** 趋势图配置（无数据时为 null 不渲染图表） */
const trendOption = computed<EChartsOption | null>(() => (trend.value ? buildTrendOption(trend.value) : null))

/**
 * 加载趋势数据（按当前时间范围）。
 */
async function loadTrend(): Promise<void> {
  trendLoading.value = true
  trendFailed.value = false
  try {
    trend.value = await getEnvTrend({ plot_id: plotId, range: range.value })
  } catch {
    trendFailed.value = true
  } finally {
    trendLoading.value = false
  }
}

// 时间范围切换时重新加载趋势
watch(range, () => {
  void loadTrend()
})
void loadTrend()

onUnmounted(() => {
  /* 页面卸载无需额外清理（轮询由总览页管理） */
})
</script>

<template>
  <div class="page">
    <StateWrap :loading="loading" :failed="failed" :rows="8" @retry="load()">
      <template v-if="plot">
        <!-- 顶部信息 -->
        <div class="page-card head-card">
          <div class="head-left">
            <h2 class="head-title">{{ plot.name }}</h2>
            <el-tag size="small" :type="plot.type === 'greenhouse' ? 'primary' : 'success'">{{ plotTypeLabel(plot.type) }}</el-tag>
            <el-tag v-for="banner in banners" :key="banner.id" type="warning" effect="dark" size="small">
              {{ banner.pesticide_name }}：{{ formatMonthDay(banner.ban_until) }}前不可采收
            </el-tag>
          </div>
          <div class="head-crop">
            {{ plot.crop_name ?? '未种植' }}
            <template v-if="plot.growth_stage"> · {{ plot.growth_stage }}</template>
          </div>
        </div>

        <!-- 环境卡片 -->
        <StateWrap :loading="envLoading" :failed="envFailed" :rows="3" @retry="loadEnv">
          <div class="page-card">
            <div class="env-head">
              <h3 class="page-card-title">实时环境</h3>
              <span class="text-muted">最后上报：{{ formatDateTime(lastReportedAt) }}</span>
            </div>
            <div v-if="realtime" class="env-grid">
              <div
                v-for="key in metricKeys"
                :key="key"
                class="env-item"
                :class="{ exceeded: realtime.metrics[key]?.exceeded }"
              >
                <span class="env-label">{{ metricLabel(key) }}</span>
                <span class="env-value">
                  {{ realtime.metrics[key]?.value != null ? `${realtime.metrics[key]?.value}${realtime.metrics[key]?.unit ?? ''}` : '-' }}
                </span>
                <el-tag v-if="realtime.metrics[key]?.exceeded" type="danger" size="small">越限</el-tag>
              </div>
            </div>
            <el-empty v-else description="暂未接入传感器，数据缺失时将展示上一有效数据" :image-size="60" />
          </div>
        </StateWrap>

        <!-- 趋势图 -->
        <div class="page-card">
          <div class="env-head">
            <h3 class="page-card-title">环境趋势</h3>
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
          <EChart v-else-if="trendOption" :option="trendOption" height="320px" />
          <el-empty v-else description="暂无趋势数据" :image-size="60" />
        </div>

        <!-- 巡检照片流 -->
        <StateWrap :loading="photosLoading" :failed="photosFailed" :rows="3" @retry="loadPhotos">
          <div class="page-card">
            <h3 class="page-card-title">巡检照片流</h3>
            <el-empty
              v-if="!records || records.items.length === 0"
              description="暂无巡检照片，上传一张试试"
              :image-size="60"
            >
              <el-button type="primary" @click="router.push('/diagnosis/upload')">去上传</el-button>
            </el-empty>
            <div v-else class="photo-grid">
              <div v-for="rec in records.items" :key="rec.id" class="photo-item">
                <el-image
                  :src="rec.thumb_url"
                  fit="cover"
                  class="photo-img"
                  :preview-src-list="[rec.thumb_url]"
                  preview-teleported
                />
                <div class="photo-overlay">
                  <span class="photo-disease">{{ rec.disease_name || '识别中' }}</span>
                  <span class="photo-conf">{{ formatConfidence(rec.confidence) }}</span>
                  <el-tag size="small" :type="rec.source === 'device' ? 'primary' : 'success'" effect="dark">
                    {{ sourceLabel(rec.source) }}
                  </el-tag>
                </div>
              </div>
            </div>
          </div>
        </StateWrap>

        <div class="live-row">
          <!-- 关联入口 -->
          <div class="page-card link-card">
            <h3 class="page-card-title">关联信息</h3>
            <el-button plain type="warning" @click="router.push('/alerts')">查看相关预警</el-button>
            <el-button plain type="primary" @click="router.push(`/diagnosis/records?plot_id=${plotId}`)">
              查看诊断记录
            </el-button>
          </div>

          <!-- 水肥建议摘要（irrigate/fertilize 为整段文本） -->
          <StateWrap :loading="adviceLoading" :failed="adviceFailed" :rows="2" @retry="loadAdvice">
            <div class="page-card advice-card">
              <h3 class="page-card-title">水肥建议摘要</h3>
              <template v-if="adviceBody && adviceBody.items.length > 0">
                <div class="advice-item">
                  <span class="advice-label">浇水</span>
                  <span>{{ adviceBody.items[0]?.irrigate ?? '-' }}</span>
                </div>
                <div class="advice-item">
                  <span class="advice-label">施肥</span>
                  <span>{{ adviceBody.items[0]?.fertilize ?? '-' }}</span>
                </div>
                <el-button link type="primary" @click="router.push('/advice')">查看 7 天完整建议 →</el-button>
              </template>
              <el-empty v-else description="暂无水肥建议" :image-size="60" />
            </div>
          </StateWrap>
        </div>
      </template>
    </StateWrap>
  </div>
</template>

<style scoped>
.head-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.head-title {
  font-size: 18px;
  margin: 0;
}

.head-crop {
  color: #606266;
  font-size: 14px;
}

.env-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
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

.chart-loading {
  height: 320px;
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.photo-item {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
}

.photo-img {
  width: 100%;
  height: 130px;
  display: block;
}

.photo-overlay {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 11px;
  padding: 4px 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.photo-disease {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.live-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.link-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
}

.advice-item {
  display: flex;
  gap: 8px;
  font-size: 13px;
  margin-bottom: 8px;
}

.advice-label {
  color: #909399;
  flex-shrink: 0;
}

@media (max-width: 767px) {
  .live-row {
    grid-template-columns: 1fr;
  }
}
</style>
