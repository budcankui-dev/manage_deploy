<template>
  <div class="intent-app">
    <!-- Top navigation bar -->
    <header class="top-bar">
      <div class="top-bar-left">
        <span class="top-logo">智联计算系统</span>
      </div>
      <div class="top-bar-center">
        <span v-if="conversation?.title" class="top-conv-title">{{ conversation.title }}</span>
      </div>
      <div class="top-bar-right">
        <el-tag size="small" type="info" class="model-badge">Qwen (通义千问)</el-tag>
        <div class="user-chip">{{ auth.username || 'user' }}</div>
      </div>
    </header>

    <div class="intent-workspace" :style="showOrders ? 'grid-template-columns: 260px 1fr 0px' : ''">
    <aside class="conversation-sidebar">
      <div class="sidebar-top">
        <div class="sidebar-nav">
          <div class="nav-item" :class="{ active: showOrders }" @click="toggleOrders">
            <el-icon><List /></el-icon>
            <span>我的工单</span>
          </div>
        </div>

        <div class="conv-list-header">
          <span>对话列表</span>
          <el-button size="small" circle @click="startNewConversation">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <div class="sidebar-conversations">
          <div
            v-for="item in conversations"
            :key="item.id"
            class="conversation-item"
            :class="{ active: !showOrders && item.id === conversation?.id }"
            @click="selectConversation(item.id)"
          >
            <div class="conversation-item-body">
              <span>{{ item.title || `任务 ${item.task_id?.slice(0, 8) || item.id.slice(0, 8)}` }}</span>
              <small>{{ formatStatus(item.status) }}</small>
            </div>
            <el-button
              class="delete-btn"
              link
              type="danger"
              :icon="DeleteIcon"
              size="small"
              @click.stop="deleteConversation(item)"
              title="删除对话"
            />
          </div>
        </div>
      </div>

      <div class="sidebar-bottom">
        <el-tag v-if="auth.isBypass" size="small" type="warning">开发绕过登录</el-tag>
        <div class="user-info">
          <div class="user-avatar-sm">{{ (auth.username || 'U')[0].toUpperCase() }}</div>
          <span class="username-label">{{ auth.username || 'user' }}</span>
        </div>
        <el-button text @click="logout" class="logout-btn">退出登录</el-button>
      </div>
    </aside>

    <main class="chat-column">
      <header v-if="!showOrders" class="chat-header">
        <div>
          <h1>{{ conversation?.title || '新任务对话' }}</h1>
          <p>任务 ID：<code>{{ conversation?.task_id || conversation?.id || '-' }}</code></p>
        </div>
        <div class="chat-header-right">
          <el-tag>{{ formatStatus(conversation?.status) }}</el-tag>
        </div>
      </header>

      <!-- Orders panel (shown when showOrders=true) -->
      <div v-if="showOrders" class="orders-panel">
        <div class="orders-panel-toolbar">
          <span class="orders-panel-title">我的工单</span>
          <div class="orders-toolbar-right">
            <el-select v-model="orderStatusFilter" placeholder="全部" clearable size="small" style="width: 130px">
              <el-option label="全部" value="" />
              <el-option label="pending" value="pending" />
              <el-option label="routing" value="routing" />
              <el-option label="submitted" value="submitted" />
              <el-option label="running" value="running" />
              <el-option label="completed" value="completed" />
              <el-option label="failed" value="failed" />
            </el-select>
            <el-button size="small" @click="loadOrders">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
        </div>
        <el-table
          :data="filteredOrders"
          v-loading="ordersLoading"
          stripe
          size="small"
          class="orders-table"
          @row-click="(row) => openOrderDetail(row)"
        >
          <el-table-column label="工单名称" min-width="160">
            <template #default="{ row }">{{ row.name || row.id.slice(0, 20) }}</template>
          </el-table-column>
          <el-table-column label="任务类型" min-width="160">
            <template #default="{ row }">{{ taskTypeLabel(row.task_type) }}</template>
          </el-table-column>
          <el-table-column label="路径" min-width="160">
            <template #default="{ row }">
              {{ row.source_name && row.destination_name ? `${row.source_name} → ${row.destination_name}` : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="orderStatusType(row.status)" size="small">{{ formatOrderStatus(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="150">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click.stop="openOrderDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- Chat view (shown when showOrders=false) -->
      <template v-else>
        <section class="messages" ref="messagesRef">
        <!-- Empty state welcome screen -->
        <div v-if="!conversation?.messages?.length" class="empty-state">
          <div class="empty-avatar">智</div>
          <h2 class="empty-title">智算意图解析助手</h2>
          <p class="empty-subtitle">请描述您想要部署的计算任务</p>
          <div class="example-chips">
            <button
              v-for="chip in exampleChips"
              :key="chip"
              class="chip"
              @click="useChip(chip)"
            >{{ chip }}</button>
          </div>
        </div>

        <div
          v-for="(message, idx) in conversation?.messages || []"
          :key="message.id || idx"
          class="message-row"
          :class="message.role"
        >
          <!-- Assistant message (left) -->
          <template v-if="message.role === 'assistant'">
            <div class="avatar assistant-avatar">智</div>
            <div class="bubble-wrap">
              <div class="bubble-name">智算助手</div>
              <div class="bubble assistant-bubble">
                <span class="bubble-text">{{ message.content }}</span><span v-if="message.streaming" class="streaming-cursor">▋</span>
              </div>
              <div class="bubble-time">{{ formatBubbleTime(message.created_at) }}</div>
            </div>
          </template>
          <!-- User message (right) -->
          <template v-else>
            <div class="bubble-wrap user-bubble-wrap">
              <div class="bubble-name user-name">{{ auth.username || '我' }}</div>
              <div class="bubble user-bubble">{{ message.content }}</div>
              <div class="bubble-time user-time">{{ formatBubbleTime(message.created_at) }}</div>
            </div>
            <div class="avatar user-avatar">{{ (auth.username || 'U')[0].toUpperCase() }}</div>
          </template>
        </div>
      </section>

      <footer class="composer">
        <el-input
          v-model="utterance"
          type="textarea"
          :rows="4"
          :disabled="isStreaming"
          placeholder="描述您的计算任务，例如：矩阵计算从A节点到B节点，运行2小时..."
          @keydown.ctrl.enter="sendMessage"
        />
        <div class="composer-actions">
          <span class="composer-hint">Ctrl + Enter 发送</span>
          <div class="composer-btns">
            <el-button v-if="isStreaming" type="danger" @click="stopStreaming">
              <el-icon><VideoPause /></el-icon>
              停止
            </el-button>
            <el-button v-else type="primary" :loading="loading" :disabled="isStreaming" @click="sendMessage">
              <el-icon><Promotion /></el-icon>
              发送
            </el-button>
          </div>
        </div>
      </footer>
      </template>
    </main>

    <!-- Order detail drawer (outside v-if/v-else, always mounted) -->
    <el-drawer
      v-model="orderDrawerVisible"
      size="50%"
      direction="rtl"
      destroy-on-close
      class="order-detail-drawer"
    >
      <template #header>
        <span>{{ selectedOrderDetail?.name || (selectedOrderId ? selectedOrderId.slice(0, 8) : '工单详情') }}</span>
        <el-tag v-if="selectedOrderDetail?.status" :type="orderStatusType(selectedOrderDetail.status)" size="small" style="margin-left: 8px">
          {{ formatOrderStatus(selectedOrderDetail.status) }}
        </el-tag>
      </template>
      <div v-if="orderDetailLoading" class="orders-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      <div v-else-if="selectedOrderDetail" class="orders-detail-content">
        <el-descriptions title="基本信息" :column="1" border size="small" class="detail-desc-block">
          <el-descriptions-item label="ID">{{ selectedOrderDetail.id?.slice(0, 8) || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="orderStatusType(selectedOrderDetail.status)" size="small">{{ formatOrderStatus(selectedOrderDetail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(selectedOrderDetail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ formatTime(selectedOrderDetail.updated_at) }}</el-descriptions-item>
        </el-descriptions>
        <el-descriptions title="任务参数" :column="1" border size="small" class="detail-desc-block">
          <el-descriptions-item label="任务类型">{{ taskTypeLabel(selectedOrderDetail.task_type) }}</el-descriptions-item>
          <el-descriptions-item label="源节点→目标节点">
            {{ selectedOrderDetail.source_name || '-' }} → {{ selectedOrderDetail.destination_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(selectedOrderDetail.business_start_time) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(selectedOrderDetail.business_end_time) }}</el-descriptions-item>
          <el-descriptions-item v-if="selectedOrderDetail.business_objective?.metric_key" label="业务目标">
            {{ selectedOrderDetail.business_objective.metric_key }}
            {{ selectedOrderDetail.business_objective.operator || '<=' }}
            {{ selectedOrderDetail.business_objective.target_value }}
            {{ selectedOrderDetail.business_objective.unit || 'ms' }}
          </el-descriptions-item>
        </el-descriptions>
        <el-descriptions v-if="selectedOrderDetail.routing_request" title="路由结果" :column="1" border size="small" class="detail-desc-block">
          <el-descriptions-item label="策略">{{ selectedOrderDetail.routing_request.selected_strategy || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="selectedOrderDetail.routing_request.placements" label="节点分配">
            {{ selectedOrderDetail.routing_request.placements.source }} →
            {{ selectedOrderDetail.routing_request.placements.compute }} →
            {{ selectedOrderDetail.routing_request.placements.sink }}
          </el-descriptions-item>
        </el-descriptions>
        <el-descriptions v-if="orderInstances.length" title="部署实例" :column="1" border size="small" class="detail-desc-block">
          <el-descriptions-item v-for="inst in orderInstances" :key="inst.id" :label="inst.id?.slice(0, 8) || '-'">
            <el-tag :type="inst.status === 'running' ? 'success' : inst.status === 'failed' ? 'danger' : 'info'" size="small">{{ inst.status }}</el-tag>
            <span v-if="inst.started_at" style="margin-left: 8px; font-size: 12px; color: var(--text-muted)">{{ formatTime(inst.started_at) }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>

    <aside class="intent-panel" v-show="!showOrders" :style="showOrders ? 'overflow: hidden; padding: 0;' : ''">
      <el-card class="panel-card" :class="{ 'valid-border': draft?.parse_status === 'valid' }">
        <template #header>
          意图参数
          <el-tag v-if="draft" :type="parseStatusType(draft.parse_status)" size="small" style="margin-left:8px">{{ draft.parse_status }}</el-tag>
        </template>
        <el-descriptions v-if="draft" :column="1" border size="small">
          <el-descriptions-item label="任务类型">{{ taskTypeLabel(draft.task_type) || draft.task_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="源节点">{{ draft.source_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="目的节点">{{ draft.destination_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(draft.business_start_time) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(draft.business_end_time) }}</el-descriptions-item>
          <el-descriptions-item label="解析引擎">{{ draft.parser_name || 'rule_based' }}</el-descriptions-item>
        </el-descriptions>
        <el-empty v-else description="发送消息后查看解析结果" :image-size="60" />
        <div v-if="draft?.validation_errors?.length" class="errors">
          <el-alert v-for="(item, index) in draft.validation_errors" :key="index" :title="item" type="warning" show-icon :closable="false" />
        </div>
      </el-card>

      <el-card class="panel-card">
        <template #header>业务目标</template>
        <div v-if="draft?.business_objective?.metric_key" class="objective-editor">
          <el-form label-width="60px" size="small">
            <el-form-item label="指标">
              <span>{{ draft.business_objective.metric_key }}</span>
            </el-form-item>
            <el-form-item label="目标值">
              <el-input-number v-model="editableTarget" :min="0" :step="1000" controls-position="right" style="width:160px" @change="onTargetChange" />
              <span style="margin-left:6px">{{ draft.business_objective.unit || 'ms' }}</span>
            </el-form-item>
            <el-form-item label="约束">
              <el-tag size="small">{{ draft.business_objective.operator || '<=' }}</el-tag>
            </el-form-item>
          </el-form>
        </div>
        <el-empty v-else description="从对话中提取业务目标" :image-size="60" />
      </el-card>

      <el-card class="panel-card">
        <template #header>输入文件（可选）</template>
        <el-upload
          :action="uploadAction"
          :headers="uploadHeaders"
          :on-success="onUploadSuccess"
          :file-list="uploadedFiles"
          :disabled="!conversation"
          drag
          multiple
        >
          <div class="upload-tip">拖拽文件到此处，或点击上传</div>
        </el-upload>
        <p class="file-hint">文件将作为 Worker 输入数据，不影响业务目标和路由决策。</p>
      </el-card>

      <el-card class="panel-card">
        <template #header>
          操作
          <el-tag v-if="routing" :type="routingStatusType(routing.status)" size="small" style="margin-left:8px">{{ formatRoutingStatus(routing.status) }}</el-tag>
        </template>
        <div v-if="routing" class="routing-summary">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="策略">{{ routing.selected_strategy || '-' }}</el-descriptions-item>
            <el-descriptions-item label="节点分配">{{ routing.placements ? `${routing.placements.source} → ${routing.placements.compute} → ${routing.placements.sink}` : '-' }}</el-descriptions-item>
          </el-descriptions>
        </div>
        <div v-if="routing?.status === 'pending' || routing?.status === 'computing'" class="routing-waiting">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>等待路由计算...</span>
        </div>
        <div class="actions">
          <el-button v-if="canConfirm" type="primary" @click="confirmIntent">确认参数并创建工单</el-button>
          <el-button v-if="canSubmit" type="success" @click="submitTask">确认部署</el-button>
          <el-button v-if="conversation?.status === 'submitted'" type="info" text>已提交</el-button>
        </div>
      </el-card>
    </aside>
  </div>

    <!-- Bottom status bar -->
    <footer class="bottom-bar">
      <span class="bottom-left">智联计算系统意图解析模块 v1.0</span>
      <span class="bottom-right">模型: qwen-plus · DashScope API</span>
    </footer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete as DeleteIcon, Loading, VideoPause, Plus, Promotion, List, Refresh } from '@element-plus/icons-vue'
import { conversationApi, ordersApi, instancesApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { taskTypeLabel } from '@/constants/businessTaskDisplay'

const router = useRouter()
const auth = useAuthStore()
const conversations = ref([])
const conversation = ref(null)
const utterance = ref('')
const loading = ref(false)
const isStreaming = ref(false)
const messagesRef = ref(null)
const editableTarget = ref(null)
const uploadedFiles = ref([])
const myOrders = ref([])
const ordersLoading = ref(false)
const showOrders = ref(false)
const orderDrawerVisible = ref(false)
const selectedOrderId = ref(null)
const selectedOrderDetail = ref(null)
const orderDetailLoading = ref(false)
const orderStatusFilter = ref('')
const orderInstances = ref([])
let routingTimer = null
let abortController = null

const filteredOrders = computed(() => {
  if (!orderStatusFilter.value) return myOrders.value
  return myOrders.value.filter(o => o.status === orderStatusFilter.value)
})

function toggleOrders() { showOrders.value = !showOrders.value }

const exampleChips = [
  '矩阵计算，从compute-1到compute-3，跑2小时',
  '视频转发任务，低延迟要求',
  '大模型推理服务部署',
]

const draft = computed(() => conversation.value?.latest_draft || null)
const routing = computed(() => conversation.value?.latest_routing_request || null)
const canConfirm = computed(() => draft.value && draft.value.parse_status === 'valid' && conversation.value?.status === 'drafting')
const canSubmit = computed(() => conversation.value?.status === 'ready_to_submit')

const uploadAction = computed(() => conversation.value ? `/api/uploads?conversation_id=${conversation.value.id}` : '')
const uploadHeaders = computed(() => {
  const token = localStorage.getItem('access_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
})

function formatTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatBubbleTime(value) {
  if (!value) return ''
  const d = new Date(value)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function parseStatusType(status) {
  return { valid: 'success', incomplete: 'warning', rejected: 'danger' }[status] || 'info'
}

function routingStatusType(status) {
  return { pending: 'warning', computing: 'warning', completed: 'success', failed: 'danger' }[status] || 'info'
}

function formatRoutingStatus(status) {
  return { pending: '等待计算', computing: '计算中', completed: '已完成', failed: '失败', cancelled: '已取消' }[status] || status
}

function orderStatusType(status) {
  return {
    pending: 'info',
    routing: 'warning',
    ready_to_submit: 'warning',
    submitted: 'success',
    running: 'success',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info'
  }[status] || 'info'
}

function formatOrderStatus(status) {
  return { pending: '待处理', materialized: '已物化', running: '运行中', failed: '失败', cancelled: '已取消', completed: '已完成' }[status] || status || '-'
}

function onTargetChange(val) {
  if (!conversation.value || !draft.value) return
  const updated = { ...draft.value.business_objective, target_value: val }
  conversationApi.updateDraft(conversation.value.id, { business_objective: updated })
}

function onUploadSuccess(response) {
  uploadedFiles.value.push({ name: response.filename, url: response.uri })
  ElMessage.success(`${response.filename} 上传成功`)
}

function formatStatus(status) {
  return ({
    drafting: '草稿中',
    awaiting_routing: '待路由',
    ready_to_submit: '可提交',
    submitted: '已提交',
    rejected: '已拒绝',
    failed: '失败',
  }[status] || status || '未开始')
}

async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

async function refreshList() {
  const { data } = await conversationApi.list()
  conversations.value = data
}

async function refreshConversation() {
  if (!conversation.value?.id) return
  const { data } = await conversationApi.get(conversation.value.id)
  conversation.value = data
  await refreshList()
  await scrollToBottom()
  updateRoutingPolling()
}

async function loadConversation(id) {
  const { data } = await conversationApi.get(id)
  conversation.value = data
  utterance.value = ''
  await scrollToBottom()
  updateRoutingPolling()
}

function selectConversation(id) {
  showOrders.value = false
  loadConversation(id)
}

async function startNewConversation() {
  const { data } = await conversationApi.create({})
  conversation.value = data
  utterance.value = ''
  // Prepend to list immediately so it appears highlighted at the top
  conversations.value = [data, ...conversations.value.filter(c => c.id !== data.id)]
  updateRoutingPolling()
}

async function deleteConversation(item) {
  try {
    await ElMessageBox.confirm(
      `确认删除对话「${item.title || item.id.slice(0, 8)}」？`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  // Optimistic: remove from list immediately
  conversations.value = conversations.value.filter(c => c.id !== item.id)
  const wasActive = item.id === conversation.value?.id

  try {
    await conversationApi.delete(item.id)
    ElMessage.success('对话已删除')

    // If deleted the active conversation, switch to next or create new
    if (wasActive) {
      if (conversations.value.length) {
        await loadConversation(conversations.value[0].id)
      } else {
        await startNewConversation()
      }
    }
  } catch (err) {
    // Rollback: re-fetch list on error
    await refreshList()
    ElMessage.error('删除失败')
  }
}

async function loadOrders() {
  ordersLoading.value = true
  try {
    const { data } = await ordersApi.list({ include_cancelled: true, reconcile: false })
    myOrders.value = data
  } catch {
    myOrders.value = []
  } finally {
    ordersLoading.value = false
  }
}

watch(showOrders, (val) => {
  if (val) loadOrders()
})

async function openOrderDetail(order) {
  selectedOrderId.value = order.id
  selectedOrderDetail.value = null
  orderInstances.value = []
  orderDrawerVisible.value = true
  orderDetailLoading.value = true
  try {
    const [detailRes, instancesRes] = await Promise.all([
      ordersApi.get(order.id),
      instancesApi.list({ order_id: order.id })
    ])
    selectedOrderDetail.value = detailRes.data
    orderInstances.value = instancesRes.data
  } catch {
    // keep nulls
  } finally {
    orderDetailLoading.value = false
  }
}

function useChip(text) {
  utterance.value = text
}

async function sendMessage() {
  if (!utterance.value.trim() || loading.value || isStreaming.value) return
  loading.value = true
  const text = utterance.value.trim()
  utterance.value = ''

  try {
    if (!conversation.value?.id) {
      await startNewConversation()
    }

    if (!conversation.value.messages) conversation.value.messages = []
    conversation.value.messages = [
      ...conversation.value.messages,
      { role: 'user', content: text, id: '_user_' + Date.now() },
      { role: 'assistant', content: '', id: '_stream', streaming: true },
    ]
    await nextTick()
    await scrollToBottom()

    const token = localStorage.getItem('access_token')
    abortController = new AbortController()
    isStreaming.value = true

    const response = await fetch(`/api/conversations/${conversation.value.id}/messages/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ content: text }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const raw = line.slice(5).trim()
        try {
          const event = JSON.parse(raw)
          if (event.type === 'token') {
            const msgs = conversation.value.messages
            const idx = msgs.findIndex(m => m.id === '_stream')
            if (idx !== -1) {
              conversation.value.messages = [
                ...msgs.slice(0, idx),
                { ...msgs[idx], content: msgs[idx].content + event.content },
                ...msgs.slice(idx + 1),
              ]
            }
            await scrollToBottom()
          } else if (event.type === 'done') {
            isStreaming.value = false
            await loadConversation(conversation.value.id)
            await refreshList()
          } else if (event.type === 'error') {
            const msgs = conversation.value.messages
            const idx = msgs.findIndex(m => m.id === '_stream')
            if (idx !== -1) {
              conversation.value.messages = [
                ...msgs.slice(0, idx),
                { ...msgs[idx], content: msgs[idx].content || '解析失败，请重试', streaming: false },
                ...msgs.slice(idx + 1),
              ]
            }
          }
        } catch {
          // ignore malformed SSE lines
        }
      }
    }

    // Stream ended naturally — ensure streaming state is cleared
    isStreaming.value = false
    // Mark placeholder as done if still present (no 'done' event received)
    if (conversation.value?.messages) {
      const msgs = conversation.value.messages
      const idx = msgs.findIndex(m => m.id === '_stream')
      if (idx !== -1) {
        conversation.value.messages = [
          ...msgs.slice(0, idx),
          { ...msgs[idx], streaming: false },
          ...msgs.slice(idx + 1),
        ]
        await loadConversation(conversation.value.id)
        await refreshList()
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      if (conversation.value?.messages) {
        const msgs = conversation.value.messages
        const idx = msgs.findIndex(m => m.id === '_stream')
        if (idx !== -1) {
          conversation.value.messages = [
            ...msgs.slice(0, idx),
            { ...msgs[idx], streaming: false },
            ...msgs.slice(idx + 1),
          ]
        }
      }
    } else {
      if (conversation.value?.messages) {
        const msgs = conversation.value.messages
        const idx = msgs.findIndex(m => m.id === '_stream')
        if (idx !== -1) {
          conversation.value.messages = [
            ...msgs.slice(0, idx),
            { ...msgs[idx], content: msgs[idx].content || '解析失败，请重试', streaming: false },
            ...msgs.slice(idx + 1),
          ]
        }
      }
    }
  } finally {
    loading.value = false
    isStreaming.value = false
    abortController = null
  }
}

function stopStreaming() {
  abortController?.abort()
}

async function confirmIntent() {
  try {
    const { data } = await conversationApi.confirmIntent(conversation.value.id)
    conversation.value = data
    await refreshList()
    ElMessage.success('工单已创建，等待外部路由系统计算路径')
    updateRoutingPolling()
    if (showOrders.value) loadOrders()
  } catch (err) {
    const detail = err.response?.data?.detail
    if (detail?.validation_errors) {
      ElMessage.warning('参数不完整：' + detail.validation_errors.join('；'))
    } else {
      ElMessage.error(typeof detail === 'string' ? detail : '确认失败')
    }
  }
}

async function submitTask() {
  const { data: result } = await conversationApi.submit(conversation.value.id, { auto_start: false })
  await refreshConversation()
  if (showOrders.value) loadOrders()
  if (auth.isAdmin && result.order_id) {
    ElMessage.success('任务已提交，正在打开业务任务中心…')
    await router.push({ path: '/business-tasks', query: { orderId: result.order_id } })
    return
  }
  ElMessage.success(`任务已提交（order=${result.order_id || '-'}，instance=${result.instance_id || '-'}）`)
}

function updateRoutingPolling() {
  stopRoutingPolling()
  const status = routing.value?.status
  if (status === 'pending' || status === 'computing') {
    routingTimer = setInterval(refreshConversation, 3000)
  }
}

function stopRoutingPolling() {
  if (routingTimer) {
    clearInterval(routingTimer)
    routingTimer = null
  }
}

function logout() {
  auth.logout()
  router.push('/login')
}

onMounted(async () => {
  await refreshList()
  if (conversations.value.length) {
    await loadConversation(conversations.value[0].id)
  } else {
    await startNewConversation()
  }
})

watch(draft, (d) => {
  if (d?.business_objective?.target_value != null) {
    editableTarget.value = d.business_objective.target_value
  }
})

onBeforeUnmount(stopRoutingPolling)
</script>

<style scoped>
/* ── App shell (top bar + workspace + bottom bar) ── */
.intent-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── Top bar ── */
.top-bar {
  flex-shrink: 0;
  height: 48px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 16px;
  z-index: 10;
}

.top-bar-left { display: flex; align-items: center; width: 260px; flex-shrink: 0; }
.top-logo { font-size: 15px; font-weight: 700; color: var(--text-primary); letter-spacing: 0.02em; }

.top-bar-center { flex: 1; min-width: 0; text-align: center; }
.top-conv-title {
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  max-width: 400px;
}

.top-bar-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.model-badge { font-size: 11px; }
.user-chip {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 12px;
}

/* ── Bottom status bar ── */
.bottom-bar {
  flex-shrink: 0;
  height: 32px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  font-size: 11px;
  color: var(--text-muted);
}

.intent-workspace {
  display: grid;
  grid-template-columns: 260px minmax(420px, 1fr) 380px;
  flex: 1;
  min-height: 0;
  background: var(--bg-primary);
  color: var(--text-primary);
}

/* ── Sidebar ── */
.conversation-sidebar {
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.sidebar-top {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 20px 20px 0;
}

.sidebar-conversations {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-bottom: 12px;
}

.sidebar-bottom {
  flex-shrink: 0;
  padding: 12px 16px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.new-conv-btn {
  width: 100%;
  margin-bottom: 4px;
  justify-content: center;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar-sm {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.username-label {
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-btn {
  width: 100%;
  justify-content: flex-start;
  color: var(--text-secondary) !important;
  font-size: 13px;
}

.brand {
  display: none;
}

.brand-title {
  display: none;
}

.brand-subtitle {
  display: none;
}

.sidebar-nav {
  margin-bottom: 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  cursor: pointer;
  border-radius: 8px;
  color: rgba(255,255,255,0.7);
  transition: all 0.2s;
}

.nav-item:hover, .nav-item.active {
  background: rgba(255,255,255,0.15);
  color: white;
}

.conv-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0 4px;
  font-size: 12px;
  color: rgba(255,255,255,0.5);
  margin: 18px 0 6px;
}

.history-title {
  color: var(--text-secondary);
  font-size: 12px;
  margin: 18px 0 10px;
}

.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 10px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
}

.conversation-item:hover { border-color: var(--el-color-primary-light-5); }
.conversation-item.active {
  border-color: var(--accent-primary);
  background: rgba(255,255,255,0.15);
  border-left: 3px solid var(--el-color-primary);
}

.conversation-item-body { flex: 1; min-width: 0; }
.conversation-item-body span,
.conversation-item-body small { display: block; }
.conversation-item-body span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conversation-item-body small {
  margin-top: 4px;
  color: var(--text-muted);
}

.delete-btn { flex-shrink: 0; opacity: 0; transition: opacity 0.15s; }
.conversation-item:hover .delete-btn { opacity: 1; }

/* orders */
.orders-section {
  margin-top: 20px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 12px;
}
.orders-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 4px 0;
  user-select: none;
}
.orders-header:hover { color: var(--text-primary); }
.orders-arrow { transition: transform 0.2s; }
.orders-arrow.expanded { transform: rotate(90deg); }
.orders-list { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.orders-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 8px 0;
}
.order-item {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--bg-tertiary);
}
.order-name {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}
.order-meta { display: flex; align-items: center; gap: 6px; }
.order-time { font-size: 11px; color: var(--text-muted); }

/* ── Chat header right ── */
.chat-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

/* ── Inline orders panel ── */
.orders-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  height: 100%;
  background: var(--el-bg-color, white);
}

.orders-panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.orders-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.orders-panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.orders-table {
  flex: 1;
  overflow-y: auto;
}

.orders-detail-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 0;
}

.detail-desc-block {
  margin: 0;
}

/* ── Chat column ── */
.chat-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 22px 28px;
  border-bottom: 1px solid var(--border-subtle);
}
.chat-header h1 { font-size: 22px; margin-bottom: 6px; }
.chat-header p { color: var(--text-secondary); font-size: 13px; }

.messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px 28px;
}

/* ── Empty state ── */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
  gap: 12px;
}

.empty-avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 28px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}

.empty-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.empty-subtitle {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.example-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
}

.chip {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-subtle);
  border-radius: 20px;
  padding: 6px 14px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.chip:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

/* ── Message bubbles ── */
.message-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.message-row.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.assistant-avatar {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
}

.user-avatar {
  background: linear-gradient(135deg, #0ea5e9, #6366f1);
  color: #fff;
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 75%;
}

.user-bubble-wrap {
  align-items: flex-end;
}

.bubble-name {
  font-size: 11px;
  color: var(--text-muted);
  padding: 0 4px;
}

.user-name {
  text-align: right;
}

.bubble {
  padding: 10px 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-bubble {
  background: #f0f7ff;
  color: #1e293b;
  border-radius: 4px 16px 16px 16px;
}

.user-bubble {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  border-radius: 16px 4px 16px 16px;
}

.bubble-text { display: inline; }

.bubble-time {
  font-size: 11px;
  color: var(--text-muted);
  padding: 0 4px;
}

.user-time {
  text-align: right;
}

.streaming-cursor {
  display: inline-block;
  margin-left: 2px;
  animation: blink 0.8s step-end infinite;
  color: #6366f1;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ── Composer ── */
.composer {
  padding: 18px 28px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
}

.composer-actions {
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.composer-hint {
  font-size: 12px;
  color: var(--text-muted);
}

.composer-btns {
  display: flex;
  gap: 8px;
}

/* ── Right panel ── */
.intent-panel {
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-subtle);
  padding: 20px;
  overflow-y: auto;
}

.panel-card { margin-bottom: 16px; }
.panel-card.valid-border { border-color: var(--el-color-success); }

.actions {
  margin-top: 12px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.errors {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.objective-editor { padding: 4px 0; }

.file-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 8px;
}

.upload-tip {
  font-size: 13px;
  color: var(--el-text-color-placeholder);
  padding: 8px 0;
}

.routing-summary { margin-bottom: 12px; }

.routing-waiting {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  padding: 12px 0;
  font-size: 13px;
}

@media (max-width: 900px) {
  .intent-workspace {
    grid-template-columns: 220px 1fr;
  }
  .intent-panel { display: none; }
}
</style>
