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
          placeholder="例如：部署低时延视频转发，720p H264，端到端时延低于 200ms"
          @keydown.ctrl.enter="sendMessage"
        />
        <div class="composer-actions">
          <span>Ctrl + Enter 发送</span>
          <el-button type="primary" :loading="loading" @click="sendMessage">发送</el-button>
        </div>
      </footer>
    </main>

    <aside class="intent-panel">
      <el-card class="panel-card">
        <template #header>实时意图参数</template>
        <el-descriptions v-if="draft" :column="1" border size="small">
          <el-descriptions-item label="任务类型">{{ draft.task_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="模态">{{ draft.modality || '-' }}</el-descriptions-item>
          <el-descriptions-item label="解析状态">{{ draft.parse_status }}</el-descriptions-item>
          <el-descriptions-item label="业务目标">{{ formatObjective(draft.business_objective) }}</el-descriptions-item>
          <el-descriptions-item label="Workflow">{{ conversation?.workflow_trace?.engine || '-' }}</el-descriptions-item>
        </el-descriptions>
        <el-empty v-else description="发送消息后查看解析结果" />
        <div v-if="draft?.validation_errors?.length" class="errors">
          <el-alert
            v-for="(item, index) in draft.validation_errors"
            :key="index"
            :title="item"
            type="warning"
            show-icon
            :closable="false"
          />
        </div>
        <div v-if="draft" class="json-block">
          <h4>data_profile</h4>
          <pre>{{ formatJson(draft.data_profile) }}</pre>
          <h4>runtime_plan</h4>
          <pre>{{ formatJson(draft.runtime_plan) }}</pre>
          <h4>resource_requirement</h4>
          <pre>{{ formatJson(draft.resource_requirement) }}</pre>
        </div>
      </el-card>

      <el-card class="panel-card">
        <template #header>路由与部署参数</template>
        <el-descriptions v-if="routing" :column="1" border size="small">
          <el-descriptions-item label="策略">{{ routing.strategy }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ routing.status }}</el-descriptions-item>
          <el-descriptions-item label="source">{{ routing.placements?.source || '-' }}</el-descriptions-item>
          <el-descriptions-item label="compute">{{ routing.placements?.compute || '-' }}</el-descriptions-item>
          <el-descriptions-item label="sink">{{ routing.placements?.sink || '-' }}</el-descriptions-item>
        </el-descriptions>
        <el-empty v-else description="确认意图并请求路由后显示" />
        <div v-if="routing?.estimated_metric" class="json-block">
          <h4>estimated_metric</h4>
          <pre>{{ formatJson(routing.estimated_metric) }}</pre>
        </div>
        <div class="actions">
          <el-button :disabled="!canConfirm" @click="confirmIntent">确认意图</el-button>
          <el-button :disabled="!canRequestRouting" @click="requestRouting">请求路由</el-button>
          <el-button type="success" :disabled="!canSubmit" @click="submitTask">确认提交</el-button>
        </div>
      </el-card>
    </aside>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { conversationApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const conversations = ref([])
const conversation = ref(null)
const utterance = ref('')
const loading = ref(false)
const messagesRef = ref(null)
let routingTimer = null

const draft = computed(() => conversation.value?.latest_draft || null)
const routing = computed(() => conversation.value?.latest_routing_request || null)
const canConfirm = computed(() => draft.value && ['incomplete', 'valid'].includes(draft.value.parse_status))
const canRequestRouting = computed(() => conversation.value?.status === 'awaiting_routing')
const canSubmit = computed(() => conversation.value?.status === 'ready_to_submit')

function formatObjective(objective) {
  if (!objective?.metric_key) return '-'
  return `${objective.metric_key} ${objective.operator || '<='} ${objective.target_value}${objective.unit || ''}`
}

function formatJson(value) {
  return JSON.stringify(value || {}, null, 2)
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
  const { data } = await conversationApi.confirmIntent(conversation.value.id)
  conversation.value = data
  await refreshList()
  ElMessage.success('意图已确认，可请求路由')
}

async function requestRouting() {
  await conversationApi.createRoutingRequest({
    conversation_id: conversation.value.id,
    strategy: 'completion_time_first',
  })
  await refreshConversation()
  ElMessage.info('已发起路由请求，等待外部路由系统回调')
}

async function submitTask() {
  const { data: result } = await conversationApi.submit(conversation.value.id, { auto_start: false })
  await refreshConversation()
  ElMessage.success(`任务已提交，instance_id=${result.instance_id}`)
}

function updateRoutingPolling() {
  stopRoutingPolling()
  if (routing.value?.status === 'pending') {
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
