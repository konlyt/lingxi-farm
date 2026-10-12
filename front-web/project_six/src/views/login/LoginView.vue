<script setup lang="ts">
/**
 * 文件说明：登录页（01）。
 * 账号密码表单：空值按钮置灰、校验、登录中 loading、错误行内红字提示。
 */
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, Sunny, User } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

/** 图标引用（输入框前缀） */
const UserIcon = User
const LockIcon = Lock

/** 登录表单数据 */
const form = reactive({ username: '', password: '' })
/** 表单引用 */
const formRef = ref<FormInstance | null>(null)
/** 登录中状态 */
const loading = ref(false)
/** 行内错误信息 */
const errorMsg = ref('')

/** 表单校验规则 */
const rules: FormRules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

/** 提交按钮禁用条件：输入为空或登录中 */
const submitDisabled = computed(
  () => form.username.trim() === '' || form.password.trim() === '' || loading.value,
)

/**
 * 提交登录。
 * 校验通过后调用登录接口，成功跳转总览；失败展示行内红字。
 * @throws 校验失败或登录失败时更新行内错误文案
 */
async function handleLogin(): Promise<void> {
  errorMsg.value = ''
  const valid = await formRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    await router.push(redirect)
  } catch (err) {
    errorMsg.value = err instanceof Error && err.message ? err.message : '服务暂不可用，请稍后再试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <el-icon :size="36" color="#409eff"><Sunny /></el-icon>
        <h1 class="login-title">农场智能管护系统</h1>
        <p class="login-sub">蔬菜大棚 · 露天农田 一站式管护</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @keyup.enter="handleLogin"
      >
        <el-form-item label="账号" prop="username">
          <el-input v-model="form.username" placeholder="请输入账号" :prefix-icon="UserIcon" clearable />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            :prefix-icon="LockIcon"
            show-password
          />
        </el-form-item>

        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          show-icon
          :closable="false"
          class="login-error"
        />

        <el-button
          type="primary"
          size="large"
          class="login-btn"
          :loading="loading"
          :disabled="submitDisabled"
          @click="handleLogin"
        >
          登 录
        </el-button>
        <p class="login-tip">家庭成员与农场主使用同一入口登录，按角色进入</p>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f3b2d 0%, #2e6e4e 50%, #3a8f5f 100%);
}

.login-card {
  width: 380px;
  background: #fff;
  border-radius: 12px;
  padding: 32px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
}

.login-brand {
  text-align: center;
  margin-bottom: 20px;
}

.login-title {
  font-size: 20px;
  margin: 8px 0 4px;
  color: #303133;
}

.login-sub {
  font-size: 12px;
  color: #909399;
  margin: 0 0 12px;
}

.login-error {
  margin-bottom: 14px;
}

.login-btn {
  width: 100%;
}

.login-tip {
  font-size: 12px;
  color: #909399;
  text-align: center;
  margin: 12px 0 0;
}
</style>
