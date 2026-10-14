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
    <!-- 左侧品牌插画区（桌面端展示，移动端隐藏） -->
    <div class="login-hero">
      <div class="hero-text">
        <h2 class="hero-title">智慧农业 · 一棚一田尽在掌握</h2>
        <p class="hero-sub">AI 病虫害诊断 · 环境实时监测 · 水肥智能决策</p>
      </div>
      <!-- 轻量田园 SVG 插画：太阳 / 远山 / 大棚拱 / 田垄 / 树 -->
      <svg class="hero-scene" viewBox="0 0 600 420" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <!-- 太阳 -->
        <circle cx="480" cy="80" r="46" fill="rgba(255, 224, 130, 0.55)" />
        <circle cx="480" cy="80" r="62" stroke="rgba(255, 224, 130, 0.25)" stroke-width="1.5" />
        <!-- 远山（两层） -->
        <path d="M0 260 L120 170 L240 250 L360 180 L480 250 L600 200 L600 420 L0 420 Z" fill="rgba(255,255,255,0.08)" />
        <path d="M0 310 L100 240 L220 300 L340 250 L460 310 L600 270 L600 420 L0 420 Z" fill="rgba(255,255,255,0.12)" />
        <!-- 大棚拱形轮廓（三个） -->
        <path d="M60 340 Q110 260 160 340" stroke="rgba(255,255,255,0.45)" stroke-width="2" />
        <path d="M150 340 Q210 240 270 340" stroke="rgba(255,255,255,0.55)" stroke-width="2" />
        <path d="M260 340 Q330 230 400 340" stroke="rgba(255,255,255,0.45)" stroke-width="2" />
        <!-- 大棚竖向骨架 -->
        <line x1="110" y1="298" x2="110" y2="340" stroke="rgba(255,255,255,0.3)" stroke-width="1.2" />
        <line x1="210" y1="285" x2="210" y2="340" stroke="rgba(255,255,255,0.35)" stroke-width="1.2" />
        <line x1="330" y1="275" x2="330" y2="340" stroke="rgba(255,255,255,0.3)" stroke-width="1.2" />
        <!-- 田垄曲线 -->
        <path d="M0 380 Q150 360 300 380 T600 380" stroke="rgba(255,255,255,0.25)" stroke-width="1.5" />
        <path d="M0 400 Q150 385 300 400 T600 400" stroke="rgba(255,255,255,0.2)" stroke-width="1.5" />
        <!-- 树（右侧） -->
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

/* ===== 左侧品牌插画区 ===== */
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

/* ===== 右侧登录卡片：磨砂玻璃 ===== */
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
  padding: 40px 36px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.28);
}

.login-brand {
  text-align: center;
  margin-bottom: 24px;
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

.login-error {
  margin-bottom: 14px;
}

/* 输入框聚焦时显式绿色描边 */
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

.login-tip {
  font-size: 12px;
  color: var(--farm-text-secondary);
  text-align: center;
  margin: 14px 0 0;
}

/* ===== 移动端：隐藏左侧插画区，卡片居中 ===== */
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
    padding: 32px 24px;
  }
}
</style>
