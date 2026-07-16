export function orderStatusLabel(order) {
  if (isRouteOnlyCompletedOrder(order)) return '路由已建立'
  if (isRouteOnlyNetworkPreparingOrder(order)) return '网络准备中'
  const status = getOrderStatus(order)
  return {
    pending: '待分配',
    routing: '分配中',
    routed: '待部署',
    materialized: '已生成实例/待启动',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    awaiting_routing: '待分配',
  }[status] || status || '-'
}

export function orderStatusType(order) {
  if (isRouteOnlyCompletedOrder(order)) return 'success'
  if (isRouteOnlyNetworkPreparingOrder(order)) return 'primary'
  const status = getOrderStatus(order)
  return {
    pending: 'info',
    routing: 'warning',
    routed: 'primary',
    materialized: 'warning',
    running: 'success',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
    awaiting_routing: 'info',
  }[status] || 'info'
}

export function routingStatusLabel(value, order = null) {
  if (isRouteOnlyCompletedOrder(order)) return '路由已建立'
  if (isRouteOnlyNetworkPreparingOrder(order)) return '网络准备中'
  return {
    not_required: '无需分配',
    pending: '待分配',
    computing: '分配中',
    network_binding_ready: '网络准备中',
    completed: '已完成分配',
    failed: '分配失败',
  }[value] || value || '-'
}

export function deploymentModeText(order) {
  const mode = order?.runtime_config?.platform_deployment?.mode
  if (mode === 'automated_benchmark') return '可控测评部署'
  if (mode === 'user_access_demo') return '用户端外部接入'
  if (mode === 'route_only') return '不创建平台受控容器'
  if (order?.is_benchmark) return '可控测评部署'
  return ''
}

export function isRouteOnlyOrder(order) {
  const deployment = order?.runtime_config?.platform_deployment
  const routingResult = order?.runtime_config?.routing_result || order?.routing_result
  return deployment?.mode === 'route_only' || routingResult?.route_only === true
}

export function isRouteOnlyCompletedOrder(order) {
  return isRouteOnlyActiveOrder(order)
    && order?.routing_status === 'completed'
}

export function isRouteOnlyNetworkPreparingOrder(order) {
  return isRouteOnlyActiveOrder(order)
    && order?.routing_status === 'network_binding_ready'
}

function isRouteOnlyActiveOrder(order) {
  const status = getOrderStatus(order)
  return status !== 'failed'
    && status !== 'cancelled'
    && isRouteOnlyOrder(order)
    && order?.materialized_instance_id == null
}

function getOrderStatus(order) {
  return order?.status || order?.order_status || ''
}
