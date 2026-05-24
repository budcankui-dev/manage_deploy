<template>
  <div class="template-detail">
    <header class="page-header">
      <div class="title-section">
        <el-button text @click="$router.back()">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <h1>{{ template?.name || '拓扑详情' }}</h1>
      </div>
      <div class="header-actions">
        <el-button @click="editTemplate">
          <el-icon><Edit /></el-icon>
          编辑
        </el-button>
        <el-button type="danger" plain @click="confirmDeleteTemplate">删除</el-button>
        <el-button type="primary" @click="showLaunchDialog = true">创建实例</el-button>
      </div>
    </header>

    <div class="detail-grid" v-if="template">
      <div class="info-section">
        <h2>模板信息</h2>
        <p class="description">{{ template.description || '暂无描述' }}</p>
        <div class="meta">
          <span>创建于 {{ formatDate(template.created_at) }}</span>
          <span>{{ template.nodes?.length || 0 }} 个节点</span>
          <span>{{ template.edges?.length || 0 }} 条依赖</span>
        </div>
      </div>

      <div class="nodes-section">
        <h2>拓扑节点</h2>
        <p class="section-hint">运行参数（命令、端口等）在创建任务实例时填写</p>
        <div class="nodes-list">
          <div v-for="node in template.nodes" :key="node.id" class="node-card">
            <div class="node-header">
              <span class="node-name">{{ node.name }}</span>
              <span v-if="node.image" class="node-image mono">{{ node.image }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="edges-section">
        <h2>依赖关系</h2>
        <div class="edges-list">
          <div v-for="edge in template.edges" :key="edge.id" class="edge-item">
            <span class="edge-node">{{ getNodeName(edge.from_node_id) }}</span>
            <el-icon><Right /></el-icon>
            <span class="edge-node">{{ getNodeName(edge.to_node_id) }}</span>
          </div>
          <div v-if="!template.edges?.length" class="no-edges">未定义依赖关系</div>
        </div>
      </div>
    </div>

    <el-dialog v-model="showLaunchDialog" title="创建任务实例" width="400px">
      <el-form :model="launchForm" label-position="top">
        <el-form-item label="实例名称" required>
          <el-input v-model="launchForm.name" placeholder="task-001" />
        </el-form-item>
        <el-form-item label="创建方式" required>
          <el-radio-group v-model="launchForm.mode">
            <el-radio label="immediate">立即创建</el-radio>
            <el-radio label="scheduled">定时调度</el-radio>
          </el-radio-group>
        </el-form-item>
        <template v-if="launchForm.mode === 'scheduled'">
          <el-form-item label="计划启动时间 (UTC+8)" required>
            <el-date-picker
              v-model="launchForm.scheduled_start_time"
              type="datetime"
              placeholder="选择日期和时间"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="计划停止时间 (UTC+8)">
            <el-date-picker
              v-model="launchForm.scheduled_end_time"
              type="datetime"
              placeholder="可选"
              style="width: 100%"
            />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="showLaunchDialog = false">取消</el-button>
        <el-button type="primary" @click="submitLaunch" :loading="launching">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTemplatesStore } from '@/stores/templates'
import { useInstancesStore } from '@/stores/instances'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'

dayjs.extend(relativeTime)
dayjs.extend(utc)

const route = useRoute()
const router = useRouter()
const templatesStore = useTemplatesStore()
const instancesStore = useInstancesStore()

const template = ref(null)
const showLaunchDialog = ref(false)
const launching = ref(false)
const launchForm = ref({
  name: '',
  mode: 'immediate',
  scheduled_start_time: null,
  scheduled_end_time: null,
})

onMounted(async () => {
  const id = route.params.id
  template.value = await templatesStore.fetchTemplate(id)
})

function getNodeName(nodeId) {
  const node = template.value?.nodes?.find(n => n.id === nodeId)
  return node?.name || nodeId?.substring(0, 8) || '未知节点'
}

function editTemplate() {
  if (!template.value?.id) return
  router.push({
    path: '/templates',
    query: { edit: template.value.id },
  })
}

async function submitLaunch() {
  if (!launchForm.value.name) {
    ElMessage.error('实例名称不能为空')
    return
  }
  if (launchForm.value.mode === 'scheduled' && !launchForm.value.scheduled_start_time) {
    ElMessage.error('请选择计划启动时间')
    return
  }
  launching.value = true
  try {
    const instance = await instancesStore.createInstance({
      name: launchForm.value.name,
      template_id: template.value.id
    })
    if (launchForm.value.mode === 'scheduled') {
      await instancesStore.scheduleInstance(instance.id, {
        scheduled_start_time: launchForm.value.scheduled_start_time,
        scheduled_end_time: launchForm.value.scheduled_end_time,
      })
      ElMessage.success('实例已创建并加入定时调度')
    } else {
      ElMessage.success('实例已创建')
    }
    showLaunchDialog.value = false
    launchForm.value = {
      name: '',
      mode: 'immediate',
      scheduled_start_time: null,
      scheduled_end_time: null,
    }
    router.push('/instances')
  } finally {
    launching.value = false
  }
}

async function confirmDeleteTemplate() {
  if (!template.value?.id) return
  try {
    await ElMessageBox.confirm(
      `确认删除模板“${template.value.name}”吗？此操作不可撤销。`,
      '删除模板',
      { type: 'warning' }
    )
    await templatesStore.deleteTemplate(template.value.id)
    ElMessage.success('模板已删除')
    router.push('/templates')
  } catch {
    // Cancelled
  }
}

function formatDate(date) {
  return date ? dayjs.utc(date).local().fromNow() : '-'
}

function formatHealthCheck(type) {
  const labels = {
    port: '端口',
    http: 'HTTP',
    log: '日志',
    container: '容器',
  }
  return labels[type] || '无'
}
</script>

<style scoped>
.template-detail { max-width: 1000px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; }
.title-section { display: flex; align-items: center; gap: 16px; }
.title-section h1 { font-size: 24px; font-weight: 600; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.detail-grid h2 { font-size: 14px; font-weight: 600; color: var(--text-secondary); margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.05em; }
.info-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.description { color: var(--text-secondary); margin-bottom: 16px; line-height: 1.6; }
.meta { display: flex; gap: 20px; font-size: 12px; color: var(--text-muted); padding-top: 16px; border-top: 1px solid var(--border-subtle); }
.nodes-section { grid-column: span 2; background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.section-hint { color: var(--text-secondary); font-size: 13px; margin: -8px 0 16px; }
.nodes-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.node-card { background: var(--bg-tertiary); border-radius: 12px; padding: 16px; border: 1px solid var(--border-subtle); }
.node-header { display: flex; justify-content: space-between; align-items: center; }
.node-name { font-weight: 600; font-size: 14px; }
.node-image { font-size: 11px; color: var(--text-muted); }
.node-image.mono { font-family: 'JetBrains Mono', monospace; }
.node-details { display: flex; flex-direction: column; gap: 8px; }
.detail { display: flex; justify-content: space-between; font-size: 12px; }
.detail .label { color: var(--text-muted); }
.detail .value { color: var(--text-secondary); }
.detail .value.mono { font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.edges-section { background: var(--bg-secondary); border-radius: 16px; padding: 24px; border: 1px solid var(--border-subtle); }
.edges-list { display: flex; flex-direction: column; gap: 8px; }
.edge-item { display: flex; align-items: center; gap: 12px; padding: 12px; background: var(--bg-tertiary); border-radius: 10px; font-size: 13px; }
.edge-node { font-weight: 500; }
.no-edges { color: var(--text-muted); text-align: center; padding: 20px; }
</style>
