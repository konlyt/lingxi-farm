<script setup lang="ts">
/**
 * 文件说明：预警中心页（09）。
 * 状态 Tab（未解决/已解决）、类型筛选、预警列表（类型图标、等级、已升级标记、触发次数、首次触发时间）、
 * 每日汇总说明条与确认解决操作（member 隐藏）。
 */
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Cloudy, Connection, Odometer, Warning } from '@element-plus/icons-vue'
import { getAlerts, resolveAlert } from '@/api/alerts'
import StateWrap from '@/components/StateWrap.vue'
import { useAuthStore } from '@/stores/auth'
import { confirmAction } from '@/utils/confirm'
import { alertLevelTag, formatDateTime } from '@/utils/format'
import { markRaw } from 'vue'
import type { Component } from 'vue'
import type { AlertItem } from '@/types/farm'

const router = useRouter()
const auth = useAuthStore()

/** 预警类型 → 图标组件映射 */
const typeIconMap: Record<string, Component> = {
  pest: markRaw(Warning),
  env: markRaw(Odometer),
  weather: markRaw(Cloudy),
  device_offline: markRaw(Connection),
}

/** 预警类型筛选选项 */
const typeOptions = [
  { value: 'pest', label: '病虫害' },
  { value: 'env', label: '环境越限' },
  { value: 'weather', label: '气象灾害' },
  { value: 'device_offline', label: '设备离线' },
]

/**
 * 预警类型转中文标签。
 * @param type 类型键名
 * @returns 中文标签
 */
function typeLabel(type: string): string {
  return typeOptions.find((t) => t.value === type)?.label ?? type
}

/** 当前状态 Tab：active 未解决 / resolved 已解决（后端字符串枚举） */
const activeStatus = ref<'active' | 'resolved'>('active')
/** 类型筛选 */
const type = ref<string | undefined>(undefined)
/** 页码 */
const page = ref(1)

/** 列表状态 */
const items = ref<AlertItem[]>([])
const total = ref(0)
const loading = ref(false)
const failed = ref(false)
/** 解决操作进行中 */
const resolving = ref(false)

/**
 * 表格行 class：按等级/状态注入左侧色条样式。
 * @param param0 当前行数据
 * @returns 行 class
 */
function rowClassName({ row }: { row: AlertItem }): string {
  if (row.status === 'resolved') return 'alert-row-resolved'
  if (row.level === 'high') return 'alert-row-high'
  if (row.level === 'medium') return 'alert-row-medium'
  return ''
}

/**
 * 加载预警列表。
 */
async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const res = await getAlerts({ status: activeStatus.value, type: type.value, page: page.value })
    items.value = res.items
    total.value = res.total
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

/**
 * 确认解决预警（二次确认）。
 * @param row 预警行
 */
async function handleResolve(row: AlertItem): Promise<void> {
  const ok = await confirmAction(`确定将「${row.title}」标记为已解决吗？解决后关闭聚合窗口。`)
  if (!ok) return
  resolving.value = true
  try {
    await resolveAlert(row.id)
    ElMessage.success('已标记解决')
    await load()
  } finally {
    resolving.value = false
  }
}

/**
 * 跳转预警详情。
 * @param row 预警行
 */
function goDetail(row: AlertItem): void {
  void router.push(`/alerts/${row.id}`)
}

// Tab/类型/页码变化刷新
watch([activeStatus, type], () => {
  page.value = 1
  void load()
})
watch(page, () => {
  void load()
})

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page">
    <div class="page-card">
      <div class="toolbar">
        <el-tabs v-model="activeStatus" class="status-tabs">
          <el-tab-pane label="未解决" name="active" />
          <el-tab-pane label="已解决" name="resolved" />
        </el-tabs>
        <el-select v-model="type" placeholder="全部类型" clearable style="width: 150px">
          <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
      </div>

      <!-- 每日汇总说明条 -->
      <el-alert
        title="聚合说明：同一地块同一病例未解决期间自动合并计数，每日仅汇总推送一条服务号消息"
        type="info"
        show-icon
        :closable="false"
        class="summary-tip"
      />

      <StateWrap :loading="loading" :failed="failed" :rows="7" @retry="load()">
        <el-empty v-if="items.length === 0" description="当前无预警" />
        <template v-else>
          <el-table :data="items" stripe :row-class-name="rowClassName" @row-click="goDetail">
            <el-table-column label="类型" width="120">
              <template #default="{ row }">
                <div class="type-cell">
                  <el-icon :size="16" color="#e6a23c"><component :is="typeIconMap[row.type] ?? Warning" /></el-icon>
                  <span>{{ typeLabel(row.type) }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="等级" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="alertLevelTag(row.level).type">{{ alertLevelTag(row.level).text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
            <el-table-column prop="plot_name" label="地块" width="110" />
            <el-table-column label="触发" width="90">
              <template #default="{ row }">{{ row.occurrence_count }} 次</template>
            </el-table-column>
            <el-table-column label="首次触发" width="150">
              <template #default="{ row }">{{ formatDateTime(row.first_triggered_at) }}</template>
            </el-table-column>
            <el-table-column label="升级" width="90">
              <template #default="{ row }">
                <el-tag v-if="row.is_upgraded" size="small" type="danger" effect="dark">已升级</el-tag>
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>
            <el-table-column v-if="auth.isOwner && activeStatus === 'active'" label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button link type="success" :loading="resolving" @click.stop="handleResolve(row as AlertItem)">确认解决</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pager">
            <el-pagination
              v-model:current-page="page"
              :total="total"
              :page-size="10"
              layout="total, prev, pager, next"
              background
            />
          </div>
        </template>
      </StateWrap>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.status-tabs {
  flex: 1;
}

.summary-tip {
  margin-bottom: 14px;
}

.type-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pager {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}

:deep(.el-table__row) {
  cursor: pointer;
}

/* 预警行等级色条：用 inset 阴影在单元格左侧画一条色条，不破坏表格布局 */
:deep(.el-table__row.alert-row-high td:first-child) {
  box-shadow: inset 3px 0 0 var(--farm-danger);
}
:deep(.el-table__row.alert-row-medium td:first-child) {
  box-shadow: inset 3px 0 0 var(--farm-accent);
}
:deep(.el-table__row.alert-row-resolved td:first-child) {
  box-shadow: inset 3px 0 0 var(--farm-text-secondary);
  opacity: 0.75;
}

/* 高优未解决预警呼吸点（在等级列 Tag 前由表格行样式自然呈现，这里给行一个淡底） */
:deep(.el-table__row.alert-row-high) {
  background: rgba(217, 83, 79, 0.04);
}
:deep(.el-table__row.alert-row-medium) {
  background: rgba(245, 158, 11, 0.04);
}
</style>
