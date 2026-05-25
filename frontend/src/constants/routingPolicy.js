export const ROUTING_POLICY_LABELS = {
  resource_guarantee: '资源保障优先',
  completion_time_first: '完成时间优先',
  completion_time: '完成时间优先',
  load_balance: '负载均衡',
}

export function routingPolicyLabel(policy) {
  if (!policy) return '-'
  return ROUTING_POLICY_LABELS[policy] || policy
}

export const ORDER_STATUS_LABELS = {
  pending: '待处理',
  materialized: '已实例化',
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
