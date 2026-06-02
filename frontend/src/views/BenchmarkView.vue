<template>
  <div class="benchmark-page">
    <div class="page-header">
      <div>
        <h1>验收测试</h1>
        <p>管理基线、批量压测、路由启动，统计业务成功率。</p>
      </div>
      <div style="display:flex;gap:12px;align-items:center">
        <span>任务类型：</span>
        <el-select v-model="taskType" style="width:200px">
          <el-option label="矩阵乘法计算任务" value="high_throughput_matmul" />
        </el-select>
      </div>
    </div>

    <!-- Step 1: 基线管理 -->
    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">1</span>
          <span class="step-title">基线管理</span>
          <el-button size="small" type="warning" plain :loading="batchBaselineLoading" @click="runBatchBaseline" style="margin-left:auto">
            批量测试所有节点
          </el-button>
        </div>
      </template>
      <el-table :data="nodeBaselineRows" size="small" v-loading="nodesLoading || baselinesLoading">
        <el-table-column prop="hostname" label="节点" width="140" />
        <el-table-column label="基线值" width="160">
          <template #default="{ row }">
            <span v-if="row.baseline_value != null">{{ row.baseline_value.toFixed(2) }} {{ row.unit }}</span>
            <el-tag v-else type="danger" size="small">未测试</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="稳定性" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.stable === true" type="success" size="small">稳定</el-tag>
            <el-tag v-else-if="row.stable === false" type="warning" size="small">波动大</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="140">
          <template #default="{ row }">{{ row.updated_at ? formatTime(row.updated_at) : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text type="primary" :loading="testingNodes.get(row.node_id)" @click="runSingleBaseline(row)">
              {{ row.baseline_value != null ? '重测' : '测试' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Step 2: 批量压测 -->
    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">2</span>
          <span class="step-title">批量压测</span>
        </div>
      </template>
      <div class="inline-form">
        <el-form inline size="small">
          <el-form-item label="任务数量">
            <el-input-number v-model="benchmarkForm.count" :min="1" :max="30" style="width:90px" />
          </el-form-item>
          <el-form-item label="矩阵大小">
            <el-input-number v-model="benchmarkForm.matrix_size" :min="256" :step="256" style="width:110px" />
          </el-form-item>
          <el-form-item label="批次数">
            <el-input-number v-model="benchmarkForm.batch_count" :min="1" style="width:90px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="batchCreateLoading" @click="createBatch">创建压测工单</el-button>
          </el-form-item>
        </el-form>
        <div v-if="pendingCount > 0" class="status-hint">
          当前待处理工单：<strong>{{ pendingCount }}</strong> 个
        </div>
      </div>
    </el-card>

    <!-- Step 3: 路由与启动 -->
    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">3</span>
          <span class="step-title">路由与启动</span>
          <div style="margin-left:auto;display:flex;gap:8px">
            <el-button size="small" type="primary" :loading="routeLoading" @click="doAutoRoute">一键路由</el-button>
            <el-button size="small" type="success" :loading="startLoading" @click="doStartAll">一键启动</el-button>
            <el-button size="small" plain @click="loadOrders">刷新</el-button>
          </div>
        </div>
      </template>
      <div class="status-grid">
        <div class="status-cell">
          <div class="status-num">{{ orderStats.pending }}</div>
          <div class="status-label">待路由</div>
        </div>
        <div class="status-cell">
          <div class="status-num">{{ orderStats.materialized }}</div>
          <div class="status-label">待启动</div>
        </div>
        <div class="status-cell">
          <div class="status-num">{{ orderStats.running }}</div>
          <div class="status-label">运行中</div>
        </div>
        <div class="status-cell">
          <div class="status-num">{{ orderStats.completed }}</div>
          <div class="status-label">已完成</div>
        </div>
        <div class="status-cell">
          <div class="status-num" style="color:#f56c6c">{{ orderStats.failed }}</div>
          <div class="status-label">失败</div>
        </div>
      </div>
    </el-card>

    <!-- Step 4: 成功率统计 -->
    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">4</span>
          <span class="step-title">成功率统计</span>
          <el-button size="small" plain @click="loadSummary" style="margin-left:auto">刷新</el-button>
        </div>
      </template>
      <div v-if="!summaryRow" class="empty-hint">暂无统计数据，完成压测后查看。</div>
      <div v-else class="result-block">
        <div class="result-rate" :style="{color: summaryRow.business_success_rate >= 0.9 ? '#67c23a' : '#f56c6c'}">
          {{ summaryRow.business_success_rate != null ? (summaryRow.business_success_rate * 100).toFixed(1) + '%' : '—' }}
        </div>
        <div class="result-detail">
          {{ summaryRow.success_count }} / {{ summaryRow.evaluated_count }} 个任务达标
          <el-tag :type="summaryRow.business_success_rate >= 0.9 ? 'success' : 'danger'" size="small" style="margin-left:8px">
            {{ summaryRow.business_success_rate >= 0.9 ? '验收通过 ✓' : '未达标' }}
          </el-tag>
        </div>
        <el-progress
          :percentage="summaryRow.business_success_rate != null ? Math.round(summaryRow.business_success_rate * 100) : 0"
          :status="summaryRow.business_success_rate >= 0.9 ? 'success' : 'exception'"
          :stroke-width="12"
          style="margin-top:12px"
        />
        <div class="target-hint">验收标准：成功率 ≥ 90%</div>
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
const benchmarkForm = reactive({ count: 10, matrix_size: 1024, batch_count: 50 })

const nodeBaselineRows = computed(() =>
  nodes.value.filter(n => n.is_schedulable).map(n => {
    const bl = baselines.value.find(b => b.node_id === n.id)
    return {
      node_id: n.id,
      hostname: n.hostname,
      baseline_value: bl?.baseline_value ?? null,
      unit: bl?.unit || 'GFLOPS',
      stable: bl?.stable ?? null,
      updated_at: bl?.updated_at ?? null,
    }
  })
)

const orderStats = computed(() => {
  const s = { pending: 0, materialized: 0, running: 0, completed: 0, failed: 0 }
  orders.value.forEach(o => { if (s[o.status] !== undefined) s[o.status]++ })
  return s
})

const pendingCount = computed(() => orderStats.value.pending + orderStats.value.materialized)

const summaryRow = computed(() => summary.value.find(s => s.task_type === taskType.value))

function formatTime(v) {
  return new Date(v).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
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
  const { data } = await businessApi.summary()
  summary.value = data
}

async function loadAll() {
  await Promise.all([loadNodes(), loadBaselines(), loadOrders(), loadSummary()])
}

async function runSingleBaseline(row) {
  testingNodes.value = new Map(testingNodes.value.set(row.node_id, true))
  try {
    const { data } = await baselinesApi.run({ node_id: row.node_id, task_type: taskType.value, runs: 3 })
    ElMessage.success(`基线测试完成: ${data.baseline_value?.toFixed(2)} ${data.unit || ''}`)
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
      data_profile: { matrix_size: benchmarkForm.matrix_size, batch_count: benchmarkForm.batch_count },
    })
    ElMessage.success(`已创建 ${data.created} 条压测工单`)
    await loadOrders()
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
  } finally {
    routeLoading.value = false
  }
}

async function doStartAll() {
  startLoading.value = true
  try {
    const { data } = await ordersApi.startAllRouted()
    ElMessage.success(`已启动 ${data.started ?? data.routed ?? '全部'} 个实例`)
    await loadOrders()
  } finally {
    startLoading.value = false
  }
}

watch(taskType, () => Promise.all([loadBaselines(), loadSummary()]))
onMounted(loadAll)
</script>

<style scoped>
.benchmark-page { padding: 24px; max-width: 900px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.page-header h1 { margin: 0 0 4px; font-size: 22px; }
.step-card { margin-bottom: 20px; }
.step-header { display: flex; align-items: center; gap: 10px; }
.step-num { width: 24px; height: 24px; border-radius: 50%; background: var(--el-color-primary); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 600; flex-shrink: 0; }
.step-title { font-size: 15px; font-weight: 600; }
.inline-form { display: flex; flex-direction: column; gap: 8px; }
.status-hint { font-size: 13px; color: #606266; }
.status-grid { display: flex; gap: 24px; padding: 8px 0; }
.status-cell { text-align: center; min-width: 60px; }
.status-num { font-size: 28px; font-weight: 700; line-height: 1; }
.status-label { font-size: 12px; color: #909399; margin-top: 4px; }
.result-block { text-align: center; padding: 16px 0; }
.result-rate { font-size: 52px; font-weight: 700; line-height: 1; }
.result-detail { font-size: 14px; color: #606266; margin-top: 8px; }
.target-hint { font-size: 12px; color: #909399; margin-top: 8px; }
.empty-hint { text-align: center; color: #909399; padding: 24px 0; }
</style>
