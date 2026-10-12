<script setup lang="ts">
/**
 * 文件说明：预警详情页（10）。
 * 预警标题/类型/等级/地块跳转、现场照片（取自 content.latest_image_url）、
 * 病情时间线（content 为各类型快照对象，提取关键字段展示）、
 * 设备离线预警跳转设备管理、确认解决操作（member 隐藏）。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getAlertDetail, resolveAlert } from '@/api/alerts'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import { useAuthStore } from '@/stores/auth'
import { confirmAction } from '@/utils/confirm'
import { alertLevelTag, formatDateTime, metricLabel } from '@/utils/format'
import type { AlertContent } from '@/types/farm'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/** 预警 ID（路由参数） */
const alertId = Number(route.params.id)

/** 详情异步状态 */
const { loading, failed, data: alert, load } = useAsyncData(() => getAlertDetail(alertId))

/** 时间线是否展开 */
const timelineExpanded = ref(false)
/** 解决操作进行中 */
const resolving = ref(false)

/** 现场照片（pest 类型预警的 latest_image_url，可空） */
const photos = computed<string[]>(() => {
  const url = alert.value?.content?.latest_image_url
  return url ? [url] : []
})

/** 时间线展示条目（收起时仅显示前 3 条） */
const visibleTimeline = computed(() => {
  const list = alert.value?.timeline ?? []
  return timelineExpanded.value ? list : list.slice(0, 3)
})

/**
 * 将时间线事件快照对象转为可读文本（按预警类型提取关键字段）。
 * @param content 事件快照对象
 * @returns 展示文本
 */
function timelineText(content: AlertContent): string {
  if (content.description) return content.description
  if (content.metric) {
    const bound = content.direction === 'low' ? content.threshold?.min : content.threshold?.max
    return `${metricLabel(String(content.metric))} ${content.value}${content.unit ?? ''}（${content.direction === 'low' ? '低于下限' : '高于上限'} ${bound}）`
  }
  if (content.device_no) return `设备 ${content.device_no} 最近心跳：${formatDateTime(content.last_heartbeat_at)}`
  const entries = Object.entries(content).filter(([, v]) => v !== null && v !== undefined)
  return entries.length > 0 ? entries.map(([k, v]) => `${k}: ${String(v)}`).join('；') : '-'
}

/**
 * 详情正文摘要（按预警类型提取 content 关键字段）。
 * @returns 展示文本
 */
const contentSummary = computed<string>(() => {
  const content = alert.value?.content
  if (!content) return ''
  return timelineText(content)
})

/**
 * 确认解决预警。
 */
async function handleResolve(): Promise<void> {
  const ok = await confirmAction('确定将该预警标记为已解决吗？')
  if (!ok) return
  resolving.value = true
  try {
    await resolveAlert(alertId)
    ElMessage.success('已标记解决')
    await router.push('/alerts')
  } finally {
    resolving.value = false
  }
}
</script>

<template>
  <div class="page">
    <StateWrap :loading="loading" :failed="failed" :rows="8" @retry="load()">
      <template v-if="alert">
        <!-- 基本信息 -->
        <div class="page-card">
          <div class="head-row">
            <h2 class="head-title">{{ alert.title }}</h2>
            <el-tag size="small" :type="alertLevelTag(alert.level).type">{{ alertLevelTag(alert.level).text }}级</el-tag>
            <el-tag v-if="alert.is_upgraded" size="small" type="danger" effect="dark">已升级</el-tag>
            <el-tag size="small" :type="alert.status === 'resolved' ? 'info' : 'warning'">
              {{ alert.status === 'resolved' ? '已解决' : '未解决' }}
            </el-tag>
          </div>
          <div class="meta-row">
            <span class="meta-item">
              地块：<el-link type="primary" @click="router.push('/plots')">{{ alert.plot_name }}</el-link>
            </span>
            <span class="meta-item">首次触发：{{ formatDateTime(alert.first_triggered_at) }}</span>
            <span class="meta-item">累计触发：{{ alert.occurrence_count }} 次</span>
          </div>
          <p class="content-text">{{ contentSummary }}</p>
        </div>

        <div class="detail-row">
          <!-- 现场照片 -->
          <div class="page-card">
            <h3 class="page-card-title">现场照片</h3>
            <el-empty v-if="photos.length === 0" description="暂无现场照片" :image-size="60" />
            <div v-else class="img-grid">
              <el-image
                v-for="(img, idx) in photos"
                :key="idx"
                :src="img"
                fit="cover"
                class="photo"
                :preview-src-list="photos"
                preview-teleported
              />
            </div>
          </div>

          <!-- 病情时间线 -->
          <div class="page-card">
            <div class="head-row">
              <h3 class="page-card-title" style="margin: 0">病情变化时间线</h3>
              <el-button v-if="alert.timeline.length > 3" link type="primary" @click="timelineExpanded = !timelineExpanded">
                {{ timelineExpanded ? '收起' : `展开全部（${alert.timeline.length}）` }}
              </el-button>
            </div>
            <el-empty v-if="alert.timeline.length === 0" description="暂无时间线记录" :image-size="60" />
            <el-timeline v-else class="timeline">
              <el-timeline-item
                v-for="(ev, idx) in visibleTimeline"
                :key="idx"
                :timestamp="formatDateTime(ev.time)"
                placement="top"
              >
                <div class="tl-event">{{ ev.event }}</div>
                <div class="tl-content">{{ timelineText(ev.content) }}</div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </div>

        <!-- 关联与操作 -->
        <div class="page-card action-card">
          <el-button v-if="alert.type === 'device_offline'" plain @click="router.push('/devices')">前往设备管理</el-button>
          <el-button v-if="alert.type === 'pest' && alert.related_task_id" plain type="primary" @click="router.push(`/diagnosis/${alert.related_task_id}`)">
            查看关联诊断
          </el-button>
          <el-button v-else-if="alert.type === 'pest' && alert.content?.plan_id" plain type="info" disabled>
            关联防治方案 #{{ alert.content.plan_id }}
          </el-button>
          <el-button v-if="auth.isOwner && alert.status === 'active'" type="success" :loading="resolving" @click="handleResolve">
            确认解决
          </el-button>
        </div>
      </template>
    </StateWrap>
  </div>
</template>

<style scoped>
.head-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.head-title {
  font-size: 18px;
  margin: 0;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin: 12px 0;
  font-size: 13px;
  color: #606266;
}

.content-text {
  font-size: 14px;
  color: #303133;
  line-height: 1.7;
  margin: 0;
}

.detail-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.img-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
}

.photo {
  width: 100%;
  height: 120px;
  border-radius: 8px;
  display: block;
}

.timeline {
  padding-left: 4px;
  margin-top: 12px;
}

.tl-event {
  font-size: 13px;
  font-weight: 600;
}

.tl-content {
  font-size: 12px;
  color: #606266;
  margin-top: 2px;
}

.action-card {
  display: flex;
  gap: 10px;
}

@media (max-width: 767px) {
  .detail-row {
    grid-template-columns: 1fr;
  }
}
</style>
