<template>
  <div class="instance-detail">
    <header class="page-header">
      <div class="title-section">
        <el-button text @click="$router.back()">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <h1>{{ instance?.name || '实例详情' }}</h1>
        <span class="status-badge" :class="instance?.status">{{ formatStatus(instance?.status) }}</span>
      </div>
      <div class="header-actions">
        <el-button @click="goEdit">编辑配置</el-button>
        <template v-if="instance?.status === 'running'">
          <el-button @click="handleStop"><el-icon><VideoPause /></el-icon>停止</el-button>
          <el-button @click="handleRestart"><el-icon><RefreshRight /></el-icon>重启</el-button>
        </template>
        <el-button
          v-else-if="instance?.status === 'pending' || instance?.status === 'stopped' || instance?.status === 'failed'"
          type="primary"
          @click="handleStart"
        >
          <el-icon><VideoPlay /></el-icon>启动
        </el-button>
      </div>
    </header>

    <div class="detail-grid" v-if="instance">
      <el-alert
        v-if="instance.error_message"
        :title="instance.error_message"
        type="error"
        :closable="false"
        show-icon
        style="grid-column: span 2;"
      />
      <el-alert
        v-if="instance.status === 'scheduled' && instance.scheduled_start_time"
        :title="`将于 ${formatUtc8Time(instance.scheduled_start_time)} 自动启动`"
        type="info"
        :closable="false"
        show-icon
        style="grid-column: span 2;"
      />

      <div class="info-section">
        <h2>实例信息</h2>
        <div class="info-rows">
          <div class="info-row"><span class="label">拓扑模板</span><span class="value">{{ templateName }}</span></div>
          <div class="info-row"><span class="label">创建时间</span><span class="value">{{ formatUtc8Time(instance.created_at) }}</span></div>
          <div class="info-row" v-if="instance.start_time"><span class="label">启动时间</span><span class="value">{{ formatUtc8Time(instance.start_time) }}</span></div>
          <div class="info-row" v-if="instance.end_time"><span class="label">结束时间</span><span class="value">{{ formatUtc8Time(instance.end_time) }}</span></div>
          <div class="info-row"><span class="label">节点数</span><span class="value">{{ instance.nodes?.length || 0 }}</span></div>
        </div>
      </div>

      <div class="info-section">
        <h2>调度</h2>
        <div class="info-rows">
          <div class="info-row"><span class="label">计划启动</span><span class="value">{{ instance.scheduled_start_time ? formatUtc8Time(instance.scheduled_start_time) : '-' }}</span></div>
          <div class="info-row"><span class="label">计划停止</span><span class="value">{{ instance.scheduled_end_time ? formatUtc8Time(instance.scheduled_end_time) : '-' }}</span></div>
        </div>
        <el-form :model="scheduleForm" label-position="top" class="schedule-inline">
          <el-form-item label="修改计划启动"><el-date-picker v-model="scheduleForm.scheduled_start_time" type="datetime" style="width: 100%" /></el-form-item>
          <el-form-item label="修改计划停止"><el-date-picker v-model="scheduleForm.scheduled_end_time" type="datetime" style="width: 100%" /></el-form-item>
          <el-button type="primary" size="small" @click="submitSchedule">更新调度</el-button>
        </el-form>
      </div>

      <div class="info-section full-width" v-if="macroEntries.length">
        <h2>模板宏变量</h2>
        <div class="macro-table">
          <div v-for="item in macroEntries" :key="item.name" class="macro-row">
            <code>{{ item.name }}</code>
            <span class="macro-label">{{ item.label || item.name }}</span>
            <span class="macro-value mono">{{ item.value || '-' }}</span>
          </div>
        </div>
      </div>

      <div class="dag-section full-width">
        <h2>任务图</h2>
        <div class="dag-canvas">
          <svg :width="dagWidth" height="280" ref="dagSvg">
            <g v-for="edge in layoutEdges" :key="edge.id">
              <line
                :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2"
                stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arrowhead-detail)"
              />
            </g>
            <defs>
              <marker id="arrowhead-detail" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="var(--text-muted)" />
              </marker>
            </defs>
            <g v-for="node in layoutNodes" :key="node.id">
              <rect
                :x="node.x - 50" :y="node.y - 25" width="100" height="50" rx="10"
                :fill="getNodeBgColor(node.status)" :stroke="getNodeBorderColor(node.status)" stroke-width="2"
              />
              <text :x="node.x" :y="node.y - 5" text-anchor="middle" fill="var(--text-primary)" font-size="12" font-weight="600">{{ node.name }}</text>
              <text :x="node.x" :y="node.y + 12" text-anchor="middle" fill="var(--text-muted)" font-size="10">{{ formatStatus(node.status) }}</text>
            </g>
          </svg>
        </div>
      </div>

      <div class="nodes-section full-width">
        <h2>节点部署参数</h2>
        <div class="nodes-list">
          <div v-for="node in instance.nodes" :key="node.id" class="node-detail-card" :class="node.status">
            <div class="node-header">
              <span class="node-name">{{ node.name }}</span>
              <span class="node-status" :class="node.status">{{ formatStatus(node.status) }}</span>
            </div>
            <div class="param-grid">
              <div class="param-block"><span class="label">Worker</span><span class="value mono">{{ workerName(node.node_id) }}</span></div>
              <div class="param-block"><span class="label">镜像</span><span class="value mono">{{ node.image }}</span></div>
              <div class="param-block"><span class="label">网络</span><span class="value">{{ node.network_mode || 'host' }}</span></div>
              <div class="param-block"><span class="label">重启策略</span><span class="value">{{ node.restart_policy || 'on-failure' }}</span></div>
              <div class="param-block span-2"><span class="label">命令</span><span class="value mono">{{ node.command || '-' }}</span></div>
              <div class="param-block" v-if="node.cpu_limit != null"><span class="label">CPU 上限</span><span class="value">{{ node.cpu_limit }}</span></div>
              <div class="param-block" v-if="node.cpu_reservation != null"><span class="label">CPU 预留</span><span class="value">{{ node.cpu_reservation }}</span></div>
              <div class="param-block" v-if="node.cpu_shares != null"><span class="label">CPU 权重</span><span class="value">{{ node.cpu_shares }}</span></div>
              <div class="param-block" v-if="node.cpuset_cpus"><span class="label">绑核</span><span class="value mono">{{ node.cpuset_cpus }}</span></div>
              <div class="param-block" v-if="node.cpu_quota != null"><span class="label">CPU 配额</span><span class="value">{{ node.cpu_quota }}</span></div>
              <div class="param-block" v-if="node.cpu_period != null"><span class="label">CPU 周期</span><span class="value">{{ node.cpu_period }}</span></div>
              <div class="param-block" v-if="node.memory_limit"><span class="label">内存上限</span><span class="value">{{ node.memory_limit }}</span></div>
              <div class="param-block" v-if="node.memory_reservation"><span class="label">内存预留</span><span class="value">{{ node.memory_reservation }}</span></div>
              <div class="param-block" v-if="node.memory_swap_limit"><span class="label">Swap 上限</span><span class="value">{{ node.memory_swap_limit }}</span></div>
              <div class="param-block" v-if="node.gpu_id"><span class="label">GPU</span><span class="value mono">{{ node.gpu_id }}</span></div>
              <div class="param-block" v-if="node.port_defs?.length"><span class="label">命名端口</span>
                <div class="named-ports">
                  <div v-for="def in node.port_defs" :key="def.name" class="named-port-tag">
                    <code>{{ def.name }}</code><span>{{ def.label || def.name }}</span><span class="port-val">
  <template v-if="node.business_address">
    {{ node.business_address.includes(':') ? `[${node.business_address}]` : node.business_address }}:{{ node.port_values?.[def.name] ?? def.default ?? '-' }}
  </template>
  <template v-else>
    {{ node.port_values?.[def.name] ?? def.default ?? '-' }}
  </template>
</span>
                  </div>
                </div>
              </div>
              <div class="param-block span-2" v-if="node.port_values && Object.keys(node.port_values).length && !node.port_defs?.length">
                <span class="label">命名端口</span>
                <pre class="value mono pre">{{ formatJson(node.port_values) }}</pre>
              </div>
              <div class="param-block span-2" v-if="node.ports && Object.keys(node.ports).length">
                <span class="label">端口映射</span>
                <pre class="value mono pre">{{ formatJson(node.ports) }}</pre>
              </div>
              <div class="param-block span-2" v-if="node.env && Object.keys(node.env).length">
                <span class="label">环境变量</span>
                <pre class="value mono pre">{{ formatJson(node.env) }}</pre>
              </div>
              <div class="param-block span-2" v-if="node.volume_mounts?.length">
                <span class="label">挂载卷</span>
                <pre class="value mono pre">{{ formatJson(node.volume_mounts) }}</pre>
              </div>
              <div class="param-block span-2" v-if="node.health_check">
                <span class="label">健康检查</span>
                <pre class="value mono pre">{{ formatJson(node.health_check) }}</pre>
              </div>
              <div class="param-block span-2" v-if="node.error_message"><span class="label">错误</span><span class="value error">{{ node.error_message }}</span></div>
              <div class="param-block"><span class="label">容器 ID</span><span class="value mono">{{ node.container_id || '-' }}</span></div>
              <div class="param-block"><span class="label">容器名</span><span class="value mono">{{ node.container_name || '-' }}</span></div>
            </div>
            <div class="node-actions">
              <el-button size="small" @click="fetchLogs(node)"><el-icon><Document /></el-icon>日志</el-button>
            </div>
          </div>
        </div>
      </div>

      <div class="events-section full-width">
        <h2>事件记录</h2>
        <div class="events-list">
          <div v-for="event in events" :key="event.id" class="event-item">
            <span class="event-time">{{ formatTime(event.created_at) }}</span>
            <span class="event-status" :class="event.new_status">{{ formatStatus(event.new_status) }}</span>
            <span class="event-message">{{ event.message || event.event_type }}</span>
          </div>
          <div v-if="!events.length" class="no-events">暂无事件记录</div>
        </div>
      </div>
    </div>

    <el-dialog v-model="showLogs" title="容器日志" width="800px">
      <pre class="logs-content">{{ logs }}</pre>
    </el-dialog>

    <el-drawer v-model="showEditDrawer" :title="`编辑实例：${instance?.name}`" direction="rtl" size="880px" :before-close="handleEditDrawerClose">
      <div v-if="editLocked" class="edit-locked-warning">
        <el-alert type="warning" show-icon :closable="false" title="实例处于运行态，部署参数已锁定，仅可修改名称与调度。" />
      </div>
      <el-form :model="editForm" label-position="top" class="drawer-form">
        <el-form-item label="实例名称"><el-input v-model="editForm.name" :disabled="editLocked" /></el-form-item>
        <el-form-item label="计划启动时间 (UTC+8)">
          <el-date-picker v-model="editForm.scheduled_start_time" :disabled="editLocked" type="datetime" style="width: 100%" />
        </el-form-item>
        <el-form-item label="计划停止时间 (UTC+8)">
          <el-date-picker v-model="editForm.scheduled_end_time" :disabled="editLocked" type="datetime" style="width: 100%" />
        </el-form-item>
        <div class="drawer-divider">宏变量</div>
        <div v-if="!editMacroDefs.length" class="empty-hint">无宏变量</div>
        <div v-else class="macro-form">
          <div v-for="def in editMacroDefs" :key="def.name" class="macro-row">
            <code class="macro-name">{{ def.name }}</code>
            <span class="macro-label">{{ def.label || def.name }}</span>
            <el-input v-model="editMacroValues[def.name]" :disabled="editLocked" :placeholder="String(def.default || '')" />
          </div>
        </div>
        <div class="drawer-divider">节点容器配置</div>
        <NodeContainerConfig
          v-for="(node, idx) in editNodeOverrides"
          :key="node.template_node_id"
          :ref="(el) => setEditConfigRef(el, idx)"
          :node="editNodeOverrides[idx]"
          :workers="workers"
          :disabled="editLocked"
        />
      </el-form>
      <template #footer>
        <div class="drawer-footer">
          <el-button @click="showEditDrawer = false">取消</el-button>
          <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useInstancesStore } from '@/stores/instances'
import { useTemplatesStore } from '@/stores/templates'
import { instancesApi, nodesApi } from '@/api'
import { formatJson } from '@/utils/templateForm'
import {
  mapApiNodeToForm,
  mapApiNodeToOverride,
  mapFormNodeToOverride,
  buildAbcTopologyNodes,
  buildAbcTopologyEdges,
  DEFAULT_PLACEHOLDER_IMAGE,
} from '@/utils/deployJson'
import { DOCKER_PARAM_DOCS } from '@/utils/dockerFieldHints'
import NodeContainerConfig from '@/components/NodeContainerConfig.vue'
import { ElMessage } from 'element-plus'
import { extractErrorMessage } from '@/utils/errorMessage'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'

dayjs.extend(relativeTime)
dayjs.extend(utc)

const route = useRoute()
const router = useRouter()
const store = useInstancesStore()
const templatesStore = useTemplatesStore()

const instance = ref(null)
const templateDetail = ref(null)
const workers = ref([])
const events = ref([])
const showLogs = ref(false)
const logs = ref('')
let refreshTimer = null

const showEditDrawer = ref(false)
const editing = ref(false)
const editNodeOverrides = ref([])
const editMacroDefs = ref([])
const editMacroValues = ref({})
const editConfigRefs = ref([])
const originalEditSnapshot = ref(null)
const pendingEditPayload = ref(null)

const scheduleForm = ref({ scheduled_start_time: null, scheduled_end_time: null })
const editForm = ref({ name: '', scheduled_start_time: null, scheduled_end_time: null })
const editLocked = computed(() => ['running', 'starting', 'stopping'].includes(instance.value?.status))

const templateName = computed(() => templateDetail.value?.name || instance.value?.template_id || '-')

const macroEntries = computed(() => {
  const defs = templateDetail.value?.macro_defs || []
  const values = instance.value?.macro_values || {}
  if (defs.length) {
    return defs.map((d) => ({
      name: d.name,
      label: d.label,
      value: values[d.name] ?? d.default ?? '',
    }))
  }
  return Object.entries(values).map(([name, value]) => ({ name, label: '', value }))
})

const dagWidth = computed(() => Math.max(500, (instance.value?.nodes?.length || 0) * 160))

const layoutNodes = computed(() => {
  if (!instance.value?.nodes) return []
  const nodes = instance.value.nodes
  const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)))
  return nodes.map((node, i) => ({
    ...node,
    x: 90 + (i % cols) * 160,
    y: 70 + Math.floor(i / cols) * 110,
  }))
})

const layoutEdges = computed(() => {
  const edges = templateDetail.value?.edges || []
  const pos = Object.fromEntries(
    layoutNodes.value.map((n) => [n.template_node_id || n.id, n])
  )
  return edges.map((edge) => {
    const from = pos[edge.from_node_id]
    const to = pos[edge.to_node_id]
    if (!from || !to) return null
    return { id: edge.id, x1: from.x, y1: from.y + 25, x2: to.x, y2: to.y - 25 }
  }).filter(Boolean)
})

onMounted(async () => {
  await refreshInstanceData()
  startAutoRefresh()
})

onBeforeUnmount(stopAutoRefresh)

async function refreshInstanceData() {
  const id = route.params.id
  instance.value = await store.fetchInstance(id)
  if (instance.value) {
    scheduleForm.value.scheduled_start_time = instance.value.scheduled_start_time
    scheduleForm.value.scheduled_end_time = instance.value.scheduled_end_time
    if (instance.value.template_id) {
      templateDetail.value = await templatesStore.fetchTemplate(instance.value.template_id)
    }
  }
  if (!workers.value.length) {
    const { data } = await nodesApi.list()
    workers.value = data
  }
  const { data } = await instancesApi.getEvents(id)
  events.value = data
}

function workerName(nodeId) {
  return workers.value.find((w) => w.id === nodeId)?.hostname || nodeId || '-'
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(refreshInstanceData, 5000)
}

function stopAutoRefresh() {
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
}

function setEditConfigRef(el, idx) {
  if (el) editConfigRefs.value[idx] = el
}

function flushEditConfigRefs() {
  editConfigRefs.value.forEach((c) => c?.syncNodeFromRows?.())
}

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

function initMacroValues(defs, existing = {}) {
  const out = {}
  for (const def of defs || []) {
    const name = def.name
    if (!name) continue
    out[name] = existing[name] ?? def.default ?? ''
  }
  return out
}

async function goEdit() {
  editConfigRefs.value = []
  if (instance.value) {
    editForm.value.name = instance.value.name
    editForm.value.scheduled_start_time = instance.value.scheduled_start_time
    editForm.value.scheduled_end_time = instance.value.scheduled_end_time
  }
  const templateId = instance.value?.template_id
  if (templateId && !templateDetail.value) {
    templateDetail.value = await templatesStore.fetchTemplate(templateId)
  }
  const tpl = templateDetail.value
  editMacroDefs.value = tpl?.macro_defs || []
  editMacroValues.value = initMacroValues(editMacroDefs.value, instance.value?.macro_values || {})

  editNodeOverrides.value = (instance.value?.nodes || []).map((n) => {
    const tplNode = tpl?.nodes?.find((t) => t.id === n.template_node_id)
    const form = mapApiNodeToForm(
      { ...n, port_defs: n.port_defs || tplNode?.port_defs },
      { formatObjectLines }
    )
    for (const def of form.port_defs || []) {
      if (form.port_values[def.name] == null && def.default != null) {
        form.port_values[def.name] = def.default
      }
    }
    return form
  })

  originalEditSnapshot.value = {
    name: instance.value?.name || '',
    scheduled_start_time: instance.value?.scheduled_start_time || null,
    scheduled_end_time: instance.value?.scheduled_end_time || null,
    macro_values: instance.value?.macro_values || null,
    nodes: (instance.value?.nodes || []).map((n) => mapApiNodeToOverride(n)),
  }
  showEditDrawer.value = true
}

function handleEditDrawerClose(done) {
  flushEditConfigRefs()
  done()
}

function buildEditPayload() {
  return {
    name: editForm.value.name,
    scheduled_start_time: editForm.value.scheduled_start_time,
    scheduled_end_time: editForm.value.scheduled_end_time,
    macro_values: Object.keys(editMacroValues.value).length ? { ...editMacroValues.value } : null,
    node_overrides: editNodeOverrides.value.map((n) => mapFormNodeToOverride(n, { parseLines })),
  }
}

function deepEqual(a, b) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

function buildChangeSummary(original, payload) {
  if (!original || !payload) return []
  const lines = []
  if (!deepEqual(original.name, payload.name)) lines.push(`实例名称：${original.name || '-'} → ${payload.name || '-'}`)
  if (!deepEqual(original.scheduled_start_time, payload.scheduled_start_time)) {
    lines.push(`计划启动时间：${original.scheduled_start_time || '-'} → ${payload.scheduled_start_time || '-'}`)
  }
  if (!deepEqual(original.scheduled_end_time, payload.scheduled_end_time)) {
    lines.push(`计划停止时间：${original.scheduled_end_time || '-'} → ${payload.scheduled_end_time || '-'}`)
  }
  if (!deepEqual(original.macro_values, payload.macro_values)) {
    lines.push('模板宏变量已修改')
  }
  const keys = [
    ['image', '镜像'], ['command', '命令'], ['env', '环境变量'],
    ['volume_mounts', '挂载'], ['ports', '端口'], ['port_values', '命名端口'],
    ['gpu_id', 'GPU'], ['cpu_limit', 'CPU上限'], ['cpu_reservation', 'CPU预留'],
    ['memory_limit', '内存上限'], ['memory_reservation', '内存预留'],
    ['network_mode', '网络'], ['restart_policy', '重启策略'], ['node_id', '部署节点'],
  ]
  payload.node_overrides.forEach((nodePayload) => {
    const base = (original.nodes || []).find((n) => n.template_node_id === nodePayload.template_node_id)
    if (!base) return
    const changedFields = keys.filter(([key]) => !deepEqual(base[key], nodePayload[key])).map(([, label]) => label)
    if (changedFields.length) {
      lines.push(`节点「${nodePayload.template_node_name || nodePayload.template_node_id}」修改：${changedFields.join('、')}`)
    }
  })
  return lines
}

async function submitEdit() {
  flushEditConfigRefs()
  if (!instance.value?.id) return
  pendingEditPayload.value = buildEditPayload()
  const lines = buildChangeSummary(originalEditSnapshot.value, pendingEditPayload.value)
  if (!lines.length) {
    ElMessage.warning('未检测到参数变更')
    return
  }
  editing.value = true
  try {
    await store.updateInstance(instance.value.id, pendingEditPayload.value)
    ElMessage.success('实例已更新')
    showEditDrawer.value = false
    pendingEditPayload.value = null
    await refreshInstanceData()
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '更新实例失败'))
  } finally {
    editing.value = false
  }
}

async function handleStart() {
  await store.startInstance(instance.value.id)
  await refreshInstanceData()
  ElMessage.success('实例已启动')
}

async function handleStop() {
  await store.stopInstance(instance.value.id)
  await refreshInstanceData()
  ElMessage.success('实例已停止')
}

async function handleRestart() {
  await store.restartInstance(instance.value.id)
  await refreshInstanceData()
  ElMessage.success('实例已重启')
}

async function submitSchedule() {
  await store.scheduleInstance(instance.value.id, scheduleForm.value)
  await refreshInstanceData()
  ElMessage.success('调度已更新')
}

async function fetchLogs(node) {
  try {
    const { data } = await instancesApi.getNodeLogs(instance.value.id, node.id)
    logs.value = data.logs || '暂无日志'
    showLogs.value = true
  } catch {
    ElMessage.error("获取日志失败")
  }
}

function parseApiTime(value) {
  return value ? dayjs.utc(value) : null
}

function formatTime(time) {
  const parsed = parseApiTime(time)
  return parsed ? parsed.local().fromNow() : '-'
}

function formatUtc8Time(time) {
  const parsed = parseApiTime(time)
  return parsed ? `${parsed.utcOffset(8).format('YYYY-MM-DD HH:mm:ss')} (UTC+8)` : '-'
}

function getNodeBgColor(status) {
  const colors = {
    pending: 'var(--bg-tertiary)', starting: 'rgba(245, 158, 11, 0.15)', running: 'rgba(59, 130, 246, 0.15)',
    ready: 'rgba(34, 197, 94, 0.15)', stopping: 'rgba(245, 158, 11, 0.15)', stopped: 'var(--bg-tertiary)', failed: 'rgba(239, 68, 68, 0.15)',
  }
  return colors[status] || 'var(--bg-tertiary)'
}

function getNodeBorderColor(status) {
  const colors = {
    pending: 'var(--border-subtle)', starting: 'var(--warning)', running: 'var(--info)',
    ready: 'var(--success)', stopping: 'var(--warning)', stopped: 'var(--border-subtle)', failed: 'var(--danger)',
  }
  return colors[status] || 'var(--border-subtle)'
}

function formatStatus(status) {
  const labels = {
    pending: '待启动', scheduled: '已调度', starting: '启动中', running: '运行中', ready: '就绪',
    stopping: '停止中', stopped: '已停止', failed: '失败', expired: '已过期',
  }
  return labels[status] || status
}
</script>

<style scoped>
.instance-detail { max-width: 1200px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; }
.title-section { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.title-section h1 { font-size: 24px; font-weight: 600; }
.status-badge { font-size: 12px; padding: 4px 12px; border-radius: 12px; font-weight: 500; }
.status-badge.running { background: rgba(59, 130, 246, 0.15); color: var(--info); }
.status-badge.failed { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.full-width { grid-column: span 2; }
.detail-grid h2 { font-size: 14px; font-weight: 600; color: var(--text-secondary); margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.05em; }
.info-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.info-rows { display: flex; flex-direction: column; gap: 10px; }
.info-row { display: flex; justify-content: space-between; font-size: 13px; gap: 12px; }
.info-row .label { color: var(--text-muted); flex-shrink: 0; }
.info-row .value { color: var(--text-secondary); text-align: right; word-break: break-all; }
.schedule-inline { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border-subtle); }
.macro-table { display: flex; flex-direction: column; gap: 8px; }
.macro-row { display: grid; grid-template-columns: 120px 140px 1fr; gap: 12px; align-items: center; font-size: 13px; }
.macro-row code { font-size: 12px; padding: 2px 6px; border-radius: 4px; background: var(--bg-tertiary); }
.macro-label { color: var(--text-muted); }
.macro-value { word-break: break-all; }
.dag-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.dag-canvas { background: var(--bg-tertiary); border-radius: 12px; padding: 16px; overflow-x: auto; }
.nodes-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.nodes-list { display: flex; flex-direction: column; gap: 16px; }
.node-detail-card { background: var(--bg-tertiary); border-radius: 12px; padding: 16px; border: 1px solid var(--border-subtle); }
.node-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.node-name { font-weight: 600; font-size: 15px; }
.node-status { font-size: 11px; padding: 2px 8px; border-radius: 8px; }
.node-status.running { background: rgba(59, 130, 246, 0.15); color: var(--info); }
.node-status.failed { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
.param-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; }
.param-block { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.param-block.span-2 { grid-column: span 2; }
.param-block .label { color: var(--text-muted); font-weight: 500; }
.param-block .value { color: var(--text-secondary); }
.param-block .value.error { color: var(--danger); }
.param-block .pre { margin: 0; white-space: pre-wrap; word-break: break-all; background: var(--bg-primary); padding: 8px; border-radius: 6px; font-size: 11px; }
.named-ports { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.named-port-tag { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.named-port-tag code { font-family: 'JetBrains Mono', monospace; background: var(--bg-tertiary); padding: 1px 6px; border-radius: 4px; }
.named-port-tag span { color: var(--text-secondary); }
.named-port-tag .port-val { font-family: 'JetBrains Mono', monospace; color: var(--accent-primary); font-weight: 600; }
.mono { font-family: 'JetBrains Mono', ui-monospace, monospace; }
.node-actions { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-subtle); }
.events-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.events-list { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; }
.event-item { display: flex; align-items: center; gap: 12px; font-size: 12px; padding: 8px; background: var(--bg-tertiary); border-radius: 8px; }
.event-time { color: var(--text-muted); }
.event-status { padding: 2px 8px; border-radius: 6px; font-size: 10px; }
.event-message { color: var(--text-secondary); flex: 1; }
.no-events { color: var(--text-muted); text-align: center; padding: 24px; }
.logs-content { background: var(--bg-primary); padding: 16px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 11px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; }
.edit-locked-warning { margin-bottom: 16px; }
.drawer-form { padding-bottom: 80px; }
.drawer-divider { margin: 16px 0 12px; font-weight: 600; font-size: 14px; color: var(--text-secondary); border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px; }
.drawer-footer { display: flex; justify-content: flex-end; gap: 12px; }
.empty-hint { color: var(--text-muted); font-size: 13px; margin-bottom: 12px; }
.macro-form { margin-bottom: 12px; }
.macro-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.macro-name { font-size: 12px; padding: 2px 6px; border-radius: 4px; background: var(--bg-tertiary); font-family: 'JetBrains Mono', monospace; min-width: 80px; }
.macro-label { width: 120px; font-size: 13px; color: var(--text-secondary); flex-shrink: 0; }
.macro-row .el-input { flex: 1; }
</style>
