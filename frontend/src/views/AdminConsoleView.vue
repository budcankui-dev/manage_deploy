<template>
  <div class="admin-page">
    <header class="page-header">
      <h1>管理控制台</h1>
    </header>
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <el-tab-pane label="用户管理" name="users">
        <el-table :data="users" stripe border size="small">
          <el-table-column prop="username" label="用户名" width="160" />
          <el-table-column prop="role" label="角色" width="100">
            <template #default="{ row }">
              <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">{{ row.role }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="id" label="ID" width="300" />
          <el-table-column prop="created_at" label="创建时间">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button size="small" type="danger" text :disabled="row.role === 'admin'" @click="deleteUser(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="对话审计" name="conversations">
        <div class="filter-bar">
          <el-select v-model="convFilter.status" placeholder="状态" clearable size="small" @change="loadConversations">
            <el-option label="草稿中" value="drafting" />
            <el-option label="待分配" value="awaiting_routing" />
            <el-option label="待部署" value="ready_to_submit" />
            <el-option label="已提交" value="submitted" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-pagination small :total="convTotal" v-model:current-page="convFilter.page" :page-size="20" @current-change="loadConversations" />
        </div>
        <el-table :data="conversations" stripe border size="small" @row-click="showConvDetail">
          <el-table-column prop="title" label="标题" min-width="160" />
          <el-table-column prop="status" label="状态" width="120">
            <template #default="{ row }"><el-tag size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="user_id" label="用户ID" width="140">
            <template #default="{ row }">{{ row.user_id?.slice(0, 8) }}...</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="160">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="路由审计" name="routing">
        <div class="filter-bar">
          <el-select v-model="routingFilter.status" placeholder="状态" clearable size="small" @change="loadRouting">
            <el-option label="等待" value="pending" />
            <el-option label="计算中" value="computing" />
            <el-option label="等待网络确认" value="network_binding_ready" />
            <el-option label="完成" value="completed" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-pagination small :total="routingTotal" v-model:current-page="routingFilter.page" :page-size="20" @current-change="loadRouting" />
        </div>
        <el-table :data="routingRequests" stripe border size="small">
          <el-table-column prop="id" label="ID" width="140">
            <template #default="{ row }">{{ row.id?.slice(0, 8) }}...</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="routingTagType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="source_name" label="源" width="120" />
          <el-table-column prop="destination_name" label="目的" width="120" />
          <el-table-column prop="selected_strategy" label="策略" width="140" />
          <el-table-column prop="created_at" label="创建时间" width="160">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="completed_at" label="完成时间" width="160">
            <template #default="{ row }">{{ formatTime(row.completed_at) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="意图解析测试" name="parser">
        <div class="parser-test">
          <el-input v-model="parserInput" type="textarea" :rows="3" placeholder="输入自然语言描述，如：矩阵计算，从 nodeA 到 nodeB，现在开始跑2小时，延迟 60000ms" />
          <el-button type="primary" @click="testParse" :loading="parserLoading" style="margin-top:10px">解析</el-button>
          <div v-if="parserResult" class="parser-result">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="task_type">{{ parserResult.task_type || '-' }}</el-descriptions-item>
              <el-descriptions-item label="parse_status">
                <el-tag :type="parserResult.parse_status === 'valid' ? 'success' : 'warning'" size="small">{{ parserResult.parse_status }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="source_name">{{ parserResult.source_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="destination_name">{{ parserResult.destination_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="business_start_time">{{ parserResult.business_start_time || '-' }}</el-descriptions-item>
              <el-descriptions-item label="business_end_time">{{ parserResult.business_end_time || '-' }}</el-descriptions-item>
              <el-descriptions-item label="parser">{{ parserResult.parser_name }} v{{ parserResult.parser_version }}</el-descriptions-item>
              <el-descriptions-item label="assistant_message" :span="2">{{ parserResult.assistant_message }}</el-descriptions-item>
            </el-descriptions>
            <div v-if="parserResult.validation_errors?.length" style="margin-top:8px">
              <el-alert v-for="(e, i) in parserResult.validation_errors" :key="i" :title="e" type="warning" :closable="false" show-icon />
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '@/api'

const activeTab = ref('users')
const users = ref([])
const conversations = ref([])
const convTotal = ref(0)
const convFilter = reactive({ status: '', page: 1 })
const routingRequests = ref([])
const routingTotal = ref(0)
const routingFilter = reactive({ status: '', page: 1 })
const parserInput = ref('')
const parserResult = ref(null)
const parserLoading = ref(false)

function formatTime(v) {
  if (!v) return '-'
  return new Date(v).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function routingTagType(status) {
  return {
    pending: 'warning',
    computing: 'warning',
    network_binding_ready: 'primary',
    completed: 'success',
    failed: 'danger',
  }[status] || 'info'
}

async function loadUsers() {
  const { data } = await adminApi.listUsers()
  users.value = data
}

async function deleteUser(row) {
  await ElMessageBox.confirm(`确认删除用户 ${row.username}？`, '警告', { type: 'warning' })
  await adminApi.deleteUser(row.id)
  ElMessage.success('已删除')
  await loadUsers()
}

async function loadConversations() {
  const params = { page: convFilter.page, page_size: 20 }
  if (convFilter.status) params.status = convFilter.status
  const { data } = await adminApi.listConversations(params)
  conversations.value = data.items
  convTotal.value = data.total
}

function showConvDetail(row) {
  ElMessage.info(`对话 ${row.id?.slice(0, 8)}... 详情功能待实现`)
}

async function loadRouting() {
  const params = { page: routingFilter.page, page_size: 20 }
  if (routingFilter.status) params.status = routingFilter.status
  const { data } = await adminApi.listRoutingRequests(params)
  routingRequests.value = data.items
  routingTotal.value = data.total
}

async function testParse() {
  if (!parserInput.value.trim()) return
  parserLoading.value = true
  try {
    const { data } = await adminApi.parseOne({ utterance: parserInput.value.trim() })
    parserResult.value = data
  } finally {
    parserLoading.value = false
  }
}

function onTabChange(tab) {
  if (tab === 'users') loadUsers()
  else if (tab === 'conversations') loadConversations()
  else if (tab === 'routing') loadRouting()
}

onMounted(loadUsers)
</script>

<style scoped>
.admin-page {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}
.page-header h1 {
  font-size: 22px;
  margin-bottom: 20px;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.parser-test {
  max-width: 800px;
}
.parser-result {
  margin-top: 16px;
}
</style>
