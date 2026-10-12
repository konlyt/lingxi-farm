<script setup lang="ts">
/**
 * 文件说明：农事日历页（17）。
 * 地块选择、el-calendar 月视图自定义单元格标注农事节点、upcoming 提醒列表。
 */
import { computed, ref, watch } from 'vue'
import dayjs from 'dayjs'
import { getPlots } from '@/api/plots'
import { getCalendarEvents, getCalendarReminders } from '@/api/calendar'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import { formatDate } from '@/utils/format'
import type { CalendarEvent } from '@/types/farm'

/** 地块列表异步状态 */
const { loading: plotsLoading, failed: plotsFailed, data: plots, load: loadPlots } = useAsyncData(() => getPlots())

/** 选中的地块 ID（空为全部） */
const activePlotId = ref<number | undefined>(undefined)

/** 当前日历月份（YYYY-MM） */
const currentMonth = ref(dayjs().format('YYYY-MM'))

/** 日历选中日期（v-model） */
const currentDate = ref<Date>(new Date())

/** 农事事件异步状态 */
const { loading: eventsLoading, failed: eventsFailed, data: events, load: loadEvents } = useAsyncData(() =>
  getCalendarEvents({ plot_id: activePlotId.value, month: currentMonth.value }),
)

/** 提醒列表异步状态 */
const { loading: remindersLoading, failed: remindersFailed, data: reminders, load: loadReminders } = useAsyncData(() =>
  getCalendarReminders({ plot_id: activePlotId.value }),
)

/** 地块选项 */
const plotOptions = computed(() => plots.value ?? [])

/** 事件类型 → 颜色映射（含后端实际类型 pestcontrol/farmwork） */
const typeColors: Record<string, string> = {
  prune: '#67c23a',
  fertilize: '#e6a23c',
  irrigate: '#409eff',
  harvest: '#f56c6c',
  plant: '#9a6fe0',
  pesticide: '#36c9c9',
  pestcontrol: '#e6a23c',
  farmwork: '#909399',
}

/**
 * 获取某日的农事事件列表。
 * @param day 日期字符串（YYYY-MM-DD）
 * @returns 当日事件列表
 */
function eventsForDay(day: string): CalendarEvent[] {
  return (events.value ?? []).filter((e) => e.date === day)
}

/**
 * 事件类型颜色（未知类型回退默认色）。
 * @param type 事件类型
 * @returns 颜色值
 */
function typeColor(type: string): string {
  return typeColors[type] ?? '#409eff'
}

// 切换地块重载事件与提醒
watch(activePlotId, () => {
  void loadEvents()
  void loadReminders()
})

// 月份切换重载事件
watch(currentDate, (d) => {
  currentMonth.value = dayjs(d).format('YYYY-MM')
  void loadEvents()
})

// 进入页面加载地块列表
void loadPlots()
</script>

<template>
  <div class="page">
    <div class="page-card">
      <div class="head-row">
        <h3 class="page-card-title" style="margin: 0">农事日历</h3>
        <el-select v-model="activePlotId" placeholder="全部地块" clearable style="width: 200px">
          <el-option v-for="p in plotOptions" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </div>

      <StateWrap :loading="plotsLoading" :failed="plotsFailed" :rows="4" @retry="loadPlots">
        <el-empty v-if="plotOptions.length === 0" description="地块无作物档案，请先完善档案">
          <el-button type="primary" @click="$router.push('/plots')">去完善</el-button>
        </el-empty>
        <template v-else>
          <!-- 月视图日历 -->
          <StateWrap :loading="eventsLoading" :failed="eventsFailed" :rows="6" @retry="loadEvents">
            <el-calendar v-model="currentDate">
              <template #date-cell="{ data }">
                <div class="cal-cell">
                  <span class="cal-day">{{ Number(data.day.slice(8)) }}</span>
                  <div
                    v-for="(ev, idx) in eventsForDay(data.day)"
                    :key="idx"
                    class="cal-event"
                    :style="{ background: typeColor(ev.type) }"
                    :title="`${ev.plot_name} · ${ev.title}`"
                  >
                    {{ ev.title }}
                  </div>
                </div>
              </template>
            </el-calendar>
          </StateWrap>

          <!-- upcoming 提醒 -->
          <h3 class="page-card-title">即将到来</h3>
          <StateWrap :loading="remindersLoading" :failed="remindersFailed" :rows="3" @retry="loadReminders">
            <el-empty v-if="!reminders || reminders.length === 0" description="暂无 upcoming 提醒" :image-size="60" />
            <el-table v-else :data="reminders" stripe size="small">
              <el-table-column label="日期" width="130">
                <template #default="{ row }">{{ formatDate(row.date) }}</template>
              </el-table-column>
              <el-table-column prop="title" label="农事事项" min-width="160" />
              <el-table-column prop="plot_name" label="地块" width="120" />
              <el-table-column label="剩余" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.days_until <= 3 ? 'danger' : 'info'">
                    {{ row.days_until <= 0 ? '今天' : `${row.days_until} 天后` }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </StateWrap>
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

.cal-cell {
  min-height: 56px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cal-day {
  font-size: 13px;
}

.cal-event {
  font-size: 11px;
  color: #fff;
  border-radius: 4px;
  padding: 1px 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.el-calendar-table .el-calendar-day) {
  padding: 4px;
}
</style>
