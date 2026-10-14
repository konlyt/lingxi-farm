<script setup lang="ts">
/**
 * 文件说明：农场总览页（02）。
 * 采收禁令角标区、地块实况卡片网格、今日待办、最新预警滚动条、今日天气条与快捷入口；30 秒自动轮询。
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
          <!-- 采收禁令角标区（同地块多条禁令合并展示最早到期日） -->
          <div v-if="mergedBanners.length > 0" class="page-card banner-zone">
            <el-tag
              v-for="banner in mergedBanners"
              :key="banner.plot_id"
              type="warning"
              effect="dark"
              size="large"
              class="banner-tag"
            >
              {{ banner.plot_name }} · {{ formatMonthDay(banner.ban_until) }}前不可采收<template v-if="banner.extra > 0">（另有 {{ banner.extra }} 条禁令）</template>
            </el-tag>
          </div>

          <!-- 今日天气条（按地块展示） -->
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

          <!-- 地块实况卡片网格 -->
          <div class="plot-grid">
            <div v-for="card in data.plot_cards" :key="card.id" class="plot-card" @click="goPlot(card.id)">
              <div class="plot-card-head">
                <span class="plot-name">{{ card.name }}</span>
                <el-tag size="small" :type="card.type === 'greenhouse' ? 'primary' : 'success'">
                  {{ plotTypeLabel(card.type) }}
                </el-tag>
                <el-tag v-if="card.has_active_restriction" size="small" type="warning" effect="dark">
                  采收禁令
                </el-tag>
              </div>
              <div class="plot-crop">{{ card.crop_name ?? '未种植' }}<template v-if="card.growth_stage"> · {{ card.growth_stage }}</template></div>
              <div class="plot-env">
                <span>温度 {{ metricText(card.latest_env, 'temp') }}</span>
                <span>湿度 {{ metricText(card.latest_env, 'humidity') }}</span>
                <span>墒情 {{ metricText(card.latest_env, 'soil_moisture') }}</span>
              </div>
              <div v-if="card.latest_image" class="plot-photo">
                <el-image :src="card.latest_image.url" fit="cover" class="photo-thumb">
                  <template #error>
                    <div class="photo-placeholder">图片加载失败</div>
                  </template>
                </el-image>
                <div class="photo-label">
                  <span class="ai-tag">AI：{{ card.latest_image.ai_label }}</span>
                  <span class="ai-conf">{{ formatConfidence(card.latest_image.confidence) }} · {{ sourceLabel(card.latest_image.source) }}</span>
                </div>
              </div>
              <div v-else class="plot-photo-empty">暂无巡检照片</div>
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
.banner-zone {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.banner-tag {
  border-radius: 6px;
}

.weather-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
}

.weather-text {
  font-size: 14px;
  color: #303133;
}

.weather-item {
  margin-right: 4px;
}

.plot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.plot-card {
  background: #fff;
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  transition: box-shadow 0.2s;
  border: 1px solid #e4e7ed;
}

.plot-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.plot-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.plot-name {
  font-weight: 600;
  font-size: 15px;
}

.plot-crop {
  font-size: 13px;
  color: #606266;
  margin: 6px 0;
}

.plot-env {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: #606266;
  margin-bottom: 8px;
}

.plot-photo {
  position: relative;
}

.photo-thumb {
  width: 100%;
  height: 110px;
  border-radius: 6px;
  display: block;
}

.photo-placeholder {
  width: 100%;
  height: 110px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  font-size: 12px;
  background: #f5f7fa;
}

.photo-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
}

.ai-tag {
  font-size: 12px;
  color: #e6a23c;
  font-weight: 600;
}

.ai-conf {
  font-size: 11px;
  color: #909399;
}

.plot-photo-empty {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
  font-size: 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

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
  padding: 6px 0;
  font-size: 13px;
  color: #303133;
  border-bottom: 1px dashed #ebeef5;
}

.todo-item::before {
  content: '·';
  color: #409eff;
  font-weight: 700;
  margin-right: 6px;
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
  border-bottom: 1px dashed #ebeef5;
  cursor: pointer;
  font-size: 13px;
}

.alert-row:hover .alert-title {
  color: #409eff;
}

.alert-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
}
</style>
