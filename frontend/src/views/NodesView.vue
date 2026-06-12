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
        <el-button type="primary" @click="openCreateDialog">
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
            <el-tag v-if="node.node_kind && node.node_kind !== 'both'" size="small" :type="nodeKindTagType(node.node_kind)" style="margin-left: 8px">
              {{ nodeKindLabel(node.node_kind) }}
            </el-tag>
            <template v-if="node.node_kind === 'both'">
              <el-tag size="small" type="primary" style="margin-left: 8px">计算节点</el-tag>
              <el-tag size="small" type="success" style="margin-left: 4px">终端节点</el-tag>
            </template>
            <el-tag v-if="node.is_schedulable === false" size="small" type="info" style="margin-left: 4px">不可调度</el-tag>
            <el-tag v-if="node.is_routable === false" size="small" type="warning" style="margin-left: 4px">不参与路由</el-tag>
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
          <div class="resource-panel">
            <div class="resource-item">
              <span class="label">GPU</span>
              <span class="value">{{ formatGpu(node) }}</span>
            </div>
            <div class="resource-item">
              <span class="label">CPU</span>
              <span class="value">{{ formatCpu(node) }}</span>
            </div>
            <div class="resource-item">
              <span class="label">内存</span>
              <span class="value">{{ formatMemory(node.memory_mb) }}</span>
            </div>
            <div class="resource-item">
              <span class="label">驱动/CUDA</span>
              <span class="value">{{ formatRuntime(node) }}</span>
            </div>
          </div>
          <div v-if="node.resource_note" class="resource-note">{{ node.resource_note }}</div>
        </div>
      </div>
    </div>

    <div class="empty-state" v-else>
      <div class="empty-icon">
        <el-icon><Connection /></el-icon>
      </div>
      <h3>还没有注册节点</h3>
      <p>先添加一个工作节点，才能开始分发任务容器</p>
      <el-button type="primary" @click="openCreateDialog">
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
      width="760px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-position="top" ref="formRef">
        <div class="form-section-title">基础连接</div>
        <div class="form-grid">
          <el-form-item label="主机名" required>
            <el-input v-model="form.hostname" placeholder="worker-1" />
          </el-form-item>
          <el-form-item label="节点类型">
            <el-select v-model="form.node_kind" placeholder="选择节点类型">
              <el-option label="计算节点" value="worker" />
              <el-option label="终端节点" value="terminal" />
              <el-option label="计算+终端" value="both" />
              <el-option label="管理节点" value="admin" />
              <el-option label="路由设备" value="router" />
              <el-option label="交换机" value="switch" />
              <el-option label="存储节点" value="storage" />
            </el-select>
          </el-form-item>
          <el-form-item label="管理 IP" required>
            <el-input v-model="form.management_ip" placeholder="192.168.1.100" />
          </el-form-item>
          <el-form-item label="Agent 地址" required>
            <el-input v-model="form.agent_address" placeholder="http://192.168.1.100:8001" />
          </el-form-item>
          <el-form-item label="业务 IP (IPv4)" required>
            <el-input v-model="form.business_ip" placeholder="10.0.1.100" />
          </el-form-item>
          <el-form-item label="业务 IPv6（验收/生产互访）">
            <el-input v-model="form.business_ipv6" placeholder="2001:db8:1::a" />
          </el-form-item>
        </div>

        <div class="form-section-title">资源属性</div>
        <div class="form-grid">
          <el-form-item label="GPU 数量">
            <el-input-number v-model="form.gpu_count" :min="0" :max="16" controls-position="right" />
          </el-form-item>
          <el-form-item label="GPU 型号">
            <el-input v-model="form.gpu_model" placeholder="例如 NVIDIA TITAN X" />
          </el-form-item>
          <el-form-item label="单卡显存 MB">
            <el-input-number v-model="form.gpu_memory_mb" :min="0" :max="262144" controls-position="right" />
          </el-form-item>
          <el-form-item label="CPU 核数">
            <el-input-number v-model="form.cpu_cores" :min="0" :max="256" controls-position="right" />
          </el-form-item>
          <el-form-item label="CPU 型号">
            <el-input v-model="form.cpu_model" placeholder="例如 Intel Xeon ..." />
          </el-form-item>
          <el-form-item label="内存 MB">
            <el-input-number v-model="form.memory_mb" :min="0" :max="2097152" controls-position="right" />
          </el-form-item>
          <el-form-item label="NVIDIA 驱动版本">
            <el-input v-model="form.driver_version" placeholder="例如 535.183.01" />
          </el-form-item>
          <el-form-item label="CUDA 版本">
            <el-input v-model="form.cuda_version" placeholder="例如 12.2" />
          </el-form-item>
        </div>

        <div class="form-section-title">调度控制</div>
        <div class="form-grid compact">
          <el-form-item label="参与任务调度">
            <el-switch v-model="form.is_schedulable" active-text="参与" inactive-text="不参与" />
          </el-form-item>
          <el-form-item label="参与外部路由">
            <el-switch v-model="form.is_routable" active-text="参与" inactive-text="不参与" />
          </el-form-item>
        </div>
        <el-form-item label="资源备注">
          <el-input v-model="form.resource_note" type="textarea" :rows="2" placeholder="例如：验收 GPU 节点；视频业务需确认 CUDA 后端可用" />
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

const form = ref(defaultForm())

onMounted(() => {
  fetchNodes()
})

const paginatedNodes = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return (nodes.value || []).slice(start, start + pageSize.value)
})

function nodeKindLabel(kind) {
  const labels = { worker: '计算节点', terminal: '终端节点', both: '计算+终端', admin: '管理节点', router: '路由设备', switch: '交换机', storage: '存储节点' }
  return labels[kind] || kind || '未知'
}
function nodeKindTagType(kind) {
  const types = { worker: 'primary', terminal: 'success', both: 'primary', admin: 'danger', router: 'warning', switch: 'info', storage: '' }
  return types[kind] || 'info'
}

function defaultForm() {
  return {
    hostname: '',
    management_ip: '',
    business_ip: '',
    business_ipv6: '',
    agent_address: '',
    node_kind: 'worker',
    gpu_count: 0,
    gpu_model: '',
    gpu_memory_mb: null,
    cpu_model: '',
    cpu_cores: null,
    memory_mb: null,
    driver_version: '',
    cuda_version: '',
    resource_note: '',
    is_schedulable: true,
    is_routable: true
  }
}

function formatGpu(node) {
  const count = Number(node.gpu_count || 0)
  if (!count) return '无 GPU'
  const model = node.gpu_model || '未填写型号'
  const memory = node.gpu_memory_mb ? ` / ${formatMemory(node.gpu_memory_mb)}` : ''
  return `${count} × ${model}${memory}`
}

function formatCpu(node) {
  const cores = node.cpu_cores ? `${node.cpu_cores} 核` : '未填写核数'
  const model = node.cpu_model ? ` / ${node.cpu_model}` : ''
  return `${cores}${model}`
}

function formatMemory(value) {
  const mb = Number(value || 0)
  if (!mb) return '未填写'
  if (mb >= 1024) return `${(mb / 1024).toFixed(mb % 1024 === 0 ? 0 : 1)} GB`
  return `${mb} MB`
}

function formatRuntime(node) {
  const driver = node.driver_version || '驱动未填'
  const cuda = node.cuda_version || 'CUDA 未填'
  return `${driver} / ${cuda}`
}

function toggleSelected(id) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function openCreateDialog() {
  editingNode.value = null
  form.value = defaultForm()
  showDialog.value = true
}

function editNode(node) {
  editingNode.value = node
  form.value = { ...defaultForm(), ...node }
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
    form.value = defaultForm()
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

.resource-panel {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.resource-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.resource-item .label {
  color: var(--text-muted);
  font-size: 12px;
}

.resource-item .value {
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.resource-note {
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(59, 130, 246, 0.08);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
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

.form-section-title {
  margin: 6px 0 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.form-section-title:not(:first-child) {
  margin-top: 18px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.form-grid.compact {
  grid-template-columns: repeat(2, minmax(180px, 260px));
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
