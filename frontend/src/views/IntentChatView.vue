<template>
  <div class="intent-workspace">
    <aside class="conversation-sidebar">
      <div class="brand">
        <strong>任务对话</strong>
        <span>{{ auth.username || 'user' }}</span>
      </div>
      <el-button type="primary" @click="startNewConversation">新建对话</el-button>
      <div class="history-title">历史对话</div>
      <div class="conversation-list">
        <button
          v-for="item in conversations"
          :key="item.id"
          class="conversation-item"
          :class="{ active: item.id === conversation?.id }"
          @click="loadConversation(item.id)"
        >
          <span>{{ item.title || `任务 ${item.task_id?.slice(0, 8) || item.id.slice(0, 8)}` }}</span>
          <small>{{ formatStatus(item.status) }}</small>
        </button>
      </div>
      <div class="account-tools">
        <el-tag v-if="auth.isBypass" size="small" type="warning">开发绕过登录</el-tag>
        <el-button text @click="logout">退出登录</el-button>
      </div>
    </aside>

    <main class="chat-column">
      <header class="chat-header">
        <div>
          <h1>{{ conversation?.title || '新任务对话' }}</h1>
          <p>任务 ID：<code>{{ conversation?.task_id || conversation?.id || '-' }}</code></p>
        </div>
        <el-tag>{{ formatStatus(conversation?.status) }}</el-tag>
      </header>

      <section class="messages" ref="messagesRef">
        <el-empty v-if="!conversation?.messages?.length" description="描述你的业务任务，系统会实时解析意图" />
        <div
          v-for="message in conversation?.messages || []"
          :key="message.id"
          class="message"
          :class="message.role"
        >
          <strong>{{ message.role === 'user' ? '我' : '助手' }}</strong>
          <p>{{ message.content }}</p>
        </div>
      </section>

      <footer class="composer">
        <el-input
          v-model="utterance"
          type="textarea"
          :rows="4"
          placeholder="例如：跑 64×64 矩阵乘法批处理，计算耗时不超过 60 秒"
          @keydown.ctrl.enter="sendMessage"
        />
        <div class="composer-actions">
          <span>Ctrl + Enter 发送</span>
          <el-button type="primary" :loading="loading" @click="sendMessage">发送</el-button>
        </div>
      </footer>
    </main>

    <aside class="intent-panel">
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
          <el-icon class="is-loading"><i class="el-icon-loading" /></el-icon>
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
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { conversationApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { formatObjectiveSentence, taskTypeLabel } from '@/constants/businessTaskDisplay'

const router = useRouter()
const auth = useAuthStore()
const conversations = ref([])
const conversation = ref(null)
const utterance = ref('')
const loading = ref(false)
const messagesRef = ref(null)
const editableTarget = ref(null)
const uploadedFiles = ref([])
let routingTimer = null

const draft = computed(() => conversation.value?.latest_draft || null)
const routing = computed(() => conversation.value?.latest_routing_request || null)
const canConfirm = computed(() => draft.value && draft.value.parse_status === 'valid' && conversation.value?.status === 'drafting')
const canSubmit = computed(() => conversation.value?.status === 'ready_to_submit')

const uploadAction = computed(() => conversation.value ? `/api/uploads?conversation_id=${conversation.value.id}` : '')
const uploadHeaders = computed(() => {
  const token = localStorage.getItem('access_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
})

function formatJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

function formatTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
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

async function startNewConversation() {
  const { data } = await conversationApi.create({})
  conversation.value = data
  utterance.value = ''
  await refreshList()
  updateRoutingPolling()
}

async function sendMessage() {
  if (!utterance.value.trim()) return
  loading.value = true
  try {
    if (!conversation.value?.id) {
      await startNewConversation()
    }
    const { data } = await conversationApi.sendMessage(conversation.value.id, {
      content: utterance.value.trim(),
    })
    conversation.value = data
    utterance.value = ''
    await refreshList()
    await scrollToBottom()
  } finally {
    loading.value = false
  }
}

async function confirmIntent() {
  try {
    const { data } = await conversationApi.confirmIntent(conversation.value.id)
    conversation.value = data
    await refreshList()
    ElMessage.success('工单已创建，等待外部路由系统计算路径')
    updateRoutingPolling()
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
.intent-workspace {
  display: grid;
  grid-template-columns: 260px minmax(420px, 1fr) 420px;
  height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.conversation-sidebar,
.intent-panel {
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-subtle);
  padding: 20px;
  overflow-y: auto;
}

.intent-panel {
  border-right: 0;
  border-left: 1px solid var(--border-subtle);
}

.brand {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 18px;
}

.brand span,
.history-title {
  color: var(--text-secondary);
  font-size: 12px;
}

.history-title {
  margin: 18px 0 10px;
}

.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conversation-item {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 10px;
  text-align: left;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
}

.conversation-item.active {
  border-color: var(--accent-primary);
}

.conversation-item span,
.conversation-item small {
  display: block;
}

.conversation-item small {
  margin-top: 4px;
  color: var(--text-muted);
}

.account-tools {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.chat-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100vh;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 22px 28px;
  border-bottom: 1px solid var(--border-subtle);
}

.chat-header h1 {
  font-size: 22px;
  margin-bottom: 6px;
}

.chat-header p {
  color: var(--text-secondary);
  font-size: 13px;
}

.messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 24px 28px;
}

.message {
  max-width: 80%;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--bg-secondary);
}

.message.user {
  align-self: flex-end;
  background: rgba(99, 102, 241, 0.2);
}

.message p {
  margin: 6px 0 0;
  white-space: pre-wrap;
}

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
  color: var(--text-muted);
  font-size: 12px;
}

.panel-card {
  margin-bottom: 16px;
}

.panel-card.valid-border {
  border-color: var(--el-color-success);
}

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

.objective-editor {
  padding: 4px 0;
}

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

.routing-summary {
  margin-bottom: 12px;
}

.routing-waiting {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
  padding: 12px 0;
}

.json-block h4 {
  margin: 12px 0 6px;
}

.json-block pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--bg-tertiary);
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 200px;
  overflow-y: auto;
}

.routing-waiting {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.order-info {
  margin-top: 10px;
}

@media (max-width: 1100px) {
  .intent-workspace {
    grid-template-columns: 220px 1fr;
  }
  .intent-panel {
    display: none;
  }
}
</style>
