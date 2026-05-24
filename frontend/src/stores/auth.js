import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api'

const BYPASS = import.meta.env.VITE_AUTH_BYPASS === 'true'
const BYPASS_ROLE = import.meta.env.VITE_AUTH_BYPASS_ROLE || 'admin'
const BYPASS_USERNAME = import.meta.env.VITE_AUTH_BYPASS_USERNAME || 'dev'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const role = ref(localStorage.getItem('role') || (BYPASS ? BYPASS_ROLE : ''))
  const username = ref(localStorage.getItem('username') || (BYPASS ? BYPASS_USERNAME : ''))

  const isBypass = computed(() => BYPASS)
  const isAuthenticated = computed(() => Boolean(token.value) || isBypass.value)
  const isAdmin = computed(() => role.value === 'admin')
  const homePath = computed(() => (isAdmin.value ? '/instances' : '/intent-chat'))

  function persist(auth) {
    token.value = auth.access_token || ''
    role.value = auth.role || ''
    username.value = auth.username || username.value
    if (token.value) localStorage.setItem('access_token', token.value)
    if (role.value) localStorage.setItem('role', role.value)
    if (username.value) localStorage.setItem('username', username.value)
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
    localStorage.removeItem('access_token')
    localStorage.removeItem('role')
    localStorage.removeItem('username')
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
