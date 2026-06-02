<template>
  <div class="benchmark-view">
    <header class="page-header">
      <div>
        <h1>验收测试</h1>
        <p class="subtitle">管理基线、批量压测、路由与启动，统计业务成功率。</p>
      </div>
      <div class="actions">
        <el-button @click="refreshAll">刷新</el-button>
      </div>
    </header>

    <!-- Section 1: 基线管理 -->
    <section class="card">
      <h2 class="section-header">基线管理</h2>
      <div style="margin-bottom: 8px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap">
        <el-select v-model="baselineFilter.node_id" placeholder="筛选节点" clearable style="width: 180px" @change="loadBaselines">
          <el-option v-for="n in nodes" :key="n.id" :label="n.hostname || n.display_name" :value="n.id" />
        </el-select>
        <el-button size="small" type="primary" plain @click="showBaselineDialog = true">新增基线</el-button>
        <el-button size="small" type="success" plain @click="showRunBaselineDialog = true">运行基线测试</el-button>
        <el-button size="small" type="warning" plain :loading="batchBaselineLoading" @click="runBatchBaseline">批量测试基线</el-button>
      </div>
      <el-table :data="baselines" size="small" v-loading="baselinesLoading" empty-text="暂无基线数据">
        <el-table-column prop="node_hostname" label="节点" width="140" />
        <el-table-column label="任务类型" width="200">
          <template #default="{ row }">{{ taskTypeLabel(row.task_type) || row.task_type }}</template>
        </el-table-column>
        <el-table-column prop="metric_key" label="指标" width="160" />
        <el-table-column label="基线值" width="120">
          <template #default="{ row }">{{ row.baseline_value?.toFixed(2) }} {{ row.unit || '' }}</template>
        </el-table-column>
        <el-table-column prop="operator" label="方向" width="80">
          <template #default="{ row }">{{ row.operator === '>=' ? '越高越好' : '越低越好' }}</template>
        </el-table-column>
        <el-table-column prop="run_count" label="测试次数" width="80" />
        <el-table-column label="稳定性" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.stable === true" type="success" size="small">稳定</el-tag>
            <el-tag v-else-if="row.stable === false" type="warning" size="small">波动大</el-tag>
            <span v-else>—</span>
            <span v-if="row.std_dev != null" style="margin-left:4px;font-size:11px;color:#999">σ={{ row.std_dev.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" type="primary" text @click="openEditBaseline(row)">编辑</el-button>
            <el-button size="small" type="danger" text @click="deleteBaseline(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- Section 2: 批量压测 -->
    <section class="card">
      <h2 class="section-header">批量压测</h2>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-button type="warning" plain @click="showBatchBenchmarkDialog = true">批量压测</el-button>
        <span v-if="pendingBenchmarkCount > 0" class="counter-badge">
          待路由压测工单：{{ pendingBenchmarkCount }} 条
        </span>
      </div>
    </section>

    <!-- Section 3: 路由与启动 -->
    <section class="card">
      <h2 class="section-header">路由与启动</h2>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-button type="primary" plain :loading="autoRouteLoading" @click="batchAutoRoute">一键路由</el-button>
        <el-button type="success" plain :loading="startAllLoading" @click="startAllRouted">一键启动</el-button>
      </div>
    </section>

    <!-- Section 4: 成功率统计 -->
    <section class="card" v-if="totalEvaluated > 0">
      <h2 class="section-header">成功率统计</h2>
      <div class="success-rate-cards">
        <div v-for="item in successRateByType" :key="item.task_type" class="success-rate-card">
          <div class="rate-number" :class="{ pass: item.rate >= 90, fail: item.rate < 90 }">
            {{ item.rate.toFixed(1) }}%
          </div>
          <div class="rate-label">{{ taskTypeLabel(item.task_type) }}</div>
          <div class="rate-detail">{{ item.success }}/{{ item.evaluated }} 达标</div>
        </div>
      </div>
    </section>

    <!-- 运行基线测试对话框 -->
    <el-dialog v-model="showRunBaselineDialog" title="运行基线测试" width="440px" destroy-on-close>
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        在后端本地运行基准测试（矩阵乘法），计算 effective_gflops 中位数作为基线值。
      </el-alert>
      <el-form :model="runBaselineForm" label-width="90px" size="small">
        <el-form-item label="节点">
          <el-select v-model="runBaselineForm.node_id" placeholder="选择节点" style="width:100%">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="runBaselineForm.task_type" style="width:100%">
            <el-option label="矩阵乘法计算任务" value="high_throughput_matmul" />
          </el-select>
        </el-form-item>
        <el-form-item label="运行次数">
          <el-input-number v-model="runBaselineForm.runs" :min="1" :max="10" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRunBaselineDialog = false">取消</el-button>
        <el-button type="primary" :loading="runBaselineLoading" @click="runBaseline">开始测试</el-button>
      </template>
    </el-dialog>

    <!-- 编辑基线对话框 -->
    <el-dialog v-model="showEditBaselineDialog" title="编辑基线" width="440px" destroy-on-close>
      <el-form :model="editBaselineForm" label-width="90px" size="small">
        <el-form-item label="基线值">
          <el-input-number v-model="editBaselineForm.baseline_value" :precision="2" :min="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="方向">
          <el-select v-model="editBaselineForm.operator" style="width:100%">
            <el-option label=">= (越大越好)" value=">=" />
            <el-option label="<= (越小越好)" value="<=" />
          </el-select>
        </el-form-item>
        <el-form-item label="单位">
          <el-input v-model="editBaselineForm.unit" placeholder="如 GFLOPS" />
        </el-form-item>
        <el-form-item label="测试次数">
          <el-input-number v-model="editBaselineForm.run_count" :min="1" :max="100" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditBaselineDialog = false">取消</el-button>
        <el-button type="primary" @click="saveEditBaseline">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量压测对话框 -->
    <el-dialog v-model="showBatchBenchmarkDialog" title="批量压测" width="440px" destroy-on-close>
      <el-form :model="batchBenchmarkForm" label-width="90px" size="small">
        <el-form-item label="任务数量">
          <el-input-number v-model="batchBenchmarkForm.count" :min="1" :max="30" style="width:100%" />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="batchBenchmarkForm.task_type" style="width:100%">
            <el-option label="矩阵乘法计算任务" value="high_throughput_matmul" />
          </el-select>
        </el-form-item>
        <el-form-item label="矩阵大小">
          <el-input-number v-model="batchBenchmarkForm.matrix_size" :min="64" :max="8192" style="width:100%" />
        </el-form-item>
        <el-form-item label="批次数">
          <el-input-number v-model="batchBenchmarkForm.batch_count" :min="1" :max="500" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBatchBenchmarkDialog = false">取消</el-button>
        <el-button type="primary" :loading="batchBenchmarkLoading" @click="submitBatchBenchmark">确认</el-button>
      </template>
    </el-dialog>

    <!-- 新增基线对话框 -->
    <el-dialog v-model="showBaselineDialog" title="新增节点基线" width="440px" destroy-on-close>
      <el-form :model="newBaseline" label-width="90px" size="small">
        <el-form-item label="节点">
          <el-select v-model="newBaseline.node_id" placeholder="选择节点" style="width:100%">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="newBaseline.task_type" placeholder="选择任务类型" style="width:100%">
            <el-option label="矩阵乘法计算任务" value="high_throughput_matmul" />
            <el-option label="低时延视频链路" value="low_latency_video_pipeline" />
            <el-option label="模型训练" value="llm_text_generation" />
          </el-select>
        </el-form-item>
        <el-form-item label="指标">
          <el-input v-model="newBaseline.metric_key" placeholder="如 effective_gflops" />
        </el-form-item>
        <el-form-item label="基线值">
          <el-input-number v-model="newBaseline.baseline_value" :precision="2" :min="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="方向">
          <el-select v-model="newBaseline.operator" style="width:100%">
            <el-option label=">= (越大越好)" value=">=" />
            <el-option label="<= (越小越好)" value="<=" />
          </el-select>
        </el-form-item>
        <el-form-item label="单位">
          <el-input v-model="newBaseline.unit" placeholder="如 GFLOPS" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBaselineDialog = false">取消</el-button>
        <el-button type="primary" @click="createBaseline">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { baselinesApi, businessApi, instancesApi, nodesApi, ordersApi } from '@/api'
import { taskTypeLabel } from '@/constants/businessTaskDisplay'

const nodes = ref([])
const baselines = ref([])
const baselinesLoading = ref(false)
const baselineFilter = reactive({ node_id: '' })
const showBaselineDialog = ref(false)
const showRunBaselineDialog = ref(false)
const runBaselineLoading = ref(false)
const batchBaselineLoading = ref(false)
const runBaselineForm = reactive({ node_id: '', task_type: 'high_throughput_matmul', runs: 3 })
const showEditBaselineDialog = ref(false)
const editBaselineId = ref('')
const editBaselineForm = reactive({ baseline_value: 0, operator: '>=', unit: '', run_count: 3 })
const showBatchBenchmarkDialog = ref(false)
const batchBenchmarkLoading = ref(false)
const batchBenchmarkForm = reactive({ task_type: 'high_throughput_matmul', count: 10, matrix_size: 1024, batch_count: 50 })
const autoRouteLoading = ref(false)
const startAllLoading = ref(false)
const summary = ref([])
const pendingBenchmarkCount = ref(0)
const newBaseline = reactive({
  node_id: '', task_type: 'high_throughput_matmul', metric_key: 'effective_gflops',
  baseline_value: 0, operator: '>=', unit: 'GFLOPS',
})

const totalEvaluated = computed(() => summary.value.reduce((s, r) => s + (r.evaluated_count || 0), 0))
const successRateByType = computed(() => {
  const map = {}
  summary.value.forEach(row => {
    const t = row.task_type || 'unknown'
    if (!map[t]) map[t] = { task_type: t, evaluated: 0, success: 0 }
    map[t].evaluated += row.evaluated_count || 0
    map[t].success += row.success_count || 0
  })
  return Object.values(map).filter(x => x.evaluated > 0).map(x => ({ ...x, rate: (x.success / x.evaluated) * 100 }))
})

function canStart(status) {
  return ['pending', 'stopped', 'failed'].includes(status)
}

async function refreshAll() {
  await Promise.all([loadNodes(), loadBaselines(), loadSummary(), loadPendingBenchmarkCount()])
}

async function loadNodes() {
  const { data } = await nodesApi.list()
  nodes.value = data
}

async function loadBaselines() {
  baselinesLoading.value = true
  try {
    const params = {}
    if (baselineFilter.node_id) params.node_id = baselineFilter.node_id
    const { data } = await baselinesApi.list(params)
    baselines.value = data
  } finally {
    baselinesLoading.value = false
  }
}

async function loadSummary() {
  const { data } = await businessApi.summary()
  summary.value = data
}

async function loadPendingBenchmarkCount() {
  try {
    const { data } = await ordersApi.list({ is_benchmark: true, order_status: 'pending', page_size: 1 })
    pendingBenchmarkCount.value = data.total || 0
  } catch {
    pendingBenchmarkCount.value = 0
  }
}

function openEditBaseline(row) {
  editBaselineId.value = row.id
  editBaselineForm.baseline_value = row.baseline_value
  editBaselineForm.operator = row.operator
  editBaselineForm.unit = row.unit || ''
  editBaselineForm.run_count = row.run_count
  showEditBaselineDialog.value = true
}

async function saveEditBaseline() {
  await baselinesApi.update(editBaselineId.value, { ...editBaselineForm })
  ElMessage.success('基线已更新')
  showEditBaselineDialog.value = false
  await loadBaselines()
}

async function deleteBaseline(row) {
  await ElMessageBox.confirm(`确认删除 ${row.node_hostname} / ${taskTypeLabel(row.task_type)} 的基线？`, '删除确认')
  await baselinesApi.delete(row.id)
  ElMessage.success('已删除')
  await loadBaselines()
}

async function createBaseline() {
  if (!newBaseline.node_id || !newBaseline.task_type || !newBaseline.metric_key) {
    ElMessage.warning('请填写完整信息')
    return
  }
  try {
    await baselinesApi.create({ ...newBaseline })
    ElMessage.success('基线已创建')
    showBaselineDialog.value = false
    await loadBaselines()
  } catch (e) {
    if (e.response?.status === 409) ElMessage.warning('该节点/任务类型/指标的基线已存在')
  }
}

async function runBaseline() {
  if (!runBaselineForm.node_id) { ElMessage.warning('请选择节点'); return }
  runBaselineLoading.value = true
  try {
    const { data } = await baselinesApi.run({ ...runBaselineForm })
    ElMessage.success(`基线测试完成: ${data.baseline_value?.toFixed(2)} ${data.unit || ''}`)
    showRunBaselineDialog.value = false
    await loadBaselines()
  } finally {
    runBaselineLoading.value = false
  }
}

async function runBatchBaseline() {
  batchBaselineLoading.value = true
  try {
    const { data } = await baselinesApi.batchRun({ task_type: 'high_throughput_matmul', runs: 3 })
    ElMessage.success(`批量基线测试完成：${data.succeeded} 个节点成功`)
    loadBaselines()
  } catch {
    ElMessage.error('批量基线测试失败')
  } finally {
    batchBaselineLoading.value = false
  }
}

async function submitBatchBenchmark() {
  batchBenchmarkLoading.value = true
  try {
    const { data } = await ordersApi.batchBenchmark({
      task_type: batchBenchmarkForm.task_type,
      count: batchBenchmarkForm.count,
      data_profile: { matrix_size: batchBenchmarkForm.matrix_size, batch_count: batchBenchmarkForm.batch_count },
    })
    ElMessage.success(`已创建 ${data.created} 条压测工单`)
    showBatchBenchmarkDialog.value = false
    await loadPendingBenchmarkCount()
  } finally {
    batchBenchmarkLoading.value = false
  }
}

async function batchAutoRoute() {
  autoRouteLoading.value = true
  try {
    const { data } = await ordersApi.batchAutoRoute()
    ElMessage.success(`已路由 ${data.routed} 条工单${data.failed?.length ? `，${data.failed.length} 条失败` : ''}`)
    await loadPendingBenchmarkCount()
  } finally {
    autoRouteLoading.value = false
  }
}

async function startAllRouted() {
  startAllLoading.value = true
  try {
    const { data } = await businessApi.list({ order_status: 'materialized', page: 1, page_size: 100 })
    const toStart = (data.items || []).filter(row => row.instance_id && canStart(row.deployment_status))
    if (!toStart.length) { ElMessage.info('没有待启动的实例'); return }
    await instancesApi.batchStart(toStart.map(r => r.instance_id))
    ElMessage.success(`已启动 ${toStart.length} 个实例`)
  } finally {
    startAllLoading.value = false
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.benchmark-view {
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

.section-header {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
}

.counter-badge {
  font-size: 13px;
  color: var(--text-secondary);
}

.success-rate-cards {
  display: flex;
  gap: 16px;
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

.rate-number {
  font-size: 48px;
  font-weight: 700;
  line-height: 1.2;
}
.rate-number.pass { color: #67c23a; }
.rate-number.fail { color: #f56c6c; }
.rate-label { font-size: 14px; color: #606266; margin-top: 8px; }
.rate-detail { font-size: 12px; color: #909399; margin-top: 4px; }
</style>
