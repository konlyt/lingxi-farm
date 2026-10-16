<script setup lang="ts">
/**
 * 文件说明：注册页。
 * 单页表单：手机号 + 短信验证码 + 设置密码 + 确认密码 + 可选昵称。
 * 注册成功后自动登录并跳转 dashboard。
 */
import { computed, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Iphone, Lock, Message, Sunny, User } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { checkPhoneExists, sendSmsCode } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const form = reactive({
  phone: '',
  code: '',
  password: '',
  confirmPassword: '',
  nickname: '',
  agreed: false,
})

const formRef = ref<FormInstance | null>(null)
const loading = ref(false)
const errorMsg = ref('')
const codeLoading = ref(false)
const countdown = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const phonePattern = /^1[3-9]\d{9}$/

const PhoneIcon = Iphone
const LockIcon = Lock
const MessageIcon = Message
const UserIcon = User

const rules = computed<FormRules>(() => ({
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: phonePattern, message: '请输入正确的 11 位手机号', trigger: 'blur' },
  ],
  code: [{ required: true, message: '请输入验证码', trigger: 'blur' }],
  password: [
    { required: true, message: '请设置密码', trigger: 'blur' },
    { min: 6, max: 64, message: '密码长度 6-64 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_r, value: string, cb) => {
        if (value !== form.password) cb(new Error('两次输入的密码不一致'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
}))

const codeBtnText = computed(() => {
  if (codeLoading.value) return '发送中…'
  return countdown.value > 0 ? `${countdown.value}s 后重发` : '获取验证码'
})
const codeBtnDisabled = computed(() => codeLoading.value || countdown.value > 0)

const submitDisabled = computed(
  () =>
    loading.value ||
    !phonePattern.test(form.phone) ||
    !form.code ||
    form.password.length < 6 ||
    form.password !== form.confirmPassword ||
    !form.agreed,
)

function startCountdown(): void {
  countdown.value = 60
  timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  }, 1000)
}

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function handleSendCode(): Promise<void> {
  errorMsg.value = ''
  if (!phonePattern.test(form.phone)) {
    errorMsg.value = '请先输入正确的手机号'
    return
  }
  codeLoading.value = true
  try {
    // 预检查：已注册的号码不能走注册流程
    const { exists } = await checkPhoneExists(form.phone)
    if (exists) {
      errorMsg.value = '该手机号已注册，请直接登录'
      return
    }
    const result = await sendSmsCode(form.phone, 'register')
    if (result.dev_code) {
      form.code = result.dev_code
      errorMsg.value = `（开发模式）验证码：${result.dev_code}`
    } else {
      errorMsg.value = '验证码已发送，请查收短信'
    }
    startCountdown()
  } catch (err) {
    errorMsg.value = err instanceof Error && err.message ? err.message : '验证码发送失败'
  } finally {
    codeLoading.value = false
  }
}

async function handleSubmit(): Promise<void> {
  errorMsg.value = ''
  const valid = await formRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false)
  if (!valid) return
  if (!form.agreed) {
    errorMsg.value = '请先勾选并同意用户协议'
    return
  }

  loading.value = true
  try {
    await auth.register(
      form.phone.trim(),
      form.password,
      form.code.trim(),
      form.nickname.trim() || undefined,
    )
    await router.push('/dashboard')
  } catch (err) {
    errorMsg.value = err instanceof Error && err.message ? err.message : '注册失败，请稍后再试'
  } finally {
    loading.value = false
  }
}

function goLogin(): void {
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="login-page">
    <div class="login-hero">
      <div class="hero-text">
        <h2 class="hero-title">创建账号</h2>
        <p class="hero-sub">用您的手机号注册，开始使用灵犀田园系统</p>
      </div>
    </div>

    <div class="login-card">
      <div class="login-brand">
        <el-icon :size="40" color="#2e7d4f" class="brand-logo"><Sunny /></el-icon>
        <h1 class="login-title">手机号注册</h1>
        <p class="login-sub">注册后默认拥有农场主权限</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @keyup.enter="handleSubmit"
      >
        <el-form-item label="手机号" prop="phone">
          <el-input
            v-model="form.phone"
            placeholder="请输入 11 位手机号"
            :prefix-icon="PhoneIcon"
            maxlength="11"
            clearable
          />
        </el-form-item>

        <el-form-item label="短信验证码" prop="code">
          <div class="code-row">
            <el-input
              v-model="form.code"
              placeholder="请输入 6 位验证码"
              :prefix-icon="MessageIcon"
              maxlength="6"
              class="code-input"
            />
            <el-button
              class="code-btn"
              :loading="codeLoading"
              :disabled="codeBtnDisabled"
              @click="handleSendCode"
            >
              {{ codeBtnText }}
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="设置密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="6-64 位密码"
            :prefix-icon="LockIcon"
            show-password
          />
        </el-form-item>

        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
            :prefix-icon="LockIcon"
            show-password
          />
        </el-form-item>

        <el-form-item label="昵称（可选）">
          <el-input
            v-model="form.nickname"
            placeholder="不填则默认「用户+手机号后 4 位」"
            :prefix-icon="UserIcon"
            maxlength="32"
            clearable
          />
        </el-form-item>

        <el-checkbox v-model="form.agreed" size="small" class="agree-check">
          我已阅读并同意 <a class="link">《用户协议》</a> 与 <a class="link">《隐私政策》</a>
        </el-checkbox>

        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          :type="errorMsg.startsWith('验证码已发送') || errorMsg.startsWith('（开发模式）') ? 'success' : 'error'"
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
          @click="handleSubmit"
        >
          注 册
        </el-button>

        <div class="login-extra">
          <span class="link" @click="goLogin">已有账号？直接登录</span>
        </div>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  height: 100%;
  display: flex;
  align-items: stretch;
  background:
    radial-gradient(circle at 20% 20%, rgba(127, 214, 164, 0.25) 0%, transparent 40%),
    radial-gradient(circle at 80% 80%, rgba(245, 158, 11, 0.12) 0%, transparent 40%),
    linear-gradient(135deg, #16402a 0%, #256b43 50%, #2e7d4f 100%);
  overflow: hidden;
}

.login-hero {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 48px 56px;
  position: relative;
  z-index: 1;
}

.hero-title {
  margin: 0 0 10px;
  font-size: 30px;
  font-weight: 600;
  color: #f3f8f4;
  letter-spacing: 1px;
}

.hero-sub {
  margin: 0;
  font-size: 14px;
  color: rgba(230, 242, 234, 0.75);
}

.login-card {
  position: relative;
  z-index: 2;
  width: 460px;
  flex: none;
  align-self: center;
  margin-right: 72px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(20px) saturate(1.4);
  -webkit-backdrop-filter: blur(20px) saturate(1.4);
  border: 1px solid rgba(255, 255, 255, 0.55);
  border-radius: 18px;
  padding: 32px 36px 24px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.28);
}

.login-brand {
  text-align: center;
  margin-bottom: 12px;
}

.brand-logo {
  margin-bottom: 8px;
}

.login-title {
  font-size: 22px;
  margin: 8px 0 4px;
  color: var(--farm-text-primary);
  font-weight: 600;
}

.login-sub {
  font-size: 13px;
  color: var(--farm-text-secondary);
  margin: 0 0 12px;
}

.code-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.code-input {
  flex: 1;
}

.code-btn {
  flex: none;
  width: 118px;
  border-radius: 8px;
}

.agree-check {
  margin: 4px 0 14px;
}

.agree-check .link,
.login-extra .link {
  color: var(--farm-primary-600);
  cursor: pointer;
}

.login-error {
  margin-bottom: 14px;
}

.login-card :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.6);
  box-shadow: 0 0 0 1px rgba(46, 125, 79, 0.25) inset;
  border-radius: 8px;
}

.login-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px var(--farm-primary-500) inset, 0 0 0 3px rgba(46, 125, 79, 0.15);
  background: #fff;
}

.login-btn {
  width: 100%;
  background: var(--farm-primary-500);
  border-color: var(--farm-primary-500);
  font-weight: 600;
  letter-spacing: 4px;
  border-radius: 8px;
  height: 44px;
}

.login-btn:hover {
  background: var(--farm-primary-600);
  border-color: var(--farm-primary-600);
}

.login-extra {
  display: flex;
  justify-content: center;
  margin-top: 14px;
  font-size: 12px;
}

@media (max-width: 768px) {
  .login-hero {
    display: none;
  }
  .login-page {
    justify-content: center;
    padding: 20px;
  }
  .login-card {
    width: 100%;
    max-width: 400px;
    margin-right: 0;
    padding: 24px 22px;
  }
}
</style>
