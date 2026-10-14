<script setup lang="ts">
/**
 * 文件说明：农场总览页（02）。
 * 顶部 KPI 条（纯前端聚合现有 overview 数据）、采收禁令横幅、地块实况头图卡片、
 * 今日待办、最新预警滚动条、天气条与快捷入口；30 秒自动轮询。
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { getOverview } from '@/api/overview'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import { useAuthStore } from '@/stores/auth'
import { formatMonthDay, plotTypeLabel, sourceLabel, formatConfidence, alertLevelTag } from '@/utils/format'
import type { HarvestBanner } from '@/types/farm'

const router = useRouter()
/** 认证状态（member 隐藏写操作入口） */
const auth = useAuthStore()

/** 总览数据异步状态 */
const { loading, failed, data, load } = useAsyncData(getOverview)

/**
 * 按地块合并采收禁令角标（同一地块多条禁令时展示最早到期日并折叠计数）。
 * 修复缺陷 D-10：此前同一地块多条禁令重复平铺展示，信息冗余。
 */
const mergedBanners = computed<Array<HarvestBanner & { extra: number }>>(() => {
  const map = new Map<number, HarvestBanner & { extra: number }>()
  for (const banner of data.value?.harvest_banners ?? []) {
    const current = map.get(banner.plot_id)
    if (current === undefined) {
      map.set(banner.plot_id, { ...banner, extra: 0 })
    } else {
      current.extra += 1
      // 展示最早到期的禁令日期
      if (banner.ban_until < current.ban_until) current.ban_until = banner.ban_until
    }
  }
  return [...map.values()]
})

/** KPI 条：全部由现有 overview 字段前端聚合，不新增接口 */
const kpis = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    { key: 'plots', label: '地块 / 棚室', value: d.plot_cards.length, tone: 'green' },
    { key: 'alerts', label: '活跃预警', value: d.latest_alerts.length, tone: 'red' },
    { key: 'todos', label: '今日待办', value: d.today_todos.length, tone: 'amber' },
    { key: 'bans', label: '采收禁令', value: mergedBanners.value.length, tone: 'gray' },
  ]
})

/** 轮询定时器句柄 */
let pollTimer: number | undefined

/**
 * 读取地块平铺环境快照的展示文本（值 + 内置单位）。
 * @param env 平铺环境快照 {temp, humidity, soil_moisture}
 * @param key 指标键名
 * @returns 如「28℃」；缺失返回 '-'
 */
function metricText(env: { temp: number | null; humidity: number | null; soil_moisture: number | null } | null | undefined, key: 'temp' | 'humidity' | 'soil_moisture'): string {
  const value = env?.[key]
  if (value === null || value === undefined) return '-'
  const units: Record<string, string> = { temp: '℃', humidity: '%RH', soil_moisture: '%' }
  return `${value}${units[key] ?? ''}`
}

/**
 * 跳转到地块实况详情。
 * @param id 地块 ID
 */
function goPlot(id: number): void {
  void router.push(`/plot-live/${id}`)
}

onMounted(() => {
  // 30 秒轮询刷新总览数据（加载中时跳过）
  pollTimer = window.setInterval(() => {
    if (!loading.value) void load()
  }, 30000)
})

onUnmounted(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="page">
    <StateWrap :loading="loading" :failed="failed" :rows="8" @retry="load()">
      <template v-if="data">
        <!-- 无地块空态：引导创建档案 -->
        <div v-if="data.plot_cards.length === 0" class="page-card empty-guide">
          <el-empty description="还没有地块/棚室档案">
            <el-button type="primary" @click="router.push('/plots')">先创建你的第一块地/棚</el-button>
          </el-empty>
        </div>

        <template v-else>
          <!-- KPI 条 -->
          <div class="kpi-row">
            <div v-for="kpi in kpis" :key="kpi.key" class="kpi-card" :class="`tone-${kpi.tone}`">
              <div class="kpi-value tnum">{{ kpi.value }}</div>
              <div class="kpi-label">{{ kpi.label }}</div>
            </div>
          </div>

          <!-- 采收禁令横幅（合并后） -->
          <div v-if="mergedBanners.length > 0" class="ban-banner">
            <el-icon class="ban-icon" :size="20"><Warning /></el-icon>
            <div class="ban-content">
              <div class="ban-title">采收禁令提示</div>
              <div class="ban-list">
                <span v-for="banner in mergedBanners" :key="banner.plot_id" class="ban-item">
                  {{ banner.plot_name }} · {{ formatMonthDay(banner.ban_until) }} 前不可采收<template v-if="banner.extra > 0">（另有 {{ banner.extra }} 条）</template>
                </span>
              </div>
            </div>
          </div>

          <!-- 今日天气条 -->
          <div class="page-card weather-bar">
            <el-icon color="#e6a23c"><Sunny /></el-icon>
            <span class="weather-text">
              {{ data.weather.date }} ·
              <template v-if="data.weather.items.length > 0">
                <span v-for="(w, idx) in data.weather.items" :key="w.plot_id" class="weather-item">
                  {{ w.plot_name }} {{ w.condition }} {{ w.temp_low }}~{{ w.temp_high }}℃{{ w.precipitation_mm > 0 ? ` 降水${w.precipitation_mm}mm` : '' }}<template v-if="idx < data.weather.items.length - 1">；</template>
                </span>
              </template>
              <template v-else>暂无天气数据</template>
            </span>
          </div>

          <!-- 地块实况头图卡片网格 -->
          <div class="plot-grid">
            <div v-for="card in data.plot_cards" :key="card.id" class="plot-card" @click="goPlot(card.id)">
              <div class="plot-cover" :class="`cover-${card.type}`">
                <el-image v-if="card.latest_image" :src="card.latest_image.url" fit="cover" class="cover-img">
                  <template #error>
                    <div class="cover-fallback">图片加载失败</div>
                  </template>
                </el-image>
                <div v-else class="cover-fallback">
                  <el-icon :size="28"><Picture /></el-icon>
                  <span>暂无巡检照片</span>
                </div>
                <span class="cover-type" :class="`type-${card.type}`">{{ plotTypeLabel(card.type) }}</span>
              </div>
              <div class="plot-body">
                <div class="plot-head">
                  <span class="plot-name">{{ card.name }}</span>
                  <el-tag v-if="card.has_active_restriction" size="small" type="warning" effect="dark">采收禁令</el-tag>
                </div>
                <div class="plot-crop">{{ card.crop_name ?? '未种植' }}<template v-if="card.growth_stage"> · {{ card.growth_stage }}</template></div>
                <div class="plot-env">
                  <span class="env-metric">温度 <b class="tnum">{{ metricText(card.latest_env, 'temp') }}</b></span>
                  <span class="env-metric">湿度 <b class="tnum">{{ metricText(card.latest_env, 'humidity') }}</b></span>
                  <span class="env-metric">墒情 <b class="tnum">{{ metricText(card.latest_env, 'soil_moisture') }}</b></span>
                </div>
                <div v-if="card.latest_image" class="plot-ai">
                  <span class="ai-tag">AI：{{ card.latest_image.ai_label }}</span>
                  <span class="ai-conf">{{ formatConfidence(card.latest_image.confidence) }} · {{ sourceLabel(card.latest_image.source) }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="overview-row">
            <!-- 今日待办 -->
            <div class="page-card todo-card">
              <h3 class="page-card-title">今日待办</h3>
              <el-empty v-if="data.today_todos.length === 0" description="今日暂无待办" :image-size="60" />
              <ul v-else class="todo-list">
                <li v-for="(todo, idx) in data.today_todos" :key="idx" class="todo-item">
                  <b>{{ todo.plot_name }} · {{ todo.title }}</b>：{{ todo.content }}
                </li>
              </ul>
            </div>

            <!-- 最新预警滚动条 -->
            <div class="page-card alert-card">
              <h3 class="page-card-title">最新预警</h3>
              <el-empty v-if="data.latest_alerts.length === 0" description="今日无预警" :image-size="60" />
              <div v-else class="alert-scroll">
                <div
                  v-for="alert in data.latest_alerts"
                  :key="alert.id"
                  class="alert-row"
                  @click="router.push(`/alerts/${alert.id}`)"
                >
                  <el-tag size="small" :type="alertLevelTag(alert.level).type">{{ alertLevelTag(alert.level).text }}</el-tag>
                  <span class="alert-title">{{ alert.title }}</span>
                  <span class="text-muted">{{ alert.occurrence_count }} 次</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 快捷入口 -->
          <div class="page-card quick-entry">
            <el-button v-if="auth.isOwner" type="primary" @click="router.push('/diagnosis/upload')">
              <el-icon><Camera /></el-icon>&nbsp;上传诊断
            </el-button>
            <el-button type="success" @click="router.push('/chat')">
              <el-icon><ChatDotRound /></el-icon>&nbsp;知识问答
            </el-button>
          </div>
        </template>
      </template>
    </StateWrap>
  </div>
</template>

<style scoped>
/* ===== KPI 条 ===== */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}

.kpi-card {
  background: var(--farm-surface);
  border: 1px solid var(--farm-border-light);
  border-radius: var(--farm-radius);
  padding: 14px 18px;
  box-shadow: var(--farm-shadow-sm);
  position: relative;
  overflow: hidden;
}

.kpi-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
}

.kpi-card.tone-green::before { background: var(--farm-primary-500); }
.kpi-card.tone-red::before { background: var(--farm-danger); }
.kpi-card.tone-amber::before { background: var(--farm-accent); }
.kpi-card.tone-gray::before { background: var(--farm-text-secondary); }

.kpi-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--farm-text-primary);
  line-height: 1.2;
}

.kpi-label {
  margin-top: 2px;
  font-size: 12px;
  color: var(--farm-text-secondary);
}

/* ===== 采收禁令横幅 ===== */
.ban-banner {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: linear-gradient(135deg, #fff7e6 0%, #fdf2d8 100%);
  border: 1px solid #f5d98b;
  border-left: 4px solid var(--farm-accent);
  border-radius: var(--farm-radius);
  padding: 12px 16px;
  margin-bottom: 16px;
}

.ban-icon {
  color: var(--farm-accent);
  margin-top: 2px;
}

.ban-title {
  font-size: 13px;
  font-weight: 600;
  color: #8a6d1a;
  margin-bottom: 4px;
}

.ban-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  font-size: 12px;
  color: #6b5516;
}

/* ===== 天气条 ===== */
.weather-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
}

.weather-text {
  font-size: 14px;
  color: var(--farm-text-regular);
}

.weather-item {
  margin-right: 4px;
}

/* ===== 地块头图卡片 ===== */
.plot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.plot-card {
  background: var(--farm-surface);
  border: 1px solid var(--farm-border-light);
  border-radius: var(--farm-radius);
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  box-shadow: var(--farm-shadow-sm);
}

.plot-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--farm-shadow-md);
}

.plot-cover {
  position: relative;
  height: 150px;
  background: var(--farm-primary-100);
}

.cover-img {
  width: 100%;
  height: 100%;
  display: block;
}

.cover-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--farm-primary-300);
  font-size: 12px;
  background: linear-gradient(135deg, #e6f2ea 0%, #d4e8dc 100%);
}

.cover-type {
  position: absolute;
  top: 10px;
  right: 10px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  backdrop-filter: blur(4px);
}

.cover-type.type-greenhouse {
  background: rgba(46, 125, 79, 0.85);
  color: #fff;
}

.cover-type.type-open {
  background: rgba(180, 140, 60, 0.85);
  color: #fff;
}

.plot-body {
  padding: 12px 14px 14px;
}

.plot-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.plot-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--farm-text-primary);
}

.plot-crop {
  font-size: 13px;
  color: var(--farm-text-regular);
  margin: 6px 0 8px;
}

.plot-env {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  font-size: 12px;
  color: var(--farm-text-secondary);
  padding-top: 8px;
  border-top: 1px dashed var(--farm-border-light);
}

.env-metric b {
  color: var(--farm-text-primary);
  font-weight: 600;
}

.plot-ai {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

.ai-tag {
  font-size: 12px;
  color: var(--farm-accent);
  font-weight: 600;
}

.ai-conf {
  font-size: 11px;
  color: var(--farm-text-secondary);
}

/* ===== 待办 / 预警 ===== */
.overview-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.todo-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.todo-item {
  padding: 8px 0;
  font-size: 13px;
  color: var(--farm-text-regular);
  border-bottom: 1px dashed var(--farm-border-light);
  line-height: 1.5;
}

.todo-item b {
  color: var(--farm-text-primary);
}

.todo-item::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--farm-primary-500);
  margin-right: 8px;
  vertical-align: middle;
}

.alert-scroll {
  max-height: 180px;
  overflow-y: auto;
}

.alert-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--farm-border-light);
  cursor: pointer;
  font-size: 13px;
}

.alert-row:hover .alert-title {
  color: var(--farm-primary-500);
}

.alert-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--farm-text-regular);
}

.quick-entry {
  display: flex;
  gap: 12px;
}

.empty-guide {
  padding: 40px 16px;
}

@media (max-width: 767px) {
  .overview-row {
    grid-template-columns: 1fr;
  }
  .kpi-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
