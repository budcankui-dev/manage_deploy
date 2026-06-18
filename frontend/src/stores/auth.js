import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api'
import { clearSessionState } from '@/utils/sessionState'

const BYPASS = import.meta.env.VITE_AUTH_BYPASS === 'true'
const BYPASS_ROLE = import.meta.env.VITE_AUTH_BYPASS_ROLE || 'admin'
const BYPASS_USERNAME = import.meta.env.VITE_AUTH_BYPASS_USERNAME || 'dev'

function safeLocalStorage() {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const storage = safeLocalStorage()
  const token = ref(storage?.getItem('access_token') || '')
  const role = ref(storage?.getItem('role') || (BYPASS ? BYPASS_ROLE : ''))
  const username = ref(storage?.getItem('username') || (BYPASS ? BYPASS_USERNAME : ''))

  const isBypass = computed(() => BYPASS)
  const isAuthenticated = computed(() => Boolean(token.value) || isBypass.value)
  const isAdmin = computed(() => role.value === 'admin')
  const homePath = computed(() => (isAdmin.value ? '/business-tasks' : '/intent-chat'))
  const needsTokenValidation = ref(Boolean(token.value) && !BYPASS)

  function persist(auth) {
    token.value = auth.access_token || ''
    role.value = auth.role || ''
    username.value = auth.username || username.value
    const currentStorage = safeLocalStorage()
    if (token.value) currentStorage?.setItem('access_token', token.value)
    if (role.value) currentStorage?.setItem('role', role.value)
    if (username.value) currentStorage?.setItem('username', username.value)
  }

  async function login(payload) {
    const { data } = await authApi.login(payload)
    persist({ ...data, username: payload.username })
    return data
  }

  async function register(payload) {
    return authApi.register({ ...payload, role: 'user' })
  }

  async function bootstrap(payload) {
    return authApi.bootstrap({ ...payload, role: 'admin' })
  }

  async function validateSession() {
    if (isBypass.value || !token.value) {
      needsTokenValidation.value = false
      return Boolean(token.value) || isBypass.value
    }

    try {
      const { data } = await authApi.me({ skipAuthExpired: true, silentError: true })
      role.value = data.role || role.value
      username.value = data.username || username.value
      const currentStorage = safeLocalStorage()
      if (role.value) currentStorage?.setItem('role', role.value)
      if (username.value) currentStorage?.setItem('username', username.value)
      needsTokenValidation.value = false
      return true
    } catch {
      logout()
      needsTokenValidation.value = false
      return false
    }
  }

  function logout() {
    token.value = ''
    role.value = BYPASS ? BYPASS_ROLE : ''
    username.value = BYPASS ? BYPASS_USERNAME : ''
    needsTokenValidation.value = false
    clearSessionState()
  }

  return {
    token,
    role,
    username,
    isBypass,
    isAuthenticated,
    isAdmin,
    homePath,
    needsTokenValidation,
    login,
    register,
    bootstrap,
    validateSession,
    logout,
  }
})
