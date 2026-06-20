<template>
  <div class="my-orders-page">
    <aside class="orders-list-panel">
      <div class="panel-header">
        <span class="panel-title">我的工单</span>
        <div class="panel-actions">
          <el-button
            size="small"
            type="danger"
            plain
            :disabled="!selectedOrderIds.length"
            :loading="batchDeleteLoading"
            @click="batchDeleteOrders"
          >
            批量删除
          </el-button>
          <el-button size="small" @click="loadOrders" :loading="listLoading">刷新</el-button>
        </div>
      </div>

      <div v-if="listLoading" class="list-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      <el-empty v-else-if="!orders.length" description="暂无工单" :image-size="60" />
      <el-table
        v-else
        :data="orders"
        class="orders-table"
        size="small"
        row-key="id"
        :show-header="false"
        highlight-current-row
        @selection-change="handleSelectionChange"
        @row-click="selectOrder"
      >
        <el-table-column type="selection" width="36" />
        <el-table-column min-width="190">
          <template #default="{ row }">
            <div class="order-item-name">{{ taskTypeLabel(row.task_type) || '业务工单' }}</div>
            <div class="order-item-meta">
              <el-tag :type="statusTagType(row.status || row.order_status, row)" size="small">
                {{ formatStatus(row.status || row.order_status, row) }}
              </el-tag>
              <span class="order-item-time">{{ formatTime(row.created_at) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="74" align="right">
          <template #default="{ row }">
            <el-dropdown trigger="click" @click.stop>
              <el-button size="small" text type="primary" @click.stop>操作</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="selectOrder(row)">查看详情</el-dropdown-item>
                  <el-dropdown-item
                    v-if="canStopOrder(row)"
                    @click="stopOrder(row)"
                  >
                    停止运行
                  </el-dropdown-item>
                  <el-dropdown-item
                    v-if="canCancelOrder(row)"
                    @click="cancelOrder(row)"
                  >
                    取消工单
                  </el-dropdown-item>
                  <el-dropdown-item divided @click="deleteOrder(row)">删除工单</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
    </aside>

    <main class="order-detail-area">
      <div v-if="!selectedOrderId" class="detail-empty">
        <el-empty description="请从左侧选择一个工单" :image-size="80" />
      </div>
      <div v-else v-loading="detailLoading" class="detail-shell">
        <div class="detail-toolbar">
          <span class="detail-toolbar-title">任务工单详情</span>
          <div class="detail-actions">
            <el-button
              v-if="canStopOrder(detail)"
              type="primary"
              plain
              size="small"
              :loading="stopLoading"
              @click="stopOrder(detail)"
            >
              停止运行
            </el-button>
            <el-button
              v-if="canCancelOrder(detail)"
              type="warning"
              plain
              size="small"
              :loading="cancelLoading"
              @click="cancelOrder(detail)"
            >
              取消工单
            </el-button>
            <el-button
              v-if="detail"
              type="danger"
              plain
              size="small"
              :loading="deleteLoading"
              @click="deleteOrder(detail)"
            >
              删除工单
            </el-button>
          </div>
        </div>
        <OrderDetailPanel
          v-model:active-tab="detailTab"
          :detail="detail"
          :result-objects="resultObjects"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { businessApi, ordersApi } from '@/api'
import OrderDetailPanel from '@/components/OrderDetailPanel.vue'
import { taskTypeLabel } from '@/constants/businessTaskDisplay'

const orders = ref([])
const selectedOrderId = ref('')
const detail = ref(null)
const resultObjects = ref([])
const selectedOrderIds = ref([])
const listLoading = ref(false)
const detailLoading = ref(false)
const cancelLoading = ref(false)
const deleteLoading = ref(false)
const stopLoading = ref(false)
const batchDeleteLoading = ref(false)
const detailTab = ref('business')

function orderId(order) {
  return order?.order_id || order?.id || ''
}

function shortId(value) {
  return value ? String(value).slice(0, 12) : '-'
}

function handleSelectionChange(rows) {
  selectedOrderIds.value = rows.map(orderId).filter(Boolean)
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
  const id = orderId(order)
  if (!id) return
  selectedOrderId.value = id
  detail.value = null
  resultObjects.value = []
  detailTab.value = 'business'
  detailLoading.value = true
  try {
    const { data } = await ordersApi.get(id)
    detail.value = data
    const evidenceInstanceId = data.instance?.id || data.materialized_instance_id
    if (evidenceInstanceId) {
      try {
        const { data: objects } = await businessApi.results(evidenceInstanceId, { silentError: true })
        resultObjects.value = objects || []
      } catch {
        resultObjects.value = []
      }
    }
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function canCancelOrder(order) {
  return order?.status === 'pending' || order?.order_status === 'pending'
}

function canStopOrder(order) {
  const status = order?.deployment_status || order?.instance_status
  return Boolean(
    (order?.materialized_instance_id || order?.instance_id || order?.instance_exists) &&
    ['starting', 'running', 'scheduled', 'stopping'].includes(String(status || ''))
  )
}

function showBatchOperationResult(data, successText) {
  const succeeded = data?.succeeded || []
  const failed = data?.failed || {}
  const failedCount = Object.keys(failed).length
  if (failedCount) {
    ElMessage.warning(`${successText(succeeded.length)}，${failedCount} 个失败`)
    return false
  }
  ElMessage.success(successText(succeeded.length))
  return true
}

async function cancelOrder(order = null) {
  const targetOrderId = orderId(order) || selectedOrderId.value
  if (!targetOrderId) return
  try {
    await ElMessageBox.confirm('确定取消此工单？', '确认取消', {
      confirmButtonText: '取消工单',
      cancelButtonText: '返回',
      type: 'warning',
    })
  } catch {
    return
  }

  cancelLoading.value = true
  try {
    await ordersApi.cancel(targetOrderId)
    ElMessage.success('工单已取消')
    await loadOrders()
    if (selectedOrderId.value === targetOrderId) {
      await selectOrder({ id: targetOrderId })
    }
  } catch {
    ElMessage.error('取消失败')
  } finally {
    cancelLoading.value = false
  }
}

async function stopOrder(order = null) {
  const targetOrderId = orderId(order) || selectedOrderId.value
  if (!targetOrderId) return
  try {
    await ElMessageBox.confirm(
      '停止运行会停止并清理该工单当前部署的容器，工单、路由结果和已上报结果会保留。继续吗？',
      '确认停止运行',
      {
        confirmButtonText: '停止运行',
        cancelButtonText: '返回',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  stopLoading.value = true
  try {
    await ordersApi.stopRuntime(targetOrderId)
    ElMessage.success('任务运行已停止')
    await loadOrders()
    if (selectedOrderId.value === targetOrderId) {
      await selectOrder({ id: targetOrderId })
    }
  } catch {
    ElMessage.error('停止运行失败')
  } finally {
    stopLoading.value = false
  }
}

async function deleteOrder(order = null) {
  const targetOrderId = orderId(order) || selectedOrderId.value
  if (!targetOrderId) return
  try {
    await ElMessageBox.confirm(
      '删除工单前会先停止并清理该工单关联的部署实例；如果容器清理失败，工单不会被删除。继续吗？',
      '确认删除工单',
      {
        confirmButtonText: '删除工单',
        cancelButtonText: '返回',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  deleteLoading.value = true
  try {
    await ordersApi.delete(targetOrderId)
    ElMessage.success('工单已删除')
    if (selectedOrderId.value === targetOrderId) {
      selectedOrderId.value = ''
      detail.value = null
      resultObjects.value = []
    }
    await loadOrders()
  } catch {
    ElMessage.error('删除失败')
  } finally {
    deleteLoading.value = false
  }
}

async function batchDeleteOrders() {
  if (!selectedOrderIds.value.length) return
  try {
    await ElMessageBox.confirm(
      `将删除选中的 ${selectedOrderIds.value.length} 个工单及其关联实例，删除后不可恢复，继续吗？`,
      '确认批量删除',
      {
        confirmButtonText: '批量删除',
        cancelButtonText: '返回',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  batchDeleteLoading.value = true
  try {
    const { data } = await ordersApi.batchDelete(selectedOrderIds.value)
    const allOk = showBatchOperationResult(data, (count) => `已删除 ${count} 个工单`)
    if (allOk && selectedOrderIds.value.includes(selectedOrderId.value)) {
      selectedOrderId.value = ''
      detail.value = null
      resultObjects.value = []
    }
    selectedOrderIds.value = []
    await loadOrders()
  } catch {
    ElMessage.error('批量删除失败')
  } finally {
    batchDeleteLoading.value = false
  }
}

function formatStatus(status, order = null) {
  if (isRouteOnlyWaitingOrder(order)) return '待启动'
  return {
    pending: '待分配',
    routing: '分配中',
    routed: '待部署',
    materialized: '已部署',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    awaiting_routing: '待分配',
    orphaned: '待处理',
  }[status] || status || '-'
}

function statusTagType(status, order = null) {
  if (isRouteOnlyWaitingOrder(order)) return 'warning'
  return {
    pending: 'info',
    routing: 'warning',
    routed: 'warning',
    materialized: 'warning',
    running: 'success',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
    awaiting_routing: 'warning',
    orphaned: 'info',
  }[status] || 'info'
}

function isRouteOnlyWaitingOrder(order) {
  const deployment = order?.runtime_config?.platform_deployment
  return order?.status === 'pending'
    && order?.routing_status === 'completed'
    && deployment?.mode === 'route_only'
    && order?.materialized_instance_id == null
}

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(loadOrders)
</script>

<style scoped>
.my-orders-page {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
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

.panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
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

.orders-table {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.orders-table :deep(.el-table__row) {
  cursor: pointer;
}

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

.order-detail-area {
  min-width: 0;
  overflow-y: auto;
  padding: 24px;
}

.detail-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}

.detail-shell {
  min-height: 360px;
}

.detail-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.detail-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.detail-toolbar-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

@media (max-width: 900px) {
  .my-orders-page {
    grid-template-columns: 1fr;
    height: auto;
    min-height: 100vh;
  }

  .orders-list-panel {
    max-height: 320px;
    border-right: none;
    border-bottom: 1px solid var(--border-subtle);
  }
}
</style>
