<template>
  <div class="instance-detail">
    <header class="page-header">
      <div class="title-section">
        <el-button text @click="$router.back()">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <h1>{{ instance?.name || '实例详情' }}</h1>
        <span class="status-badge" :class="instance?.status">{{ formatStatus(instance?.status) }}</span>
      </div>
      <div class="header-actions">
        <template v-if="instance?.status === 'running'">
          <el-button @click="handleStop">
            <el-icon><VideoPause /></el-icon>
            停止
          </el-button>
          <el-button @click="handleRestart">
            <el-icon><RefreshRight /></el-icon>
            重启
          </el-button>
        </template>
        <el-button
          v-else-if="instance?.status === 'pending' || instance?.status === 'stopped' || instance?.status === 'failed'"
          type="primary"
          @click="handleStart"
        >
          <el-icon><VideoPlay /></el-icon>
          启动
        </el-button>
        <el-tooltip
          v-else-if="instance?.status === 'scheduled'"
          content="该任务已设置定时调度，将在计划时间自动启动"
          placement="bottom"
        >
          <el-button disabled>
            <el-icon><Clock /></el-icon>
            等待调度
          </el-button>
        </el-tooltip>
      </div>
    </header>

    <div class="detail-grid" v-if="instance">
      <el-alert
        v-if="instance.status === 'scheduled' && instance.scheduled_start_time"
        :title="`该实例已进入定时调度，将于 ${formatUtc8Time(instance.scheduled_start_time)} 自动启动。`"
        type="info"
        :closable="false"
        show-icon
      />
      <div class="dag-section">
        <h2>任务图</h2>
        <div class="dag-canvas">
          <svg :width="dagWidth" height="300" ref="dagSvg">
            <defs>
              <marker id="arrowhead-detail" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="var(--text-muted)" />
              </marker>
            </defs>
            <g v-for="(node, i) in layoutNodes" :key="node.id">
              <rect
                :x="node.x - 50"
                :y="node.y - 25"
                width="100"
                height="50"
                rx="10"
                :fill="getNodeBgColor(node.status)"
                :stroke="getNodeBorderColor(node.status)"
                stroke-width="2"
              />
              <text :x="node.x" :y="node.y - 5" text-anchor="middle" fill="var(--text-primary)" font-size="12" font-weight="600">
                {{ node.name }}
              </text>
              <text :x="node.x" :y="node.y + 12" text-anchor="middle" fill="var(--text-muted)" font-size="10">
                {{ formatStatus(node.status) }}
              </text>
            </g>
          </svg>
        </div>
      </div>

      <div class="nodes-section">
        <h2>节点</h2>
        <div class="nodes-list">
          <div v-for="node in instance.nodes" :key="node.id" class="node-detail-card" :class="node.status">
            <div class="node-header">
              <span class="node-name">{{ node.name }}</span>
              <span class="node-status" :class="node.status">{{ formatStatus(node.status) }}</span>
            </div>
            <div class="node-info">
              <div class="info-row">
                <span class="label">镜像</span>
                <span class="value mono">{{ node.image }}</span>
              </div>
              <div class="info-row">
                <span class="label">命令</span>
                <span class="value mono">{{ node.command || '-' }}</span>
              </div>
              <div class="info-row" v-if="node.container_id">
                <span class="label">容器</span>
                <span class="value mono">{{ node.container_id.substring(0, 12) }}</span>
              </div>
            </div>
            <div class="node-actions">
              <el-button size="small" @click="fetchLogs(node)">
                <el-icon><Document /></el-icon>
                日志
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <div class="schedule-section">
        <h2>定时调度</h2>
        <div class="schedule-form">
          <el-form :model="scheduleForm" label-position="top">
            <el-form-item label="计划启动时间">
              <el-date-picker v-model="scheduleForm.scheduled_start_time" type="datetime" placeholder="选择日期和时间" style="width: 100%" />
            </el-form-item>
            <div v-if="scheduleForm.scheduled_start_time" class="schedule-note">
              当前设置：{{ formatUtc8Time(scheduleForm.scheduled_start_time) }}
            </div>
            <el-form-item label="计划停止时间">
              <el-date-picker v-model="scheduleForm.scheduled_end_time" type="datetime" placeholder="选择日期和时间" style="width: 100%" />
            </el-form-item>
            <div v-if="scheduleForm.scheduled_end_time" class="schedule-note">
              当前设置：{{ formatUtc8Time(scheduleForm.scheduled_end_time) }}
            </div>
            <el-button type="primary" @click="submitSchedule">更新调度</el-button>
          </el-form>
        </div>
      </div>

      <div class="events-section">
        <h2>事件记录</h2>
        <div class="events-list">
          <div v-for="event in events" :key="event.id" class="event-item">
            <span class="event-time">{{ formatTime(event.created_at) }}</span>
            <span class="event-status" :class="event.new_status">{{ formatStatus(event.new_status) }}</span>
            <span class="event-message">{{ event.message || event.event_type }}</span>
          </div>
          <div v-if="!events.length" class="no-events">暂无事件记录</div>
        </div>
      </div>
    </div>

    <el-dialog v-model="showLogs" title="容器日志" width="800px">
      <pre class="logs-content">{{ logs }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useInstancesStore } from '@/stores/instances'
import { instancesApi } from '@/api'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'

dayjs.extend(relativeTime)
dayjs.extend(utc)

const route = useRoute()
const router = useRouter()
const store = useInstancesStore()

const instance = ref(null)
const events = ref([])
const showLogs = ref(false)
const logs = ref('')
const refreshing = ref(false)
let refreshTimer = null

const scheduleForm = ref({
  scheduled_start_time: null,
  scheduled_end_time: null
})

const dagWidth = computed(() => Math.max(400, (instance.value?.nodes?.length || 0) * 150))

const layoutNodes = computed(() => {
  if (!instance.value?.nodes) return []
  const nodes = instance.value.nodes
  const cols = Math.ceil(Math.sqrt(nodes.length))
  return nodes.map((node, i) => ({
    ...node,
    x: 80 + (i % cols) * 150,
    y: 80 + Math.floor(i / cols) * 100
  }))
})

onMounted(async () => {
  await refreshInstanceData()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})

async function refreshInstanceData() {
  const id = route.params.id
  refreshing.value = true
  try {
    instance.value = await store.fetchInstance(id)
    if (instance.value) {
      scheduleForm.value.scheduled_start_time = instance.value.scheduled_start_time
      scheduleForm.value.scheduled_end_time = instance.value.scheduled_end_time
    }
    const { data } = await instancesApi.getEvents(id)
    events.value = data
  } catch (e) {
    console.error('获取实例详情失败', e)
  } finally {
    refreshing.value = false
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(() => {
    refreshInstanceData()
  }, 5000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

async function handleStart() {
  await store.startInstance(instance.value.id)
  await refreshInstanceData()
  ElMessage.success('实例已启动')
}

async function handleStop() {
  await store.stopInstance(instance.value.id)
  await refreshInstanceData()
  ElMessage.success('实例已停止')
}

async function handleRestart() {
  await store.restartInstance(instance.value.id)
  await refreshInstanceData()
  ElMessage.success('实例已重启')
}

async function submitSchedule() {
  await store.scheduleInstance(instance.value.id, scheduleForm.value)
  await refreshInstanceData()
  ElMessage.success('调度已更新')
}

async function fetchLogs(node) {
  try {
    const { data } = await instancesApi.getNodeLogs(instance.value.id, node.id)
    logs.value = data.logs || '暂无日志'
    showLogs.value = true
  } catch (e) {
    ElMessage.error('获取日志失败')
  }
}

function parseApiTime(value) {
  return value ? dayjs.utc(value) : null
}

function formatTime(time) {
  const parsed = parseApiTime(time)
  return parsed ? parsed.local().fromNow() : '-'
}

function formatUtc8Time(time) {
  const parsed = parseApiTime(time)
  return parsed ? `${parsed.utcOffset(8).format('YYYY-MM-DD HH:mm:ss')} (UTC+8)` : '-'
}

function getNodeBgColor(status) {
  const colors = {
    pending: 'var(--bg-tertiary)',
    starting: 'rgba(245, 158, 11, 0.15)',
    running: 'rgba(59, 130, 246, 0.15)',
    ready: 'rgba(34, 197, 94, 0.15)',
    stopping: 'rgba(245, 158, 11, 0.15)',
    stopped: 'var(--bg-tertiary)',
    failed: 'rgba(239, 68, 68, 0.15)'
  }
  return colors[status] || 'var(--bg-tertiary)'
}

function getNodeBorderColor(status) {
  const colors = {
    pending: 'var(--border-subtle)',
    starting: 'var(--warning)',
    running: 'var(--info)',
    ready: 'var(--success)',
    stopping: 'var(--warning)',
    stopped: 'var(--border-subtle)',
    failed: 'var(--danger)'
  }
  return colors[status] || 'var(--border-subtle)'
}

function formatStatus(status) {
  const labels = {
    pending: '待启动',
    scheduled: '已调度',
    starting: '启动中',
    running: '运行中',
    ready: '就绪',
    stopping: '停止中',
    stopped: '已停止',
    failed: '失败',
    expired: '已过期'
  }
  return labels[status] || status
}
</script>

<style scoped>
.instance-detail { max-width: 1200px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; }
.title-section { display: flex; align-items: center; gap: 16px; }
.title-section h1 { font-size: 24px; font-weight: 600; }
.status-badge { font-size: 12px; padding: 4px 12px; border-radius: 12px; font-weight: 500; text-transform: capitalize; }
.status-badge.running { background: rgba(59, 130, 246, 0.15); color: var(--info); }
.status-badge.failed { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
.status-badge.stopped { background: rgba(34, 197, 94, 0.15); color: var(--success); }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.detail-grid h2 { font-size: 14px; font-weight: 600; color: var(--text-secondary); margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.05em; }
.dag-section { grid-column: span 2; background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.dag-canvas { background: var(--bg-tertiary); border-radius: 12px; padding: 16px; }
.nodes-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.nodes-list { display: flex; flex-direction: column; gap: 12px; }
.node-detail-card { background: var(--bg-tertiary); border-radius: 12px; padding: 16px; border: 1px solid var(--border-subtle); }
.node-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.node-name { font-weight: 600; font-size: 14px; }
.node-status { font-size: 11px; padding: 2px 8px; border-radius: 8px; text-transform: capitalize; }
.node-status.running { background: rgba(59, 130, 246, 0.15); color: var(--info); }
.node-status.failed { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
.node-status.ready { background: rgba(34, 197, 94, 0.15); color: var(--success); }
.node-info { display: flex; flex-direction: column; gap: 8px; }
.info-row { display: flex; justify-content: space-between; font-size: 12px; }
.info-row .label { color: var(--text-muted); }
.info-row .value { color: var(--text-secondary); }
.info-row .value.mono { font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.node-actions { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-subtle); }
.schedule-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.schedule-form { margin-top: 16px; }
.schedule-note { margin: -6px 0 12px; font-size: 12px; color: var(--text-muted); }
.events-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.events-list { display: flex; flex-direction: column; gap: 8px; max-height: 300px; overflow-y: auto; }
.event-item { display: flex; align-items: center; gap: 12px; font-size: 12px; padding: 8px; background: var(--bg-tertiary); border-radius: 8px; }
.event-time { color: var(--text-muted); }
.event-status { padding: 2px 8px; border-radius: 6px; font-size: 10px; text-transform: capitalize; }
.event-status.running { background: rgba(59, 130, 246, 0.15); color: var(--info); }
.event-status.failed { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
.event-message { color: var(--text-secondary); flex: 1; }
.no-events { color: var(--text-muted); text-align: center; padding: 24px; }
.logs-content { background: var(--bg-primary); padding: 16px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 11px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; color: var(--text-secondary); }
</style>
