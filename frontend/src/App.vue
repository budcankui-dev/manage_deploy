<template>
  <div class="app-container" :class="{ 'plain-container': !showAdminShell }">
    <aside v-if="showAdminShell" class="sidebar">
      <div class="logo">
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
          <rect x="2" y="2" width="28" height="28" rx="6" stroke="currentColor" stroke-width="2"/>
          <circle cx="10" cy="10" r="3" fill="currentColor"/>
          <circle cx="22" cy="10" r="3" fill="currentColor"/>
          <circle cx="16" cy="22" r="3" fill="currentColor"/>
          <line x1="10" y1="13" x2="16" y2="19" stroke="currentColor" stroke-width="2"/>
          <line x1="22" y1="13" x2="16" y2="19" stroke="currentColor" stroke-width="2"/>
        </svg>
        <span>任务编排</span>
      </div>
      <nav class="nav-menu">
        <button
          v-for="item in adminMenuItems"
          :key="item.path"
          class="nav-item"
          :class="{ active: isActivePath(item.path) }"
          type="button"
          @click="goAdminPage(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </button>
      </nav>
      <div class="sidebar-footer">
        <div class="account-row">
          <el-icon><User /></el-icon>
          <span>{{ auth.username || auth.role }}</span>
        </div>
        <div class="status-indicator">
          <span class="dot"></span>
          <span class="text">系统就绪</span>
        </div>
        <el-button size="small" text @click="logout">退出登录</el-button>
      </div>
    </aside>
    <main class="main-content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { cleanupStaleElementOverlays } from '@/utils/staleOverlayCleanup'
import {
  DataAnalysis,
  DataLine,
  Document,
  List,
  Monitor,
  Setting,
  TrendCharts,
  UserFilled,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const showAdminShell = computed(() =>
  auth.isAuthenticated && auth.isAdmin && !auth.needsTokenValidation && !route.meta.public
)
const adminMenuItems = [
  { path: '/business-tasks', label: '业务任务中心', icon: DataAnalysis },
  { path: '/benchmark', label: '业务测评', icon: TrendCharts },
  { path: '/intent-evaluation', label: '意图评测', icon: DataLine },
  { path: '/nodes', label: '拓扑节点', icon: Monitor },
  { path: '/templates', label: '任务模板', icon: Document },
  { path: '/dev/instances', label: '运维 / 手动部署', icon: List },
  { path: '/users', label: '用户管理', icon: UserFilled },
  { path: '/settings', label: '系统设置', icon: Setting },
]

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    cleanupStaleElementOverlays()
    setTimeout(cleanupStaleElementOverlays, 300)
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

watch(
  () => route.fullPath,
  () => {
    setTimeout(cleanupStaleElementOverlays, 0)
    setTimeout(cleanupStaleElementOverlays, 300)
  }
)

function isActivePath(path) {
  return route.path === path || (path !== '/' && route.path.startsWith(`${path}/`))
}

async function goAdminPage(path) {
  if (route.path === path) return
  try {
    await router.push(path)
  } catch (err) {
    if (err?.name !== 'NavigationDuplicated') {
      ElMessage.warning('页面跳转失败，请刷新后重试')
    }
  }
}

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<style>
:root {
  --bg-primary: #0c0c0f;
  --bg-secondary: #131318;
  --bg-tertiary: #1a1a21;
  --bg-elevated: #22222b;
  --border-subtle: rgba(255, 255, 255, 0.06);
  --border-active: rgba(255, 255, 255, 0.12);
  --text-primary: #f0f0f5;
  --text-secondary: #8888a0;
  --text-muted: #55556a;
  --accent-primary: #6366f1;
  --accent-secondary: #818cf8;
  --accent-glow: rgba(99, 102, 241, 0.4);
  --success: #22c55e;
  --warning: #f59e0b;
  --danger: #ef4444;
  --info: #3b82f6;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  height: 100%;
  font-family: 'Outfit', sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
}

body::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

body::-webkit-scrollbar-track {
  background: var(--bg-secondary);
}

body::-webkit-scrollbar-thumb {
  background: var(--bg-elevated);
  border-radius: 3px;
}

body::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

.app-container {
  display: flex;
  height: 100vh;
  background: var(--bg-primary);
  isolation: isolate;
}

.app-container.plain-container {
  display: block;
  overflow: hidden;
}

.sidebar {
  width: 220px;
  flex: 0 0 220px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  padding: 24px 16px;
  position: relative;
  z-index: 20;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--accent-primary);
  padding: 0 8px 24px;
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 24px;
}

.logo span {
  font-weight: 600;
  font-size: 18px;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}

.nav-menu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px 16px;
  border-radius: 10px;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  font-family: inherit;
  text-align: left;
  transition: all 0.2s ease;
  position: relative;
  z-index: 1;
  cursor: pointer;
  user-select: none;
}

.nav-item:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--accent-primary);
  color: white;
  box-shadow: 0 4px 20px var(--accent-glow);
}

.sidebar-footer {
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle);
}

.account-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
}

.status-indicator .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
}

.status-indicator .text {
  font-size: 12px;
  color: var(--text-muted);
}

.main-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 32px;
  position: relative;
  z-index: 1;
}

.plain-container .main-content {
  height: 100vh;
  padding: 0;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
