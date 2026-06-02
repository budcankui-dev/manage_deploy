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
        <router-link to="/business-tasks" class="nav-item">
          <el-icon><DataAnalysis /></el-icon>
          <span>业务任务中心</span>
        </router-link>
        <router-link to="/benchmark" class="nav-item">
          <el-icon><TrendCharts /></el-icon>
          <span>验收测试</span>
        </router-link>
        <router-link to="/nodes" class="nav-item">
          <el-icon><Monitor /></el-icon>
          <span>工作节点</span>
        </router-link>
        <router-link to="/templates" class="nav-item">
          <el-icon><Document /></el-icon>
          <span>任务模板</span>
        </router-link>
        <router-link to="/dev/instances" class="nav-item">
          <el-icon><List /></el-icon>
          <span>运维 / 手动部署</span>
        </router-link>
        <router-link to="/users" class="nav-item">
          <el-icon><UserFilled /></el-icon>
          <span>用户管理</span>
        </router-link>
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
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const showAdminShell = computed(() => auth.isAuthenticated && auth.isAdmin && !route.meta.public)

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
}

.app-container.plain-container {
  display: block;
  overflow: hidden;
}

.sidebar {
  width: 220px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  padding: 24px 16px;
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
  padding: 12px 16px;
  border-radius: 10px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s ease;
}

.nav-item:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.nav-item.router-link-active {
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
  overflow-y: auto;
  padding: 32px;
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
