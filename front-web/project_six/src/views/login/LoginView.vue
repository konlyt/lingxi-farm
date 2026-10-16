<script setup lang="ts">
/**
 * 文件说明：登录页。
 * 手机号 + 密码 / 手机号 + 短信验证码 两种登录方式，tab 切换。
 * 保留原有农场主题品牌视觉。
 */
import { computed, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Iphone, Lock, Message, Sunny } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { sendSmsCode } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

type LoginMode = 'password' | 'code'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

/** 当前 tab */
const activeTab = ref<LoginMode>('password')
/** 登录表单 */
const form = reactive({ phone: '', password: '', code: '' })
const formRef = ref<FormInstance | null>(null)
const loading = ref(false)
const errorMsg = ref('')
/** 发送验证码按钮状态 */
const codeLoading = ref(false)
const countdown = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const PhoneIcon = Iphone
const LockIcon = Lock
const MessageIcon = Message

/** 手机号校验 */
const phonePattern = /^1[3-9]\d{9}$/

const rules = computed<FormRules>(() => ({
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: phonePattern, message: '请输入正确的 11 位手机号', trigger: 'blur' },
  ],
  password:
    activeTab.value === 'password'
      ? [{ required: true, message: '请输入密码', trigger: 'blur' }]
      : [],
  code:
    activeTab.value === 'code'
      ? [{ required: true, message: '请输入验证码', trigger: 'blur' }]
      : [],
}))

/** 提交按钮禁用条件 */
const submitDisabled = computed(() => {
  if (loading.value) return true
  if (!phonePattern.test(form.phone)) return true
  if (activeTab.value === 'password') return form.password.length === 0
  return form.code.length === 0
})

/** 验证码按钮文案 */
const codeBtnText = computed(() => {
  if (codeLoading.value) return '发送中…'
  return countdown.value > 0 ? `${countdown.value}s 后重发` : '获取验证码'
})
const codeBtnDisabled = computed(() => codeLoading.value || countdown.value > 0)

/** 启动倒计时 */
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

/** 切换 tab 时清理错误与校验 */
function switchTab(tab: LoginMode): void {
  activeTab.value = tab
  errorMsg.value = ''
  formRef.value?.clearValidate()
}

/** 发送短信验证码 */
async function handleSendCode(): Promise<void> {
  errorMsg.value = ''
  if (!phonePattern.test(form.phone)) {
    errorMsg.value = '请先输入正确的手机号'
    return
  }
  codeLoading.value = true
  try {
    const result = await sendSmsCode(form.phone, 'login')
    if (result.dev_code) {
      // dev_mode：后端直接把验证码返回，填进输入框方便演示
      form.code = result.dev_code
      errorMsg.value = `（开发模式）验证码：${result.dev_code}`
    } else {
      errorMsg.value = ''
    }
    startCountdown()
  } catch (err) {
    errorMsg.value = err instanceof Error && err.message ? err.message : '验证码发送失败'
  } finally {
    codeLoading.value = false
  }
}

/** 一键填充测试账号（owner） */
function fillTestOwner(): void {
  form.phone = '18890259380'
  form.password = '123456'
  form.code = ''
  activeTab.value = 'password'
  errorMsg.value = ''
  formRef.value?.clearValidate()
}

/** 提交登录 */
async function handleLogin(): Promise<void> {
  errorMsg.value = ''
  const valid = await formRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    if (activeTab.value === 'password') {
      await auth.loginWithPhone(form.phone.trim(), form.password)
    } else {
      await auth.loginWithCode(form.phone.trim(), form.code.trim())
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    await router.push(redirect)
  } catch (err) {
    errorMsg.value = err instanceof Error && err.message ? err.message : '服务暂不可用，请稍后再试'
  } finally {
    loading.value = false
  }
}

function goRegister(): void {
  router.push({ name: 'register' })
}
</script>

<template>
  <div class="login-page">
    <!-- 左侧品牌插画区（桌面端展示，移动端隐藏） -->
    <div class="login-hero">
      <div class="hero-text">
        <h2 class="hero-title">智慧农业 · 一棚一田尽在掌握</h2>
        <p class="hero-sub">AI 病虫害诊断 · 环境实时监测 · 水肥智能决策</p>
      </div>
      <svg class="hero-scene" viewBox="0 0 600 420" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <circle cx="480" cy="80" r="46" fill="rgba(255, 224, 130, 0.55)" />
        <circle cx="480" cy="80" r="62" stroke="rgba(255, 224, 130, 0.25)" stroke-width="1.5" />
        <path d="M0 260 L120 170 L240 250 L360 180 L480 250 L600 200 L600 420 L0 420 Z" fill="rgba(255,255,255,0.08)" />
        <path d="M0 310 L100 240 L220 300 L340 250 L460 310 L600 270 L600 420 L0 420 Z" fill="rgba(255,255,255,0.12)" />
        <path d="M60 340 Q110 260 160 340" stroke="rgba(255,255,255,0.45)" stroke-width="2" />
        <path d="M150 340 Q210 240 270 340" stroke="rgba(255,255,255,0.55)" stroke-width="2" />
        <path d="M260 340 Q330 230 400 340" stroke="rgba(255,255,255,0.45)" stroke-width="2" />
        <line x1="110" y1="298" x2="110" y2="340" stroke="rgba(255,255,255,0.3)" stroke-width="1.2" />
        <line x1="210" y1="285" x2="210" y2="340" stroke="rgba(255,255,255,0.35)" stroke-width="1.2" />
        <line x1="330" y1="275" x2="330" y2="340" stroke="rgba(255,255,255,0.3)" stroke-width="1.2" />
        <path d="M0 380 Q150 360 300 380 T600 380" stroke="rgba(255,255,255,0.25)" stroke-width="1.5" />
        <path d="M0 400 Q150 385 300 400 T600 400" stroke="rgba(255,255,255,0.2)" stroke-width="1.5" />
        <g>
          <rect x="500" y="320" width="6" height="40" fill="rgba(255,255,255,0.3)" />
          <circle cx="503" cy="310" r="22" fill="rgba(255,255,255,0.22)" />
        </g>
        <g>
          <rect x="540" y="335" width="5" height="30" fill="rgba(255,255,255,0.25)" />
          <circle cx="542" cy="328" r="15" fill="rgba(255,255,255,0.18)" />
        </g>
      </svg>
    </div>

    <!-- 右侧登录卡片 -->
    <div class="login-card">
      <div class="login-brand">
        <el-icon :size="40" color="#2e7d4f" class="brand-logo"><Sunny /></el-icon>
        <h1 class="login-title">灵犀田园系统</h1>
        <p class="login-sub">手机号一键登录，开始管护您的农场</p>
      </div>

      <!-- 登录方式 tab -->
      <div class="auth-tabs">
        <button
          type="button"
          class="auth-tab"
          :class="{ active: activeTab === 'password' }"
          @click="switchTab('password')"
        >
          密码登录
        </button>
        <button
          type="button"
          class="auth-tab"
          :class="{ active: activeTab === 'code' }"
          @click="switchTab('code')"
        >
          验证码登录
        </button>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @keyup.enter="handleLogin"
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

        <el-form-item v-if="activeTab === 'password'" label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            :prefix-icon="LockIcon"
            show-password
          />
        </el-form-item>

        <el-form-item v-else label="短信验证码" prop="code">
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

        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          :type="errorMsg.startsWith('（开发模式）') ? 'success' : 'error'"
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

        <div class="login-extra">
          <span class="link" @click="fillTestOwner">测试账号一键填充</span>
          <span class="link" @click="goRegister">还没有账号？立即注册</span>
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

.hero-text {
  position: relative;
  z-index: 2;
  margin-bottom: 24px;
}

.hero-title {
  margin: 0 0 10px;
  font-size: 30px;
  font-weight: 600;
  color: #f3f8f4;
  letter-spacing: 1px;
  line-height: 1.4;
}

.hero-sub {
  margin: 0;
  font-size: 14px;
  color: rgba(230, 242, 234, 0.75);
  letter-spacing: 0.5px;
}

.hero-scene {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: auto;
  z-index: 1;
  pointer-events: none;
}

.login-card {
  position: relative;
  z-index: 2;
  width: 440px;
  flex: none;
  align-self: center;
  margin-right: 72px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(20px) saturate(1.4);
  -webkit-backdrop-filter: blur(20px) saturate(1.4);
  border: 1px solid rgba(255, 255, 255, 0.55);
  border-radius: 18px;
  padding: 36px 36px 28px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.28);
}

.login-brand {
  text-align: center;
  margin-bottom: 16px;
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

/* tab 切换 */
.auth-tabs {
  display: flex;
  border-bottom: 1px solid rgba(46, 125, 79, 0.2);
  margin-bottom: 18px;
}

.auth-tab {
  flex: 1;
  background: transparent;
  border: none;
  padding: 10px 0;
  font-size: 15px;
  color: var(--farm-text-secondary);
  cursor: pointer;
  position: relative;
  transition: color 0.2s;
}

.auth-tab.active {
  color: var(--farm-primary-600);
  font-weight: 600;
}

.auth-tab.active::after {
  content: '';
  position: absolute;
  left: 20%;
  right: 20%;
  bottom: -1px;
  height: 2px;
  background: var(--farm-primary-500);
  border-radius: 1px;
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

.login-error {
  margin-bottom: 14px;
}

.login-card :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.6);
  box-shadow: 0 0 0 1px rgba(46, 125, 79, 0.25) inset;
  border-radius: 8px;
  transition: box-shadow 0.2s;
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
  justify-content: space-between;
  margin-top: 14px;
  font-size: 12px;
}

.login-extra .link {
  color: var(--farm-primary-600);
  cursor: pointer;
}

.login-extra .link:hover {
  text-decoration: underline;
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
    max-width: 380px;
    margin-right: 0;
    padding: 28px 22px;
  }
}
</style>
