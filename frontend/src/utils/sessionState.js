const SESSION_KEYS = [
  'access_token',
  'role',
  'username',
  'lastConversationId',
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

