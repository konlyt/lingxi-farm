<script setup lang="ts">
/**
 * 文件说明：案例库管理页（08）。
 * 统计头（总/待确认/已确认/已纠正/病种样本量）、三状态 Tab、案例列表、行内确认/纠正（member 隐藏）、待确认批量确认。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { batchConfirmCases, confirmCase, correctCase, getCaseStats, getCases } from '@/api/cases'
import StateWrap from '@/components/StateWrap.vue'
import { useAsyncData } from '@/composables/useAsyncData'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime, sourceLabel, statusTag } from '@/utils/format'
import type { CaseItem } from '@/types/farm'

const auth = useAuthStore()

/** 统计头异步状态 */
const { loading: statsLoading, failed: statsFailed, data: stats, load: loadStats } = useAsyncData(getCaseStats)

/** 当前状态 Tab */
const activeTab = ref<'pending' | 'confirmed' | 'corrected'>('pending')
/** 病种筛选 */
const category = ref<string | undefined>(undefined)
/** 页码 */
const page = ref(1)
const pageSize = ref(10)

/** 列表状态 */
const items = ref<CaseItem[]>([])
const total = ref(0)
const loading = ref(false)
const failed = ref(false)

/** 已勾选的待确认案例 */
const selected = ref<CaseItem[]>([])

/** 纠正弹窗 */
const correctDialog = reactive({ visible: false, id: 0, name: '', note: '' })
/** 操作进行中 */
const operating = ref(false)

/** 病种筛选选项（后端 by_category 为 {病种名: 数量} 对象，转换为选项数组） */
const categoryOptions = computed<Array<{ category: string; count: number }>>(() => {
  const map = stats.value?.by_category ?? {}
  return Object.entries(map).map(([category, count]) => ({ category, count }))
})

/**
 * 加载案例列表。
 */
async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const res = await getCases({ status: activeTab.value, category: category.value, page: page.value, page_size: pageSize.value })
    items.value = res.items
    total.value = res.total
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

/**
 * 确认单条案例正确。
 * @param row 案例行
 */
async function handleConfirm(row: CaseItem): Promise<void> {
  operating.value = true
  try {
    await confirmCase(row.id)
    ElMessage.success('已确认')
    await Promise.all([load(), loadStats()])
  } finally {
    operating.value = false
  }
}

/**
 * 打开纠正弹窗。
 * @param row 案例行
 */
function openCorrect(row: CaseItem): void {
  correctDialog.id = row.id
  correctDialog.name = ''
  correctDialog.note = ''
  correctDialog.visible = true
}

/**
 * 提交纠正。
 */
async function submitCorrect(): Promise<void> {
  if (correctDialog.name.trim() === '') {
    ElMessage.warning('请输入正确病名')
    return
  }
  operating.value = true
  try {
    await correctCase(correctDialog.id, { final_disease_name: correctDialog.name.trim(), note: correctDialog.note })
    ElMessage.success('已纠正')
    correctDialog.visible = false
    await Promise.all([load(), loadStats()])
  } finally {
    operating.value = false
  }
}

/**
 * 批量确认勾选的待确认案例。
 */
async function handleBatchConfirm(): Promise<void> {
  if (selected.value.length === 0) {
    ElMessage.warning('请先勾选案例')
    return
  }
  operating.value = true
  try {
    await batchConfirmCases(selected.value.map((c) => c.id))
    ElMessage.success(`已批量确认 ${selected.value.length} 条`)
    selected.value = []
    await Promise.all([load(), loadStats()])
  } finally {
    operating.value = false
  }
}

// Tab/病种切换重置页码并刷新
watch([activeTab, category], () => {
  page.value = 1
  selected.value = []
  void load()
})
watch([page, pageSize], () => {
  void load()
})

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page">
    <!-- 统计头 -->
    <StateWrap :loading="statsLoading" :failed="statsFailed" :rows="2" @retry="loadStats">
      <div class="page-card stat-bar">
        <div class="stat-item">
          <span class="stat-num">{{ stats?.total ?? 0 }}</span>
          <span class="stat-label">总案例数</span>
        </div>
        <div class="stat-item">
          <span class="stat-num warn">{{ stats?.pending ?? 0 }}</span>
          <span class="stat-label">待确认</span>
        </div>
        <div class="stat-item">
          <span class="stat-num ok">{{ stats?.confirmed ?? 0 }}</span>
          <span class="stat-label">已确认</span>
        </div>
        <div class="stat-item">
          <span class="stat-num">{{ stats?.corrected ?? 0 }}</span>
          <span class="stat-label">已纠正</span>
        </div>
        <div class="stat-category">
          <span class="stat-label">病种样本量：</span>
          <el-tag v-for="c in categoryOptions" :key="c.category" size="small" class="cat-tag">
            {{ c.category }} · {{ c.count }}
          </el-tag>
          <span v-if="categoryOptions.length === 0" class="text-muted">暂无样本</span>
        </div>
      </div>
    </StateWrap>

    <div class="page-card">
      <div class="toolbar">
        <el-tabs v-model="activeTab" class="stat-tabs">
          <el-tab-pane label="待确认" name="pending" />
          <el-tab-pane label="已确认" name="confirmed" />
          <el-tab-pane label="已纠正" name="corrected" />
        </el-tabs>
        <el-select v-model="category" placeholder="按病种筛选" clearable style="width: 160px">
          <el-option v-for="c in categoryOptions" :key="c.category" :label="c.category" :value="c.category" />
        </el-select>
      </div>

      <!-- 批量操作（仅待确认 Tab 且 owner） -->
      <div v-if="auth.isOwner && activeTab === 'pending'" class="batch-bar">
        <el-button type="success" size="small" :loading="operating" @click="handleBatchConfirm">
          批量确认勾选项
        </el-button>
        <span class="text-muted">已勾选 {{ selected.length }} 条</span>
      </div>

      <StateWrap :loading="loading" :failed="failed" :rows="6" @retry="load()">
        <!-- 整体空态 -->
        <el-empty
          v-if="items.length === 0 && activeTab !== 'pending'"
          description="完成诊断并确认后自动积累案例"
        />
        <!-- 待确认空态 -->
        <el-empty v-else-if="items.length === 0" description="全部处理完毕" />
        <template v-else>
          <el-table :data="items" stripe @selection-change="selected = $event">
            <el-table-column v-if="auth.isOwner && activeTab === 'pending'" type="selection" width="44" />
            <el-table-column label="图像" width="90">
              <template #default="{ row }">
                <el-image
                  :src="row.image_urls[0] ?? ''"
                  fit="cover"
                  class="case-thumb"
                  :preview-src-list="row.image_urls"
                  preview-teleported
                />
              </template>
            </el-table-column>
            <el-table-column prop="ai_disease_name" label="AI 初判" min-width="120" />
            <el-table-column label="最终名称" min-width="120">
              <template #default="{ row }">{{ row.final_disease_name || '-' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTag(row.status).type">{{ statusTag(row.status).text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="disease_category" label="病种分类" width="110">
              <template #default="{ row }">{{ row.disease_category || '-' }}</template>
            </el-table-column>
            <el-table-column label="来源" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.source === 'device' ? 'primary' : 'success'">
                  {{ sourceLabel(row.source) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="150">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column v-if="auth.isOwner && activeTab === 'pending'" label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="success" :disabled="operating" @click="handleConfirm(row as CaseItem)">确认</el-button>
                <el-button link type="warning" :disabled="operating" @click="openCorrect(row as CaseItem)">纠正</el-button>
              </template>
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
        </template>
      </StateWrap>
    </div>

    <!-- 纠正弹窗 -->
    <el-dialog v-model="correctDialog.visible" title="纠正案例病名" width="420px">
      <el-form label-width="90px">
        <el-form-item label="正确病名" required>
          <el-input v-model="correctDialog.name" placeholder="请输入正确病名" maxlength="30" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="correctDialog.note" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="correctDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="operating" @click="submitCorrect">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stat-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 28px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.stat-num {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}

.stat-num.warn {
  color: #e6a23c;
}

.stat-num.ok {
  color: #67c23a;
}

.stat-label {
  font-size: 12px;
  color: #909399;
}

.stat-category {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.cat-tag {
  margin-right: 4px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.stat-tabs {
  flex: 1;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.case-thumb {
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
</style>
