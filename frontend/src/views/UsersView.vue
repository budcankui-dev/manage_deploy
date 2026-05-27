<template>
  <div class="hub-view">
    <header class="page-header">
      <div>
        <h1>用户管理</h1>
        <p class="subtitle">管理系统用户账号、角色与权限。</p>
      </div>
      <div class="actions">
        <el-button @click="loadList">刷新</el-button>
        <el-button type="primary" @click="openCreateDialog">新建用户</el-button>
      </div>
    </header>

    <section class="card">
      <el-table :data="users" size="small" v-loading="listLoading" @row-click="openEditDialog">
        <el-table-column prop="username" label="用户名" min-width="160" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.role === 'admin' ? 'danger' : 'primary'">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="对话数" width="90">
          <template #default="{ row }">{{ row.conversation_count ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="工单数" width="90">
          <template #default="{ row }">{{ row.order_count ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openEditDialog(row)">详情</el-button>
            <el-popconfirm
              title="确认删除该用户？此操作不可撤销。"
              confirm-button-text="删除"
              cancel-button-text="取消"
              confirm-button-type="danger"
              @confirm="deleteUser(row)"
            >
              <template #reference>
                <el-button link type="danger" @click.stop>删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- Create user dialog -->
    <el-dialog v-model="createDialogVisible" title="新建用户" width="420px" destroy-on-close>
      <el-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="80px"
        @submit.prevent="submitCreate"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="createForm.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="createForm.password" type="password" placeholder="请输入密码" show-password />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="createForm.role" style="width: 100%">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createLoading" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- Edit user dialog -->
    <el-dialog
      v-model="editDialogVisible"
      :title="editUser ? `用户详情 — ${editUser.username}` : '用户详情'"
      width="480px"
      destroy-on-close
    >
      <div v-loading="editLoading">
        <el-descriptions :column="1" border class="detail-desc">
          <el-descriptions-item label="用户名">{{ editUser?.username }}</el-descriptions-item>
          <el-descriptions-item label="角色">
            <el-tag size="small" :type="editUser?.role === 'admin' ? 'danger' : 'primary'">
              {{ editUser?.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(editUser?.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="对话数">{{ editUserDetail?.conversation_count ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="工单数">{{ editUserDetail?.order_count ?? '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="edit-section">
          <h3 class="section-title">修改角色</h3>
          <div class="inline-action">
            <el-select v-model="newRole" style="width: 160px">
              <el-option label="普通用户" value="user" />
              <el-option label="管理员" value="admin" />
            </el-select>
            <el-button type="primary" :loading="roleLoading" @click="submitRoleChange">确认修改</el-button>
          </div>
        </div>

        <div class="edit-section">
          <h3 class="section-title">重置密码</h3>
          <div class="inline-action">
            <el-input
              v-model="newPassword"
              type="password"
              placeholder="输入新密码"
              show-password
              style="width: 220px"
            />
            <el-button type="warning" :loading="passwordLoading" @click="submitPasswordReset">确认重置</el-button>
          </div>
        </div>

        <div class="edit-section">
          <h3 class="section-title">危险操作</h3>
          <el-popconfirm
            title="确认删除该用户？此操作不可撤销。"
            confirm-button-text="删除"
            cancel-button-text="取消"
            confirm-button-type="danger"
            @confirm="deleteUserFromEdit"
          >
            <template #reference>
              <el-button type="danger" plain>删除用户</el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>
      <template #footer>
        <el-button @click="editDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api/index.js'

// --- List ---
const users = ref([])
const listLoading = ref(false)

async function loadList() {
  listLoading.value = true
  try {
    const res = await adminApi.listUsers()
    users.value = Array.isArray(res.data) ? res.data : (res.data?.items ?? [])
  } finally {
    listLoading.value = false
  }
}

function formatTime(val) {
  if (!val) return '-'
  return new Date(val).toLocaleString('zh-CN', { hour12: false })
}

// --- Create dialog ---
const createDialogVisible = ref(false)
const createLoading = ref(false)
const createFormRef = ref(null)
const createForm = reactive({ username: '', password: '', role: 'user' })
const createRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function openCreateDialog() {
  createForm.username = ''
  createForm.password = ''
  createForm.role = 'user'
  createDialogVisible.value = true
}

async function submitCreate() {
  if (!createFormRef.value) return
  await createFormRef.value.validate()
  createLoading.value = true
  try {
    await adminApi.createUser({ ...createForm })
    ElMessage.success('用户创建成功')
    createDialogVisible.value = false
    loadList()
  } finally {
    createLoading.value = false
  }
}

// --- Edit dialog ---
const editDialogVisible = ref(false)
const editLoading = ref(false)
const editUser = ref(null)
const editUserDetail = ref(null)
const newRole = ref('user')
const newPassword = ref('')
const roleLoading = ref(false)
const passwordLoading = ref(false)

async function openEditDialog(row) {
  editUser.value = { ...row }
  newRole.value = row.role
  newPassword.value = ''
  editUserDetail.value = null
  editDialogVisible.value = true
  editLoading.value = true
  try {
    const res = await adminApi.getUser(row.id)
    editUserDetail.value = res.data
    editUser.value = { ...row, ...res.data }
    newRole.value = editUser.value.role
  } finally {
    editLoading.value = false
  }
}

async function submitRoleChange() {
  if (!editUser.value) return
  roleLoading.value = true
  try {
    await adminApi.updateUser(editUser.value.id, { role: newRole.value })
    ElMessage.success('角色已更新')
    editUser.value = { ...editUser.value, role: newRole.value }
    loadList()
  } finally {
    roleLoading.value = false
  }
}

async function submitPasswordReset() {
  if (!newPassword.value) { ElMessage.warning('请输入新密码'); return }
  passwordLoading.value = true
  try {
    await adminApi.updateUser(editUser.value.id, { password: newPassword.value })
    ElMessage.success('密码已重置')
    newPassword.value = ''
  } finally {
    passwordLoading.value = false
  }
}

async function deleteUser(row) {
  await adminApi.deleteUser(row.id)
  ElMessage.success('用户已删除')
  loadList()
}

async function deleteUserFromEdit() {
  if (!editUser.value) return
  await adminApi.deleteUser(editUser.value.id)
  ElMessage.success('用户已删除')
  editDialogVisible.value = false
  loadList()
}

onMounted(loadList)
</script>

<style scoped>
.hub-view {
  max-width: 1100px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.page-header h1 {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 14px;
}

.actions {
  display: flex;
  gap: 8px;
}

.card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 20px;
}

.detail-desc {
  margin-bottom: 8px;
}

.edit-section {
  margin-top: 20px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 10px;
}

.inline-action {
  display: flex;
  gap: 10px;
  align-items: center;
}
</style>
