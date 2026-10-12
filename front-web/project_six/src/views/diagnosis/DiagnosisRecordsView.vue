<script setup lang="ts">
/**
 * 文件说明：诊断记录列表页（06）。
 * 筛选栏（地块/来源/时间范围/置信度档位）、记录表格（缩略图、置信度进度条、来源与状态标签、低置信度黄色标识）、分页与空态。
 */
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getPlots } from '@/api/plots'
import { listDiagnosisRecords } from '@/api/diagnosis'
import StateWrap from '@/components/StateWrap.vue'
import { formatDateTime, sourceLabel, statusTag } from '@/utils/format'
import type { DiagnosisRecord } from '@/types/farm'

const route = useRoute()
const router = useRouter()

/** 地块下拉选项 */
const plotOptions = ref<Array<{ id: number; name: string }>>([])

/** 筛选条件 */
const filters = reactive({
  plot_id: undefined as number | undefined,
  source: undefined as string | undefined,
  range: null as [string, string] | null,
  level: undefined as string | undefined,
})

/** 页码与每页条数 */
const page = ref(1)
const pageSize = ref(10)
/** 总条数 */
const total = ref(0)
/** 记录列表 */
const items = ref<DiagnosisRecord[]>([])
/** 加载状态 */
const loading = ref(false)
/** 失败状态 */
const failed = ref(false)

/**
 * 加载记录列表（组合筛选条件与分页）。
 */
async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const res = await listDiagnosisRecords({
      plot_id: filters.plot_id,
      source: filters.source,
      start: filters.range?.[0],
      end: filters.range?.[1],
      level: filters.level,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = res.items
    total.value = res.total
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

/**
 * 筛选条件变化：重置页码并重新加载。
 */
function onFilterChange(): void {
  page.value = 1
  void load()
}

// 筛选/分页变化自动刷新
watch(
  () => [filters.plot_id, filters.source, filters.range, filters.level],
  () => onFilterChange(),
)
watch([page, pageSize], () => {
  void load()
})

/**
 * 跳转诊断详情。
 * @param row 记录行
 */
function goDetail(row: DiagnosisRecord): void {
  void router.push(`/diagnosis/${row.id}`)
}

onMounted(async () => {
  // 支持从其他页面携带 plot_id 查询参数进入
  const q = route.query.plot_id
  if (typeof q === 'string' && q !== '') {
    const n = Number(q)
    if (!Number.isNaN(n)) filters.plot_id = n
  }
  try {
    const plots = await getPlots()
    plotOptions.value = plots.map((p) => ({ id: p.id, name: p.name }))
  } catch {
    /* 地块选项加载失败不阻塞列表 */
  }
  void load()
})
</script>

<template>
  <div class="page">
    <div class="page-card">
      <h3 class="page-card-title">诊断记录</h3>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-select v-model="filters.plot_id" placeholder="全部地块" clearable style="width: 160px">
          <el-option v-for="p in plotOptions" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-select v-model="filters.source" placeholder="全部来源" clearable style="width: 140px">
          <el-option label="设备采集" value="device" />
          <el-option label="手动上传" value="manual" />
        </el-select>
        <el-date-picker
          v-model="filters.range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 260px"
        />
        <el-select v-model="filters.level" placeholder="置信度档位" clearable style="width: 140px">
          <el-option label="高置信度" value="high" />
          <el-option label="低置信度" value="low" />
        </el-select>
      </div>

      <StateWrap :loading="loading" :failed="failed" :rows="8" @retry="load()">
        <el-empty v-if="items.length === 0" description="暂无诊断记录，调整筛选或去上传">
          <el-button type="primary" @click="router.push('/diagnosis/upload')">去上传</el-button>
        </el-empty>
        <el-table v-else :data="items" stripe @row-click="goDetail">
          <el-table-column label="缩略图" width="90">
            <template #default="{ row }">
              <el-image
                :src="row.thumb_url"
                fit="cover"
                class="rec-thumb"
                :preview-src-list="[row.thumb_url]"
                preview-teleported
                @click.stop
              />
            </template>
          </el-table-column>
          <el-table-column prop="disease_name" label="诊断名称" min-width="130">
            <template #default="{ row }">{{ row.disease_name || '识别中' }}</template>
          </el-table-column>
          <el-table-column label="置信度" width="150">
            <template #default="{ row }">
              <el-progress
                :percentage="Math.round((row.confidence ?? 0) * 1000) / 10"
                :stroke-width="8"
                :color="(row.confidence ?? 0) >= 0.85 ? '#67c23a' : '#e6a23c'"
              />
            </template>
          </el-table-column>
          <el-table-column label="来源" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.source === 'device' ? 'primary' : 'success'">
                {{ sourceLabel(row.source) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="plot_name" label="地块" width="110" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="statusTag(row.status).type"
                :effect="(row.confidence ?? 1) < 0.85 && row.result_level === 'low' ? 'dark' : 'light'"
                :class="{ 'low-conf-mark': (row.confidence ?? 1) < 0.85 }"
              >
                {{ row.case_status_display ?? statusTag(row.status).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            background
          />
        </div>
      </StateWrap>
    </div>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

.rec-thumb {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  display: block;
}

.pager {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}

.low-conf-mark {
  color: #e6a23c;
}

:deep(.el-table__row) {
  cursor: pointer;
}
</style>
