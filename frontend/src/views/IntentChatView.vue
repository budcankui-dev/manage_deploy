<template>
  <div class="intent-view">
    <header class="page-header">
      <div>
        <h1>意图解析对话</h1>
        <p class="subtitle">输入自然语言需求，右侧实时查看解析结果、路由与部署参数。</p>
      </div>
      <el-button type="primary" @click="startNewConversation">新建对话</el-button>
    </header>

    <div class="layout">
      <section class="chat-panel">
        <el-card class="panel-card">
          <template #header>对话</template>
          <div class="messages" ref="messagesRef">
            <div
              v-for="message in conversation?.messages || []"
              :key="message.id"
              class="message"
              :class="message.role"
            >
              <strong>{{ message.role === 'user' ? '我' : '助手' }}</strong>
              <p>{{ message.content }}</p>
            </div>
          </div>
          <el-input
            v-model="utterance"
            type="textarea"
            :rows="4"
            placeholder="例如：部署低时延视频转发，720p H264，端到端时延低于 200ms"
            @keydown.ctrl.enter="sendMessage"
          />
          <div class="actions">
            <el-button type="primary" :loading="loading" @click="sendMessage">发送</el-button>
          </div>
        </el-card>
      </section>

      <section class="detail-panel">
        <el-card class="panel-card">
          <template #header>解析结果</template>
          <el-descriptions v-if="draft" :column="1" border size="small">
            <el-descriptions-item label="状态">{{ conversation?.status }}</el-descriptions-item>
            <el-descriptions-item label="任务类型">{{ draft.task_type || '-' }}</el-descriptions-item>
            <el-descriptions-item label="模态">{{ draft.modality || '-' }}</el-descriptions-item>
            <el-descriptions-item label="解析状态">{{ draft.parse_status }}</el-descriptions-item>
            <el-descriptions-item label="业务目标">
              {{ formatObjective(draft.business_objective) }}
            </el-descriptions-item>
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
            <pre>{{ JSON.stringify(draft.data_profile || {}, null, 2) }}</pre>
            <h4>runtime_plan</h4>
            <pre>{{ JSON.stringify(draft.runtime_plan || {}, null, 2) }}</pre>
          </div>
        </el-card>

        <el-card class="panel-card">
          <template #header>路由与部署</template>
          <el-descriptions v-if="routing" :column="1" border size="small">
            <el-descriptions-item label="策略">{{ routing.strategy }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ routing.status }}</el-descriptions-item>
            <el-descriptions-item label="source">{{ routing.placements?.source || '-' }}</el-descriptions-item>
            <el-descriptions-item label="compute">{{ routing.placements?.compute || '-' }}</el-descriptions-item>
            <el-descriptions-item label="sink">{{ routing.placements?.sink || '-' }}</el-descriptions-item>
          </el-descriptions>
          <el-empty v-else description="确认意图并请求路由后显示" />

          <div class="actions">
            <el-button :disabled="!canConfirm" @click="confirmIntent">确认意图</el-button>
            <el-button :disabled="!canRequestRouting" @click="requestRouting">请求路由</el-button>
            <el-button type="success" :disabled="!canSubmit" @click="submitTask">确认提交</el-button>
          </div>
        </el-card>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { conversationApi } from '@/api'

const conversation = ref(null)
const utterance = ref('')
const loading = ref(false)
const messagesRef = ref(null)

const draft = computed(() => conversation.value?.latest_draft || null)
const routing = computed(() => conversation.value?.latest_routing_request || null)
const canConfirm = computed(() => draft.value && ['incomplete', 'valid'].includes(draft.value.parse_status))
const canRequestRouting = computed(() => conversation.value?.status === 'awaiting_routing')
const canSubmit = computed(() => conversation.value?.status === 'ready_to_submit')

function formatObjective(objective) {
  if (!objective?.metric_key) return '-'
  return `${objective.metric_key} ${objective.operator || '<='} ${objective.target_value}${objective.unit || ''}`
}

async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

async function refreshConversation() {
  if (!conversation.value?.id) return
  const { data } = await conversationApi.get(conversation.value.id)
  conversation.value = data
  await scrollToBottom()
}

async function startNewConversation() {
  const { data } = await conversationApi.create({})
  conversation.value = data
  utterance.value = ''
}

async function sendMessage() {
  if (!utterance.value.trim()) return
  loading.value = true
  try {
    if (!conversation.value?.id) {
      await startNewConversation()
    }
    const { data } = await conversationApi.sendMessage(conversation.value.id, {
      content: utterance.value.trim()
    })
    conversation.value = data
    utterance.value = ''
    await scrollToBottom()
  } finally {
    loading.value = false
  }
}

async function confirmIntent() {
  const { data } = await conversationApi.confirmIntent(conversation.value.id)
  conversation.value = data
  ElMessage.success('意图已确认，可请求路由')
}

async function requestRouting() {
  await conversationApi.createRoutingRequest({
    conversation_id: conversation.value.id,
    strategy: 'completion_time_first'
  })
  await refreshConversation()
  ElMessage.info('已发起路由请求，等待外部路由系统回调')
}

async function submitTask() {
  const { data: result } = await conversationApi.submit(conversation.value.id, { auto_start: false })
  await refreshConversation()
  ElMessage.success(`任务已提交，instance_id=${result.instance_id}`)
}

onMounted(async () => {
  await startNewConversation()
})
</script>

<style scoped>
.intent-view {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.subtitle {
  color: var(--text-secondary);
}

.layout {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 16px;
}

.panel-card {
  margin-bottom: 16px;
}

.messages {
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.message {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.message.user {
  background: rgba(64, 158, 255, 0.12);
}

.message p {
  margin: 6px 0 0;
  white-space: pre-wrap;
}

.actions {
  margin-top: 12px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.errors {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.json-block pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--el-fill-color-light);
  padding: 10px;
  border-radius: 6px;
}

@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
