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
            <div class="step-desc">实时查看待路由、已路由、运行中和已完成数量；当前一键路由为验收 mock 路由，不替代外部路由系统。</div>
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
          <div class="status-num">{{ orderStats.waitingRoute }}</div>
          <div class="status-label">待路由</div>
        </div>
        <div class="status-cell routed">
          <div class="status-num">{{ orderStats.routed }}</div>
          <div class="status-label">已路由</div>
        </div>
        <div class="status-cell running">
          <div class="status-num">{{ orderStats.running }}</div>
          <div class="status-label">运行中</div>
        </div>
        <div class="status-cell done">
          <div class="status-num">{{ orderStats.completed }}</div>
          <div class="status-label">已完成</div>
        </div>
        <div class="status-cell failed">
          <div class="status-num">{{ orderStats.failed }}</div>
          <div class="status-label">失败</div>
        </div>
      </div>
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
const formalEvaluationCount = 30
const benchmarkForm = reactive({ count: formalEvaluationCount, matrix_size: 1024, batch_count: 50 })

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

const pendingWorkCount = computed(() => orderStats.value.waitingRoute + orderStats.value.routed)

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
      },
    })
    ElMessage.success(`已创建 ${data.created} 条压测工单`)
    await Promise.all([loadOrders(), loadSummary()])
    return data
  } finally {
    batchCreateLoading.value = false
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
}
</style>
