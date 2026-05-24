<template>
  <div class="instances-view">
    <header class="page-header">
      <div class="title-section">
        <h1>任务实例</h1>
        <p class="subtitle">选择拓扑模板，填写各节点的镜像、命令、端口等运行参数</p>
      </div>
      <div class="header-actions">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button label="card">卡片</el-radio-button>
          <el-radio-button label="list">列表</el-radio-button>
        </el-radio-group>
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 120px">
          <el-option label="全部" value="" />
          <el-option label="待启动" value="pending" />
          <el-option label="已调度" value="scheduled" />
          <el-option label="运行中" value="running" />
          <el-option label="失败" value="failed" />
          <el-option label="已停止" value="stopped" />
        </el-select>
        <template v-if="selectedIds.length">
          <span class="selection-summary">已选 {{ selectedIds.length }}</span>
          <el-button size="small" type="primary" plain @click="handleBatchStart">启动</el-button>
          <el-button size="small" type="warning" plain @click="handleBatchStop">停止</el-button>
          <el-button size="small" type="danger" plain @click="handleBatchDelete">删除</el-button>
        </template>
        <el-button type="primary" @click="openCreateDialog">新建实例</el-button>
      </div>
    </header>

    <div v-if="viewMode === 'card'" class="instances-grid">
      <div v-for="instance in paginatedInstances" :key="instance.id" class="instance-card" :class="instance.status">
        <div class="instance-header">
          <div>
            <el-checkbox :model-value="selectedIds.includes(instance.id)" @change="toggleSelected(instance.id)" />
            <h3>{{ instance.name }}</h3>
            <el-tag size="small" :type="statusTag(instance.status)">{{ formatStatus(instance.status) }}</el-tag>
          </div>
          <el-dropdown trigger="click">
            <el-button text circle>···</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="canStart(instance.status)" @click="startInstance(instance.id)">启动</el-dropdown-item>
                <el-dropdown-item v-if="instance.status === 'running'" @click="stopInstance(instance.id)">停止</el-dropdown-item>
                <el-dropdown-item v-if="instance.status === 'running'" @click="restartInstance(instance.id)">重启</el-dropdown-item>
                <el-dropdown-item @click="openEditDialog(instance.id)">编辑</el-dropdown-item>
                <el-dropdown-item @click="viewInstance(instance.id)">详情</el-dropdown-item>
                <el-dropdown-item divided @click="confirmDelete(instance)">删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div class="instance-meta">
          <span>{{ templateName(instance.template_id) }}</span>
          <span>{{ instance.nodes?.length || 0 }} 节点</span>
        </div>
      </div>
    </div>

    <el-table v-else :data="paginatedInstances" v-loading="loading" size="small">
      <el-table-column label="选择" width="70">
        <template #default="{ row }">
          <el-checkbox :model-value="selectedIds.includes(row.id)" @change="toggleSelected(row.id)" />
        </template>
      </el-table-column>
      <el-table-column prop="name" label="实例名称" min-width="200" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }"><el-tag :type="statusTag(row.status)">{{ formatStatus(row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column label="模板" min-width="160">
        <template #default="{ row }">{{ templateName(row.template_id) }}</template>
      </el-table-column>
      <el-table-column label="节点数" width="90">
        <template #default="{ row }">{{ row.nodes?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="计划启动(UTC+8)" min-width="190">
        <template #default="{ row }">{{ row.scheduled_start_time ? formatUtc8Time(row.scheduled_start_time) : '-' }}</template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canStart(row.status)" size="small" type="primary" link @click="startInstance(row.id)">启动</el-button>
          <el-button v-if="row.status === 'running'" size="small" type="warning" link @click="stopInstance(row.id)">停止</el-button>
          <el-button size="small" link @click="viewInstance(row.id)">详情</el-button>
          <el-button size="small" link @click="openEditDialog(row.id)">编辑</el-button>
          <el-button size="small" type="danger" link @click="confirmDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !filteredInstances.length" description="没有任务实例" />
    <div v-if="filteredInstances.length" class="pagination-wrap">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        background
        layout="total, sizes, prev, pager, next"
        :page-sizes="[8, 12, 20, 50]"
        :total="filteredInstances.length"
      />
    </div>

    <el-dialog v-model="showCreateDialog" title="新建任务实例" width="920px">
      <el-tabs v-model="createMode">
        <el-tab-pane label="JSON 粘贴" name="json">
          <p class="json-hint">
            支持 template_name、node_overrides。资源字段：
            <code>cpu_limit</code>（核数 → NanoCPUs）、
            <code>memory_limit</code>（如 512m）、
            <code>gpu_id</code>（如 "0"）。
          </p>
          <el-input v-model="createJsonText" type="textarea" :rows="18" placeholder="粘贴实例 JSON..." />
          <div class="json-actions">
            <el-button link type="primary" @click="loadInstanceExample">填入示例</el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="表单" name="form">
      <el-form :model="createForm" label-position="top">
        <el-form-item label="实例名称" required><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="拓扑模板" required>
          <el-select v-model="createForm.template_id" style="width: 100%" @change="onTemplateChange">
            <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="创建方式" required>
          <el-radio-group v-model="createForm.mode">
            <el-radio label="immediate">立即部署</el-radio>
            <el-radio label="scheduled">定时调度</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="createForm.mode === 'scheduled'" label="计划启动时间 (UTC+8)" required>
          <el-date-picker v-model="createForm.scheduled_start_time" type="datetime" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="createForm.mode === 'scheduled'" label="计划停止时间 (UTC+8)">
          <el-date-picker v-model="createForm.scheduled_end_time" type="datetime" style="width: 100%" />
        </el-form-item>
        <el-form-item label="创建后自动启动">
          <el-switch v-model="createForm.auto_start" />
        </el-form-item>

        <div class="divider">节点运行参数</div>
        <div v-if="!nodeOverrides.length" class="empty-overrides">选择模板后，为每个节点配置容器参数</div>
        <NodeContainerConfig
          v-for="(node, idx) in nodeOverrides"
          :key="node.template_node_id"
          :ref="(el) => setConfigRef(el, idx)"
          :node="nodeOverrides[idx]"
          :workers="nodes"
        />
      </el-form>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreateUnified">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditDialog" title="编辑任务实例" width="920px">
      <el-form :model="editForm" label-position="top">
        <el-form-item label="实例名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-alert
          v-if="editLocked"
          type="warning"
          show-icon
          :closable="false"
          title="实例处于运行态（运行中/启动中/停止中），仅允许修改实例名称，其余部署参数已锁定。"
          style="margin-bottom: 12px;"
        />
        <el-form-item label="计划启动时间 (UTC+8)">
          <el-date-picker v-model="editForm.scheduled_start_time" :disabled="editLocked" type="datetime" style="width: 100%" />
        </el-form-item>
        <el-form-item label="计划停止时间 (UTC+8)">
          <el-date-picker v-model="editForm.scheduled_end_time" :disabled="editLocked" type="datetime" style="width: 100%" />
        </el-form-item>
        <div class="divider">节点容器配置</div>
        <NodeContainerConfig
          v-for="(node, idx) in editNodeOverrides"
          :key="node.template_node_id"
          :ref="(el) => setEditConfigRef(el, idx)"
          :node="editNodeOverrides[idx]"
          :workers="nodes"
          :disabled="editLocked"
        />
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showChangeSummaryDialog" title="变更确认" width="640px">
      <div v-if="changeSummaryLines.length">
        <div v-for="(line, idx) in changeSummaryLines" :key="idx" class="summary-line">{{ line }}</div>
      </div>
      <el-empty v-else description="未检测到参数变更" />
      <template #footer>
        <el-button @click="showChangeSummaryDialog = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="confirmSubmitEdit">确认保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useInstancesStore } from '@/stores/instances'
import { instancesApi, nodesApi, templatesApi } from '@/api'
import { useTemplatesStore } from '@/stores/templates'
import { buildInstancePayload, INSTANCE_JSON_EXAMPLE } from '@/utils/deployJson'
import NodeContainerConfig from '@/components/NodeContainerConfig.vue'

dayjs.extend(relativeTime)
dayjs.extend(utc)
const router = useRouter()
const viewMode = ref('card')
const statusFilter = ref('')
const showCreateDialog = ref(false)
const createMode = ref('json')
const createJsonText = ref('')
const showEditDialog = ref(false)
const creating = ref(false)
const editing = ref(false)
const showChangeSummaryDialog = ref(false)
const nodeOverrides = ref([])
const editNodeOverrides = ref([])
const nodes = ref([])
const editingInstanceId = ref('')
const editingInstanceStatus = ref('')
const originalEditSnapshot = ref(null)
const pendingEditPayload = ref(null)
const selectedIds = ref([])
const currentPage = ref(1)
const pageSize = ref(8)

const instancesStore = useInstancesStore()
const templatesStore = useTemplatesStore()
const { instances, loading } = storeToRefs(instancesStore)
const { templates } = storeToRefs(templatesStore)
const {
  fetchInstances,
  createInstance,
  updateInstance,
  deleteInstance,
  startInstance: storeStart,
  stopInstance: storeStop,
  restartInstance: storeRestart,
} = instancesStore
const { fetchTemplates } = templatesStore

const configRefs = ref([])
const editConfigRefs = ref([])

function setConfigRef(el, idx) {
  if (el) configRefs.value[idx] = el
}
function setEditConfigRef(el, idx) {
  if (el) editConfigRefs.value[idx] = el
}

function flushConfigRefs(refs) {
  refs.forEach((c) => c?.syncNodeFromRows?.())
}

const createForm = ref({
  name: '',
  template_id: '',
  mode: 'immediate',
  scheduled_start_time: null,
  scheduled_end_time: null,
  auto_start: false,
})
const editForm = ref({
  name: '',
  scheduled_start_time: null,
  scheduled_end_time: null,
})

const filteredInstances = computed(() => {
  const list = [...(instances.value || [])].sort((a, b) => {
    const ta = new Date(a.created_at || 0).getTime()
    const tb = new Date(b.created_at || 0).getTime()
    return tb - ta
  })
  return statusFilter.value ? list.filter((i) => i.status === statusFilter.value) : list
})
const paginatedInstances = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredInstances.value.slice(start, start + pageSize.value)
})
const editLocked = computed(() => ['running', 'starting', 'stopping'].includes(editingInstanceStatus.value))
const changeSummaryLines = computed(() => buildChangeSummary(originalEditSnapshot.value, pendingEditPayload.value))

onMounted(async () => {
  await Promise.all([fetchInstances(), fetchTemplates()])
  const { data } = await nodesApi.list()
  nodes.value = data
})

function formatObjectLines(obj, sep = '=') {
  if (!obj || typeof obj !== 'object') return ''
  return Object.entries(obj).map(([k, v]) => `${k}${sep}${v}`).join('\n')
}

function parseLines(text, sep = '=') {
  const out = {}
  if (!text) return out
  text.split('\n').map((x) => x.trim()).filter(Boolean).forEach((line) => {
    const idx = line.indexOf(sep)
    if (idx > 0) out[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
  })
  return out
}

function toggleSelected(id) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function clearSelection() {
  selectedIds.value = []
}

async function onTemplateChange(templateId) {
  nodeOverrides.value = []
  configRefs.value = []
  if (!templateId) return
  const { data } = await templatesApi.get(templateId)
  nodeOverrides.value = (data.nodes || []).map((n) => ({
    template_node_id: n.id,
    template_node_name: n.name,
    image: n.image || '',
    command: n.command || '',
    env_text: formatObjectLines(n.env, '='),
    volumes_text: formatObjectLines(n.volumes, ':'),
    ports_text: formatObjectLines(n.ports, ':'),
    gpu_id: n.gpu_id || '',
    cpu_limit: n.cpu_limit ?? null,
    memory_limit: n.memory_limit || '',
    network_mode: n.network_mode || 'host',
    restart_policy: n.restart_policy || 'on-failure',
    node_id: n.node_id || '',
  }))
}

function templateName(templateId) {
  return templates.value.find((t) => t.id === templateId)?.name || templateId || '-'
}

function openCreateDialog() {
  createMode.value = 'json'
  createJsonText.value = INSTANCE_JSON_EXAMPLE
  showCreateDialog.value = true
}

function loadInstanceExample() {
  createJsonText.value = INSTANCE_JSON_EXAMPLE
}

function buildCreatePayloadFromForm() {
  return {
    name: createForm.value.name,
    template_id: createForm.value.template_id,
    deployment_mode: createForm.value.mode,
    scheduled_start_time: createForm.value.mode === 'scheduled' ? createForm.value.scheduled_start_time : null,
    scheduled_end_time: createForm.value.mode === 'scheduled' ? createForm.value.scheduled_end_time : null,
    auto_start: createForm.value.auto_start,
    node_overrides: nodeOverrides.value.map((n) => ({
      template_node_id: n.template_node_id,
      image: n.image || null,
      command: n.command || null,
      env: parseLines(n.env_text, '='),
      volumes: parseLines(n.volumes_text, ':'),
      ports: parseLines(n.ports_text, ':'),
      gpu_id: n.gpu_id || null,
      cpu_limit: n.cpu_limit ?? null,
      memory_limit: n.memory_limit || null,
      network_mode: n.network_mode || null,
      restart_policy: n.restart_policy || null,
      node_id: n.node_id || null,
    })),
  }
}

async function runPreflightIfNeeded(payload) {
  if (payload.deployment_mode !== 'immediate') return
  const { data } = await instancesApi.preflight(payload)
  if (!data.ok) {
    const detail = (data.conflicts || []).map((item) => item.message).join('\n')
    throw new Error(detail || '启动前预检查失败')
  }
  if (data.warnings?.length) {
    const detail = data.warnings.map((item) => item.message).join('\n')
    await ElMessageBox.confirm(detail, '预检查提示', {
      type: 'warning',
      confirmButtonText: '继续创建',
      cancelButtonText: '返回修改',
    })
  }
}

async function finalizeCreate(payload) {
  const created = await createInstance(payload)
  ElMessage.success(payload.auto_start ? '实例已创建并启动' : '实例已创建')
  statusFilter.value = ''
  showCreateDialog.value = false
  createForm.value = {
    name: '',
    template_id: '',
    mode: 'immediate',
    scheduled_start_time: null,
    scheduled_end_time: null,
    auto_start: false,
  }
  createJsonText.value = ''
  nodeOverrides.value = []
  configRefs.value = []
  await fetchInstances()
  return created
}

async function submitCreateUnified() {
  if (createMode.value === 'json') {
    await submitCreateFromJson()
  } else {
    await submitCreate()
  }
}

async function submitCreate() {
  flushConfigRefs(configRefs.value)
  if (!createForm.value.name || !createForm.value.template_id) return ElMessage.error('请填写实例名和模板')
  if (createForm.value.mode === 'scheduled' && !createForm.value.scheduled_start_time) return ElMessage.error('请选择计划启动时间')
  creating.value = true
  try {
    const payload = buildCreatePayloadFromForm()
    await runPreflightIfNeeded(payload)
    await finalizeCreate(payload)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getErrorMessage(error, '创建实例失败'))
  } finally {
    creating.value = false
  }
}

async function submitCreateFromJson() {
  creating.value = true
  try {
    const draft = buildInstancePayload(createJsonText.value, { nodes: nodes.value, templates: templates.value })
    const { data: templateDetail } = await templatesApi.get(draft.template_id)
    const payload = buildInstancePayload(createJsonText.value, {
      nodes: nodes.value,
      templates: templates.value,
      templateDetail,
    })
    await runPreflightIfNeeded(payload)
    await finalizeCreate(payload)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message || getErrorMessage(error, '从 JSON 创建失败'))
  } finally {
    creating.value = false
  }
}

async function openEditDialog(instanceId) {
  const target = (instances.value || []).find((i) => i.id === instanceId)
  if (!target) return
  editingInstanceId.value = instanceId
  editingInstanceStatus.value = target.status || ''
  editConfigRefs.value = []
  editForm.value = {
    name: target.name,
    scheduled_start_time: target.scheduled_start_time || null,
    scheduled_end_time: target.scheduled_end_time || null,
  }
  editNodeOverrides.value = (target.nodes || []).map((n) => ({
    template_node_id: n.template_node_id,
    template_node_name: n.name,
    image: n.image || '',
    command: n.command || '',
    env_text: formatObjectLines(n.env, '='),
    volumes_text: formatObjectLines(n.volumes, ':'),
    ports_text: formatObjectLines(n.ports, ':'),
    gpu_id: n.gpu_id || '',
    cpu_limit: n.cpu_limit ?? null,
    memory_limit: n.memory_limit || '',
    network_mode: n.network_mode || '',
    restart_policy: n.restart_policy || '',
    node_id: n.node_id || '',
  }))
  originalEditSnapshot.value = {
    name: target.name || '',
    scheduled_start_time: target.scheduled_start_time || null,
    scheduled_end_time: target.scheduled_end_time || null,
    nodes: (target.nodes || []).map((n) => ({
      template_node_id: n.template_node_id,
      template_node_name: n.name,
      image: n.image || null,
      command: n.command || null,
      env: n.env || {},
      volumes: n.volumes || {},
      ports: n.ports || {},
      gpu_id: n.gpu_id || null,
      cpu_limit: n.cpu_limit ?? null,
      memory_limit: n.memory_limit || null,
      network_mode: n.network_mode || null,
      restart_policy: n.restart_policy || null,
      node_id: n.node_id || null,
    })),
  }
  showEditDialog.value = true
}

function buildEditPayload() {
  return {
    name: editForm.value.name,
    scheduled_start_time: editForm.value.scheduled_start_time,
    scheduled_end_time: editForm.value.scheduled_end_time,
    node_overrides: editNodeOverrides.value.map((n) => ({
      template_node_id: n.template_node_id,
      template_node_name: n.template_node_name,
      image: n.image || null,
      command: n.command || null,
      env: parseLines(n.env_text, '='),
      volumes: parseLines(n.volumes_text, ':'),
      ports: parseLines(n.ports_text, ':'),
      gpu_id: n.gpu_id || null,
      cpu_limit: n.cpu_limit ?? null,
      memory_limit: n.memory_limit || null,
      network_mode: n.network_mode || null,
      restart_policy: n.restart_policy || null,
      node_id: n.node_id || null,
    })),
  }
}

function deepEqual(a, b) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

function buildChangeSummary(original, payload) {
  if (!original || !payload) return []
  const lines = []
  if (!deepEqual(original.name, payload.name)) lines.push(`实例名称：${original.name || '-'} -> ${payload.name || '-'}`)
  if (!deepEqual(original.scheduled_start_time, payload.scheduled_start_time)) {
    lines.push(`计划启动时间：${original.scheduled_start_time || '-'} -> ${payload.scheduled_start_time || '-'}`)
  }
  if (!deepEqual(original.scheduled_end_time, payload.scheduled_end_time)) {
    lines.push(`计划停止时间：${original.scheduled_end_time || '-'} -> ${payload.scheduled_end_time || '-'}`)
  }
  const keys = [
    ['image', '镜像'],
    ['command', '命令'],
    ['env', '环境变量'],
    ['volumes', '挂载'],
    ['ports', '端口'],
    ['gpu_id', 'GPU'],
    ['cpu_limit', 'CPU'],
    ['memory_limit', '内存'],
    ['network_mode', '网络'],
    ['restart_policy', '重启策略'],
    ['node_id', '部署节点'],
  ]
  payload.node_overrides.forEach((nodePayload) => {
    const base = (original.nodes || []).find((n) => n.template_node_id === nodePayload.template_node_id)
    if (!base) return
    const changedFields = keys
      .filter(([key]) => !deepEqual(base[key], nodePayload[key]))
      .map(([, label]) => label)
    if (changedFields.length) {
      lines.push(`节点「${nodePayload.template_node_name || nodePayload.template_node_id}」修改：${changedFields.join('、')}`)
    }
  })
  return lines
}

async function submitEdit() {
  flushConfigRefs(editConfigRefs.value)
  if (!editingInstanceId.value) return
  pendingEditPayload.value = buildEditPayload()
  const lines = buildChangeSummary(originalEditSnapshot.value, pendingEditPayload.value)
  if (!lines.length) {
    ElMessage.warning('未检测到参数变更')
    return
  }
  showChangeSummaryDialog.value = true
}

async function confirmSubmitEdit() {
  if (!editingInstanceId.value || !pendingEditPayload.value) return
  editing.value = true
  try {
    await updateInstance(editingInstanceId.value, pendingEditPayload.value)
    ElMessage.success('实例已更新')
    showChangeSummaryDialog.value = false
    showEditDialog.value = false
    pendingEditPayload.value = null
    await fetchInstances()
  } finally {
    editing.value = false
  }
}

function canStart(status) {
  return ['pending', 'stopped', 'failed'].includes(status)
}
async function startInstance(id) { await storeStart(id); ElMessage.success('实例已启动') }
async function stopInstance(id) { await storeStop(id); ElMessage.success('实例已停止') }
async function restartInstance(id) { await storeRestart(id); ElMessage.success('实例已重启') }
function viewInstance(id) { router.push(`/instances/${id}`) }
function getErrorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}
async function confirmDelete(instance) {
  try {
    await ElMessageBox.confirm(`确认删除实例“${instance.name}”吗？`, '删除实例', { type: 'warning' })
    await deleteInstance(instance.id)
    ElMessage.success('实例已删除')
    selectedIds.value = selectedIds.value.filter((id) => id !== instance.id)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getErrorMessage(error, '删除实例失败'))
  }
}

async function handleBatchStart() {
  const result = await instancesStore.batchStart(selectedIds.value)
  ElMessage.success(`批量启动完成，成功 ${result.succeeded.length} 个`)
  clearSelection()
}

async function handleBatchStop() {
  const result = await instancesStore.batchStop(selectedIds.value)
  ElMessage.success(`批量停止完成，成功 ${result.succeeded.length} 个`)
  clearSelection()
}

async function handleBatchDelete() {
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${selectedIds.value.length} 个实例吗？`, '批量删除', { type: 'warning' })
    const result = await instancesStore.batchDelete(selectedIds.value)
    if (Object.keys(result.failed || {}).length) {
      const firstFailure = Object.values(result.failed)[0]
      ElMessage.warning(`批量删除部分完成，成功 ${result.succeeded.length} 个，失败 ${Object.keys(result.failed).length} 个：${firstFailure}`)
    } else {
      ElMessage.success(`批量删除完成，成功 ${result.succeeded.length} 个`)
    }
    clearSelection()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getErrorMessage(error, '批量删除失败'))
  }
}

function formatStatus(s) {
  return ({ pending: '待启动', scheduled: '已调度', starting: '启动中', running: '运行中', stopping: '停止中', stopped: '已停止', failed: '失败', expired: '已过期' }[s] || s)
}
function statusTag(s) {
  return ({ running: 'success', failed: 'danger', scheduled: 'warning' }[s] || 'info')
}
function parseApiTime(value) {
  return value ? dayjs.utc(value) : null
}

function formatTime(t) {
  const parsed = parseApiTime(t)
  return parsed ? parsed.local().fromNow() : '-'
}

function formatUtc8Time(t) {
  const parsed = parseApiTime(t)
  return parsed ? `${parsed.utcOffset(8).format('YYYY-MM-DD HH:mm:ss')} (UTC+8)` : '-'
}
</script>

<style scoped>
.instances-view { display: flex; flex-direction: column; gap: 16px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-end; }
.subtitle { color: var(--text-secondary); margin-top: 4px; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.instances-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.instance-card { background: var(--bg-secondary); border: 1px solid var(--border-subtle); border-radius: 12px; padding: 14px; }
.instance-header { display: flex; justify-content: space-between; align-items: flex-start; }
.instance-meta { margin-top: 10px; display: flex; justify-content: space-between; color: var(--text-secondary); font-size: 12px; }
.card-actions { margin-top: 12px; display: flex; justify-content: flex-end; gap: 8px; }
.selection-summary { color: var(--text-secondary); font-size: 13px; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
.divider { margin: 10px 0; font-weight: 600; }
.empty-overrides { color: var(--text-secondary); margin-bottom: 8px; }
.override-card { border: 1px solid var(--border-subtle); border-radius: 10px; padding: 10px; margin-bottom: 10px; }
.override-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 10px; }
.span-2 { grid-column: span 2; }
.summary-line { padding: 8px 10px; border-radius: 8px; background: var(--bg-tertiary); margin-bottom: 8px; }
.json-hint { color: var(--text-secondary); font-size: 13px; margin-bottom: 12px; }
.json-actions { margin-top: 12px; display: flex; gap: 12px; }
</style>
