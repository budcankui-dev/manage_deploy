<template>
  <div class="batch-view">
    <header class="page-header">
      <div class="title-section">
        <h1>待部署任务中心</h1>
        <p class="subtitle">承接上游解析结果，批量实例化并查看按模板聚合指标</p>
      </div>
      <div class="header-actions">
        <el-button @click="refreshAll">刷新</el-button>
        <el-button type="primary" @click="showCreateDialog = true">新增待部署任务</el-button>
      </div>
    </header>

    <section class="card">
      <div class="card-header">
        <h2>待部署任务</h2>
        <div class="ops">
          <span class="selected-count" v-if="selectedIds.length">已选 {{ selectedIds.length }} 项</span>
          <el-select v-model="statusFilter" placeholder="状态筛选" clearable style="width: 160px">
            <el-option label="待处理" value="pending" />
            <el-option label="已实例化" value="materialized" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-button type="success" plain :disabled="!selectedIds.length" @click="materializeSelected">实例化已选</el-button>
          <el-button type="success" @click="materializePending">批量实例化待处理</el-button>
        </div>
      </div>

      <el-table :data="paginatedOrders" size="small" v-loading="loading">
        <el-table-column label="选择" width="70">
          <template #default="{ row }">
            <el-checkbox :model-value="selectedIds.includes(row.id)" @change="toggleSelected(row.id)" />
          </template>
        </el-table-column>
        <el-table-column prop="name" label="任务名" min-width="180" />
        <el-table-column prop="external_task_id" label="上游任务ID" min-width="180" />
        <el-table-column label="模式" width="120">
          <template #default="{ row }">
            {{ row.deployment_mode === 'scheduled' ? '定时调度' : '实时部署' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="计划启动(UTC+8)" min-width="180">
          <template #default="{ row }">{{ row.scheduled_start_time ? formatUtc8(row.scheduled_start_time) : '-' }}</template>
        </el-table-column>
        <el-table-column label="实例" min-width="220">
          <template #default="{ row }">
            <el-button v-if="row.materialized_instance_id" link type="primary" @click="goInstance(row.materialized_instance_id)">
              {{ row.materialized_instance_id }}
            </el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" link type="primary" @click="materializeOne(row.id)">
              立即实例化
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="filteredOrders.length" class="pagination-wrap">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[8, 12, 20, 50]"
          :total="filteredOrders.length"
        />
      </div>
    </section>

    <section class="card">
      <div class="card-header">
        <h2>模板指标聚合</h2>
        <el-select v-model="metricTemplateId" clearable placeholder="按模板筛选" style="width: 280px" @change="fetchMetrics">
          <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>
      </div>
      <el-table :data="metricSummary" size="small">
        <el-table-column prop="template_id" label="模板ID" min-width="180" />
        <el-table-column prop="metric_key" label="指标" min-width="160" />
        <el-table-column prop="count" label="样本数" width="100" />
        <el-table-column prop="avg" label="平均值" width="120" />
        <el-table-column prop="min" label="最小值" width="120" />
        <el-table-column prop="max" label="最大值" width="120" />
      </el-table>
    </section>

    <el-dialog v-model="showCreateDialog" title="新增待部署任务" width="980px">
      <el-form :model="orderForm" label-position="top">
        <el-form-item label="上游任务ID（可选）">
          <el-input v-model="orderForm.external_task_id" placeholder="parser-task-xxx" />
        </el-form-item>
        <el-form-item label="任务名称" required>
          <el-input v-model="orderForm.name" placeholder="视频AI任务-001" />
        </el-form-item>
        <el-form-item label="模板" required>
          <el-select v-model="orderForm.template_id" style="width: 100%" @change="onTemplateChange">
            <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="部署模式" required>
          <el-radio-group v-model="orderForm.deployment_mode">
            <el-radio label="immediate">实时部署</el-radio>
            <el-radio label="scheduled">定时调度</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="orderForm.deployment_mode === 'scheduled'" label="计划启动时间（UTC+8）" required>
          <el-date-picker v-model="orderForm.scheduled_start_time" type="datetime" style="width: 100%" />
        </el-form-item>
        <el-form-item label="创建后自动启动">
          <el-switch v-model="orderForm.auto_start" />
        </el-form-item>

        <div class="divider">节点运行参数覆盖（实例级）</div>
        <div v-if="!nodeOverrides.length" class="empty-overrides">选择模板后可按节点覆盖运行参数</div>
        <div v-for="(item, index) in nodeOverrides" :key="item.template_node_id" class="override-card">
          <div class="override-title">节点 {{ index + 1 }}：{{ item.template_node_name }}</div>
          <div class="override-grid">
            <el-form-item label="镜像">
              <el-input v-model="item.image" />
            </el-form-item>
            <el-form-item label="部署节点">
              <el-select v-model="item.node_id">
                <el-option v-for="n in nodes" :key="n.id" :label="`${n.hostname} (${n.management_ip})`" :value="n.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="启动命令" class="span-2">
              <el-input v-model="item.command" />
            </el-form-item>
            <el-form-item label="CPU">
              <el-input-number v-model="item.cpu_limit" :min="0" :step="0.1" :precision="1" style="width: 100%" />
            </el-form-item>
            <el-form-item label="GPU ID">
              <el-input v-model="item.gpu_id" placeholder="例如 0" />
            </el-form-item>
            <el-form-item label="内存限制">
              <el-input v-model="item.memory_limit" placeholder="例如 2g" />
            </el-form-item>
            <el-form-item label="网络模式">
              <el-select v-model="item.network_mode">
                <el-option label="主机网络" value="host" />
                <el-option label="桥接网络" value="bridge" />
              </el-select>
            </el-form-item>
            <el-form-item label="重启策略">
              <el-select v-model="item.restart_policy">
                <el-option label="失败时重启" value="on-failure" />
                <el-option label="始终重启" value="always" />
                <el-option label="不自动重启" value="no" />
              </el-select>
            </el-form-item>
            <el-form-item label="环境变量 (KEY=VALUE，每行一条)" class="span-2">
              <el-input v-model="item.env_text" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item label="端口映射 (HOST:CONTAINER，每行一条)" class="span-2">
              <el-input v-model="item.ports_text" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="目录挂载 (HOST:CONTAINER，每行一条)" class="span-2">
              <el-input v-model="item.volumes_text" type="textarea" :rows="2" />
            </el-form-item>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createOrder">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import { ElMessage } from 'element-plus'
import { instancesApi, nodesApi, ordersApi, templatesApi } from '@/api'

dayjs.extend(utc)

const router = useRouter()
const loading = ref(false)
const statusFilter = ref('')
const metricTemplateId = ref('')
const showCreateDialog = ref(false)
const orders = ref([])
const templates = ref([])
const nodes = ref([])
const metricSummary = ref([])
const nodeOverrides = ref([])
const selectedIds = ref([])
const currentPage = ref(1)
const pageSize = ref(8)

const orderForm = ref({
  external_task_id: '',
  name: '',
  template_id: '',
  deployment_mode: 'immediate',
  scheduled_start_time: null,
  auto_start: false,
})

const filteredOrders = computed(() => {
  if (!statusFilter.value) return orders.value
  return orders.value.filter((o) => o.status === statusFilter.value)
})
const paginatedOrders = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredOrders.value.slice(start, start + pageSize.value)
})

onMounted(() => {
  refreshAll()
})

function parseKeyValueText(text) {
  const result = {}
  if (!text) return result
  text.split('\n').map((line) => line.trim()).filter(Boolean).forEach((line) => {
    const idx = line.indexOf('=')
    if (idx > 0) {
      const key = line.slice(0, idx).trim()
      const value = line.slice(idx + 1).trim()
      if (key) result[key] = value
    }
  })
  return result
}

function toggleSelected(id) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function parsePairText(text) {
  const result = {}
  if (!text) return result
  text.split('\n').map((line) => line.trim()).filter(Boolean).forEach((line) => {
    const idx = line.indexOf(':')
    if (idx > 0) {
      const a = line.slice(0, idx).trim()
      const b = line.slice(idx + 1).trim()
      if (a && b) result[a] = b
    }
  })
  return result
}

function formatObjToLines(obj, sep = '=') {
  if (!obj || typeof obj !== 'object') return ''
  return Object.entries(obj).map(([k, v]) => `${k}${sep}${v}`).join('\n')
}

async function refreshAll() {
  loading.value = true
  try {
    const [orderResp, templateResp, nodeResp] = await Promise.all([ordersApi.list(), templatesApi.list(), nodesApi.list()])
    orders.value = orderResp.data
    templates.value = templateResp.data
    nodes.value = nodeResp.data
    await fetchMetrics()
  } finally {
    loading.value = false
  }
}

async function onTemplateChange(templateId) {
  nodeOverrides.value = []
  if (!templateId) return
  const { data } = await templatesApi.get(templateId)
  nodeOverrides.value = (data.nodes || []).map((n) => ({
    template_node_id: n.id,
    template_node_name: n.name,
    image: n.image || '',
    command: n.command || '',
    node_id: n.node_id || '',
    gpu_id: n.gpu_id || '',
    cpu_limit: n.cpu_limit ?? null,
    memory_limit: n.memory_limit || '',
    network_mode: n.network_mode || 'host',
    restart_policy: n.restart_policy || 'on-failure',
    env_text: formatObjToLines(n.env, '='),
    ports_text: formatObjToLines(n.ports, ':'),
    volumes_text: formatObjToLines(n.volumes, ':'),
  }))
}

async function fetchMetrics() {
  const { data } = await instancesApi.templateMetricSummary(metricTemplateId.value || undefined)
  metricSummary.value = data
}

async function createOrder() {
  if (!orderForm.value.name || !orderForm.value.template_id) {
    ElMessage.error('请填写任务名称和模板')
    return
  }
  if (orderForm.value.deployment_mode === 'scheduled' && !orderForm.value.scheduled_start_time) {
    ElMessage.error('请填写定时启动时间')
    return
  }

  const overridesPayload = nodeOverrides.value.map((item) => ({
    template_node_id: item.template_node_id,
    template_node_name: item.template_node_name,
    image: item.image || null,
    command: item.command || null,
    node_id: item.node_id || null,
    gpu_id: item.gpu_id || null,
    cpu_limit: item.cpu_limit ?? null,
    memory_limit: item.memory_limit || null,
    network_mode: item.network_mode || null,
    restart_policy: item.restart_policy || null,
    env: parseKeyValueText(item.env_text),
    ports: parsePairText(item.ports_text),
    volumes: parsePairText(item.volumes_text),
  }))

  await ordersApi.create({
    ...orderForm.value,
    node_overrides: overridesPayload,
  })
  ElMessage.success('待部署任务已创建')
  showCreateDialog.value = false
  orderForm.value = {
    external_task_id: '',
    name: '',
    template_id: '',
    deployment_mode: 'immediate',
    scheduled_start_time: null,
    auto_start: false,
  }
  nodeOverrides.value = []
  await refreshAll()
}

async function materializeOne(orderId) {
  await ordersApi.materialize(orderId)
  ElMessage.success('实例化成功')
  await refreshAll()
}

async function materializePending() {
  const { data } = await ordersApi.materializePending()
  ElMessage.success(`完成批量实例化，成功 ${data.succeeded.length} 个`)
  await refreshAll()
}

async function materializeSelected() {
  let success = 0
  for (const id of selectedIds.value) {
    const order = orders.value.find((item) => item.id === id)
    if (!order || order.status !== 'pending') continue
    await ordersApi.materialize(id)
    success += 1
  }
  selectedIds.value = []
  ElMessage.success(`已实例化 ${success} 个待部署任务`)
  await refreshAll()
}

function goInstance(id) {
  router.push(`/instances/${id}`)
}

function formatUtc8(value) {
  return value ? `${dayjs.utc(value).utcOffset(8).format('YYYY-MM-DD HH:mm:ss')} (UTC+8)` : '-'
}

function statusText(status) {
  const map = { pending: '待处理', materialized: '已实例化', failed: '失败' }
  return map[status] || status
}

function statusTag(status) {
  const map = { pending: 'info', materialized: 'success', failed: 'danger' }
  return map[status] || 'info'
}
</script>

<style scoped>
.batch-view { display: flex; flex-direction: column; gap: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-end; }
.title-section h1 { margin: 0; }
.subtitle { color: var(--text-secondary); margin-top: 6px; }
.header-actions { display: flex; gap: 10px; }
.card { border: 1px solid var(--border-subtle); border-radius: 14px; padding: 16px; background: var(--bg-secondary); }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.ops { display: flex; gap: 10px; }
.selected-count { color: var(--text-secondary); font-size: 13px; }
.divider { margin: 16px 0 8px; font-weight: 600; }
.empty-overrides { color: var(--text-secondary); margin-bottom: 8px; }
.override-card { border: 1px solid var(--border-subtle); border-radius: 12px; padding: 12px; margin-bottom: 12px; }
.override-title { font-weight: 600; margin-bottom: 8px; }
.override-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; }
.span-2 { grid-column: span 2; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
