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
        <el-icon :size="22"><Sunny /></el-icon>
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
        <el-menu-item index="/thresholds">
          <el-icon><Histogram /></el-icon><span>阈值配置</span>
        </el-menu-item>
        <el-menu-item index="/devices">
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
        <el-menu-item index="/exports">
          <el-icon><Download /></el-icon><span>数据导出</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon><span>系统设置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="app-body">
      <!-- 顶部条：标题 + 用户信息 -->
      <el-header class="app-header" height="52px">
        <span class="header-title">{{ pageTitle || (isMobile ? '农场智能管护系统' : '') }}</span>
        <div class="header-user">
          <el-tag :type="auth.isOwner ? 'danger' : 'primary'" size="small">{{ roleLabel }}</el-tag>
          <span class="user-name">{{ auth.user?.nickname ?? auth.user?.username ?? '未登录' }}</span>
          <el-button link type="primary" @click="handleLogout">退出</el-button>
        </div>
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

.app-aside {
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  font-size: 15px;
  font-weight: 600;
  color: #409eff;
  cursor: pointer;
  white-space: nowrap;
}

.app-menu {
  border-right: none;
  flex: 1;
}

.app-body {
  min-width: 0;
}

.app-header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
}

.header-user {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-name {
  font-size: 13px;
  color: #606266;
}

.app-main {
  padding: 16px;
  overflow-y: auto;
}

.tab-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  height: 56px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
  display: flex;
  z-index: 100;
}

.tab-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  font-size: 11px;
  color: #909399;
  cursor: pointer;
}

.tab-item.active {
  color: #409eff;
}

.tab-pop-item {
  padding: 8px 0;
  text-align: center;
  cursor: pointer;
  color: #303133;
  font-size: 13px;
}

.tab-pop-item:hover {
  color: #409eff;
}

@media (max-width: 991px) {
  .app-main {
    padding: 12px 12px 70px;
  }
}
</style>
