<template>
  <div class="hub-view">
    <header class="page-header">
      <div>
        <h1>业务工单中心</h1>
        <p class="subtitle">管理业务部署请求、工单状态与业务目标评估。</p>
      </div>
      <div class="actions">
        <el-button @click="refreshAll">刷新</el-button>
        <el-button type="primary" plain :loading="demoRunning" @click="submitSample">
          一键演示矩阵乘法
        </el-button>
      </div>
    </header>

    <section class="card">
      <div class="card-header">
        <h2>工单列表</h2>
        <div class="batch-actions">
          <span>已选 {{ selectedOrderIds.length }} 个</span>
          <el-button
            size="small"
            type="warning"
            plain
            :disabled="!selectedOrderIds.length"
            :loading="batchCleanupLoading"
            @click="cleanupSelectedOrderInstances"
          >
            清理实例保留工单
          </el-button>
          <el-button
            size="small"
            type="danger"
            plain
            :disabled="!selectedOrderIds.length"
            :loading="batchDeleteLoading"
            @click="deleteSelectedOrders"
          >
            删除选中工单
          </el-button>
          <el-button
            size="small"
            type="warning"
            :disabled="!hasBenchmarkRunScope"
            :loading="runCleanupLoading"
            @click="cleanupCurrentBenchmarkRun"
          >
            清理本轮实例
          </el-button>
          <el-button
            size="small"
            type="danger"
            :disabled="!hasBenchmarkRunScope"
            :loading="runDeleteLoading"
            @click="deleteCurrentBenchmarkRun"
          >
            删除本轮工单
          </el-button>
        </div>
        <div class="filters">
          <el-input v-model="filters.q" placeholder="搜索名称/任务ID" clearable style="width: 200px" @keyup.enter="applyFilters" />
          <el-select v-model="filters.task_type" placeholder="任务类型" clearable style="width: 180px" @change="applyFilters">
            <el-option v-for="t in taskTypeOptions" :key="t" :label="taskTypeLabel(t)" :value="t" />
          </el-select>
          <el-select v-model="filters.is_benchmark" placeholder="工单来源" clearable style="width: 130px" @change="applyFilters">
            <el-option label="验收压测" :value="true" />
            <el-option label="普通工单" :value="false" />
          </el-select>
          <el-input
            v-model="filters.benchmark_run_id"
            placeholder="验收轮次ID"
            clearable
            style="width: 230px"
            @keyup.enter="applyFilters"
            @clear="applyFilters"
          />
          <el-select v-model="filters.routing_policy" placeholder="路由策略" clearable style="width: 150px" @change="applyFilters">
            <el-option v-for="(label, key) in ROUTING_POLICY_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select v-model="filters.order_status" placeholder="工单状态" clearable style="width: 130px" @change="applyFilters">
            <el-option v-for="(label, key) in ORDER_STATUS_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select v-model="filters.deployment_status" placeholder="部署状态" clearable style="width: 130px" @change="applyFilters">
            <el-option v-for="(label, key) in DEPLOYMENT_STATUS_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select v-model="filters.business_success" placeholder="性能达标" clearable style="width: 120px" @change="applyFilters">
            <el-option label="达标" :value="true" />
            <el-option label="未达标" :value="false" />
          </el-select>
          <el-checkbox v-model="filters.include_cancelled" @change="applyFilters">显示已取消</el-checkbox>
          <el-button size="small" @click="applyFilters">应用筛选</el-button>
        </div>
        <p class="batch-hint">
          清理实例会释放远端容器和实例记录，但保留工单、路由结果、业务指标和结果文件；删除工单用于清掉废弃压测轮次。
        </p>
      </div>

      <el-table
        :data="items"
        size="small"
        v-loading="listLoading"
        @selection-change="handleOrderSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="工单ID" width="120">
          <template #default="{ row }"><code style="font-size:11px">{{ row.order_id?.slice(0,8) }}</code></template>
        </el-table-column>
        <el-table-column label="任务类型" min-width="160">
          <template #default="{ row }">
            {{ taskTypeLabel(row.task_type) || '-' }}
            <el-tag v-if="row.is_benchmark" size="small" type="warning" effect="plain" style="margin-left:6px">压测</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属模态" min-width="150">
          <template #default="{ row }">
            <el-tag size="small" type="success" effect="plain">{{ modalityLabel(row.modality) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="路由策略" min-width="130">
          <template #default="{ row }">{{ routingPolicyLabel(row.routing_policy) }}</template>
        </el-table-column>
        <el-table-column label="验收轮次" min-width="190">
          <template #default="{ row }">
            <code v-if="row.benchmark_run_id" style="font-size:11px">{{ row.benchmark_run_id }}</code>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="工单状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="orderStatusTag(row.order_status)">{{ ORDER_STATUS_LABELS[row.order_status] || row.order_status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="部署状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.instance_exists === false" size="small" type="warning">实例已删除</el-tag>
            <el-tag v-else-if="row.deployment_status" size="small" :type="deploymentStatusTag(row.deployment_status)">
              {{ DEPLOYMENT_STATUS_LABELS[row.deployment_status] || row.deployment_status }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="目标 / 实际" min-width="160">
          <template #default="{ row }">
            <span v-if="row.target_value != null">
              {{ formatMetric(row.actual_value) }} / {{ formatMetric(row.target_value) }} {{ row.unit || '' }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="性能达标" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.business_success === true" type="success" size="small">达标</el-tag>
            <el-tag v-else-if="row.business_success === false" type="danger" size="small">未达标</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="业务指标" min-width="160">
          <template #default="{ row }">
            <span v-if="row.target_value != null">{{ metricMeaningLabel(row) }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="调度开始" min-width="150">
          <template #default="{ row }">
            {{ row.scheduled_start_time ? dayjs(row.scheduled_start_time).format('MM-DD HH:mm') : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="调度结束" min-width="150">
          <template #default="{ row }">
            {{ row.scheduled_end_time ? dayjs(row.scheduled_end_time).format('MM-DD HH:mm') : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="关联实例" width="120">
          <template #default="{ row }">
            <template v-if="row.instance_id && row.instance_exists !== false">
              <el-button link type="primary" @click="$router.push(`/dev/instances/${row.instance_id}`)">
                查看实例
              </el-button>
            </template>
            <el-tag v-else-if="row.instance_id && row.instance_exists === false" size="small" type="warning">
              实例已删除
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row.order_id)">详情</el-button>
            <el-button
              v-if="row.order_status === 'pending' && !row.instance_id"
              link
              type="warning"
              @click="openManualRouting(row)"
            >手动路由</el-button>
            <el-button
              v-if="row.instance_id && row.instance_exists !== false && canStart(row.deployment_status)"
              link
              type="success"
              @click="startInstance(row.instance_id)"
            >启动</el-button>
            <el-button
              v-if="row.instance_id && row.instance_exists !== false && row.deployment_status === 'running'"
              link
              type="warning"
              @click="stopInstance(row.instance_id)"
            >停止</el-button>
            <el-button link type="danger" @click="deleteOrder(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="total" class="pagination-wrap">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[10, 20, 50]"
          :total="total"
          @current-change="loadList"
          @size-change="loadList"
        />
      </div>
    </section>

    <el-drawer v-model="drawerOpen" :title="detailTitle" size="64%" destroy-on-close class="task-detail-drawer">
      <OrderDetailPanel
        v-loading="detailLoading"
        v-model:active-tab="detailTab"
        :detail="orderDetail"
        :result-objects="resultObjects"
      >
        <template #deployment-actions="{ instance }">
          <el-button v-if="canStart(instance?.status)" type="primary" @click="startInstance(instance.id)">启动</el-button>
          <el-button v-if="instance?.status === 'running'" type="warning" @click="stopInstance(instance.id)">停止</el-button>
          <el-button v-if="instance?.id" @click="$router.push(`/dev/instances/${instance.id}`)">完整实例页</el-button>
        </template>
      </OrderDetailPanel>
    </el-drawer>

    <!-- 手动路由对话框 -->
    <el-dialog v-model="manualRoutingVisible" title="手动分配路由" width="520px" destroy-on-close>
      <p style="margin-bottom:12px">为任务 <strong>{{ manualRoutingOrder?.name || '未命名' }}</strong> 分配计算节点</p>
      <el-form label-width="100px" size="small">
        <el-form-item label="数据源节点">
          <el-select v-model="manualPlacements.source.worker_host" placeholder="选择节点" :disabled="manualPlacements.source.skip_deploy" clearable style="width:200px">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.hostname" />
          </el-select>
          <el-checkbox v-model="manualPlacements.source.skip_deploy" style="margin-left:12px">不部署</el-checkbox>
        </el-form-item>
        <el-form-item label="计算节点">
          <el-select v-model="manualPlacements.worker.worker_host" placeholder="选择节点" style="width:200px">
            <el-option v-for="n in schedulableNodes" :key="n.id" :label="n.hostname" :value="n.hostname" />
          </el-select>
          <el-input v-model="manualPlacements.worker.gpu_device" placeholder="GPU编号" style="width:80px;margin-left:8px" />
        </el-form-item>
        <el-form-item label="汇总节点">
          <el-select v-model="manualPlacements.sink.worker_host" placeholder="选择节点" :disabled="manualPlacements.sink.skip_deploy" clearable style="width:200px">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.hostname" />
          </el-select>
          <el-checkbox v-model="manualPlacements.sink.skip_deploy" style="margin-left:12px">不部署</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualRoutingVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualRoutingLoading" @click="submitManualRouting">确认分配</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'
import { businessApi, instancesApi, nodesApi, ordersApi } from '@/api'
import OrderDetailPanel from '@/components/OrderDetailPanel.vue'
import {
  DEPLOYMENT_STATUS_LABELS,
  ORDER_STATUS_LABELS,
  ROUTING_POLICY_LABELS,
  routingPolicyLabel,
} from '@/constants/routingPolicy'
import {
  MATMUL_PIPELINE_STEPS,
  TASK_TYPE_LABELS,
  VIDEO_PIPELINE_STEPS,
  buildMatmulInputRows,
  buildMatmulOutputRows,
  buildMatmulParamConsistency,
  buildMatmulVerdict,
  buildVideoInputRows,
  buildVideoOutputRows,
  buildVideoVerdict,
  describeDataProfile,
  describeObjectiveMeaning,
  describeRuntimePlan,
  formatObjectiveSentence,
  modalityLabel,
  taskTypeLabel,
  taskTypeSummary,
  videoDetectionBoxStyle,
  videoDetections,
  videoPreviewEvidenceRows,
  videoPreviewNeedsOverlay,
  videoPreviewDataUrl,
} from '@/constants/businessTaskDisplay'

const route = useRoute()
const router = useRouter()
const demoRunning = ref(false)
const listLoading = ref(false)
const detailLoading = ref(false)
const batchCleanupLoading = ref(false)
const batchDeleteLoading = ref(false)
const runCleanupLoading = ref(false)
const runDeleteLoading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const nodes = ref([])
const selectedOrderIds = ref([])

const schedulableNodes = computed(() => nodes.value.filter(n => n.is_schedulable !== false))

const filters = reactive({
  q: '',
  task_type: '',
  is_benchmark: '',
  benchmark_run_id: '',
  routing_policy: '',
  order_status: '',
  deployment_status: '',
  business_success: '',
  include_cancelled: false,
})

const drawerOpen = ref(false)
const detailTab = ref('business')
const orderDetail = ref(null)
const instanceDetail = ref(null)
const resultObjects = ref([])

const taskTypeOptions = computed(() => Object.keys(TASK_TYPE_LABELS))
const hasBenchmarkRunScope = computed(() =>
  filters.is_benchmark === true && Boolean(String(filters.benchmark_run_id || '').trim())
)

const detailTitle = computed(() => orderDetail.value?.name || '任务详情')

const manualRoutingVisible = ref(false)
const manualRoutingOrder = ref(null)
const manualRoutingLoading = ref(false)
const manualPlacements = ref({
  source: { worker_host: '', gpu_device: null, skip_deploy: false },
  worker: { worker_host: '', gpu_device: '0', skip_deploy: false },
  sink: { worker_host: '', gpu_device: null, skip_deploy: false },
})


const placementRows = computed(() => {
  const placements = orderDetail.value?.routing_result?.placements
  if (!placements) return []
  const rowFor = (role, placement) => {
    const roleName = { source: '数据源', worker: '计算', compute: '计算', sink: '汇总' }[role] || role
    const requiresGpu = ['worker', 'compute'].includes(role)
    if (!placement) {
      return {
        role: roleName,
        node_id: role,
        worker_host: '未部署',
        gpu_device: null,
        gpu_display: requiresGpu ? '未记录' : '不需要',
        requires_gpu: requiresGpu,
      }
    }
    if (typeof placement === 'string') {
      return {
        role: roleName,
        node_id: role,
        worker_host: placement,
        gpu_device: null,
        gpu_display: requiresGpu ? '未记录' : '不需要',
        requires_gpu: requiresGpu,
      }
    }
    const gpu = placement.gpu_device ?? (Array.isArray(placement.gpu_indices) ? placement.gpu_indices[0] : null)
    return {
      role: roleName,
      node_id: placement.node_id || role,
      worker_host: placement.worker_host || placement.node_name || placement.hostname || placement.node_id || '未部署',
      gpu_device: gpu,
      gpu_display: hasGpuValue(gpu) ? String(gpu) : (requiresGpu ? '未记录' : '不需要'),
      requires_gpu: requiresGpu,
    }
  }
  if (Array.isArray(placements)) {
    const map = {}
    placements.forEach(p => { map[p.node_id] = p })
    return [
      rowFor('source', map.source),
      rowFor('compute', map.compute || map.worker),
      rowFor('sink', map.sink),
    ]
  }
  return [
    rowFor('source', placements.source),
    rowFor('compute', placements.compute || placements.worker),
    rowFor('sink', placements.sink),
  ]
})

const portAccessRows = computed(() => {
  if (!instanceDetail.value?.nodes) return []
  const rows = []
  for (const node of instanceDetail.value.nodes) {
    const addr = node.business_address || ''
    for (const [name, port] of Object.entries(node.port_values || {})) {
      rows.push({
        nodeName: node.name,
        portName: name,
        accessUrl: addr ? (addr.includes(':') ? `http://[${addr}]:${port}` : `http://${addr}:${port}`) : `*:${port}`,
      })
    }
  }
  return rows
})

const detailTaskType = computed(() => orderDetail.value?.business_task?.task_type || '')
const detailTaskSummary = computed(() => taskTypeSummary(detailTaskType.value))
const detailObjectiveSentence = computed(() =>
  formatObjectiveSentence(orderDetail.value?.business_task?.business_objective)
)
const detailObjectiveMeaning = computed(() =>
  describeObjectiveMeaning(detailTaskType.value, orderDetail.value?.business_task?.business_objective)
)
const detailDataProfileRows = computed(() =>
  describeDataProfile(detailTaskType.value, orderDetail.value?.business_task?.data_profile)
)
const detailRuntimePlanRows = computed(() =>
  describeRuntimePlan(detailTaskType.value, orderDetail.value?.business_task?.runtime_plan)
)
const isMatmulDetail = computed(() => detailTaskType.value === 'high_throughput_matmul')
const isVideoDetail = computed(() => detailTaskType.value === 'low_latency_video_pipeline')
const matmulPipelineSteps = MATMUL_PIPELINE_STEPS
const videoPipelineSteps = VIDEO_PIPELINE_STEPS
const detailMatmulInputRows = computed(() =>
  buildMatmulInputRows(orderDetail.value?.business_task?.data_profile)
)
const detailMatmulOutputRows = computed(() =>
  buildMatmulOutputRows(
    orderDetail.value?.evaluation?.result_metadata,
    orderDetail.value?.evaluation
  )
)
const detailMatmulConsistency = computed(() =>
  buildMatmulParamConsistency(
    orderDetail.value?.business_task?.data_profile,
    orderDetail.value?.evaluation?.result_metadata
  )
)
const detailMatmulVerdict = computed(() => buildMatmulVerdict(orderDetail.value?.evaluation))
const detailVideoInputRows = computed(() =>
  buildVideoInputRows(orderDetail.value?.business_task?.data_profile)
)
const detailVideoOutputRows = computed(() =>
  buildVideoOutputRows(
    orderDetail.value?.evaluation?.result_metadata,
    orderDetail.value?.evaluation
  )
)
const detailVideoVerdict = computed(() => buildVideoVerdict(orderDetail.value?.evaluation))
const detailVideoPreview = computed(() =>
  videoPreviewDataUrl(orderDetail.value?.evaluation?.result_metadata)
)
const detailVideoDetections = computed(() =>
  videoDetections(orderDetail.value?.evaluation?.result_metadata)
)
const detailVideoEvidenceRows = computed(() =>
  videoPreviewEvidenceRows(orderDetail.value?.evaluation?.result_metadata)
)
const detailVideoNeedsOverlay = computed(() =>
  videoPreviewNeedsOverlay(orderDetail.value?.evaluation?.result_metadata)
)

function detailVideoBoxStyle(row) {
  return videoDetectionBoxStyle(row, orderDetail.value?.evaluation?.result_metadata)
}

const resultVerdictClass = computed(() => {
  const evaluation = orderDetail.value?.evaluation
  if (!evaluation) return 'pending'
  return evaluation.business_success ? 'success' : 'danger'
})
const resultVerdictTitle = computed(() => {
  const evaluation = orderDetail.value?.evaluation
  if (!evaluation) return '等待计算结果'
  return evaluation.business_success ? '耗时已达标' : '耗时未达标'
})
const resultVerdictSubtitle = computed(() => {
  const evaluation = orderDetail.value?.evaluation
  if (!evaluation) {
    return '任务跑完并上报指标后，将在此展示是否达标。'
  }
  if (evaluation.business_success) {
    return `实际 ${evaluation.actual_value} ${evaluation.unit || ''}，满足目标 ${formatObjectiveSentence(orderDetail.value?.business_task?.business_objective)}。`
  }
  return evaluation.failure_reason || '未满足业务目标阈值。'
})

onMounted(async () => {
  applyRouteFilters()
  await refreshAll()
  const orderId = route.query.orderId
  if (typeof orderId === 'string' && orderId) {
    await openDetail(orderId, 'result')
    router.replace({ query: {} })
  }
})

watch(
  () => route.query.orderId,
  async (orderId) => {
    if (typeof orderId === 'string' && orderId) {
      await openDetail(orderId, 'result')
      router.replace({ query: {} })
    }
  }
)

function applyRouteFilters() {
  const query = route.query
  if (typeof query.task_type === 'string') filters.task_type = query.task_type
  if (typeof query.benchmark_run_id === 'string') filters.benchmark_run_id = query.benchmark_run_id
  if (typeof query.is_benchmark === 'string') {
    filters.is_benchmark = query.is_benchmark === 'true'
  }
}


function formatMetric(value) {
  return value == null ? '-' : Number(value)
}

function metricMeaningLabel(row) {
  const METRIC_LABELS = {
    compute_latency_ms: '计算耗时',
    end_to_end_latency_ms: '端到端时延',
    effective_gflops: '有效算力',
    tokens_per_second: '推理吞吐',
    frame_latency_p90_ms: '帧推理时延 P90',
  }
  return METRIC_LABELS[row.metric_key] || row.metric_key || '指标'
}

function formatTime(value) {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-'
}

function pretty(value) {
  if (value == null) return '-'
  return JSON.stringify(value, null, 2)
}

function hasGpuValue(value) {
  return value !== null && value !== undefined && String(value) !== ''
}

function orderStatusTag(status) {
  return { pending: 'info', materialized: 'success', failed: 'danger', cancelled: 'warning' }[status] || 'info'
}

function deploymentStatusTag(status) {
  return {
    pending: 'info',
    scheduled: 'info',
    starting: 'warning',
    running: 'success',
    stopping: 'warning',
    stopped: 'info',
    failed: 'danger',
    expired: 'warning',
  }[status] || 'info'
}

function canStart(status) {
  return ['pending', 'scheduled', 'stopped', 'failed'].includes(status)
}

function handleOrderSelectionChange(rows) {
  selectedOrderIds.value = rows.map(row => row.order_id).filter(Boolean)
}

async function refreshAll() {
  await Promise.all([loadList(), loadNodes()])
}

function buildFilterParams({ includePaging = false } = {}) {
  const params = {
    include_cancelled: filters.include_cancelled,
  }
  if (includePaging) {
    params.page = page.value
    params.page_size = pageSize.value
  }
  if (filters.q && includePaging) params.q = filters.q
  if (filters.task_type) params.task_type = filters.task_type
  if (filters.is_benchmark !== '' && filters.is_benchmark != null) params.is_benchmark = filters.is_benchmark
  if (filters.benchmark_run_id) params.benchmark_run_id = String(filters.benchmark_run_id).trim()
  if (filters.routing_policy && includePaging) params.routing_policy = filters.routing_policy
  if (filters.order_status && includePaging) params.order_status = filters.order_status
  if (filters.deployment_status && includePaging) params.deployment_status = filters.deployment_status
  if (filters.business_success !== '' && filters.business_success != null && includePaging) {
    params.business_success = filters.business_success
  }
  return params
}

async function applyFilters() {
  page.value = 1
  selectedOrderIds.value = []
  await loadList()
}

async function loadNodes() {
  const { data } = await nodesApi.list()
  nodes.value = data
}

async function loadList() {
  listLoading.value = true
  try {
    const { data } = await businessApi.list(buildFilterParams({ includePaging: true }))
    items.value = data.items
    total.value = data.total
    selectedOrderIds.value = []
  } finally {
    listLoading.value = false
  }
}

async function openDetail(orderId, tab = 'business') {
  drawerOpen.value = true
  detailTab.value = tab
  detailLoading.value = true
  orderDetail.value = null
  instanceDetail.value = null
  resultObjects.value = []
  try {
    const { data } = await ordersApi.get(orderId)
    const evidenceInstanceId = data.instance?.id || data.materialized_instance_id
    let evaluationData = data.evaluation || null
    if (data.instance?.id) {
      const [instResp, objectsResp, evalResp] = await Promise.all([
        instancesApi.get(data.instance.id),
        evidenceInstanceId ? businessApi.results(evidenceInstanceId).catch(() => ({ data: [] })) : { data: [] },
        evidenceInstanceId && !evaluationData
          ? businessApi.evaluation(evidenceInstanceId).catch(() => ({ data: null }))
          : { data: evaluationData },
      ])
      instanceDetail.value = instResp.data
      resultObjects.value = objectsResp.data
      evaluationData = evalResp.data || evaluationData
    } else if (evidenceInstanceId) {
      const [objectsResp, evalResp] = await Promise.all([
        businessApi.results(evidenceInstanceId).catch(() => ({ data: [] })),
        evaluationData ? Promise.resolve({ data: evaluationData }) : businessApi.evaluation(evidenceInstanceId).catch(() => ({ data: null })),
      ])
      resultObjects.value = objectsResp.data
      evaluationData = evalResp.data || evaluationData
    }
    orderDetail.value = {
      ...data,
      evaluation: evaluationData || data.evaluation || null,
    }
  } finally {
    detailLoading.value = false
  }
}

async function startInstance(instanceId) {
  await instancesApi.start(instanceId)
  ElMessage.success('实例已启动')
  await refreshAll()
  if (orderDetail.value?.instance?.id === instanceId) {
    await openDetail(orderDetail.value.id)
  }
}

async function stopInstance(instanceId) {
  await instancesApi.stop(instanceId)
  ElMessage.success('实例已停止')
  await refreshAll()
  if (orderDetail.value?.instance?.id === instanceId) {
    await openDetail(orderDetail.value.id)
  }
}

async function deleteOrder(row) {
  const { order_id, instance_id, instance_exists } = row
  if (instance_id && instance_exists !== false) {
    try {
      await ElMessageBox.confirm(
        '删除工单的同时会删除对应的部署实例，继续吗？',
        '确认删除',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
      )
    } catch {
      return
    }
  }
  await ordersApi.delete(order_id)
  ElMessage.success('工单已删除')
  drawerOpen.value = false
  await refreshAll()
}

async function cleanupSelectedOrderInstances() {
  if (!selectedOrderIds.value.length) return
  try {
    await ElMessageBox.confirm(
      `将清理 ${selectedOrderIds.value.length} 个已选工单的容器实例，工单、路由和评估结果会保留，继续吗？`,
      '清理实例保留证据',
      { type: 'warning', confirmButtonText: '清理实例', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  batchCleanupLoading.value = true
  try {
    const { data } = await ordersApi.cleanupInstances(selectedOrderIds.value)
    ElMessage.success(`已清理 ${data.succeeded?.length || 0} 个工单实例，工单证据已保留`)
    selectedOrderIds.value = []
    await refreshAll()
  } finally {
    batchCleanupLoading.value = false
  }
}

async function deleteSelectedOrders() {
  if (!selectedOrderIds.value.length) return
  try {
    await ElMessageBox.confirm(
      `将删除 ${selectedOrderIds.value.length} 个工单及其关联实例，删除后不可恢复，继续吗？`,
      '确认批量删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  batchDeleteLoading.value = true
  try {
    const { data } = await ordersApi.batchDelete(selectedOrderIds.value)
    ElMessage.success(`已删除 ${data.succeeded?.length || 0} 个工单`)
    selectedOrderIds.value = []
    drawerOpen.value = false
    await refreshAll()
  } finally {
    batchDeleteLoading.value = false
  }
}

function buildBenchmarkRunScopePayload() {
  return {
    benchmark_run_id: String(filters.benchmark_run_id || '').trim(),
    task_type: filters.task_type || undefined,
    is_benchmark: true,
  }
}

async function cleanupCurrentBenchmarkRun() {
  if (!hasBenchmarkRunScope.value) return
  const payload = buildBenchmarkRunScopePayload()
  const typeText = filters.task_type ? `，任务类型 ${taskTypeLabel(filters.task_type)}` : ''
  try {
    await ElMessageBox.confirm(
      `将清理验收轮次 ${payload.benchmark_run_id}${typeText} 的全部容器实例，但保留工单、路由和评估证据，继续吗？`,
      '清理本轮实例',
      { type: 'warning', confirmButtonText: '清理实例', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  runCleanupLoading.value = true
  try {
    const { data } = await ordersApi.cleanupInstances(payload)
    ElMessage.success(`本轮已清理 ${data.succeeded?.length || 0} 个工单实例，证据已保留`)
    selectedOrderIds.value = []
    await refreshAll()
  } finally {
    runCleanupLoading.value = false
  }
}

async function deleteCurrentBenchmarkRun() {
  if (!hasBenchmarkRunScope.value) return
  const payload = buildBenchmarkRunScopePayload()
  const typeText = filters.task_type ? `，任务类型 ${taskTypeLabel(filters.task_type)}` : ''
  try {
    await ElMessageBox.confirm(
      `将删除验收轮次 ${payload.benchmark_run_id}${typeText} 的全部工单及关联实例。删除后该轮不会再计入验收统计，继续吗？`,
      '删除本轮工单',
      { type: 'error', confirmButtonText: '删除本轮', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  runDeleteLoading.value = true
  try {
    const { data } = await ordersApi.batchDelete(payload)
    ElMessage.success(`本轮已删除 ${data.succeeded?.length || 0} 个工单`)
    selectedOrderIds.value = []
    drawerOpen.value = false
    await refreshAll()
  } finally {
    runDeleteLoading.value = false
  }
}

function openManualRouting(row) {
  manualRoutingOrder.value = row
  manualPlacements.value = {
    source: { worker_host: '', gpu_device: null, skip_deploy: false },
    worker: { worker_host: '', gpu_device: '0', skip_deploy: false },
    sink: { worker_host: '', gpu_device: null, skip_deploy: false },
  }
  manualRoutingVisible.value = true
}

async function submitManualRouting() {
  if (!manualPlacements.value.worker.worker_host) {
    ElMessage.warning('Worker 节点必须选择')
    return
  }
  manualRoutingLoading.value = true
  try {
    const placements = ['source', 'worker', 'sink']
      .filter(role => !manualPlacements.value[role].skip_deploy && manualPlacements.value[role].worker_host)
      .map(role => ({
        node_id: role,
        worker_host: manualPlacements.value[role].worker_host,
        gpu_device: manualPlacements.value[role].gpu_device || null,
      }))
    await ordersApi.submitRoutingResult(manualRoutingOrder.value.order_id, { placements })
    ElMessage.success('路由分配成功，实例已创建')
    manualRoutingVisible.value = false
    await refreshAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '路由分配失败')
  } finally {
    manualRoutingLoading.value = false
  }
}

async function waitForEvaluation(instanceId, maxAttempts = 80, intervalMs = 3000) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const { data } = await businessApi.evaluation(instanceId)
      if (data && data.actual_value != null) {
        return data
      }
    } catch (error) {
      if (error.response?.status !== 404) {
        throw error
      }
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  return null
}

async function submitSample() {
  if (nodes.value.length < 3) {
    ElMessage.error('至少需要 3 个工作节点才能提交示例任务')
    return
  }
  demoRunning.value = true
  const payload = {
    external_task_id: `matmul-ui-${Date.now()}`,
    task_type: 'high_throughput_matmul',
    modality: 'high_throughput_compute',
    name: '矩阵乘法示例任务',
    description: '演示科学计算流水线：三节点 batched 矩阵乘法，以计算耗时验收是否达标。',
    data_profile: {
      profile_id: 'matmul_dev',
      matrix_size: 64,
      batch_count: 1,
      seed: 42,
    },
    business_objective: {
      metric_key: 'effective_gflops',
      operator: '>=',
      target_value: 100,
      unit: 'GFLOPS',
    },
    runtime_plan: {
      algorithm: 'batched_matmul',
      precision: 'fp32',
      use_gpu: false,
    },
    routing_result: {
      strategy: 'completion_time_first',
      placements: {
        source: nodes.value[0].id,
        compute: nodes.value[1].id,
        sink: nodes.value[2].id,
      },
      estimated_metric: { metric_key: 'effective_gflops', metric_value: 200, unit: 'GFLOPS' },
    },
    result_storage: { backend: 'minio', bucket: 'task-results' },
    auto_start: true,
  }
  try {
    const { data } = await businessApi.submit(payload)
    ElMessage.info('任务已提交并自动启动，等待计算完成…')
    await refreshAll()
    const evaluation = await waitForEvaluation(data.instance_id)
    await refreshAll()
    if (evaluation) {
      ElMessage.success('演示完成，可在结果 Tab 查看计算内容与是否达标')
      await openDetail(data.order_id, 'result')
    } else {
      ElMessage.warning('任务已启动，评估结果尚未就绪，请稍后刷新或打开详情')
      await openDetail(data.order_id, 'deployment')
    }
  } finally {
    demoRunning.value = false
  }
}
</script>

<style scoped>
.hub-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
}

.subtitle {
  color: var(--text-secondary);
  margin-top: 6px;
}

.actions {
  display: flex;
  gap: 10px;
}

.card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 16px;
  background: var(--bg-secondary);
}

.card-header {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.card-header h2 {
  margin: 0;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.batch-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 13px;
}

.batch-hint {
  margin: -2px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.task-summary {
  margin: 0 0 14px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.task-type-cell {
  display: block;
}

.task-type-code {
  display: block;
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 11px;
}

.objective-card {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
}

.objective-headline {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.objective-meaning {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.raw-collapse {
  margin-top: 8px;
}

.result-verdict {
  margin-bottom: 14px;
  padding: 14px 16px;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
}

.result-verdict strong {
  display: block;
  margin-bottom: 6px;
  color: var(--text-primary);
  font-size: 15px;
}

.result-verdict p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.result-verdict.success {
  border-color: rgba(34, 197, 94, 0.35);
  background: rgba(34, 197, 94, 0.08);
}

.result-verdict.danger {
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.08);
}

.result-verdict.pending {
  border-color: rgba(59, 130, 246, 0.35);
  background: rgba(59, 130, 246, 0.08);
}

.field-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.pipeline-steps {
  margin: 0 0 16px;
  padding-left: 20px;
  color: var(--text-secondary);
  line-height: 1.7;
  font-size: 13px;
}

.pipeline-steps strong {
  color: var(--accent-secondary);
  text-transform: uppercase;
  font-size: 12px;
}

.video-result-card {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}

.video-preview {
  min-height: 240px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--bg-tertiary);
  overflow: hidden;
}

.video-proof-frame {
  position: relative;
}

.video-preview img,
.video-proof-frame img {
  display: block;
  width: 100%;
  height: auto;
}

.video-proof-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.video-proof-badge {
  position: absolute;
  left: 10px;
  bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: calc(100% - 20px);
}

.video-proof-badge span,
.video-proof-box span {
  color: #fff;
  background: rgba(15, 23, 42, 0.88);
  border-radius: 6px;
  padding: 3px 7px;
  font-size: 12px;
  line-height: 1.4;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.28);
}

.video-proof-box {
  position: absolute;
  border: 2px solid #22c55e;
  box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.3);
}

.video-proof-box span {
  position: absolute;
  left: -2px;
  top: -28px;
  background: rgba(22, 163, 74, 0.94);
  white-space: nowrap;
}

.video-result-side .section-title:first-child {
  margin-top: 0;
}

.consistency-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: 12px 0 4px;
}

.consistency-detail {
  color: var(--text-secondary);
  font-size: 13px;
}

.warning-text {
  color: #e6a23c;
  font-weight: 700;
}

.text-success {
  color: var(--success);
  font-weight: 600;
}

.text-danger {
  color: var(--danger);
  font-weight: 600;
}

.json-block {
  background: var(--bg-tertiary);
  border-radius: 8px;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
}

.success-rate-cards {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.success-rate-card {
  text-align: center;
  padding: 20px 32px;
  background: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  flex: 1;
  min-width: 180px;
}
.rate-detail {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.rate-number {
  font-size: 48px;
  font-weight: 700;
  line-height: 1.2;
}
.rate-number.pass { color: #67c23a; }
.rate-number.fail { color: #f56c6c; }
.rate-label {
  font-size: 14px;
  color: #606266;
  margin-top: 8px;
}

.deploy-actions {
  display: flex;
  gap: 10px;
  margin: 16px 0;
}
</style>

<style>
.task-detail-drawer.el-drawer {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.task-detail-drawer .el-drawer__header {
  margin-bottom: 0;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-primary);
}

.task-detail-drawer .el-drawer__title {
  color: var(--text-primary);
}

.task-detail-drawer .el-drawer__body {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.task-detail-drawer .el-tabs__item {
  color: var(--text-secondary);
}

.task-detail-drawer .el-tabs__item.is-active {
  color: var(--accent-secondary);
}

.task-detail-drawer .detail-desc .el-descriptions__label,
.task-detail-drawer .detail-desc .el-descriptions__content {
  background: var(--bg-tertiary) !important;
  color: var(--text-primary) !important;
  border-color: var(--border-subtle) !important;
}

.task-detail-drawer .raw-collapse .el-collapse-item__header {
  background: transparent;
  color: var(--text-secondary);
  border-color: var(--border-subtle);
}

.task-detail-drawer .raw-collapse .el-collapse-item__wrap,
.task-detail-drawer .raw-collapse .el-collapse-item__content {
  background: transparent;
  border-color: var(--border-subtle);
}
</style>
