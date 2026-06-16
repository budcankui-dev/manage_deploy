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

  function logout() {
    token.value = ''
    role.value = BYPASS ? BYPASS_ROLE : ''
    username.value = BYPASS ? BYPASS_USERNAME : ''
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
    login,
    register,
    bootstrap,
    logout,
  }
})
