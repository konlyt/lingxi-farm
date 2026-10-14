/**
 * 文件说明：路由配置与全局守卫。
 * 登录页独立；其余页面挂载主布局；含登录守卫、角色控制（监测大屏仅 owner）与页面标题设置。
 */
import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import type { UserRole } from '@/types/farm'

/** 路由 meta 类型扩充 */
declare module 'vue-router' {
  interface RouteMeta {
    /** 页面标题（中文） */
    title?: string
    /** 是否公开页面（无需登录） */
    public?: boolean
    /** 允许访问的角色列表（缺省表示全部角色） */
    roles?: UserRole[]
  }
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/login/LoginView.vue'),
      meta: { title: '登录', public: true },
    },
    {
      path: '/greenhouse-twin',
      name: 'greenhouse-twin',
      component: () => import('@/views/greenhouse/GreenhouseTwinView.vue'),
      meta: { title: '3D 大棚孪生', roles: ['owner'] },
    },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/dashboard/DashboardView.vue'),
          meta: { title: '农场总览' },
        },
        {
          path: 'plot-live/:id',
          name: 'plot-live',
          component: () => import('@/views/plot/PlotLiveView.vue'),
          meta: { title: '实况详情' },
        },
        {
          path: 'plots',
          name: 'plots',
          component: () => import('@/views/plot/PlotsView.vue'),
          meta: { title: '地块档案' },
        },
        {
          path: 'diagnosis/upload',
          name: 'diagnosis-upload',
          component: () => import('@/views/diagnosis/DiagnosisUploadView.vue'),
          meta: { title: '上传诊断' },
        },
        {
          path: 'diagnosis/records',
          name: 'diagnosis-records',
          component: () => import('@/views/diagnosis/DiagnosisRecordsView.vue'),
          meta: { title: '诊断记录' },
        },
        {
          path: 'diagnosis/:id',
          name: 'diagnosis-detail',
          component: () => import('@/views/diagnosis/DiagnosisDetailView.vue'),
          meta: { title: '诊断详情' },
        },
        {
          path: 'cases',
          name: 'cases',
          component: () => import('@/views/cases/CasesView.vue'),
          meta: { title: '案例库' },
        },
        {
          path: 'alerts',
          name: 'alerts',
          component: () => import('@/views/alerts/AlertsView.vue'),
          meta: { title: '预警中心' },
        },
        {
          path: 'alerts/:id',
          name: 'alert-detail',
          component: () => import('@/views/alerts/AlertDetailView.vue'),
          meta: { title: '预警详情' },
        },
        {
          path: 'advice',
          name: 'advice',
          component: () => import('@/views/advice/AdviceView.vue'),
          meta: { title: '水肥建议' },
        },
        {
          path: 'environment',
          name: 'environment',
          component: () => import('@/views/environment/EnvironmentView.vue'),
          meta: { title: '大棚环境' },
        },
        {
          path: 'thresholds',
          name: 'thresholds',
          component: () => import('@/views/environment/ThresholdsView.vue'),
          meta: { title: '阈值配置', roles: ['owner'] },
        },
        {
          path: 'devices',
          name: 'devices',
          component: () => import('@/views/devices/DevicesView.vue'),
          meta: { title: '设备管理', roles: ['owner'] },
        },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/chat/ChatView.vue'),
          meta: { title: '知识问答' },
        },
        {
          path: 'bigscreen',
          name: 'bigscreen',
          component: () => import('@/views/bigscreen/BigScreenView.vue'),
          meta: { title: '监测大屏', roles: ['owner'] },
        },
        {
          path: 'calendar',
          name: 'calendar',
          component: () => import('@/views/calendar/CalendarView.vue'),
          meta: { title: '农事日历' },
        },
        {
          path: 'exports',
          name: 'exports',
          component: () => import('@/views/exports/ExportsView.vue'),
          meta: { title: '数据导出' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/settings/SettingsView.vue'),
          meta: { title: '系统设置' },
        },
      ],
    },
    {
      // 404 兜底：明确提示页面不存在，而非静默回退总览
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/error/NotFoundView.vue'),
      meta: { title: '页面不存在' },
    },
  ],
})

// 全局前置守卫：登录校验与角色控制
router.beforeEach((to) => {
  const auth = useAuthStore()
  // 公开页面：已登录访问登录页时跳转总览
  if (to.meta.public) {
    if (to.path === '/login' && auth.isLoggedIn) return '/dashboard'
    return true
  }
  // 未登录跳登录页并记录回跳地址
  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  // 角色控制：meta.roles 存在时仅允许列表内角色
  const roles = to.meta.roles
  if (roles && roles.length > 0 && !roles.includes(auth.user?.role ?? 'member')) {
    ElMessage.warning('该页面仅农场主可访问')
    return '/dashboard'
  }
  return true
})

// 全局后置守卫：设置页面标题
router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 农场智能管护系统` : '农场智能管护系统'
})

export default router
