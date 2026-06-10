<template>
  <div class="my-orders-page">
    <!-- Left panel: order list -->
    <aside class="orders-list-panel">
      <div class="panel-header">
        <span class="panel-title">我的工单</span>
        <el-button size="small" @click="loadOrders" :loading="listLoading">刷新</el-button>
      </div>
      <div v-if="listLoading" class="list-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      <el-empty v-else-if="!orders.length" description="暂无工单" :image-size="60" />
      <div v-else class="order-items">
        <div
          v-for="order in orders"
          :key="order.id"
          class="order-item"
          :class="{ active: order.id === selectedOrder?.id }"
          @click="selectOrder(order)"
        >
          <div class="order-item-name">{{ order.name || order.id.slice(0, 16) }}</div>
          <div class="order-item-meta">
            <el-tag :type="statusTagType(order.status)" size="small">{{ formatStatus(order.status) }}</el-tag>
            <span class="order-item-time">{{ formatTime(order.created_at) }}</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- Right panel: order detail -->
    <main class="order-detail-panel">
      <div v-if="!selectedOrder" class="detail-empty">
        <el-empty description="请从左侧选择一个工单" :image-size="80" />
      </div>
      <div v-else class="detail-content" v-loading="detailLoading">
        <div class="detail-header">
          <h2>{{ selectedOrder.name || selectedOrder.id.slice(0, 16) }}</h2>
          <el-tag :type="statusTagType(selectedOrder.status)" size="large">{{ formatStatus(selectedOrder.status) }}</el-tag>
          <el-button v-if="selectedOrder.status === 'pending'" type="danger" plain size="small" @click="cancelOrder" :loading="cancelLoading">取消工单</el-button>
        </div>

        <el-steps :active="orderStepIndex" finish-status="success" align-center style="margin: 0 0 20px">
          <el-step title="提交" />
          <el-step title="节点分配" />
          <el-step title="部署" />
          <el-step title="运行" />
          <el-step title="评估完成" />
        </el-steps>

        <el-tabs v-model="detailTab" class="detail-tabs">
          <!-- 业务 tab -->
          <el-tab-pane label="业务" name="business">
            <template v-if="detail?.business_task">
              <el-descriptions :column="1" border class="detail-desc">
                <el-descriptions-item label="任务类型">{{ taskTypeLabel(detail.business_task.task_type) }}</el-descriptions-item>
                <el-descriptions-item label="路由">{{ detail.source_name || '-' }} → {{ detail.destination_name || '-' }}</el-descriptions-item>
                <el-descriptions-item label="模态">{{ modalityLabel(detail.business_task.modality) }}</el-descriptions-item>
              </el-descriptions>

              <h3 class="section-title">数据画像</h3>
              <el-descriptions v-if="detailDataProfileRows.length" :column="1" border class="detail-desc">
                <el-descriptions-item v-for="row in detailDataProfileRows" :key="row.label" :label="row.label">{{ row.value }}</el-descriptions-item>
              </el-descriptions>

              <h3 class="section-title">业务目标</h3>
              <div class="objective-card">
                <p class="objective-headline">{{ detailObjectiveSentence }}</p>
                <p class="objective-meaning">{{ detailObjectiveMeaning }}</p>
              </div>

              <h3 class="section-title">运行计划</h3>
              <el-descriptions v-if="detailRuntimePlanRows.length" :column="1" border class="detail-desc">
                <el-descriptions-item v-for="row in detailRuntimePlanRows" :key="row.label" :label="row.label">{{ row.value }}</el-descriptions-item>
              </el-descriptions>
            </template>
            <el-empty v-else description="无业务任务数据" />
          </el-tab-pane>

          <!-- 路由 tab -->
          <el-tab-pane label="路由" name="routing">
            <template v-if="detail?.routing_result">
              <el-descriptions :column="1" border class="detail-desc">
                <el-descriptions-item label="路由策略">{{ routingPolicyLabel(detail.routing_result.strategy || detail.routing_result.selected_strategy) }}</el-descriptions-item>
              </el-descriptions>
              <el-collapse v-if="detail.routing_input_dag" class="raw-collapse" style="margin:12px 0">
                <el-collapse-item title="提交给路由系统的 DAG JSON" name="routing-input-dag">
                  <pre class="json-block">{{ prettyJson(detail.routing_input_dag) }}</pre>
                </el-collapse-item>
              </el-collapse>
              <h3 class="section-title">节点放置</h3>
              <el-table :data="placementRows" size="small">
                <el-table-column prop="role" label="角色" width="120" />
                <el-table-column label="部署节点" min-width="220">
                  <template #default="{ row }">
                    <span v-if="row.worker_host === '未部署'" style="color: #909399">未部署容器</span>
                    <span v-else>{{ row.worker_host }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="GPU" width="120">
                  <template #default="{ row }">
                    <span :class="{ 'warning-text': row.requires_gpu && !hasGpuValue(row.gpu_device) }">
                      {{ row.gpu_display }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="node_id" label="路由角色" width="110" />
              </el-table>
            </template>
            <el-empty v-else description="无路由结果" />
          </el-tab-pane>

          <!-- 部署 tab -->
          <el-tab-pane label="部署" name="deployment">
            <template v-if="detail?.instance">
              <el-descriptions :column="2" border>
                <el-descriptions-item label="实例 ID">{{ detail.instance.id }}</el-descriptions-item>
                <el-descriptions-item label="状态">
                  <el-tag :type="instanceStatusType(detail.instance.status)" size="small">{{ instanceStatusLabel(detail.instance.status) }}</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="错误" :span="2">{{ detail.instance.error_message || '-' }}</el-descriptions-item>
              </el-descriptions>
              <h3 class="section-title">节点列表</h3>
              <el-table v-if="instanceNodes.length" :data="instanceNodes" size="small">
                <el-table-column prop="name" label="节点" width="120" />
                <el-table-column prop="status" label="状态" width="100" />
                <el-table-column prop="image" label="镜像" min-width="180" />
                <el-table-column prop="container_id" label="容器" min-width="160" />
              </el-table>
              <div v-if="portAccessRows.length" style="margin-top: 12px">
                <h4 style="margin-bottom: 8px">端口访问</h4>
                <el-table :data="portAccessRows" size="small" border>
                  <el-table-column prop="nodeName" label="子任务" width="100" />
                  <el-table-column prop="portName" label="端口名" width="100" />
                  <el-table-column label="访问地址" min-width="240">
                    <template #default="{ row }"><code style="font-size: 12px">{{ row.accessUrl }}</code></template>
                  </el-table-column>
                </el-table>
              </div>
            </template>
            <el-empty v-else description="尚未部署实例" />
          </el-tab-pane>

          <!-- 结果 tab -->
          <el-tab-pane label="结果" name="result">
            <template v-if="isMatmul">
              <h3 class="section-title">本任务在做什么</h3>
              <ol class="pipeline-steps">
                <li v-for="step in MATMUL_PIPELINE_STEPS" :key="step.role">
                  <strong>{{ step.role }}</strong> — {{ step.title }}：{{ step.detail }}
                </li>
              </ol>

              <h3 class="section-title">输入参数</h3>
              <el-descriptions v-if="matmulInputRows.length" :column="1" border class="detail-desc">
                <el-descriptions-item v-for="row in matmulInputRows" :key="row.label" :label="row.label">{{ row.value }}</el-descriptions-item>
              </el-descriptions>

              <h3 class="section-title">计算输出</h3>
              <el-descriptions v-if="matmulOutputRows.length" :column="1" border class="detail-desc">
                <el-descriptions-item v-for="row in matmulOutputRows" :key="row.label" :label="row.label">{{ row.value }}</el-descriptions-item>
              </el-descriptions>

              <div v-if="matmulConsistency" class="consistency-row">
                <el-tag :type="matmulConsistency.ok ? 'success' : 'warning'" size="small">{{ matmulConsistency.label }}</el-tag>
                <span class="consistency-detail">{{ matmulConsistency.detail }}</span>
              </div>

              <h3 class="section-title">性能验收</h3>
              <div class="result-verdict" :class="matmulVerdict.statusClass">
                <strong>{{ matmulVerdict.title }}</strong>
                <p>{{ matmulVerdict.subtitle }}</p>
              </div>
            </template>
            <template v-else-if="isVideo">
              <h3 class="section-title">本任务在做什么</h3>
              <ol class="pipeline-steps">
                <li v-for="step in VIDEO_PIPELINE_STEPS" :key="step.role">
                  <strong>{{ step.role }}</strong> — {{ step.title }}：{{ step.detail }}
                </li>
              </ol>

              <div class="video-result-card">
                <div class="video-preview">
                  <template v-if="videoPreview">
                    <div class="video-proof-frame">
                      <img :src="videoPreview" alt="视频推理分类画框结果" />
                      <div v-if="videoNeedsOverlay" class="video-proof-overlay">
                        <div v-if="videoEvidenceRows.length" class="video-proof-badge">
                          <span v-for="row in videoEvidenceRows" :key="row">{{ row }}</span>
                        </div>
                        <div
                          v-for="row in videoDetectionRows"
                          :key="`${row.label || row.label_zh}-${row.bbox_xyxy?.join('-')}`"
                          class="video-proof-box"
                          :style="videoBoxStyle(row)"
                        >
                          <span>{{ row.label_zh || row.display_label || row.label }}</span>
                        </div>
                      </div>
                    </div>
                  </template>
                  <el-empty v-else description="等待带框预览图" :image-size="80" />
                </div>
                <div class="video-result-side">
                  <h3 class="section-title">输入参数</h3>
                  <el-descriptions v-if="videoInputRows.length" :column="1" border class="detail-desc">
                    <el-descriptions-item v-for="row in videoInputRows" :key="row.label" :label="row.label">{{ row.value }}</el-descriptions-item>
                  </el-descriptions>

                  <h3 class="section-title">推理输出</h3>
                  <el-descriptions v-if="videoOutputRows.length" :column="1" border class="detail-desc">
                    <el-descriptions-item v-for="row in videoOutputRows" :key="row.label" :label="row.label">{{ row.value }}</el-descriptions-item>
                  </el-descriptions>
                </div>
              </div>

              <h3 v-if="videoDetectionRows.length" class="section-title">分类检测结果</h3>
              <el-table v-if="videoDetectionRows.length" :data="videoDetectionRows" size="small">
                <el-table-column label="类别" min-width="140">
                  <template #default="{ row }">{{ row.display_label || row.label_zh || row.label || '-' }}</template>
                </el-table-column>
                <el-table-column label="置信度" width="100">
                  <template #default="{ row }">{{ Number(row.confidence || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column label="画框坐标" min-width="180">
                  <template #default="{ row }">{{ Array.isArray(row.bbox_xyxy) ? row.bbox_xyxy.join(', ') : '-' }}</template>
                </el-table-column>
              </el-table>

              <h3 class="section-title">性能验收</h3>
              <div class="result-verdict" :class="videoVerdict.statusClass">
                <strong>{{ videoVerdict.title }}</strong>
                <p>{{ videoVerdict.subtitle }}</p>
              </div>
            </template>
            <el-empty v-else description="任务尚未跑完或未上报业务指标" />
            <el-collapse v-if="detail?.evaluation?.result_metadata" class="raw-collapse result-json-collapse">
              <el-collapse-item title="原始结果 JSON" name="result_metadata">
                <pre class="json-block">{{ prettyJson(detail.evaluation.result_metadata) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>
        </el-tabs>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ordersApi } from '@/api'
import {
  MATMUL_PIPELINE_STEPS,
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
  videoDetectionBoxStyle,
  videoDetections,
  videoPreviewEvidenceRows,
  videoPreviewNeedsOverlay,
  videoPreviewDataUrl,
} from '@/constants/businessTaskDisplay'
import { routingPolicyLabel } from '@/constants/routingPolicy'

const orders = ref([])
const selectedOrder = ref(null)
const detail = ref(null)
const listLoading = ref(false)
const detailLoading = ref(false)
const cancelLoading = ref(false)
const detailTab = ref('business')

const orderStepIndex = computed(() => {
  const s = selectedOrder.value?.status
  if (!s || s === 'pending') return 0
  if (s === 'materialized') return 2
  if (s === 'running') return 3
  if (s === 'completed') return 4
  if (s === 'failed' || s === 'cancelled') return -1
  return 0
})

const taskType = computed(() => detail.value?.business_task?.task_type || '')
const isMatmul = computed(() => taskType.value === 'high_throughput_matmul')
const isVideo = computed(() => taskType.value === 'low_latency_video_pipeline')

const detailObjectiveSentence = computed(() =>
  formatObjectiveSentence(detail.value?.business_task?.business_objective)
)
const detailObjectiveMeaning = computed(() =>
  describeObjectiveMeaning(taskType.value, detail.value?.business_task?.business_objective)
)
const detailDataProfileRows = computed(() =>
  describeDataProfile(taskType.value, detail.value?.business_task?.data_profile)
)
const detailRuntimePlanRows = computed(() =>
  describeRuntimePlan(taskType.value, detail.value?.business_task?.runtime_plan)
)

const placementRows = computed(() => {
  const placements = detail.value?.routing_result?.placements
  if (!placements) return []
  const rowFor = (role, placement) => {
    const roleName = {
      source: '数据源',
      compute: '计算',
      worker: '计算',
      sink: '汇总',
    }[role] || role
    const requiresGpu = role === 'compute' || role === 'worker'
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

const instanceNodes = computed(() => detail.value?.instance?.nodes || [])

const portAccessRows = computed(() => {
  const nodes = instanceNodes.value
  if (!nodes.length) return []
  const rows = []
  for (const node of nodes) {
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

function prettyJson(value) {
  if (!value) return '暂无数据'
  return JSON.stringify(value, null, 2)
}

function hasGpuValue(value) {
  return value !== undefined && value !== null && String(value) !== ''
}

const matmulInputRows = computed(() => buildMatmulInputRows(detail.value?.business_task?.data_profile))
const matmulOutputRows = computed(() =>
  buildMatmulOutputRows(detail.value?.evaluation?.result_metadata, detail.value?.evaluation)
)
const matmulConsistency = computed(() =>
  buildMatmulParamConsistency(detail.value?.business_task?.data_profile, detail.value?.evaluation?.result_metadata)
)
const matmulVerdict = computed(() => buildMatmulVerdict(detail.value?.evaluation))
const videoInputRows = computed(() => buildVideoInputRows(detail.value?.business_task?.data_profile))
const videoOutputRows = computed(() =>
  buildVideoOutputRows(detail.value?.evaluation?.result_metadata, detail.value?.evaluation)
)
const videoVerdict = computed(() => buildVideoVerdict(detail.value?.evaluation))
const videoPreview = computed(() => videoPreviewDataUrl(detail.value?.evaluation?.result_metadata))
const videoDetectionRows = computed(() => videoDetections(detail.value?.evaluation?.result_metadata))
const videoEvidenceRows = computed(() => videoPreviewEvidenceRows(detail.value?.evaluation?.result_metadata))
const videoNeedsOverlay = computed(() => videoPreviewNeedsOverlay(detail.value?.evaluation?.result_metadata))

function videoBoxStyle(row) {
  return videoDetectionBoxStyle(row, detail.value?.evaluation?.result_metadata)
}

async function loadOrders() {
  listLoading.value = true
  try {
    const { data } = await ordersApi.list({ reconcile: false })
    orders.value = Array.isArray(data) ? data : (data.items || [])
  } catch {
    orders.value = []
  } finally {
    listLoading.value = false
  }
}

async function selectOrder(order) {
  selectedOrder.value = order
  detail.value = null
  detailTab.value = 'business'
  detailLoading.value = true
  try {
    const { data } = await ordersApi.get(order.id)
    detail.value = data
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

async function cancelOrder() {
  if (!selectedOrder.value) return
  try {
    await ElMessageBox.confirm('确定取消此工单？', '确认')
    cancelLoading.value = true
    await ordersApi.cancel(selectedOrder.value.id)
    ElMessage.success('工单已取消')
    await loadOrders()
    selectedOrder.value = null
    detail.value = null
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('取消失败')
  } finally {
    cancelLoading.value = false
  }
}

function formatStatus(status) {
  return {
    pending: '待路由',
    materialized: '已部署',
    running: '运行中',
    failed: '失败',
    cancelled: '已取消',
    completed: '已完成',
    awaiting_routing: '路由中',
    orphaned: '孤立',
  }[status] || status || '-'
}

function statusTagType(status) {
  return {
    pending: 'info',
    materialized: 'warning',
    running: 'success',
    failed: 'danger',
    cancelled: '',
    completed: 'success',
    awaiting_routing: 'warning',
  }[status] || 'info'
}

function instanceStatusType(status) {
  return {
    running: 'success',
    ready: 'success',
    stopped: 'info',
    failed: 'danger',
    starting: 'warning',
    scheduled: 'info',
  }[status] || 'info'
}

function instanceStatusLabel(status) {
  return {
    running: '运行中',
    stopped: '已停止',
    failed: '失败',
    starting: '启动中',
    scheduled: '已调度',
    pending: '待启动',
  }[status] || status || '-'
}

function formatTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onMounted(loadOrders)
</script>

<style scoped>
.my-orders-page {
  display: grid;
  grid-template-columns: 300px 1fr;
  height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.orders-list-panel {
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.list-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 24px 16px;
  font-size: 13px;
  color: var(--text-secondary);
}

.order-items {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.order-item {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--bg-tertiary);
  cursor: pointer;
  transition: border-color 0.15s;
}

.order-item:hover { border-color: var(--el-color-primary-light-5); }
.order-item.active { border-color: var(--accent-primary); }

.order-item-name {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 6px;
}

.order-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.order-item-time {
  font-size: 11px;
  color: var(--text-muted);
}

.order-detail-panel {
  overflow-y: auto;
  padding: 24px;
}

.detail-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.detail-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}

.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-desc {
  margin-bottom: 4px;
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
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}

.video-preview {
  min-height: 220px;
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

.result-verdict {
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

.result-verdict p { margin: 0; color: var(--text-secondary); line-height: 1.6; }
.result-verdict.success { border-color: rgba(34, 197, 94, 0.35); background: rgba(34, 197, 94, 0.08); }
.result-verdict.danger { border-color: rgba(239, 68, 68, 0.35); background: rgba(239, 68, 68, 0.08); }
.result-verdict.pending { border-color: rgba(59, 130, 246, 0.35); background: rgba(59, 130, 246, 0.08); }

.warning-text {
  color: var(--el-color-warning);
  font-weight: 600;
}

.result-json-collapse {
  margin-top: 12px;
}

.json-block {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}
</style>
