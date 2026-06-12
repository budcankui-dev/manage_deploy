import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const ADMIN_ROUTES = new Set([
  'Nodes',
  'Templates',
  'TemplateNew',
  'TemplateDetail',
  'DevInstances',
  'InstanceDetail',
  'BusinessTasksHub',
  'AdminConsole',
  'Users',
  'Benchmark',
  'IntentEvaluation',
  'SystemSettings',
])

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

router.beforeEach((to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (auth.isAuthenticated && (to.name === 'Login' || to.name === 'Register')) {
      return auth.homePath
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (ADMIN_ROUTES.has(to.name) && !auth.isAdmin) {
    return auth.homePath
  }

  return true
})

export default router
