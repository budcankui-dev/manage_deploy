<template>
  <div class="auth-page">
    <div class="auth-branding">
      <div class="brand-logo">智</div>
      <h1 class="brand-title">智联计算系统</h1>
      <p class="brand-subtitle">意图解析模块 · Intelligent Computing Intent Parser</p>
      <p class="brand-desc">智能解析计算任务意图，辅助完成任务分配与部署</p>
      <div class="model-badge">智能解析服务</div>
    </div>

    <el-card class="auth-card">
      <template #header>
        <div>
          <h2>登录</h2>
          <p>Admin 进入部署管理界面，普通用户进入意图解析对话界面。</p>
        </div>
      </template>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="admin" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <div class="actions">
          <el-button type="primary" :loading="loading" @click="handleLogin">登录</el-button>
          <el-button :loading="loading" @click="handleBootstrap">初始化管理员</el-button>
        </div>
        <p class="auth-link">
          还没有账号？
          <router-link to="/register">注册普通用户</router-link>
        </p>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { consumeAuthExpiredNotice, resetAuthExpiredRedirecting } from '@/utils/authExpired'
import { clearSessionState } from '@/utils/sessionState'
import { resolvePostLoginTarget } from '@/utils/routeAccess'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function handleLogin() {
  loading.value = true
  try {
    const data = await auth.login(form)
    clearSessionState({ keepAuth: true })
    ElMessage.success('登录成功')
    router.push(resolvePostLoginTarget(router, route.query.redirect, data.role || auth.role))
  } finally {
    loading.value = false
  }
}

async function handleBootstrap() {
  loading.value = true
  try {
    await auth.bootstrap(form)
    ElMessage.success('管理员已初始化，请登录')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  resetAuthExpiredRedirecting()
  if (consumeAuthExpiredNotice()) {
    ElMessage.warning('登录已过期，请重新登录')
  }
})
</script>

<style scoped>
.auth-page {
  max-width: 480px;
  margin: 60px auto;
  padding: 0 16px;
}

.auth-branding {
  text-align: center;
  margin-bottom: 32px;
}

.brand-logo {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 28px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
}

.brand-title {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--text-primary);
}

.brand-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 10px;
}

.brand-desc {
  font-size: 13px;
  color: var(--text-muted, #94a3b8);
  margin: 0 0 14px;
  line-height: 1.6;
}

.model-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 20px;
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #6366f1;
  font-size: 12px;
  font-weight: 500;
}

.auth-card h2 {
  margin: 0 0 8px;
}

.auth-card p {
  margin: 0;
  color: var(--text-secondary);
}

.actions {
  display: flex;
  gap: 12px;
}

.auth-link {
  margin-top: 16px !important;
  font-size: 13px;
}
</style>
