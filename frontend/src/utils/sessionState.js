const SESSION_KEYS = [
  'access_token',
  'role',
  'username',
  'lastConversationId',
  'lastAdminRoute',
  'lastUserRoute',
]

function safeLocalStorage() {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function clearSessionState({ keepAuth = false } = {}) {
  const storage = safeLocalStorage()
  if (!storage) return
  const keys = keepAuth ? ['lastConversationId'] : SESSION_KEYS
  keys.forEach((key) => storage.removeItem(key))
}

export function setLastConversationId(id) {
  const storage = safeLocalStorage()
  if (!storage) return
  if (id) storage.setItem('lastConversationId', id)
  else storage.removeItem('lastConversationId')
}

export function getLastConversationId() {
  return safeLocalStorage()?.getItem('lastConversationId') || ''
}

function routeStorageKey(role) {
  return role === 'admin' ? 'lastAdminRoute' : 'lastUserRoute'
}

export function setLastRoute(role, fullPath) {
  const storage = safeLocalStorage()
  if (!storage || !fullPath) return
  storage.setItem(routeStorageKey(role), fullPath)
}

export function getLastRoute(role) {
  return safeLocalStorage()?.getItem(routeStorageKey(role)) || ''
}
