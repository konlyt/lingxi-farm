<script setup lang="ts">
/**
 * 文件说明：报警阈值配置页（13）。
 * 默认模板区（按作物+生育期分组、一键应用到棚室）、地块覆盖配置（指标上下限表单、min<max 校验、
 * 启用开关、编辑/删除）；所有写操作仅 owner 可见。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { getPlots } from '@/api/plots'
import { createThreshold, deleteThreshold, getThresholds, updateThreshold } from '@/api/environment'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import { useAuthStore } from '@/stores/auth'
import { confirmAction } from '@/utils/confirm'
import { metricLabel } from '@/utils/format'
import type { Plot, PlotThreshold, ThresholdTemplate } from '@/types/farm'
const auth = useAuthStore()

/** 阈值配置异步状态 */
const { loading, failed, data, load } = useAsyncData(() => getThresholds())
/** 地块列表异步状态 */
const { data: plots, load: loadPlots } = useAsyncData(() => getPlots())

/** 模板分组（作物+生育期 → 模板列表） */
const templateGroups = computed<Array<{ key: string; cropName: string; stage: string; items: ThresholdTemplate[] }>>(() => {
  const map = new Map<string, { cropName: string; stage: string; items: ThresholdTemplate[] }>()
  for (const t of data.value?.templates ?? []) {
    const key = `${t.crop_name}·${t.growth_stage}`
    const group = map.get(key)
    if (group) {
      group.items.push(t)
    } else {
      map.set(key, { cropName: t.crop_name, stage: t.growth_stage, items: [t] })
    }
  }
  return Array.from(map.entries()).map(([key, group]) => ({
    key,
    cropName: group.cropName,
    stage: group.stage,
    items: group.items,
  }))
})

/** 覆盖配置列表 */
const plotConfigs = computed<PlotThreshold[]>(() => data.value?.plot_configs ?? [])

/** 地块选项 */
const plotOptions = computed<Plot[]>(() => plots.value ?? [])

/** 应用模板弹窗 */
const applyDialog = reactive({ visible: false, template: null as ThresholdTemplate | null, plot_id: undefined as number | undefined })

/** 新增/编辑配置弹窗 */
const configDialog = reactive({
  visible: false,
  editingId: null as number | null,
  plot_id: undefined as number | undefined,
  metric: 'temp',
  min_value: 0,
  max_value: 40,
  enabled: true,
})
/** 提交中 */
const submitting = ref(false)
/** 表单引用 */
const formRef = ref<FormInstance | null>(null)

/** 指标选项 */
const metricOptions = [
  { value: 'temp', label: '温度' },
  { value: 'humidity', label: '湿度' },
  { value: 'soil_moisture', label: '土壤墒情' },
  { value: 'light', label: '光照' },
]

/**
 * 上下限校验：下限必须小于上限。
 * @param _rule 校验规则（未使用）
 * @param _value 当前输入值（未使用）
 * @param callback 校验回调
 */
function validateRange(_rule: unknown, _value: unknown, callback: (error?: Error) => void): void {
  if (configDialog.min_value >= configDialog.max_value) {
    callback(new Error('下限必须小于上限'))
    return
  }
  callback()
}

/** 配置表单校验规则 */
const configRules: FormRules = {
  plot_id: [{ required: true, message: '请选择棚室', trigger: 'change' }],
  max_value: [{ validator: validateRange, trigger: 'blur' }],
}

/**
 * 打开新增配置弹窗。
 */
function openCreate(): void {
  configDialog.editingId = null
  configDialog.plot_id = activePlotFilter.value ?? undefined
  configDialog.metric = 'temp'
  configDialog.min_value = 0
  configDialog.max_value = 40
  configDialog.enabled = true
  configDialog.visible = true
}

/**
 * 打开编辑配置弹窗。
 * @param row 配置行
 */
function openEdit(row: PlotThreshold): void {
  configDialog.editingId = row.id
  configDialog.plot_id = row.plot_id ?? undefined
  configDialog.metric = row.metric
  configDialog.min_value = row.min_value ?? 0
  configDialog.max_value = row.max_value ?? 0
  configDialog.enabled = row.enabled
  configDialog.visible = true
}

/**
 * 提交新增/编辑配置。
 * @throws 校验失败或后端报错时提示
 */
async function submitConfig(): Promise<void> {
  const valid = await formRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const payload = {
      plot_id: configDialog.plot_id ?? null,
      crop_name: plotOptions.value.find((p) => p.id === configDialog.plot_id)?.crop_name ?? '',
      growth_stage: plotOptions.value.find((p) => p.id === configDialog.plot_id)?.growth_stage ?? '',
      metric: configDialog.metric,
      min_value: configDialog.min_value,
      max_value: configDialog.max_value,
      enabled: configDialog.enabled ? 1 : 0,
    }
    if (configDialog.editingId === null) {
      await createThreshold(payload)
      ElMessage.success('配置已保存')
    } else {
      await updateThreshold(configDialog.editingId, payload)
      ElMessage.success('配置已更新')
    }
    configDialog.visible = false
    await load()
  } finally {
    submitting.value = false
  }
}

/**
 * 删除覆盖配置（二次确认）。
 * @param row 配置行
 */
async function handleDelete(row: PlotThreshold): Promise<void> {
  const ok = await confirmAction('确定删除该覆盖配置吗？删除后回退到默认模板。')
  if (!ok) return
  await deleteThreshold(row.id)
  ElMessage.success('已删除')
  await load()
}

/**
 * 切换配置启用状态。
 * @param row 配置行
 */
async function handleToggleEnabled(row: PlotThreshold): Promise<void> {
  await updateThreshold(row.id, {
    plot_id: row.plot_id ?? null,
    crop_name: row.crop_name,
    growth_stage: row.growth_stage,
    metric: row.metric,
    min_value: row.min_value,
    max_value: row.max_value,
    enabled: row.enabled ? 0 : 1,
  })
  ElMessage.success(row.enabled ? '已停用' : '已启用')
  await load()
}

/**
 * 打开模板一键应用弹窗。
 * @param template 模板项
 */
function openApply(template: ThresholdTemplate): void {
  applyDialog.template = template
  applyDialog.plot_id = undefined
  applyDialog.visible = true
}

/**
 * 提交模板应用（按模板值创建地块覆盖配置）。
 */
async function submitApply(): Promise<void> {
  if (!applyDialog.plot_id || !applyDialog.template) {
    ElMessage.warning('请选择目标棚室')
    return
  }
  submitting.value = true
  try {
    const t = applyDialog.template
    await createThreshold({
      plot_id: applyDialog.plot_id,
      crop_name: t.crop_name,
      growth_stage: t.growth_stage,
      metric: t.metric,
      min_value: t.min_value,
      max_value: t.max_value,
      enabled: t.enabled ? 1 : 0,
    })
    ElMessage.success('模板已应用到所选棚室')
    applyDialog.visible = false
    await load()
  } finally {
    submitting.value = false
  }
}

/** 覆盖配置地块过滤（可选） */
const activePlotFilter = ref<number | undefined>(undefined)

onMounted(() => {
  void loadPlots()
})
</script>

<template>
  <div class="page">
    <div class="page-card">
      <h3 class="page-card-title">默认阈值模板（按作物 + 生育期）</h3>
      <StateWrap :loading="loading" :failed="failed" :rows="6" @retry="load()">
        <el-empty v-if="templateGroups.length === 0" description="暂无默认模板" />
        <div v-else class="group-list">
          <div v-for="group in templateGroups" :key="group.key" class="group-card">
            <div class="group-title">{{ group.cropName }} · {{ group.stage }}</div>
            <el-table :data="group.items" size="small" stripe>
              <el-table-column label="指标" width="110">
                <template #default="{ row }">{{ metricLabel(row.metric) }}</template>
              </el-table-column>
              <el-table-column label="下限" width="80">
                <template #default="{ row }">{{ row.min_value }}</template>
              </el-table-column>
              <el-table-column label="上限" width="80">
                <template #default="{ row }">{{ row.max_value }}</template>
              </el-table-column>
              <el-table-column label="启用" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column v-if="auth.isOwner" label="操作" width="120">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openApply(row as ThresholdTemplate)">一键应用</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </StateWrap>
    </div>

    <div class="page-card">
      <div class="head-row">
        <h3 class="page-card-title" style="margin: 0">地块覆盖配置</h3>
        <div class="head-actions">
          <el-select v-model="activePlotFilter" placeholder="按棚室过滤" clearable style="width: 180px">
            <el-option v-for="p in plotOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <el-button v-if="auth.isOwner" type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>&nbsp;新增覆盖配置
          </el-button>
        </div>
      </div>

      <el-empty v-if="plotConfigs.length === 0" description="未配置覆盖，当前使用默认模板" />
      <el-table v-else :data="plotConfigs.filter((c) => !activePlotFilter || c.plot_id === activePlotFilter)" stripe>
        <el-table-column label="棚室" width="130">
          <template #default="{ row }">
            {{ plotOptions.find((p) => p.id === row.plot_id)?.name ?? row.plot_name ?? '-' }}
          </template>
        </el-table-column>
        <el-table-column label="指标" width="100">
          <template #default="{ row }">{{ metricLabel(row.metric) }}</template>
        </el-table-column>
        <el-table-column label="下限" width="80">
          <template #default="{ row }">{{ row.min_value }}</template>
        </el-table-column>
        <el-table-column label="上限" width="80">
          <template #default="{ row }">{{ row.max_value }}</template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch
              v-if="auth.isOwner"
              :model-value="row.enabled"
              @change="handleToggleEnabled(row as PlotThreshold)"
            />
            <el-tag v-else size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="auth.isOwner" label="操作" width="130">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row as PlotThreshold)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(row as PlotThreshold)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑配置弹窗 -->
    <el-dialog v-model="configDialog.visible" :title="configDialog.editingId === null ? '新增覆盖配置' : '编辑覆盖配置'" width="460px">
      <el-form ref="formRef" :model="configDialog" :rules="configRules" label-width="90px">
        <el-form-item label="棚室" prop="plot_id">
          <el-select v-model="configDialog.plot_id" placeholder="请选择棚室" style="width: 100%">
            <el-option v-for="p in plotOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="指标">
          <el-select v-model="configDialog.metric" style="width: 100%">
            <el-option v-for="m in metricOptions" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="下限">
          <el-input-number v-model="configDialog.min_value" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="上限" prop="max_value">
          <el-input-number v-model="configDialog.max_value" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="configDialog.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitConfig">保存</el-button>
      </template>
    </el-dialog>

    <!-- 模板一键应用弹窗 -->
    <el-dialog v-model="applyDialog.visible" title="应用默认模板到棚室" width="400px">
      <el-form label-width="90px">
        <el-form-item label="目标棚室" required>
          <el-select v-model="applyDialog.plot_id" placeholder="请选择棚室" style="width: 100%">
            <el-option v-for="p in plotOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="applyDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitApply">应用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.group-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.group-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px;
}

.group-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 8px;
}

.head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.head-actions {
  display: flex;
  gap: 10px;
}
</style>
