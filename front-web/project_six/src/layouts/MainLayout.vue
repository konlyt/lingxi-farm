<script setup lang="ts">
/**
 * 文件说明：主布局组件。
 * 桌面端（≥992px）左侧固定导航 + 顶栏；移动端（<992px）顶部条 + 底部 5 项 Tab（总览/诊断/预警/问答/我的）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useResponsive } from '@/composables/useResponsive'
import { confirmAction } from '@/utils/confirm'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { isMobile } = useResponsive()

/** 当前激活菜单路径 */
const activePath = computed(() => route.path)

/** 智能诊断子菜单默认展开 */
const openMenus = ref<string[]>(['diagnosis-menu'])

/** 页面标题（取路由 meta） */
const pageTitle = computed(() => {
  const meta = route.meta
  return typeof meta.title === 'string' ? meta.title : ''
})

/** 角色中文标签 */
const roleLabel = computed(() => (auth.isOwner ? '农场主' : '家庭成员'))

/** 头像字符（昵称/登录名首字） */
const avatarChar = computed(() => (auth.user?.nickname || auth.user?.username || '农').slice(0, 1))

/**
 * 用户下拉命令分发。
 * @param command 命令标识
 */
function handleUserCommand(command: string | number | object): void {
  if (command === 'settings') void router.push('/settings')
  else if (command === 'logout') void handleLogout()
}

/**
 * 跳转到指定路由。
 * @param path 目标路径
 */
function go(path: string): void {
  void router.push(path)
}

/**
 * 退出登录（二次确认后清理状态并跳转登录页）。
 */
async function handleLogout(): Promise<void> {
  const ok = await confirmAction('确定要退出登录吗？')
  if (!ok) return
  auth.logout()
  ElMessage.success('已退出登录')
  await router.push('/login')
}

onMounted(() => {
  // 进入主布局时静默刷新用户信息
  void auth.refreshUser()
})
</script>

<template>
  <el-container class="app-shell">
    <!-- 桌面端左侧固定导航 -->
    <el-aside v-if="!isMobile" width="220px" class="app-aside">
      <div class="brand" @click="go('/dashboard')">
        <el-icon :size="22" class="brand-icon"><Sunny /></el-icon>
        <span>农场智能管护系统</span>
      </div>
      <el-menu :default-active="activePath" :default-openeds="openMenus" router class="app-menu">
        <el-menu-item index="/dashboard">
          <el-icon><Odometer /></el-icon><span>总览</span>
        </el-menu-item>
        <el-menu-item index="/plots">
          <el-icon><Location /></el-icon><span>地块档案</span>
        </el-menu-item>
        <el-sub-menu index="diagnosis-menu">
          <template #title>
            <el-icon><Camera /></el-icon><span>智能诊断</span>
          </template>
          <el-menu-item index="/diagnosis/upload">上传诊断</el-menu-item>
          <el-menu-item index="/diagnosis/records">诊断记录</el-menu-item>
          <el-menu-item index="/cases">案例库</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/alerts">
          <el-icon><Bell /></el-icon><span>预警中心</span>
        </el-menu-item>
        <el-menu-item index="/advice">
          <el-icon><Pouring /></el-icon><span>水肥建议</span>
        </el-menu-item>
        <el-menu-item index="/environment">
          <el-icon><DataLine /></el-icon><span>大棚环境</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isOwner" index="/thresholds">
          <el-icon><Histogram /></el-icon><span>阈值配置</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isOwner" index="/devices">
          <el-icon><Cpu /></el-icon><span>设备管理</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon><span>知识问答</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isOwner" index="/bigscreen">
          <el-icon><DataBoard /></el-icon><span>监测大屏</span>
        </el-menu-item>
        <el-menu-item index="/calendar">
          <el-icon><Calendar /></el-icon><span>农事日历</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="app-body">
      <!-- 顶部条：标题 + 用户信息 -->
      <el-header class="app-header" height="52px">
        <span class="header-title">{{ pageTitle || (isMobile ? '农场智能管护系统' : '') }}</span>
        <el-dropdown trigger="click" @command="handleUserCommand">
          <div class="user-trigger">
            <el-avatar :size="30" class="user-avatar">{{ avatarChar }}</el-avatar>
            <span class="user-name">{{ auth.user?.nickname ?? auth.user?.username ?? '未登录' }}</span>
            <el-tag :type="auth.isOwner ? 'success' : 'info'" size="small" effect="plain">{{ roleLabel }}</el-tag>
            <el-icon class="user-arrow"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu class="user-menu">
              <div class="menu-profile">
                <el-avatar :size="40" class="user-avatar">{{ avatarChar }}</el-avatar>
                <div class="menu-profile-info">
                  <div class="menu-profile-name">{{ auth.user?.nickname ?? auth.user?.username ?? '未登录' }}</div>
                  <div class="menu-profile-meta">{{ roleLabel }} · {{ auth.user?.username ?? '-' }}</div>
                </div>
              </div>
              <el-dropdown-item divided command="settings">
                <el-icon><Setting /></el-icon>系统设置
              </el-dropdown-item>
              <el-dropdown-item command="logout">
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 移动端底部 Tab -->
    <nav v-if="isMobile" class="tab-bar">
      <div class="tab-item" :class="{ active: activePath.startsWith('/dashboard') }" @click="go('/dashboard')">
        <el-icon :size="20"><HomeFilled /></el-icon>
        <span>总览</span>
      </div>
      <el-popover placement="top-start" :width="150" trigger="click">
        <template #reference>
          <div class="tab-item" :class="{ active: activePath.startsWith('/diagnosis') || activePath.startsWith('/cases') }">
            <el-icon :size="20"><Camera /></el-icon>
            <span>诊断</span>
          </div>
        </template>
        <div class="tab-pop-item" @click="go('/diagnosis/upload')">上传诊断</div>
        <div class="tab-pop-item" @click="go('/diagnosis/records')">诊断记录</div>
        <div class="tab-pop-item" @click="go('/cases')">案例库</div>
      </el-popover>
      <div class="tab-item" :class="{ active: activePath.startsWith('/alerts') }" @click="go('/alerts')">
        <el-icon :size="20"><Bell /></el-icon>
        <span>预警</span>
      </div>
      <div class="tab-item" :class="{ active: activePath.startsWith('/chat') }" @click="go('/chat')">
        <el-icon :size="20"><ChatDotRound /></el-icon>
        <span>问答</span>
      </div>
      <div class="tab-item" :class="{ active: activePath.startsWith('/settings') }" @click="go('/settings')">
        <el-icon :size="20"><User /></el-icon>
        <span>我的</span>
      </div>
    </nav>
  </el-container>
</template>

<style scoped>
.app-shell {
  height: 100%;
}

/* ===== 侧边栏：深森林绿底 ===== */
.app-aside {
  background: linear-gradient(180deg, var(--farm-primary-700) 0%, #16402a 100%);
  border-right: none;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 18px 16px 16px;
  font-size: 15px;
  font-weight: 600;
  color: #f3f8f4;
  cursor: pointer;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.brand-icon {
  color: #7fd6a4;
}

/* 深色侧边栏上的菜单：覆盖默认文字/背景 */
.app-menu {
  border-right: none;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: transparent;
  --el-menu-text-color: rgba(230, 242, 234, 0.85);
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.06);
  --el-menu-active-color: #ffffff;
}

.app-menu :deep(.el-menu-item),
.app-menu :deep(.el-sub-menu__title) {
  color: rgba(230, 242, 234, 0.85);
  height: 44px;
  line-height: 44px;
  margin: 2px 8px;
  border-radius: 8px;
}

.app-menu :deep(.el-menu-item.is-active) {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  position: relative;
}

.app-menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 2px;
  background: #7fd6a4;
}

.app-menu :deep(.el-sub-menu__title:hover),
.app-menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

.app-menu :deep(.el-sub-menu .el-menu) {
  background: transparent;
}

.app-body {
  min-width: 0;
  background: var(--farm-bg);
}

/* ===== 顶栏：毛玻璃 ===== */
.app-header {
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--farm-border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--farm-text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-title::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--farm-primary-500);
}

/* ===== 右上角用户下拉 ===== */
.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 8px;
  cursor: pointer;
  outline: none;
}

.user-trigger:hover {
  background: rgba(46, 125, 79, 0.08);
}

.user-avatar {
  background: var(--farm-primary-500);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  flex: none;
}

.user-name {
  font-size: 13px;
  color: var(--farm-text-primary);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-arrow {
  font-size: 12px;
  color: var(--farm-text-secondary);
}

/* 下拉内的个人信息头 */
.menu-profile {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px 12px;
  min-width: 200px;
  cursor: default;
}

.menu-profile-info {
  min-width: 0;
}

.menu-profile-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--farm-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.menu-profile-meta {
  margin-top: 2px;
  font-size: 12px;
  color: var(--farm-text-secondary);
}

.app-main {
  padding: 20px;
  overflow-y: auto;
}

/* ===== 移动端底部 Tab ===== */
.tab-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  height: 56px;
  background: #fff;
  border-top: 1px solid var(--farm-border-light);
  display: flex;
  z-index: 100;
  box-shadow: 0 -2px 10px rgba(27, 77, 50, 0.05);
}

.tab-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  font-size: 11px;
  color: var(--farm-text-secondary);
  cursor: pointer;
}

.tab-item.active {
  color: var(--farm-primary-500);
  font-weight: 600;
}

.tab-pop-item {
  padding: 8px 0;
  text-align: center;
  cursor: pointer;
  color: var(--farm-text-primary);
  font-size: 13px;
}

.tab-pop-item:hover {
  color: var(--farm-primary-500);
}

@media (max-width: 991px) {
  .app-main {
    padding: 12px 12px 70px;
  }
}
</style>
