import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/instances'
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue')
  },
  {
    path: '/intent-chat',
    name: 'IntentChat',
    component: () => import('@/views/IntentChatView.vue')
  },
  {
    path: '/nodes',
    name: 'Nodes',
    component: () => import('@/views/NodesView.vue')
  },
  {
    path: '/templates',
    name: 'Templates',
    component: () => import('@/views/TemplatesView.vue')
  },
  {
    path: '/templates/:id',
    name: 'TemplateDetail',
    component: () => import('@/views/TemplateDetailView.vue')
  },
  {
    path: '/instances',
    name: 'Instances',
    component: () => import('@/views/InstancesView.vue')
  },
  {
    path: '/instances/:id',
    name: 'InstanceDetail',
    component: () => import('@/views/InstanceDetailView.vue')
  },
  {
    path: '/batch',
    name: 'Batch',
    component: () => import('@/views/BatchView.vue')
  },
  {
    path: '/business-tasks',
    name: 'BusinessTasks',
    component: () => import('@/views/BusinessTasksView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router