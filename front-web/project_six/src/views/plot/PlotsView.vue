<script setup lang="ts">
/**
 * 文件说明：地块/棚室档案管理页（04）。
 * 档案表格、新增/编辑弹窗（名称唯一、露天地块必填经纬度——手动输入）、停用/启用软删除确认。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createPlot, getPlots, updatePlot, updatePlotStatus } from '@/api/plots'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import { confirmAction } from '@/utils/confirm'
import { plotTypeLabel } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import type { Plot } from '@/types/farm'

const auth = useAuthStore()

/** 列表异步状态 */
const { loading, failed, data, load } = useAsyncData(() => getPlots())

/** 地块行列表（含类型快捷访问） */
const rows = computed<Plot[]>(() => data.value ?? [])

/** 弹窗可见性 */
const dialogVisible = ref(false)
/** 编辑中的地块 ID（null 表示新增） */
const editingId = ref<number | null>(null)
/** 提交中 */
const submitting = ref(false)
/** 表单引用 */
const formRef = ref<FormInstance | null>(null)

/** 表单数据（type 与后端字符串枚举对齐） */
const form = reactive({
  name: '',
  type: 'greenhouse' as 'greenhouse' | 'open_field',
  lng: undefined as number | undefined,
  lat: undefined as number | undefined,
  area_mu: undefined as number | undefined,
  soil_type: '',
  crop_name: '',
  crop_variety: '',
  growth_stage: '',
  planted_at: '',
  remark: '',
})

/**
 * 名称唯一性校验（与现有列表比对，编辑时排除自身）。
 * @param _rule 校验规则（未使用）
 * @param value 当前输入值
 * @param callback 校验回调
 */
function validateName(_rule: unknown, value: string, callback: (error?: Error) => void): void {
  if (!value) {
    callback()
    return
  }
  const dup = rows.value.some((p) => p.name === value && p.id !== editingId.value)
  callback(dup ? new Error('名称已存在，请更换') : undefined)
}

/**
 * 露天地块经纬度必填校验。
 * @param _rule 校验规则（未使用）
 * @param value 当前输入值
 * @param callback 校验回调
 */
function makeRequiredForOpen(_rule: unknown, value: number | undefined, callback: (error?: Error) => void): void {
  if (form.type === 'open_field' && (value === undefined || value === null)) {
    callback(new Error('露天地块必须填写经纬度'))
    return
  }
  callback()
}

/**
 * 作物名称必填校验（后端 crop_name 非空约束）。
 * @param _rule 校验规则（未使用）
 * @param value 当前输入值
 * @param callback 校验回调
 */
function validateCropName(_rule: unknown, value: string, callback: (error?: Error) => void): void {
  callback(value.trim() === '' ? new Error('请输入作物名称') : undefined)
}

/**
 * 生育期必填校验（后端 growth_stage 非空约束）。
 * @param _rule 校验规则（未使用）
 * @param value 当前输入值
 * @param callback 校验回调
 */
function validateGrowthStage(_rule: unknown, value: string, callback: (error?: Error) => void): void {
  callback(value.trim() === '' ? new Error('请输入生育期') : undefined)
}

/** 表单校验规则 */
const rules: FormRules = {
  name: [
    { required: true, message: '请输入名称', trigger: 'blur' },
    { validator: validateName, trigger: 'blur' },
  ],
  lng: [{ validator: makeRequiredForOpen, trigger: 'blur' }],
  lat: [{ validator: makeRequiredForOpen, trigger: 'blur' }],
  crop_name: [{ validator: validateCropName, trigger: 'blur' }],
  growth_stage: [{ validator: validateGrowthStage, trigger: 'blur' }],
}

/**
 * 打开新增弹窗并重置表单。
 */
function openCreate(): void {
  editingId.value = null
  Object.assign(form, {
    name: '',
    type: 'greenhouse',
    lng: undefined,
    lat: undefined,
    area_mu: undefined,
    soil_type: '',
    crop_name: '',
    crop_variety: '',
    growth_stage: '',
    planted_at: '',
    remark: '',
  })
  dialogVisible.value = true
}

/**
 * 打开编辑弹窗并回填数据。
 * @param row 地块行
 */
function openEdit(row: Plot): void {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    type: row.type,
    lng: row.lng ?? undefined,
    lat: row.lat ?? undefined,
    area_mu: row.area_mu ?? undefined,
    soil_type: row.soil_type ?? '',
    crop_name: row.crop_name ?? '',
    crop_variety: row.crop_variety ?? '',
    growth_stage: row.growth_stage ?? '',
    planted_at: row.planted_at ?? '',
    remark: row.remark ?? '',
  })
  dialogVisible.value = true
}

/**
 * 提交新增/编辑表单（空串字段清理为 null，避免后端日期/非空校验失败）。
 * @throws 校验失败或后端报错时保持弹窗并提示
 */
async function handleSubmit(): Promise<void> {
  const valid = await formRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false)
  if (!valid) return
  submitting.value = true
  // 空串转 null：planted_at 非法日期串会 422，可选文本字段保持后端语义
  const payload = {
    ...form,
    soil_type: form.soil_type.trim() === '' ? null : form.soil_type.trim(),
    crop_variety: form.crop_variety.trim() === '' ? null : form.crop_variety.trim(),
    planted_at: form.planted_at === '' ? null : form.planted_at,
    remark: form.remark.trim() === '' ? null : form.remark.trim(),
  }
  try {
    if (editingId.value === null) {
      await createPlot(payload)
      ElMessage.success('地块创建成功')
    } else {
      await updatePlot(editingId.value, payload)
      ElMessage.success('地块已更新')
    }
    dialogVisible.value = false
    await load()
  } finally {
    submitting.value = false
  }
}

/**
 * 停用/启用地块（软删除，需确认）。
 * @param row 地块行
 */
async function handleToggleStatus(row: Plot): Promise<void> {
  const next: 0 | 1 = row.status === 0 ? 1 : 0
  const ok = await confirmAction(
    next === 0 ? `确定停用「${row.name}」吗？停用后不再参与诊断与建议。` : `确定启用「${row.name}」吗？`,
  )
  if (!ok) return
  await updatePlotStatus(row.id, next)
  ElMessage.success(next === 0 ? '已停用' : '已启用')
  await load()
}

onMounted(() => {
  if (rows.value.length === 0) void load()
})
</script>

<template>
  <div class="page">
    <div class="page-card">
      <div class="toolbar">
        <h3 class="page-card-title" style="margin: 0">地块/棚室档案</h3>
        <el-button v-if="auth.isOwner" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>&nbsp;新增地块/棚室
        </el-button>
      </div>

      <StateWrap :loading="loading" :failed="failed" :rows="8" @retry="load()">
        <el-empty
          v-if="rows.length === 0"
          description="暂无档案：创建地块/棚室后才能上传诊断与接收建议"
        />
        <el-table v-else :data="rows" stripe>
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.type === 'greenhouse' ? 'primary' : 'success'">{{ plotTypeLabel(row.type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="crop_name" label="作物" width="100">
            <template #default="{ row }">{{ row.crop_name || '-' }}</template>
          </el-table-column>
          <el-table-column prop="crop_variety" label="品种" width="100">
            <template #default="{ row }">{{ row.crop_variety || '-' }}</template>
          </el-table-column>
          <el-table-column prop="growth_stage" label="生育期" width="110">
            <template #default="{ row }">{{ row.growth_stage || '-' }}</template>
          </el-table-column>
          <el-table-column prop="area_mu" label="面积(亩)" width="90">
            <template #default="{ row }">{{ row.area_mu ?? '-' }}</template>
          </el-table-column>
          <el-table-column prop="soil_type" label="土壤" width="90">
            <template #default="{ row }">{{ row.soil_type || '-' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 0 ? 'info' : 'success'">
                {{ row.status === 0 ? '已停用' : '启用中' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="auth.isOwner" label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEdit(row as Plot)">编辑</el-button>
              <el-button link :type="row.status === 0 ? 'success' : 'danger'" @click="handleToggleStatus(row as Plot)">
                {{ row.status === 0 ? '启用' : '停用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </StateWrap>
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新增地块/棚室' : '编辑地块/棚室'"
      width="560px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入唯一名称" maxlength="30" />
        </el-form-item>
        <el-form-item label="类型" prop="type">
          <el-radio-group v-model="form.type">
            <el-radio value="greenhouse">大棚</el-radio>
            <el-radio value="open_field">露天</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.type === 'open_field'" label="经度" prop="lng">
          <el-input-number v-model="form.lng" :precision="6" :step="0.0001" :controls="false" placeholder="经度" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="form.type === 'open_field'" label="纬度" prop="lat">
          <el-input-number v-model="form.lat" :precision="6" :step="0.0001" :controls="false" placeholder="纬度" style="width: 100%" />
        </el-form-item>
        <el-form-item label="面积(亩)">
          <el-input-number v-model="form.area_mu" :min="0" :precision="1" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="土壤类型">
          <el-input v-model="form.soil_type" placeholder="如：壤土 / 沙壤土" />
        </el-form-item>
        <el-form-item label="作物" prop="crop_name">
          <el-input v-model="form.crop_name" placeholder="如：番茄" />
        </el-form-item>
        <el-form-item label="品种">
          <el-input v-model="form.crop_variety" placeholder="如：粉果 1 号" />
        </el-form-item>
        <el-form-item label="生育期" prop="growth_stage">
          <el-input v-model="form.growth_stage" placeholder="如：结果期" />
        </el-form-item>
        <el-form-item label="定植日期">
          <el-date-picker
            v-model="form.planted_at"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择定植日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
</style>
