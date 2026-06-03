import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

const LONG_RUNNING_TIMEOUT = 180000

function withTimeout(ms) {
  return { timeout: ms }
}

api.interceptors.request.use(config => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      const currentPath = window.location.pathname
      if (currentPath !== '/login' && currentPath !== '/register') {
        window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`
      }
      return Promise.reject(error)
    }
    const message = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export const nodesApi = {
  list: () => api.get('/nodes'),
  get: (id) => api.get(`/nodes/${id}`),
  create: (data) => api.post('/nodes', data),
  update: (id, data) => api.put(`/nodes/${id}`, data),
  delete: (id) => api.delete(`/nodes/${id}`),
  listOrphans: (id) => api.get(`/nodes/${id}/orphans`),
  cleanupOrphans: (id, containerNames = []) => api.post(`/nodes/${id}/orphans/cleanup`, { container_names: containerNames })
}

export const templatesApi = {
  list: () => api.get('/templates'),
  get: (id) => api.get(`/templates/${id}`),
  create: (data) => api.post('/templates', data),
  update: (id, data) => api.put(`/templates/${id}`, data),
  delete: (id) => api.delete(`/templates/${id}`)
}

export const instancesApi = {
  list: (params = {}) => api.get('/instances', { params }),
  get: (id) => api.get(`/instances/${id}`),
  preflight: (data) => api.post('/instances/preflight', data),
  create: (data) => api.post('/instances', data),
  update: (id, data) => api.put(`/instances/${id}`, data),
  delete: (id) => api.delete(`/instances/${id}`, withTimeout(LONG_RUNNING_TIMEOUT)),
  start: (id) => api.post(`/instances/${id}/start`, null, withTimeout(LONG_RUNNING_TIMEOUT)),
  stop: (id) => api.post(`/instances/${id}/stop`, null, withTimeout(LONG_RUNNING_TIMEOUT)),
  restart: (id) => api.post(`/instances/${id}/restart`, null, withTimeout(LONG_RUNNING_TIMEOUT)),
  schedule: (id, data) => api.put(`/instances/${id}/schedule`, data),
  getEvents: (id) => api.get(`/instances/${id}/events`),
  getNodeLogs: (instanceId, nodeId) => api.get(`/instances/${instanceId}/nodes/${nodeId}/logs`),
  batchStart: (ids) => api.post('/instances/batch/start', { instance_ids: ids }, withTimeout(LONG_RUNNING_TIMEOUT)),
  batchStop: (ids) => api.post('/instances/batch/stop', { instance_ids: ids }, withTimeout(LONG_RUNNING_TIMEOUT)),
  batchDelete: (ids) => api.post('/instances/batch/delete', { instance_ids: ids }, withTimeout(LONG_RUNNING_TIMEOUT)),
  reportMetric: (id, data) => api.post(`/instances/${id}/metrics`, data),
  templateMetricSummary: (templateId) =>
    api.get('/instances/metrics/template-summary', { params: templateId ? { template_id: templateId } : {} })
}

export const ordersApi = {
  list: (params = {}) => api.get('/orders', { params }),
  get: (id) => api.get(`/orders/${id}`),
  create: (data) => api.post('/orders', data),
  delete: (id) => api.delete(`/orders/${id}`),
  batchDelete: (ids) => api.post('/orders/batch/delete', { instance_ids: ids }),
  materialize: (id) => api.post(`/orders/${id}/materialize`),
  materializePending: () => api.post('/orders/materialize/pending'),
  submitRoutingResult: (id, data) => api.post(`/orders/${id}/routing-result`, data),
  cancel: (id) => api.post(`/orders/${id}/cancel`),
  batchBenchmark: (data) => api.post('/orders/batch-benchmark', data),
  batchAutoRoute: () => api.post('/orders/batch-auto-route'),
  startAllRouted: () => api.post('/orders/start-all-routed'),
}

export const businessApi = {
  submit: (data) => api.post('/business-tasks', data),
  list: (params = {}) => api.get('/business-tasks', { params }),
  summary: (params = {}) => api.get('/business-tasks/summary', { params }),
  evaluation: (instanceId) => api.get(`/business-tasks/${instanceId}/evaluation`),
  results: (instanceId) => api.get(`/business-tasks/${instanceId}/results`),
  catalog: () => api.get('/business-template-catalog'),
  createCatalog: (data) => api.post('/business-template-catalog', data)
}

export const baselinesApi = {
  list: (params = {}) => api.get('/baselines', { params }),
  create: (data) => api.post('/baselines', data),
  update: (id, data) => api.put(`/baselines/${id}`, data),
  delete: (id) => api.delete(`/baselines/${id}`),
  run: (data) => api.post('/baselines/run', data, { timeout: 120000 }),
  batchRun: (data) => api.post('/baselines/batch-run', data, { timeout: 300000 }),
}

export const authApi = {
  bootstrap: (data) => api.post('/auth/bootstrap', data),
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  me: () => api.get('/auth/me'),
  createUser: (data) => api.post('/auth/users', data)
}

export const conversationApi = {
  create: (data) => api.post('/conversations', data),
  list: () => api.get('/conversations'),
  get: (id) => api.get(`/conversations/${id}`),
  delete: (id) => api.delete(`/conversations/${id}`),
  sendMessage: (id, data) => api.post(`/conversations/${id}/messages`, data),
  updateDraft: (id, data) => api.patch(`/conversations/${id}/draft`, data),
  confirmIntent: (id) => api.post(`/conversations/${id}/confirm-intent`),
  cancel: (id) => api.post(`/conversations/${id}/cancel`),
  submit: (id, params = {}) =>
    api.post(`/conversations/${id}/submit`, null, {
      params: { auto_start: params.auto_start ?? false }
    }),
  createRoutingRequest: (data) => api.post('/routing-requests', data),
  getRoutingRequest: (id) => api.get(`/routing-requests/${id}`)
}

export const adminApi = {
  listUsers: () => api.get('/admin/users'),
  getUser: (id) => api.get(`/admin/users/${id}`),
  createUser: (data) => api.post('/admin/users', data),
  updateUser: (id, data) => api.put(`/admin/users/${id}`, data),
  deleteUser: (id) => api.delete(`/admin/users/${id}`),
  listConversations: (params = {}) => api.get('/admin/conversations', { params }),
  getConversation: (id) => api.get(`/admin/conversations/${id}`),
  listRoutingRequests: (params = {}) => api.get('/admin/routing-requests', { params }),
  listOrders: (params = {}) => api.get('/admin/orders', { params }),
  parseOne: (data) => api.post('/admin/intent-parser/parse-one', data),
}

export default api
