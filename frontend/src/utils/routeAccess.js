export const ADMIN_ROUTE_NAMES = new Set([
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

export const USER_ROUTE_NAMES = new Set([
  'IntentChat',
  'MyOrders',
])

export function homePathForRole(role) {
  return role === 'admin' ? '/business-tasks' : '/intent-chat'
}

export function resolvePostLoginTarget(router, rawRedirect, role) {
  const homePath = homePathForRole(role)
  const redirect = Array.isArray(rawRedirect) ? rawRedirect[0] : rawRedirect
  if (!redirect || typeof redirect !== 'string') return homePath

  const resolved = router.resolve(redirect)
  if (!resolved.name || resolved.name === 'Login' || resolved.name === 'Register') {
    return homePath
  }

  if (role === 'admin' && USER_ROUTE_NAMES.has(resolved.name)) {
    return homePath
  }

  if (role !== 'admin' && ADMIN_ROUTE_NAMES.has(resolved.name)) {
    return homePath
  }

  return resolved.fullPath || homePath
}
