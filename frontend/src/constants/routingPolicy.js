export const ROUTING_POLICY_OPTIONS = [
  { value: 'cost_priority', label: '成本开销保障' },
  { value: 'low_latency_forwarding', label: '低时延转发' },
  { value: 'resource_guarantee', label: '资源预留保障' },
  { value: 'fastest_completion', label: '完成时间优先' },
  { value: 'load_balance', label: '资源负载均衡' },
]

export const ROUTING_POLICY_LABELS = Object.fromEntries(
  ROUTING_POLICY_OPTIONS.map((item) => [item.value, item.label])
)

export function routingPolicyLabel(policy) {
  if (!policy) return '-'
  return ROUTING_POLICY_LABELS[policy] || policy
}

export const ORDER_STATUS_LABELS = {
  pending: '待分配',
  awaiting_routing: '待分配',
  routed: '待部署',
  materialized: '已部署',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export const DEPLOYMENT_STATUS_LABELS = {
  pending: '待启动',
  scheduled: '已调度',
  starting: '启动中',
  running: '运行中',
  stopping: '停止中',
  stopped: '已停止',
  failed: '失败',
  expired: '已过期',
}
