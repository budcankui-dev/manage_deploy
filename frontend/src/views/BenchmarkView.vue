<template>
  <div class="benchmark-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">验收测试</p>
        <h1>业务目标成功率闭环验证</h1>
        <p class="hero-subtitle">按基线、批量压测、路由执行、成功率统计四步完成专家验收演示；正式判定要求已评估任务 ≥ 30 且成功率 ≥ 90%。</p>
      </div>
      <div class="hero-actions">
        <span class="field-label">任务类型</span>
        <el-select v-model="taskType" class="task-select">
          <el-option label="矩阵乘法计算任务" value="high_throughput_matmul" />
        </el-select>
        <el-button type="primary" :loading="fullFlowLoading" @click="startFullFlow">
          开始完整测试流程
        </el-button>
      </div>
    </section>

    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">1</span>
          <div>
            <div class="step-title">基线</div>
            <div class="step-desc">直接列出所有可调度节点，未测试节点标红。</div>
          </div>
          <el-button
            class="header-action"
            size="small"
            type="warning"
            plain
            :loading="batchBaselineLoading"
            @click="runBatchBaseline"
          >
            批量测试所有节点
          </el-button>
        </div>
      </template>
      <el-table
        :data="nodeBaselineRows"
        size="small"
        v-loading="nodesLoading || baselinesLoading"
        :row-class-name="baselineRowClass"
      >
        <el-table-column prop="hostname" label="节点" min-width="150" />
        <el-table-column label="基线值" min-width="180">
          <template #default="{ row }">
            <span v-if="row.baseline_value != null" class="baseline-value">
              {{ row.baseline_value.toFixed(2) }} {{ row.unit }}
            </span>
            <el-tag v-else type="danger" size="small">未测试</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="稳定性" min-width="120">
          <template #default="{ row }">
            <el-tag v-if="row.stable === true" type="success" size="small">稳定</el-tag>
            <el-tag v-else-if="row.stable === false" type="warning" size="small">波动大</el-tag>
            <span v-else class="muted">未测试</span>
          </template>
        </el-table-column>
        <el-table-column label="上次更新" min-width="150">
          <template #default="{ row }">{{ row.updated_at ? formatTime(row.updated_at) : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              plain
              :loading="testingNodes.get(row.node_id)"
              @click="runSingleBaseline(row)"
            >
              {{ row.baseline_value != null ? '重测' : '测试' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">2</span>
          <div>
            <div class="step-title">批量压测</div>
            <div class="step-desc">创建带 is_benchmark 标记的验收工单。</div>
          </div>
        </div>
      </template>
      <div class="pressure-row">
        <div class="pressure-form">
          <span>任务数</span>
          <el-input-number v-model="benchmarkForm.count" :min="1" :max="30" controls-position="right" />
          <span>矩阵</span>
          <el-input-number v-model="benchmarkForm.matrix_size" :min="256" :step="256" controls-position="right" />
          <span>批次</span>
          <el-input-number v-model="benchmarkForm.batch_count" :min="1" controls-position="right" />
          <span>观测秒数</span>
          <el-input-number v-model="benchmarkForm.observation_duration_sec" :min="0" :max="120" controls-position="right" />
          <span>最少样本</span>
          <el-input-number v-model="benchmarkForm.min_samples" :min="1" :max="30" controls-position="right" />
          <el-button type="primary" :loading="batchCreateLoading" @click="createBatch">创建压测工单</el-button>
        </div>
        <div class="pending-pill">
          当前待处理工单：<strong>{{ pendingWorkCount }}</strong> 个
        </div>
      </div>
    </el-card>

    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">3</span>
          <div>
            <div class="step-title">执行</div>
            <div class="step-desc">实时查看待路由、已路由、运行中和已评估数量；当前一键路由为验收 mock 路由，不替代外部路由系统。</div>
          </div>
          <div class="header-actions">
            <el-button size="small" type="primary" :loading="routeLoading" @click="doAutoRoute">一键路由</el-button>
            <el-button size="small" type="success" :loading="startLoading" @click="doStartAll">一键启动</el-button>
            <el-button size="small" plain @click="loadOrders">刷新</el-button>
          </div>
        </div>
      </template>
      <div class="status-grid">
        <div class="status-cell waiting">
          <div class="status-num">{{ executionStats.waitingRoute }}</div>
          <div class="status-label">待路由</div>
        </div>
        <div class="status-cell routed">
          <div class="status-num">{{ executionStats.routed }}</div>
          <div class="status-label">已路由</div>
        </div>
        <div class="status-cell running">
          <div class="status-num">{{ executionStats.running }}</div>
          <div class="status-label">运行中</div>
        </div>
        <div class="status-cell done">
          <div class="status-num">{{ executionStats.completed }}</div>
          <div class="status-label">已评估完成</div>
        </div>
        <div class="status-cell failed">
          <div class="status-num">{{ executionStats.failed }}</div>
          <div class="status-label">失败</div>
        </div>
      </div>
      <p class="status-note">说明：已评估完成表示业务指标已上报并完成判定；实例状态仍可能为运行中，直到任务结束时间到达或人工停止。</p>
    </el-card>

    <el-card class="step-card evidence-card">
      <template #header>
        <div class="step-header">
          <span class="step-num muted-step">证</span>
          <div>
            <div class="step-title">验收工单证据链</div>
            <div class="step-desc">查看每个压测工单的路由结果、实例、节点/GPU 分配和业务指标，证明任务真实运行。</div>
          </div>
          <el-button class="header-action" size="small" plain @click="loadOrders">刷新工单列表</el-button>
        </div>
      </template>
      <el-table :data="orders" size="small" empty-text="暂无压测工单">
        <el-table-column prop="name" label="工单" min-width="210" show-overflow-tooltip />
        <el-table-column label="任务状态" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ orderStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="路由状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.routing_status === 'completed' ? 'success' : 'warning'">
              {{ routingStatusLabel(row.routing_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="实例状态" width="110">
          <template #default="{ row }">{{ instanceStatusLabel(row.deployment_status || row.instance_status) }}</template>
        </el-table-column>
        <el-table-column label="实例" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">{{ row.materialized_instance_id || '未物化' }}</template>
        </el-table-column>
        <el-table-column label="路由放置" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ summarizePlacements(row.runtime_config?.routing_result?.placements) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :loading="detailLoading && selectedOrderId === row.id" @click="openOrderDetail(row)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="step-card result-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">4</span>
          <div>
            <div class="step-title">结果</div>
            <div class="step-desc">业务目标成功率需达到 90%。</div>
          </div>
          <el-button class="header-action" size="small" plain @click="loadSummary">刷新</el-button>
        </div>
      </template>
      <div v-if="!summaryAggregate" class="empty-hint">暂无统计数据，完成压测后查看。</div>
      <div v-else class="result-block">
        <div class="result-title">矩阵乘法计算任务</div>
        <div class="result-meta-grid">
          <div>
            <span>统计口径</span>
            <strong>仅验收压测工单</strong>
          </div>
          <div>
            <span>总工单数</span>
            <strong>{{ summaryAggregate.count }}</strong>
          </div>
          <div>
            <span>已评估数</span>
            <strong>{{ summaryAggregate.evaluated_count }} / {{ formalEvaluationCount }}</strong>
          </div>
          <div>
            <span>看板更新时间</span>
            <strong>{{ dashboardUpdatedAt || '—' }}</strong>
          </div>
        </div>
        <div class="rate-row">
          <el-progress
            class="rate-progress"
            :percentage="successPercent"
            :status="resultProgressStatus"
            :stroke-width="16"
          />
          <div class="rate-text" :class="{ pass: isPassing, fail: !isPassing }">
            {{ successPercent.toFixed(1) }}%
          </div>
        </div>
        <div class="result-detail">
          {{ summaryAggregate.success_count }} / {{ summaryAggregate.evaluated_count }} 任务达标
          <span class="target-text" :class="{ pass: isPassing, fail: !isPassing }">
            目标：≥ 90% 且 ≥ {{ formalEvaluationCount }} 个已评估任务，{{ resultVerdictText }}
          </span>
        </div>
        <div v-if="!hasEnoughEvaluations" class="sample-warning">
          当前已评估 {{ summaryAggregate.evaluated_count }} 个任务，仍不足正式验收所需 {{ formalEvaluationCount }} 个；请完成批量压测后再截图作为最终结果。
        </div>
      </div>
    </el-card>

    <el-drawer v-model="detailDrawerVisible" title="压测工单详情" size="56%">
      <div v-if="!selectedOrderDetail" class="empty-hint">请选择一个工单查看详情。</div>
      <div v-else class="detail-drawer-body">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="工单 ID">{{ selectedOrderDetail.id }}</el-descriptions-item>
          <el-descriptions-item label="实例 ID">{{ selectedOrderDetail.materialized_instance_id || '未物化' }}</el-descriptions-item>
          <el-descriptions-item label="任务状态">{{ selectedOrderDetail.status }}</el-descriptions-item>
          <el-descriptions-item label="部署状态">{{ selectedOrderDetail.deployment_status || selectedOrderDetail.instance?.status || '—' }}</el-descriptions-item>
          <el-descriptions-item label="业务类型">{{ taskTypeLabel(selectedOrderDetail.task_type) }}</el-descriptions-item>
          <el-descriptions-item label="路由策略">{{ selectedOrderDetail.routing_policy || '—' }}</el-descriptions-item>
        </el-descriptions>

        <section class="detail-section">
          <h3>实际节点 / GPU 分配</h3>
          <el-table :data="selectedOrderDetail.node_placements || []" size="small" empty-text="暂无节点分配信息">
            <el-table-column prop="role" label="子任务" width="100" />
            <el-table-column prop="hostname" label="物理节点" min-width="140" />
            <el-table-column prop="instance_node_name" label="实例节点" min-width="120" />
            <el-table-column label="GPU" width="90">
              <template #default="{ row }">{{ row.gpu_device || row.gpu_id || '无' }}</template>
            </el-table-column>
            <el-table-column prop="status" label="节点状态" width="110" />
          </el-table>
        </section>

        <section class="detail-section">
          <h3>业务目标评估</h3>
          <div v-if="selectedOrderDetail.evaluation" class="metric-grid">
            <div><span>实测指标</span><strong>{{ formatMetric(selectedOrderDetail.evaluation.actual_value, selectedOrderDetail.evaluation.unit) }}</strong></div>
            <div><span>达标阈值</span><strong>{{ formatMetric(selectedOrderDetail.evaluation.target_value, selectedOrderDetail.evaluation.unit) }}</strong></div>
            <div><span>是否达标</span><strong :class="selectedOrderDetail.evaluation.business_success ? 'success-text' : 'danger-text'">{{ selectedOrderDetail.evaluation.business_success ? '达标' : '未达标' }}</strong></div>
            <div><span>指标键</span><strong>{{ selectedOrderDetail.evaluation.metric_key }}</strong></div>
          </div>
          <div v-else class="empty-hint compact">尚未收到业务指标上报，任务完成后会生成评估结果。</div>
        </section>

        <section class="detail-section json-grid">
          <div>
            <h3>业务参数 JSON</h3>
            <pre>{{ prettyJson(selectedOrderDetail.business_task) }}</pre>
          </div>
          <div>
            <h3>路由结果 JSON</h3>
            <pre>{{ prettyJson(selectedOrderDetail.routing_result) }}</pre>
          </div>
          <div>
            <h3>指标采集结果 JSON</h3>
            <pre>{{ prettyJson(selectedOrderDetail.evaluation?.result_metadata) }}</pre>
          </div>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { baselinesApi, businessApi, ordersApi, nodesApi } from '@/api'

const taskType = ref('high_throughput_matmul')
const nodes = ref([])
const nodesLoading = ref(false)
const baselines = ref([])
const baselinesLoading = ref(false)
const orders = ref([])
const summary = ref([])
const testingNodes = ref(new Map())
const batchBaselineLoading = ref(false)
const batchCreateLoading = ref(false)
const routeLoading = ref(false)
const startLoading = ref(false)
const fullFlowLoading = ref(false)
const dashboardUpdatedAt = ref('')
const detailDrawerVisible = ref(false)
const detailLoading = ref(false)
const selectedOrderId = ref('')
const selectedOrderDetail = ref(null)
const formalEvaluationCount = 30
const benchmarkForm = reactive({
  count: formalEvaluationCount,
  matrix_size: 1024,
  batch_count: 50,
  observation_duration_sec: 10,
  sample_interval_sec: 1,
  sample_batch_count: 5,
  warmup_batches: 3,
  min_samples: 5,
  max_samples: 12,
})

const nodeBaselineRows = computed(() =>
  nodes.value.filter(n => n.is_schedulable).map(n => {
    const bl = baselines.value.find(b => b.node_id === n.id)
    return {
      node_id: n.id,
      hostname: n.hostname,
      baseline_value: bl?.baseline_value ?? null,
      unit: bl?.unit || 'GFLOPS',
      stable: bl?.stable ?? null,
      updated_at: bl?.updated_at ?? bl?.created_at ?? null,
    }
  })
)

const missingBaselineCount = computed(() =>
  nodeBaselineRows.value.filter(row => row.baseline_value == null || row.stable === false).length
)

const orderStats = computed(() => {
  const stats = { waitingRoute: 0, routed: 0, running: 0, completed: 0, failed: 0 }
  orders.value.forEach(order => {
    const deploymentStatus = order.deployment_status || order.instance_status || ''
    if (order.status === 'failed' || deploymentStatus === 'failed') {
      stats.failed += 1
    } else if (deploymentStatus === 'running' || order.status === 'running') {
      stats.running += 1
    } else if (deploymentStatus === 'stopped' || order.status === 'completed' || order.status === 'stopped') {
      stats.completed += 1
    } else if (order.materialized_instance_id || order.status === 'materialized' || order.routing_status === 'completed') {
      stats.routed += 1
    } else {
      stats.waitingRoute += 1
    }
  })
  return stats
})

const summaryRowsForTask = computed(() =>
  summary.value.filter(row => row.task_type === taskType.value)
)

const summaryAggregate = computed(() => {
  if (!summaryRowsForTask.value.length) return null
  const aggregate = summaryRowsForTask.value.reduce((acc, row) => {
    acc.count += row.count || 0
    acc.evaluated_count += row.evaluated_count || 0
    acc.success_count += row.success_count || 0
    return acc
  }, { count: 0, evaluated_count: 0, success_count: 0 })
  aggregate.business_success_rate = aggregate.evaluated_count
    ? aggregate.success_count / aggregate.evaluated_count
    : null
  return aggregate
})

const executionStats = computed(() => {
  const stats = { ...orderStats.value }
  const aggregate = summaryAggregate.value
  if (!aggregate || !aggregate.count) return stats

  const evaluated = aggregate.evaluated_count || 0
  const total = aggregate.count || 0
  stats.completed = evaluated
  stats.running = Math.max(0, total - evaluated - stats.failed)
  if (evaluated > 0) {
    stats.waitingRoute = 0
    stats.routed = 0
  }
  return stats
})

const pendingWorkCount = computed(() => {
  const aggregate = summaryAggregate.value
  if (aggregate?.count) {
    return Math.max(0, (aggregate.count || 0) - (aggregate.evaluated_count || 0))
  }
  return orderStats.value.waitingRoute + orderStats.value.routed
})

const successPercent = computed(() =>
  summaryAggregate.value?.business_success_rate != null
    ? summaryAggregate.value.business_success_rate * 100
    : 0
)

const hasEnoughEvaluations = computed(() =>
  (summaryAggregate.value?.evaluated_count || 0) >= formalEvaluationCount
)

const isPassing = computed(() =>
  summaryAggregate.value?.business_success_rate != null &&
  summaryAggregate.value.business_success_rate >= 0.9 &&
  hasEnoughEvaluations.value
)

const resultProgressStatus = computed(() =>
  hasEnoughEvaluations.value ? (isPassing.value ? 'success' : 'exception') : 'warning'
)

const resultVerdictText = computed(() =>
  hasEnoughEvaluations.value ? (isPassing.value ? '验收通过' : '未达标') : '样本不足'
)

function formatTime(value) {
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function taskTypeLabel(value) {
  if (value === 'high_throughput_matmul') return '矩阵乘法计算任务'
  if (value === 'low_latency_video_pipeline') return '视频AI推理任务'
  if (value === 'text_model_training') return '文本模型训练任务'
  return value || '—'
}

function formatMetric(value, unit = '') {
  if (value == null) return '—'
  const numeric = Number(value)
  const text = Number.isFinite(numeric) ? numeric.toFixed(2) : String(value)
  return `${text} ${unit || ''}`.trim()
}

function orderStatusLabel(value) {
  const labels = {
    pending: '待提交',
    routing: '路由中',
    routed: '已路由',
    materialized: '已物化',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[value] || value || '—'
}

function routingStatusLabel(value) {
  const labels = {
    not_required: '无需路由',
    pending: '待路由',
    computing: '计算中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[value] || value || '—'
}

function instanceStatusLabel(value) {
  const labels = {
    pending: '待启动',
    scheduled: '已调度',
    starting: '启动中',
    running: '运行中',
    stopping: '停止中',
    stopped: '已停止',
    failed: '失败',
    expired: '已过期',
  }
  return labels[value] || value || '—'
}

function summarizePlacements(placements) {
  if (!placements) return '待路由'
  if (Array.isArray(placements)) {
    return placements.map(p => {
      const gpu = p.gpu_device != null ? ` GPU ${p.gpu_device}` : ''
      return `${p.node_id || p.role}:${p.worker_host || p.node_name || p.node_id}${gpu}`
    }).join(' / ')
  }
  if (typeof placements === 'object') {
    return Object.entries(placements).map(([role, placement]) => {
      if (typeof placement === 'string') return `${role}:${placement}`
      const node = placement?.node_name || placement?.worker_host || placement?.node_id || '—'
      const gpu = Array.isArray(placement?.gpu_indices) && placement.gpu_indices.length
        ? ` GPU ${placement.gpu_indices.join(',')}`
        : ''
      return `${role}:${node}${gpu}`
    }).join(' / ')
  }
  return String(placements)
}

function prettyJson(value) {
  if (!value) return '暂无数据'
  return JSON.stringify(value, null, 2)
}

function baselineRowClass({ row }) {
  if (row.baseline_value == null) return 'baseline-missing-row'
  if (row.stable === false) return 'baseline-unstable-row'
  return ''
}

async function loadNodes() {
  nodesLoading.value = true
  try {
    const { data } = await nodesApi.list()
    nodes.value = data
  } finally {
    nodesLoading.value = false
  }
}

async function loadBaselines() {
  baselinesLoading.value = true
  try {
    const { data } = await baselinesApi.list({ task_type: taskType.value })
    baselines.value = data
  } finally {
    baselinesLoading.value = false
  }
}

async function loadOrders() {
  const { data } = await ordersApi.list({ is_benchmark: true, limit: 100 })
  orders.value = Array.isArray(data) ? data : (data.items || [])
}

async function loadSummary() {
  const { data } = await businessApi.summary({ is_benchmark: true })
  summary.value = data
  dashboardUpdatedAt.value = formatTime(new Date())
}

async function loadAll() {
  await Promise.all([loadNodes(), loadBaselines(), loadOrders(), loadSummary()])
}

async function runSingleBaseline(row) {
  testingNodes.value = new Map(testingNodes.value.set(row.node_id, true))
  try {
    const { data } = await baselinesApi.run({ node_id: row.node_id, task_type: taskType.value, runs: 3 })
    ElMessage.success(`基线测试完成：${data.baseline_value?.toFixed(2)} ${data.unit || ''}`)
    await loadBaselines()
  } finally {
    testingNodes.value = new Map(testingNodes.value.set(row.node_id, false))
  }
}

async function runBatchBaseline() {
  batchBaselineLoading.value = true
  try {
    const { data } = await baselinesApi.batchRun({ task_type: taskType.value, runs: 3 })
    ElMessage.success(`批量基线测试完成：${data.succeeded} 个节点成功${data.failed ? `，${data.failed} 个失败` : ''}`)
    await loadBaselines()
  } finally {
    batchBaselineLoading.value = false
  }
}

async function createBatch() {
  batchCreateLoading.value = true
  try {
    const { data } = await ordersApi.batchBenchmark({
      task_type: taskType.value,
      count: benchmarkForm.count,
      data_profile: {
        matrix_size: benchmarkForm.matrix_size,
        batch_count: benchmarkForm.batch_count,
        seed: 42,
        warmup_batches: benchmarkForm.warmup_batches,
        observation_duration_sec: benchmarkForm.observation_duration_sec,
        sample_interval_sec: benchmarkForm.sample_interval_sec,
        sample_batch_count: benchmarkForm.sample_batch_count,
        min_samples: benchmarkForm.min_samples,
        max_samples: benchmarkForm.max_samples,
      },
    })
    ElMessage.success(`已创建 ${data.created} 条压测工单`)
    await Promise.all([loadOrders(), loadSummary()])
    return data
  } finally {
    batchCreateLoading.value = false
  }
}

async function openOrderDetail(row) {
  selectedOrderId.value = row.id
  detailLoading.value = true
  try {
    const { data } = await ordersApi.get(row.id)
    selectedOrderDetail.value = data
    detailDrawerVisible.value = true
  } finally {
    detailLoading.value = false
  }
}

async function doAutoRoute() {
  routeLoading.value = true
  try {
    const { data } = await ordersApi.batchAutoRoute()
    ElMessage.success(`已路由 ${data.routed} 条工单${data.failed?.length ? `，${data.failed.length} 条失败` : ''}`)
    await loadOrders()
    return data
  } finally {
    routeLoading.value = false
  }
}

async function doStartAll() {
  startLoading.value = true
  try {
    const { data } = await ordersApi.startAllRouted()
    ElMessage.success(`已启动 ${data.started ?? data.routed ?? '全部'} 个实例`)
    await Promise.all([loadOrders(), loadSummary()])
    return data
  } finally {
    startLoading.value = false
  }
}

async function startFullFlow() {
  await loadAll()
  if (missingBaselineCount.value > 0) {
    ElMessage.warning(`还有 ${missingBaselineCount.value} 个节点缺少稳定基线，请先完成 Step 1。`)
    return
  }
  fullFlowLoading.value = true
  try {
    await createBatch()
    await doAutoRoute()
    await doStartAll()
    ElMessage.success('完整测试流程已启动，请等待任务完成后查看 Step 4。')
  } finally {
    fullFlowLoading.value = false
  }
}

watch(taskType, () => Promise.all([loadBaselines(), loadSummary()]))
onMounted(loadAll)
</script>

<style scoped>
.benchmark-page {
  padding: 28px;
  max-width: 1120px;
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: center;
  padding: 26px 28px;
  margin-bottom: 22px;
  border: 1px solid #dcdfe6;
  border-radius: 14px;
  background: linear-gradient(135deg, #f7fbff 0%, #ffffff 48%, #f8faf4 100%);
  box-shadow: 0 12px 30px rgba(40, 62, 90, 0.06);
}

.eyebrow {
  margin: 0 0 6px;
  color: #409eff;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.hero-card h1 {
  margin: 0;
  font-size: 26px;
  line-height: 1.2;
}

.hero-subtitle {
  margin: 8px 0 0;
  color: #606266;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.field-label {
  color: #606266;
  font-size: 14px;
}

.task-select {
  width: 220px;
}

.step-card {
  margin-bottom: 18px;
  border-radius: 12px;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.muted-step {
  background: #606266;
  font-size: 13px;
}

.step-title {
  font-size: 16px;
  font-weight: 700;
}

.step-desc {
  margin-top: 2px;
  color: #909399;
  font-size: 12px;
}

.header-action,
.header-actions {
  margin-left: auto;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.baseline-value {
  font-weight: 700;
  color: #303133;
}

:deep(.baseline-missing-row) {
  background: #fff4f2;
}

:deep(.baseline-unstable-row) {
  background: #fff9ec;
}

.muted {
  color: #c0c4cc;
}

.pressure-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}

.pressure-form {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: #606266;
}

.pressure-form :deep(.el-input-number) {
  width: 118px;
}

.pending-pill {
  padding: 9px 14px;
  border-radius: 999px;
  background: #f5f7fa;
  color: #606266;
  font-size: 14px;
}

.pending-pill strong {
  color: #303133;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 14px;
}

.status-note {
  margin: 12px 0 0;
  color: #606266;
  font-size: 12px;
}

.status-cell {
  padding: 18px 16px;
  border-radius: 12px;
  text-align: center;
  background: #f5f7fa;
}

.status-cell.waiting {
  background: #fff7e6;
}

.status-cell.routed {
  background: #ecf5ff;
}

.status-cell.running {
  background: #f0f9eb;
}

.status-cell.done {
  background: #eef8f4;
}

.status-cell.failed {
  background: #fef0f0;
}

.status-num {
  font-size: 32px;
  font-weight: 800;
  line-height: 1;
}

.status-label {
  margin-top: 8px;
  color: #606266;
  font-size: 13px;
}

.result-card :deep(.el-card__body) {
  padding: 30px 34px;
}

.result-block {
  max-width: 720px;
  margin: 0 auto;
}

.result-title {
  margin-bottom: 18px;
  font-size: 18px;
  font-weight: 800;
  text-align: center;
}

.result-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.result-meta-grid div {
  padding: 12px;
  border-radius: 10px;
  background: #f5f7fa;
  text-align: center;
}

.result-meta-grid span {
  display: block;
  color: #909399;
  font-size: 12px;
}

.result-meta-grid strong {
  display: block;
  margin-top: 5px;
  color: #303133;
  font-size: 14px;
}

.rate-row {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 18px;
}

.rate-progress {
  width: 100%;
}

.rate-text {
  min-width: 96px;
  font-size: 34px;
  font-weight: 900;
  text-align: right;
}

.rate-text.pass,
.target-text.pass {
  color: #67c23a;
}

.rate-text.fail,
.target-text.fail {
  color: #f56c6c;
}

.result-detail {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-top: 14px;
  color: #606266;
  font-size: 14px;
}

.target-text {
  font-weight: 700;
}

.sample-warning {
  margin-top: 10px;
  color: #b88230;
  font-size: 13px;
}

.empty-hint {
  text-align: center;
  color: #909399;
  padding: 28px 0;
}

.empty-hint.compact {
  padding: 10px 0;
  text-align: left;
}

.detail-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-section h3 {
  margin: 0 0 10px;
  color: #303133;
  font-size: 15px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-grid div {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fafcff;
}

.metric-grid span {
  display: block;
  color: #909399;
  font-size: 12px;
}

.metric-grid strong {
  display: block;
  margin-top: 6px;
  color: #303133;
}

.success-text {
  color: #67c23a !important;
}

.danger-text {
  color: #f56c6c !important;
}

.json-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.json-grid div:last-child {
  grid-column: 1 / -1;
}

.json-grid pre {
  max-height: 280px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-radius: 10px;
  background: #1f2933;
  color: #e5edf5;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .benchmark-page {
    padding: 18px;
  }

  .hero-card {
    align-items: flex-start;
    flex-direction: column;
  }

  .hero-actions {
    justify-content: flex-start;
  }

  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .rate-row {
    grid-template-columns: 1fr;
  }

  .rate-text {
    text-align: left;
  }

  .result-detail {
    flex-direction: column;
  }

  .result-meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-grid,
  .json-grid {
    grid-template-columns: 1fr;
  }

  .json-grid div:last-child {
    grid-column: auto;
  }
}
</style>
