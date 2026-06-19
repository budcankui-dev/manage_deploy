import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ADMIN_ROUTE_NAMES, USER_ROUTE_NAMES } from '@/utils/routeAccess'
import { markAuthExpiredNotice } from '@/utils/authExpired'
import {
  clearChunkReloadMarker,
  isDynamicImportLoadError,
  recoverFromChunkLoadError,
} from '@/utils/routeChunkRecovery'
import { ElMessage } from 'element-plus'

const routes = [
  {
    path: '/',
    redirect: () => {
      const auth = useAuthStore()
      return auth.homePath
    },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { public: true },
  },
  {
    path: '/intent-chat',
    name: 'IntentChat',
    component: () => import('@/views/IntentChatView.vue'),
  },
  {
    path: '/my-orders',
    name: 'MyOrders',
    component: () => import('@/views/MyOrdersView.vue'),
  },
  {
    path: '/nodes',
    name: 'Nodes',
    component: () => import('@/views/NodesView.vue'),
  },
  {
    path: '/templates',
    name: 'Templates',
    component: () => import('@/views/TemplatesView.vue'),
  },
  {
    path: '/templates/new',
    name: 'TemplateNew',
    component: () => import('@/views/TemplateDetailView.vue'),
  },
  {
    path: '/templates/:id',
    name: 'TemplateDetail',
    component: () => import('@/views/TemplateDetailView.vue'),
  },
  {
    path: '/dev/instances',
    name: 'DevInstances',
    component: () => import('@/views/InstancesView.vue'),
  },
  {
    path: '/dev/instances/:id',
    name: 'InstanceDetail',
    component: () => import('@/views/InstanceDetailView.vue'),
  },
  {
    path: '/instances',
    redirect: '/dev/instances',
  },
  {
    path: '/instances/:id',
    redirect: (to) => `/dev/instances/${to.params.id}`,
  },
  {
    path: '/business-tasks',
    name: 'BusinessTasksHub',
    component: () => import('@/views/BusinessTasksHubView.vue'),
  },
  {
    path: '/benchmark',
    name: 'Benchmark',
    component: () => import('@/views/BenchmarkView.vue'),
  },
  {
    path: '/intent-evaluation',
    name: 'IntentEvaluation',
    component: () => import('@/views/IntentEvaluationView.vue'),
  },
  {
    path: '/admin',
    name: 'AdminConsole',
    component: () => import('@/views/AdminConsoleView.vue'),
  },
  {
    path: '/users',
    name: 'Users',
    component: () => import('@/views/UsersView.vue'),
  },
  {
    path: '/settings',
    name: 'SystemSettings',
    component: () => import('@/views/SystemSettingsView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (auth.needsTokenValidation) {
    const valid = await auth.validateSession()
    if (!valid && !to.meta.public) {
      markAuthExpiredNotice()
      return { name: 'Login', query: { redirect: to.fullPath } }
    }
  }

  if (to.meta.public) {
    if (auth.isAuthenticated && (to.name === 'Login' || to.name === 'Register')) {
      return auth.homePath
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (ADMIN_ROUTE_NAMES.has(to.name) && !auth.isAdmin) {
    return auth.homePath
  }

  if (USER_ROUTE_NAMES.has(to.name) && auth.isAdmin) {
    return auth.homePath
  }

  return true
})

router.onError((error, to) => {
  if (isDynamicImportLoadError(error)) {
    const recovered = recoverFromChunkLoadError(to, (message) => {
      ElMessage.warning(message)
    })
    if (recovered) return
  }

  console.error('路由跳转失败', error)
})

router.afterEach((to) => {
  clearChunkReloadMarker(to.fullPath)
})

export default router
