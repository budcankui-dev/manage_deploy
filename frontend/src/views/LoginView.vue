<template>
  <div class="auth-page">
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
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api'

const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function handleLogin() {
  loading.value = true
  try {
    const { data } = await authApi.login(form)
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('role', data.role)
    ElMessage.success('登录成功')
    router.push(data.role === 'admin' ? '/business-tasks' : '/intent-chat')
  } finally {
    loading.value = false
  }
}

async function handleBootstrap() {
  loading.value = true
  try {
    await authApi.bootstrap({ ...form, role: 'admin' })
    ElMessage.success('管理员已初始化，请登录')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  max-width: 520px;
  margin: 80px auto;
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
</style>
