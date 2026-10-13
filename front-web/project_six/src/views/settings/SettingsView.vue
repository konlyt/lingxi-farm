<script setup lang="ts">
/**
 * 文件说明：系统设置页（19）。
 * 置信度阈值分病种配置（owner 可编辑，0–1 两位小数）、家庭成员管理（邀请/停用）、
 * 消息推送（邮箱绑定 + 微信服务号状态「暂缓接入」标注）、修改密码表单、数据导出（自侧边栏整合）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  createMember,
  getConfidenceThresholds,
  getEmailBind,
  getMembers,
  getWxBind,
  updateConfidenceThresholds,
  updateEmailBind,
  updateMemberStatus,
} from '@/api/settings'
import { changePassword } from '@/api/auth'
import { useAsyncData } from '@/composables/useAsyncData'
import StateWrap from '@/components/StateWrap.vue'
import ExportsView from '@/views/exports/ExportsView.vue'
import { useAuthStore } from '@/stores/auth'
import { wxBindTag } from '@/utils/format'
import { confirmAction } from '@/utils/confirm'
import type { ConfidenceThreshold, Member, WxBindItem } from '@/types/farm'

const router = useRouter()
const auth = useAuthStore()

/** 当前激活 Tab */
const activeTab = ref('confidence')

// ---------- 置信度阈值 ----------
const ctState = useAsyncData(getConfidenceThresholds)
/** 可编辑的阈值副本 */
const ctItems = ref<ConfidenceThreshold[]>([])
/** 保存中 */
const ctSaving = ref(false)

// 异步数据到达后复制为可编辑副本
watch(
  () => ctState.data.value,
  (val) => {
    if (val) ctItems.value = val.map((item) => ({ ...item }))
  },
  { immediate: true },
)

/**
 * 保存置信度阈值（0–1 两位小数校验）。
 * @throws 数值非法或保存失败时提示
 */
async function saveThresholds(): Promise<void> {
  for (const item of ctItems.value) {
    if (item.threshold < 0 || item.threshold > 1) {
      ElMessage.warning(`「${item.disease_category}」阈值需在 0–1 之间`)
      return
    }
  }
  ctSaving.value = true
  try {
    await updateConfidenceThresholds(ctItems.value.map((item) => ({ id: item.id, threshold: item.threshold })))
    ElMessage.success('阈值已保存，即时生效')
    await ctState.load()
  } finally {
    ctSaving.value = false
  }
}

// ---------- 家庭成员 ----------
const memberState = useAsyncData(getMembers)
/** 邀请弹窗 */
const inviteDialog = reactive({ visible: false, username: '', nickname: '', password: '' })
/** 邀请提交中 */
const inviting = ref(false)
/** 邀请表单引用 */
const inviteFormRef = ref<FormInstance | null>(null)

/** 邀请表单校验规则 */
const inviteRules: FormRules = {
  username: [{ required: true, message: '请输入登录名', trigger: 'blur' }],
  nickname: [{ required: true, message: '请输入昵称', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

/**
 * 提交邀请成员。
 * @throws 校验失败或后端报错时提示
 */
async function submitInvite(): Promise<void> {
  const valid = await inviteFormRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false)
  if (!valid) return
  inviting.value = true
  try {
    await createMember({
      username: inviteDialog.username.trim(),
      nickname: inviteDialog.nickname.trim(),
      password: inviteDialog.password,
    })
    ElMessage.success('成员已创建，可使用账号密码登录（只读）')
    inviteDialog.visible = false
    await memberState.load()
  } finally {
    inviting.value = false
  }
}

/**
 * 启用/停用成员账号。
 * @param member 成员
 */
async function toggleMember(member: Member): Promise<void> {
  const next: 0 | 1 = member.status === 0 ? 1 : 0
  const ok = await confirmAction(next === 0 ? `确定停用「${member.nickname}」吗？` : `确定启用「${member.nickname}」吗？`)
  if (!ok) return
  await updateMemberStatus(member.id, next)
  ElMessage.success(next === 0 ? '已停用' : '已启用')
  await memberState.load()
}

// ---------- 消息推送：邮箱绑定 ----------
const emailState = useAsyncData(getEmailBind)
/** 邮箱输入值 */
const emailInput = ref('')
/** 邮箱保存中 */
const emailSaving = ref(false)
/** 当前用户邮箱绑定信息（null 表示尚未加载完成） */
const emailInfo = computed(() => emailState.data.value ?? null)

// 异步数据到达后回填输入框（仅输入框未被用户编辑时）
watch(
  () => emailState.data.value,
  (val) => {
    if (val?.email && !emailInput.value) emailInput.value = val.email
  },
  { immediate: true },
)

/**
 * 简易邮箱格式前端预校验（与后端正则一致）。
 * @param value 输入邮箱
 * @returns 是否为合法格式
 */
function isValidEmail(value: string): boolean {
  return /^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(value)
}

/**
 * 保存邮箱绑定（保存即生效；格式非法前端直接拦截，唯一性冲突由后端 400 提示）。
 * @throws 后端报错时由 axios 拦截器统一提示
 */
async function saveEmail(): Promise<void> {
  const value = emailInput.value.trim()
  if (!isValidEmail(value)) {
    ElMessage.warning('请输入合法的邮箱地址')
    return
  }
  emailSaving.value = true
  try {
    const result = await updateEmailBind(value)
    ElMessage.success(
      result.bind_mail_sent ? '邮箱已绑定，绑定通知邮件已发送' : '邮箱已绑定（邮件通道未配置，通知邮件未发送）',
    )
    await emailState.load()
  } finally {
    emailSaving.value = false
  }
}

// ---------- 消息推送：服务号绑定（暂缓接入） ----------
const wxState = useAsyncData(getWxBind)

/** 绑定列表 */
const wxList = computed<WxBindItem[]>(() => wxState.data.value ?? [])

// ---------- 修改密码 ----------
const pwdFormRef = ref<FormInstance | null>(null)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })
const pwdSaving = ref(false)

/** 修改密码校验规则 */
const pwdRules: FormRules = {
  old_password: [{ required: true, message: '请输入旧密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirm: [
    {
      validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (value !== pwdForm.new_password) {
          callback(new Error('两次输入的新密码不一致'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

/**
 * 提交修改密码（成功后强制重新登录）。
 * @throws 校验失败或旧密码错误时提示
 */
async function submitPassword(): Promise<void> {
  const valid = await pwdFormRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false)
  if (!valid) return
  pwdSaving.value = true
  try {
    await changePassword(pwdForm.old_password, pwdForm.new_password)
    ElMessage.success('密码已修改，请重新登录')
    auth.logout()
    await router.push('/login')
  } finally {
    pwdSaving.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="page-card">
      <el-tabs v-model="activeTab">
        <!-- 置信度阈值 -->
        <el-tab-pane label="置信度阈值" name="confidence">
          <StateWrap :loading="ctState.loading.value" :failed="ctState.failed.value" :rows="5" @retry="ctState.load()">
            <el-table :data="ctItems" stripe>
              <el-table-column prop="disease_category" label="病种分类" min-width="140" />
              <el-table-column label="置信度阈值" width="180">
                <template #default="{ row }">
                  <el-input-number
                    v-model="row.threshold"
                    :min="0"
                    :max="1"
                    :step="0.01"
                    :precision="2"
                    :controls="false"
                    :disabled="!auth.isOwner"
                    style="width: 120px"
                  />
                </template>
              </el-table-column>
              <el-table-column label="参考样本量基线" width="140">
                <template #default="{ row }">{{ row.sample_count_baseline }}</template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
            <div class="tab-actions">
              <span class="text-muted">常见病建议 0.85，罕见病建议 0.95；样本量动态调整说明见知识库</span>
              <el-button v-if="auth.isOwner" type="primary" :loading="ctSaving" @click="saveThresholds">保存</el-button>
            </div>
          </StateWrap>
        </el-tab-pane>

        <!-- 家庭成员 -->
        <el-tab-pane label="家庭成员" name="members">
          <StateWrap :loading="memberState.loading.value" :failed="memberState.failed.value" :rows="4" @retry="memberState.load()">
            <div class="tab-actions" style="margin-bottom: 10px">
              <span class="text-muted">家庭成员仅可查看实况与接收预警</span>
              <el-button v-if="auth.isOwner" type="primary" @click="inviteDialog.visible = true">邀请成员</el-button>
            </div>
            <el-empty v-if="(memberState.data.value ?? []).length === 0" description="邀请家人查看实况与接收预警" />
            <el-table v-else :data="memberState.data.value ?? []" stripe>
              <el-table-column prop="username" label="登录名" min-width="120" />
              <el-table-column prop="nickname" label="昵称" min-width="120" />
              <el-table-column label="角色" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.role === 'owner' ? 'danger' : 'primary'">
                    {{ row.role === 'owner' ? '农场主' : '家庭成员' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.status === 0 ? 'info' : 'success'">
                    {{ row.status === 0 ? '已停用' : '启用中' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column v-if="auth.isOwner" label="操作" width="120">
                <template #default="{ row }">
                  <el-button v-if="row.role !== 'owner'" link :type="row.status === 0 ? 'success' : 'danger'" @click="toggleMember(row as Member)">
                    {{ row.status === 0 ? '启用' : '停用' }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </StateWrap>
        </el-tab-pane>

        <!-- 消息推送：邮箱绑定 + 服务号（暂缓接入） -->
        <el-tab-pane label="消息推送" name="push">
          <!-- 邮箱绑定 -->
          <el-alert
            title="绑定邮箱后，农情预警、病情升级、每日汇总与每日农情简报将发送到您的邮箱"
            type="info"
            show-icon
            :closable="false"
            style="margin-bottom: 12px"
          />
          <StateWrap :loading="emailState.loading.value" :failed="emailState.failed.value" :rows="2" @retry="emailState.load()">
            <div class="email-bind-row">
              <el-input
                v-model="emailInput"
                placeholder="请输入邮箱地址，如 farm@qq.com"
                maxlength="128"
                style="width: 320px"
                clearable
              />
              <el-button type="primary" :loading="emailSaving" @click="saveEmail">保存绑定</el-button>
              <el-tag v-if="emailInfo?.email_bind_status === 1 && emailInfo.email" type="success" size="large">
                已绑定：{{ emailInfo.email }}
              </el-tag>
              <el-tag v-else type="info" size="large">未绑定</el-tag>
            </div>
          </StateWrap>

          <el-divider content-position="left">微信服务号</el-divider>
          <el-alert
            title="微信服务号模板消息推送暂缓接入，当前消息推送主通道为邮箱"
            type="warning"
            show-icon
            :closable="false"
            style="margin-bottom: 12px"
          />
          <StateWrap :loading="wxState.loading.value" :failed="wxState.failed.value" :rows="3" @retry="wxState.load()">
            <el-table :data="wxList" stripe>
              <el-table-column prop="nickname" label="成员" min-width="120" />
              <el-table-column label="角色" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.role === 'owner' ? 'danger' : 'primary'">
                    {{ row.role === 'owner' ? '农场主' : '家庭成员' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="绑定状态" width="120">
                <template #default="{ row }">
                  <el-tag size="small" :type="wxBindTag(row.wx_bind_status).type">{{ wxBindTag(row.wx_bind_status).text }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="接入进度" width="120">
                <template #default>
                  <el-tag size="small" type="info">暂缓接入</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </StateWrap>
        </el-tab-pane>

        <!-- 账号安全 -->
        <el-tab-pane label="修改密码" name="password">
          <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="100px" class="pwd-form">
            <el-form-item label="旧密码" prop="old_password">
              <el-input v-model="pwdForm.old_password" type="password" show-password style="width: 260px" />
            </el-form-item>
            <el-form-item label="新密码" prop="new_password">
              <el-input v-model="pwdForm.new_password" type="password" show-password style="width: 260px" />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm">
              <el-input v-model="pwdForm.confirm" type="password" show-password style="width: 260px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="pwdSaving" @click="submitPassword">保存修改</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 数据导出（自侧边栏整合，懒加载复用导出页组件） -->
        <el-tab-pane label="数据导出" name="exports" lazy>
          <div class="exports-embed">
            <ExportsView />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 邀请成员弹窗 -->
    <el-dialog v-model="inviteDialog.visible" title="邀请家庭成员" width="420px">
      <el-form ref="inviteFormRef" :model="inviteDialog" :rules="inviteRules" label-width="90px">
        <el-form-item label="登录名" prop="username">
          <el-input v-model="inviteDialog.username" placeholder="登录账号" maxlength="20" />
        </el-form-item>
        <el-form-item label="昵称" prop="nickname">
          <el-input v-model="inviteDialog.nickname" placeholder="显示昵称" maxlength="20" />
        </el-form-item>
        <el-form-item label="初始密码" prop="password">
          <el-input v-model="inviteDialog.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inviteDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="inviting" @click="submitInvite">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 数据导出嵌入样式：抹平子页面自带的卡片外框，避免卡中卡 */
.exports-embed :deep(.page) {
  max-width: none;
}

.exports-embed :deep(.page-card) {
  padding: 0;
  margin-bottom: 0;
  background: transparent;
}

.tab-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 10px;
}

.email-bind-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.pwd-form {
  max-width: 420px;
  padding-top: 10px;
}
</style>
