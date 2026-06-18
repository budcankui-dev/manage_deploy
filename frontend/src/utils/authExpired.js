import { ElMessage } from 'element-plus'
import { clearSessionState } from '@/utils/sessionState'

let redirecting = false
const NOTICE_KEY = 'authExpiredNotice'

function safeSessionStorage() {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function consumeAuthExpiredNotice() {
  const storage = safeSessionStorage()
  if (!storage?.getItem(NOTICE_KEY)) return false
  storage.removeItem(NOTICE_KEY)
  return true
}

export function handleAuthExpired() {
  clearSessionState()

  if (redirecting) return
  redirecting = true

  safeSessionStorage()?.setItem(NOTICE_KEY, '1')

  const currentPath = `${window.location.pathname}${window.location.search}`
  if (window.location.pathname === '/login' || window.location.pathname === '/register') {
    ElMessage.warning('登录已过期，请重新登录')
    redirecting = false
    return
  }

  const target = `/login?redirect=${encodeURIComponent(currentPath)}`
  window.location.href = target
}

export function resetAuthExpiredRedirecting() {
  redirecting = false
}
