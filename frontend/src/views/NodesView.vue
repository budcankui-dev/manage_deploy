<template>
  <div class="nodes-view">
    <header class="page-header">
      <div class="title-section">
        <h1>工作节点</h1>
        <p class="subtitle">管理运行任务容器的工作节点</p>
      </div>
      <div class="header-actions">
        <span class="selected-count" v-if="selectedIds.length">已选 {{ selectedIds.length }} 项</span>
        <el-button type="danger" plain :disabled="!selectedIds.length" @click="batchDeleteNodes">批量删除</el-button>
        <el-button type="primary" @click="showDialog = true">
          <el-icon><Plus /></el-icon>
          新增节点
        </el-button>
      </div>
    </header>

    <div class="nodes-grid" v-if="nodes.length">
      <div
        v-for="node in paginatedNodes"
        :key="node.id"
        class="node-card"
      >
        <div class="node-header">
          <el-checkbox :model-value="selectedIds.includes(node.id)" @change="toggleSelected(node.id)" />
          <div class="node-icon">
            <el-icon><Monitor /></el-icon>
          </div>
          <div class="node-info">
            <h3>{{ node.hostname }}</h3>
            <span class="status-badge" :class="node.status">
              已注册
            </span>
            <el-tag v-if="node.node_kind" size="small" :type="nodeKindTagType(node.node_kind)" style="margin-left: 8px">
              {{ nodeKindLabel(node.node_kind) }}
            </el-tag>
            <el-tag v-if="node.is_schedulable === false" size="small" type="info" style="margin-left: 4px">不可调度</el-tag>
          </div>
          <el-dropdown trigger="click">
            <el-button text circle>
              <el-icon><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="editNode(node)">
                  <el-icon><Edit /></el-icon>
                  编辑
                </el-dropdown-item>
                <el-dropdown-item @click="openOrphanDialog(node)">
                  <el-icon><Warning /></el-icon>
                  孤儿容器
                </el-dropdown-item>
                <el-dropdown-item divided @click="confirmDelete(node)">
                  <el-icon><Delete /></el-icon>
                  删除
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div class="node-details">
          <div class="detail-row">
            <span class="label">管理 IP</span>
            <span class="value mono">{{ node.management_ip }}</span>
          </div>
          <div class="detail-row">
            <span class="label">业务 IPv4</span>
            <span class="value mono">{{ node.business_ip }}</span>
          </div>
          <div v-if="node.business_ipv6" class="detail-row">
            <span class="label">业务 IPv6</span>
            <span class="value mono">{{ node.business_ipv6 }}</span>
          </div>
          <div class="detail-row">
            <span class="label">Agent 地址</span>
            <span class="value mono truncate">{{ node.agent_address }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="empty-state" v-else>
      <div class="empty-icon">
        <el-icon><Connection /></el-icon>
      </div>
      <h3>还没有注册节点</h3>
      <p>先添加一个工作节点，才能开始分发任务容器</p>
      <el-button type="primary" @click="showDialog = true">
        <el-icon><Plus /></el-icon>
        添加第一个节点
      </el-button>
    </div>

    <div v-if="nodes.length" class="pagination-wrap">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        background
        layout="total, sizes, prev, pager, next"
        :page-sizes="[8, 12, 20, 50]"
        :total="nodes.length"
      />
    </div>

    <el-dialog
      v-model="showDialog"
      :title="editingNode ? '编辑节点' : '新增节点'"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-position="top" ref="formRef">
        <el-form-item label="主机名" required>
          <el-input v-model="form.hostname" placeholder="worker-1" />
        </el-form-item>
        <el-form-item label="管理 IP" required>
          <el-input v-model="form.management_ip" placeholder="192.168.1.100" />
        </el-form-item>
        <el-form-item label="业务 IP (IPv4)" required>
          <el-input v-model="form.business_ip" placeholder="10.0.1.100" />
        </el-form-item>
        <el-form-item label="业务 IPv6（验收/生产互访）">
          <el-input v-model="form.business_ipv6" placeholder="2001:db8:1::a" />
        </el-form-item>
        <el-form-item label="Agent 地址" required>
          <el-input v-model="form.agent_address" placeholder="http://192.168.1.100:8001" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">
          {{ editingNode ? '更新' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showOrphanDialog"
      title="孤儿容器巡检"
      width="860px"
      :close-on-click-modal="false"
    >
      <div class="orphan-toolbar">
        <div class="orphan-summary">
          <strong>{{ orphanNode?.hostname || '-' }}</strong>
          <span v-if="orphanContainers.length">发现 {{ orphanContainers.length }} 个孤儿容器</span>
          <span v-else>当前没有孤儿容器</span>
        </div>
        <div class="orphan-actions">
          <el-button @click="refreshOrphans" :loading="orphanLoading">刷新</el-button>
          <el-button type="danger" plain :disabled="!selectedOrphanNames.length" @click="cleanupSelectedOrphans">
            清理已选
          </el-button>
          <el-button type="danger" :disabled="!orphanContainers.length" @click="cleanupAllOrphans">
            一键清理全部
          </el-button>
        </div>
      </div>

      <el-table :data="orphanContainers" v-loading="orphanLoading" size="small">
        <el-table-column width="64">
          <template #default="{ row }">
            <el-checkbox :model-value="selectedOrphanNames.includes(row.container_name)" @change="toggleOrphanSelected(row.container_name)" />
          </template>
        </el-table-column>
        <el-table-column prop="container_name" label="容器名" min-width="280" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="image" label="镜像" min-width="160" />
        <el-table-column prop="reason" label="原因" min-width="220" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useNodesStore } from '@/stores/nodes'
import { nodesApi } from '@/api'
import { ElMessageBox, ElMessage } from 'element-plus'

const store = useNodesStore()
const { nodes } = storeToRefs(store)
const { fetchNodes, createNode, updateNode, deleteNode } = store

const showDialog = ref(false)
const editingNode = ref(null)
const submitting = ref(false)
const formRef = ref(null)
const selectedIds = ref([])
const currentPage = ref(1)
const pageSize = ref(8)
const showOrphanDialog = ref(false)
const orphanNode = ref(null)
const orphanContainers = ref([])
const selectedOrphanNames = ref([])
const orphanLoading = ref(false)

const form = ref({
  hostname: '',
  management_ip: '',
  business_ip: '',
  business_ipv6: '',
  agent_address: ''
})

onMounted(() => {
  fetchNodes()
})

const paginatedNodes = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return (nodes.value || []).slice(start, start + pageSize.value)
})

function nodeKindLabel(kind) {
  const labels = { worker: '计算节点', terminal: '终端节点', both: '计算+终端', router: '路由设备', switch: '交换机', storage: '存储节点' }
  return labels[kind] || kind || '未知'
}
function nodeKindTagType(kind) {
  const types = { worker: 'primary', terminal: 'success', both: 'warning', router: 'warning', switch: 'info', storage: '' }
  return types[kind] || 'info'
}

function toggleSelected(id) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function editNode(node) {
  editingNode.value = node
  form.value = { ...node }
  showDialog.value = true
}

async function submitForm() {
  submitting.value = true
  try {
    if (editingNode.value) {
      await updateNode(editingNode.value.id, form.value)
      ElMessage.success('节点已更新')
    } else {
      await createNode(form.value)
      ElMessage.success('节点已创建')
    }
    showDialog.value = false
    editingNode.value = null
    form.value = { hostname: '', management_ip: '', business_ip: '', business_ipv6: '', agent_address: '' }
  } finally {
    submitting.value = false
  }
}

async function confirmDelete(node) {
  try {
    await ElMessageBox.confirm(
      `确认删除节点 ${node.hostname} 吗？此操作不可撤销。`,
      '删除节点',
      { type: 'warning' }
    )
    await deleteNode(node.id)
    selectedIds.value = selectedIds.value.filter((id) => id !== node.id)
    ElMessage.success('节点已删除')
  } catch {
    // Cancelled
  }
}

async function batchDeleteNodes() {
  await ElMessageBox.confirm(`确认删除选中的 ${selectedIds.value.length} 个节点吗？`, '批量删除节点', { type: 'warning' })
  for (const id of [...selectedIds.value]) {
    await deleteNode(id)
  }
  selectedIds.value = []
  ElMessage.success('批量删除完成')
}

async function openOrphanDialog(node) {
  orphanNode.value = node
  selectedOrphanNames.value = []
  showOrphanDialog.value = true
  await refreshOrphans()
}

async function refreshOrphans() {
  if (!orphanNode.value?.id) return
  orphanLoading.value = true
  try {
    const { data } = await nodesApi.listOrphans(orphanNode.value.id)
    orphanContainers.value = data
    selectedOrphanNames.value = selectedOrphanNames.value.filter((name) =>
      data.some((item) => item.container_name === name)
    )
  } finally {
    orphanLoading.value = false
  }
}

function toggleOrphanSelected(containerName) {
  if (selectedOrphanNames.value.includes(containerName)) {
    selectedOrphanNames.value = selectedOrphanNames.value.filter((name) => name !== containerName)
  } else {
    selectedOrphanNames.value = [...selectedOrphanNames.value, containerName]
  }
}

async function cleanupSelectedOrphans() {
  if (!orphanNode.value?.id || !selectedOrphanNames.value.length) return
  await ElMessageBox.confirm(`确认清理选中的 ${selectedOrphanNames.value.length} 个孤儿容器吗？`, '清理孤儿容器', { type: 'warning' })
  const { data } = await nodesApi.cleanupOrphans(orphanNode.value.id, selectedOrphanNames.value)
  if (Object.keys(data.failed || {}).length) {
    const firstFailure = Object.values(data.failed)[0]
    ElMessage.warning(`已清理 ${data.succeeded.length} 个，失败 ${Object.keys(data.failed).length} 个：${firstFailure}`)
  } else {
    ElMessage.success(`已清理 ${data.succeeded.length} 个孤儿容器`)
  }
  await refreshOrphans()
}

async function cleanupAllOrphans() {
  if (!orphanNode.value?.id || !orphanContainers.value.length) return
  await ElMessageBox.confirm(`确认清理节点 ${orphanNode.value.hostname} 上的全部孤儿容器吗？`, '一键清理孤儿容器', { type: 'warning' })
  const { data } = await nodesApi.cleanupOrphans(orphanNode.value.id)
  if (Object.keys(data.failed || {}).length) {
    const firstFailure = Object.values(data.failed)[0]
    ElMessage.warning(`已清理 ${data.succeeded.length} 个，失败 ${Object.keys(data.failed).length} 个：${firstFailure}`)
  } else {
    ElMessage.success(`已清理 ${data.succeeded.length} 个孤儿容器`)
  }
  await refreshOrphans()
}
</script>

<style scoped>
.nodes-view {
  max-width: 1400px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
}

.title-section h1 {
  font-size: 28px;
  font-weight: 600;
  margin-bottom: 4px;
  letter-spacing: -0.02em;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 14px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.selected-count {
  color: var(--text-secondary);
  font-size: 13px;
}

.nodes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 20px;
}

.node-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  padding: 20px;
  transition: all 0.2s ease;
}

.node-card:hover {
  border-color: var(--border-active);
  transform: translateY(-2px);
}

.node-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
}

.node-icon {
  width: 44px;
  height: 44px;
  background: var(--accent-primary);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 20px;
}

.node-info {
  flex: 1;
}

.node-info h3 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 4px;
}

.status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(34, 197, 94, 0.15);
  color: var(--success);
  font-weight: 500;
}

.node-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.detail-row .label {
  color: var(--text-muted);
}

.detail-row .value {
  color: var(--text-secondary);
}

.detail-row .value.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.detail-row .value.truncate {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-state {
  text-align: center;
  padding: 80px 40px;
  background: var(--bg-secondary);
  border-radius: 20px;
  border: 1px dashed var(--border-subtle);
}

.empty-icon {
  width: 72px;
  height: 72px;
  background: var(--bg-tertiary);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 20px;
  font-size: 32px;
  color: var(--text-muted);
}

.empty-state h3 {
  font-size: 18px;
  margin-bottom: 8px;
}

.empty-state p {
  color: var(--text-secondary);
  margin-bottom: 24px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 18px;
}

.orphan-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}

.orphan-summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--text-secondary);
}

.orphan-actions {
  display: flex;
  gap: 8px;
}
</style>
