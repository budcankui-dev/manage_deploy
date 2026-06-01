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
      <div v-else class="detail-content">
        <div class="detail-header">
          <h2>{{ selectedOrder.name || selectedOrder.id.slice(0, 16) }}</h2>
          <el-tag :type="statusTagType(selectedOrder.status)" size="large">{{ formatStatus(selectedOrder.status) }}</el-tag>
          <el-button v-if="selectedOrder.status === 'pending'" type="danger" plain size="small" @click="cancelOrder" :loading="cancelLoading">取消工单</el-button>
        </div>

        <!-- Basic info -->
        <el-card class="detail-card">
          <template #header>基本信息</template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="工单 ID">
              <code>{{ selectedOrder.id }}</code>
            </el-descriptions-item>
            <el-descriptions-item label="状态">{{ formatStatus(selectedOrder.status) }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatTime(selectedOrder.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ formatTime(selectedOrder.updated_at) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- Status steps -->
        <el-steps :active="orderStepIndex" finish-status="success" align-center style="margin: 16px 0">
          <el-step title="提交" />
          <el-step title="节点分配" />
          <el-step title="部署" />
          <el-step title="运行" />
          <el-step title="评估完成" />
        </el-steps>

        <!-- Task info -->
        <el-card v-if="detail" class="detail-card">
          <template #header>任务信息</template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="任务类型">{{ taskTypeLabel(detail.task_type) || detail.task_type || '-' }}</el-descriptions-item>
            <el-descriptions-item label="路由">
              {{ detail.source_name || '-' }} → {{ detail.destination_name || '-' }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- Business objective -->
        <el-card v-if="detail?.business_objective?.metric_key" class="detail-card">
          <template #header>业务目标</template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="指标">{{ detail.business_objective.metric_key }}</el-descriptions-item>
            <el-descriptions-item label="约束">
              {{ detail.business_objective.operator }} {{ detail.business_objective.target_value }} {{ detail.business_objective.unit || '' }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- Routing result -->
        <el-card v-if="detail?.routing_result" class="detail-card">
          <template #header>路由结果</template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="策略">{{ detail.routing_result.selected_strategy || '-' }}</el-descriptions-item>
            <el-descriptions-item label="节点分配">
              <span v-if="detail.routing_result.placements">
                {{ detail.routing_result.placements?.source || '(未部署)' }} → {{ detail.routing_result.placements?.compute || detail.routing_result.placements?.worker || '-' }} → {{ detail.routing_result.placements?.sink || '(未部署)' }}
              </span>
              <span v-else>-</span>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- Instance status -->
        <el-card v-if="detail?.instance" class="detail-card">
          <template #header>实例状态</template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="实例 ID"><code>{{ detail.instance.id }}</code></el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="instanceStatusType(detail.instance.status)" size="small">{{ instanceStatusLabel(detail.instance.status) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item v-if="detail?.instance?.port_access_urls" label="端口访问">
              <div v-for="(url, role) in detail.instance.port_access_urls" :key="role" style="font-family: monospace; font-size: 12px">
                {{ role }}: {{ url }}
              </div>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- Business metrics -->
        <el-card v-if="detail?.evaluation" class="detail-card">
          <template #header>业务指标</template>
          <div class="result-verdict" :class="verdictClass">
            <strong>{{ verdictTitle }}</strong>
            <p>{{ verdictSubtitle }}</p>
          </div>
        </el-card>

        <div v-if="detailLoading" class="detail-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>加载详情...</span>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ordersApi } from '@/api'
import { taskTypeLabel, buildMatmulVerdict } from '@/constants/businessTaskDisplay'

const orders = ref([])
const selectedOrder = ref(null)
const detail = ref(null)
const listLoading = ref(false)
const detailLoading = ref(false)
const cancelLoading = ref(false)

const orderStepIndex = computed(() => {
  const s = selectedOrder.value?.status
  if (!s || s === 'pending') return 0
  if (s === 'materialized') return 2
  if (s === 'running') return 3
  if (s === 'completed') return 4
  if (s === 'failed' || s === 'cancelled') return -1
  return 0
})

const verdict = computed(() => {
  if (!detail.value?.evaluation) return null
  return buildMatmulVerdict(detail.value.evaluation)
})
const verdictClass = computed(() => verdict.value?.statusClass || '')
const verdictTitle = computed(() => verdict.value?.title || '')
const verdictSubtitle = computed(() => verdict.value?.subtitle || '')

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
    pending: '待处理',
    materialized: '已部署',
    running: '运行中',
    failed: '失败',
    cancelled: '已取消',
    completed: '已完成',
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
  }[status] || 'info'
}

function instanceStatusType(status) {
  return {
    running: 'success',
    ready: 'success',
    stopped: 'info',
    failed: 'danger',
    starting: 'warning',
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

/* ── Left panel ── */
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

/* ── Right panel ── */
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

.detail-card {
  margin-bottom: 16px;
}

.result-verdict { padding: 16px; border-radius: 8px; }
.result-verdict.success { background: #f0f9eb; }
.result-verdict.danger { background: #fef0f0; }
.result-verdict.pending { background: #f4f4f5; }
.result-verdict strong { display: block; margin-bottom: 4px; }
.result-verdict p { margin: 0; color: #606266; font-size: 13px; }

.detail-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 0;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
