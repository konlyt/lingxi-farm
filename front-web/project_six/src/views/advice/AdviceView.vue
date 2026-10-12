<script setup lang="ts">
/**
 * 文件说明：水肥建议页（11）。
 * 地块 Tab 切换、未来 7 天时间轴卡片（浇水/施肥建议、依据展开）、降级数据标注、
 * 「每日 06:00 生成」说明与手动刷新按钮。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getPlots } from '@/api/plots'
import { generateWaterFertilizerAdvice, getWaterFertilizerAdvice } from '@/api/advice'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import { formatDate } from '@/utils/format'

/** 地块列表异步状态 */
const { loading: plotsLoading, failed: plotsFailed, data: plots, load: loadPlots } = useAsyncData(() => getPlots())

/** 当前地块 ID */
const activePlotId = ref<number | undefined>(undefined)

/** 建议数据异步状态（依赖 activePlotId，选中地块后由 watch 触发加载） */
const { loading, failed, data: advice, load } = useAsyncData(
  () => getWaterFertilizerAdvice({ plot_id: activePlotId.value ?? 1 }),
  false,
)

/** 手动刷新中 */
const refreshing = ref(false)

/** 地块选项列表 */
const plotList = computed(() => plots.value ?? [])

/** 建议数据体（后端双层 data 包装） */
const adviceBody = computed(() => advice.value?.data ?? null)

// 地块列表加载完成后默认选中第一个
watch(
  plotList,
  (list) => {
    if (list.length > 0 && activePlotId.value === undefined) {
      activePlotId.value = list[0]?.id
    }
  },
  { immediate: true },
)

// 切换地块重新加载建议
watch(activePlotId, () => {
  void load()
})

/**
 * 手动触发生成并刷新建议。
 * @throws 生成失败时由拦截器统一提示
 */
async function handleRefresh(): Promise<void> {
  refreshing.value = true
  try {
    await generateWaterFertilizerAdvice({ plot_id: activePlotId.value })
    ElMessage.success('已触发重新生成')
    await load()
  } finally {
    refreshing.value = false
  }
}

// 进入页面加载地块列表
void loadPlots()
</script>

<template>
  <div class="page">
    <div class="page-card">
      <div class="head-row">
        <h3 class="page-card-title" style="margin: 0">水肥建议</h3>
        <div class="head-right">
          <span class="text-muted">每日 06:00 自动生成，也可手动刷新</span>
          <el-button
            v-if="activePlotId"
            size="small"
            type="primary"
            plain
            :loading="refreshing"
            @click="handleRefresh"
          >
            手动刷新
          </el-button>
        </div>
      </div>

      <!-- 地块 Tab -->
      <StateWrap :loading="plotsLoading" :failed="plotsFailed" :rows="2" @retry="loadPlots">
        <el-empty v-if="plotList.length === 0" description="暂无地块档案，请先创建">
          <el-button type="primary" @click="$router.push('/plots')">去创建</el-button>
        </el-empty>
        <el-tabs v-else v-model="activePlotId">
          <el-tab-pane v-for="p in plotList" :key="p.id" :label="p.name" :name="p.id" />
        </el-tabs>
      </StateWrap>

      <!-- 降级标注 -->
      <el-alert
        v-if="adviceBody?.data_fallback_flag"
        title="部分数据使用上一有效数据（外部气象/墒情接口暂不可用），依据中已标注数据时间"
        type="warning"
        show-icon
        :closable="false"
        class="fallback-tip"
      />

      <!-- 7 天建议时间轴（irrigate/fertilize 为整段文本） -->
      <StateWrap :loading="loading" :failed="failed" :rows="6" @retry="load()">
        <el-empty v-if="!adviceBody || adviceBody.items.length === 0" description="暂无建议，将于每日 06:00 生成" />
        <div v-else class="day-list">
          <div v-for="item in adviceBody.items" :key="item.date" class="day-card">
            <div class="day-head">
              <span class="day-date">{{ formatDate(item.date) }}</span>
            </div>
            <div class="day-body">
              <div class="advice-row">
                <span class="advice-icon">💧 浇水</span>
                <span>{{ item.irrigate }}</span>
              </div>
              <div class="advice-row">
                <span class="advice-icon">🌾 施肥</span>
                <span>{{ item.fertilize }}</span>
              </div>
              <el-collapse v-if="adviceBody.summary || adviceBody.risk_notes" class="basis-collapse">
                <el-collapse-item title="查看总结与风险提示" :name="item.date">
                  <div class="basis-text">
                    <p v-if="adviceBody.summary"><b>总结：</b>{{ adviceBody.summary }}</p>
                    <p v-if="adviceBody.risk_notes"><b>风险提示：</b>{{ adviceBody.risk_notes }}</p>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
        </div>
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
  margin-bottom: 8px;
}

.head-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fallback-tip {
  margin-bottom: 14px;
}

.day-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.day-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}

.day-head {
  background: #f0f9eb;
  padding: 8px 12px;
}

.day-date {
  font-weight: 600;
  font-size: 14px;
}

.day-body {
  padding: 12px;
}

.advice-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
  margin-bottom: 8px;
}

.advice-icon {
  flex-shrink: 0;
}

.basis-collapse {
  border: none;
}

.basis-text {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
}
</style>
