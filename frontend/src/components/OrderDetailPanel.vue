<template>
  <div class="order-detail-panel">
    <el-empty v-if="!detail" description="请选择一个工单查看详情" :image-size="80" />
    <template v-else>
      <section class="overview-card">
        <div>
          <p class="eyebrow">工单详情</p>
          <h2>{{ detail.name || shortId(detail.id) }}</h2>
          <p class="summary">{{ taskSummary }}</p>
        </div>
        <div class="overview-tags">
          <el-tag :type="orderStatusType(detail.status)" size="large">{{ orderStatusLabel(detail.status) }}</el-tag>
          <el-tag v-if="businessTask?.modality" type="success" effect="plain" size="large">
            {{ modalityLabel(businessTask.modality) }}
          </el-tag>
          <el-tag v-if="businessPriorityText !== '-'" type="primary" effect="plain" size="large">
            优先级 {{ businessPriorityText }}
          </el-tag>
          <el-tag v-if="detail.is_benchmark" type="warning" effect="plain" size="large">验收测评工单</el-tag>
        </div>
      </section>

      <el-tabs v-model="tab" class="detail-tabs">
        <el-tab-pane label="业务" name="business">
          <el-descriptions :column="2" border class="detail-desc">
            <el-descriptions-item label="工单 ID"><code>{{ detail.id }}</code></el-descriptions-item>
            <el-descriptions-item label="外部任务 ID">{{ detail.external_task_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="任务类型">{{ taskTypeLabel(taskType) }}</el-descriptions-item>
            <el-descriptions-item label="所属模态">{{ modalityLabel(businessTask?.modality) }}</el-descriptions-item>
            <el-descriptions-item label="业务优先级">{{ businessPriorityText }}</el-descriptions-item>
            <el-descriptions-item label="所属用户">{{ detail.owner_username || detail.owner_user_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="业务源节点">{{ detail.source_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="业务目的节点">{{ detail.destination_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="开始时间">{{ formatTime(detail.business_start_time || detail.scheduled_start_time) }}</el-descriptions-item>
            <el-descriptions-item label="结束时间">{{ formatTime(detail.business_end_time || detail.scheduled_end_time) }}</el-descriptions-item>
          </el-descriptions>

          <h3 class="section-title">数据画像</h3>
          <el-descriptions v-if="dataProfileRows.length" :column="1" border class="detail-desc">
            <el-descriptions-item v-for="row in dataProfileRows" :key="row.label" :label="row.label">
              {{ row.value }}
            </el-descriptions-item>
          </el-descriptions>

          <h3 class="section-title">业务目标</h3>
          <div class="objective-card">
            <p class="objective-headline">{{ objectiveSentence }}</p>
            <p class="objective-meaning">{{ objectiveMeaning }}</p>
          </div>

          <h3 class="section-title">运行计划</h3>
          <el-descriptions v-if="runtimePlanRows.length" :column="1" border class="detail-desc">
            <el-descriptions-item v-for="row in runtimePlanRows" :key="row.label" :label="row.label">
              {{ row.value }}
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>

        <el-tab-pane label="路由" name="routing">
          <el-descriptions :column="2" border class="detail-desc">
            <el-descriptions-item label="路由状态">{{ routingStatusLabel(detail.routing_status) }}</el-descriptions-item>
            <el-descriptions-item label="路由策略">{{ routingPolicyLabel(routingResult?.strategy || routingResult?.selected_strategy || detail.routing_policy) }}</el-descriptions-item>
            <el-descriptions-item label="所属模态">{{ modalityLabel(businessTask?.modality) }}</el-descriptions-item>
            <el-descriptions-item label="网络确认">{{ networkReadyText }}</el-descriptions-item>
          </el-descriptions>

          <h3 class="section-title">节点放置与端口</h3>
          <el-table :data="placementRows" size="small" border empty-text="暂无节点放置信息">
            <el-table-column prop="roleLabel" label="子任务" width="110" />
            <el-table-column prop="hostname" label="部署节点" min-width="150" />
            <el-table-column label="业务面地址" min-width="180">
              <template #default="{ row }">
                <code v-if="row.business_address">{{ row.business_address }}</code>
                <span v-else class="muted">未分配或不部署</span>
              </template>
            </el-table-column>
            <el-table-column label="端口" min-width="180">
              <template #default="{ row }">
                <span v-if="row.portText">{{ row.portText }}</span>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="GPU" width="110">
              <template #default="{ row }">
                <span :class="{ 'warning-text': row.requiresGpu && !hasGpuValue(row.gpu) }">
                  {{ gpuDisplay(row) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="statusLabel" label="节点状态" width="110" />
          </el-table>

          <h3 class="section-title">业务链路</h3>
          <el-table :data="networkBindingRows" size="small" border empty-text="路由结果回写后会展示业务链路 IP 和端口">
            <el-table-column label="链路" min-width="160">
              <template #default="{ row }">{{ roleLabel(row.from) }} → {{ roleLabel(row.to) }}</template>
            </el-table-column>
            <el-table-column label="源业务面" min-width="210">
              <template #default="{ row }">
                <span>{{ row.src_host || '-' }}</span>
                <code v-if="row.src_ip">{{ formatHost(row.src_ip) }}</code>
              </template>
            </el-table-column>
            <el-table-column label="目的业务面 IP:端口" min-width="260">
              <template #default="{ row }">
                <span>{{ row.dst_host || '-' }}</span>
                <code v-if="row.dst_ip && row.dst_port">{{ formatHostPort(row.dst_ip, row.dst_port) }}</code>
                <code v-else-if="row.dst_ip">{{ formatHost(row.dst_ip) }}</code>
                <span v-else class="muted">等待端口分配</span>
              </template>
            </el-table-column>
            <el-table-column label="端口名" min-width="160">
              <template #default="{ row }">{{ namedPortsText(row.dst_named_ports) }}</template>
            </el-table-column>
            <el-table-column label="带宽需求" width="120">
              <template #default="{ row }">{{ row.bandwidth_mbps ? `${row.bandwidth_mbps} Mbps` : '-' }}</template>
            </el-table-column>
          </el-table>

          <el-collapse v-if="detail.routing_input_dag || routingResult" class="raw-collapse">
            <el-collapse-item v-if="detail.routing_input_dag" title="提交给路由系统的 DAG JSON" name="routing-input">
              <pre class="json-block">{{ prettyJson(detail.routing_input_dag) }}</pre>
            </el-collapse-item>
            <el-collapse-item v-if="routingResult" title="路由结果原始 JSON" name="routing-result">
              <pre class="json-block">{{ prettyJson(routingResult) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>

        <el-tab-pane label="部署" name="deployment">
          <template v-if="detail.instance">
            <el-descriptions :column="2" border class="detail-desc">
              <el-descriptions-item label="实例 ID"><code>{{ detail.instance.id }}</code></el-descriptions-item>
              <el-descriptions-item label="实例状态">
                <el-tag :type="instanceStatusType(detail.instance.status)" size="small">
                  {{ instanceStatusLabel(detail.instance.status) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="节点数">{{ detail.instance.node_count }}</el-descriptions-item>
              <el-descriptions-item label="错误信息">{{ detail.instance.error_message || '-' }}</el-descriptions-item>
            </el-descriptions>

            <div v-if="$slots['deployment-actions']" class="deployment-actions">
              <slot name="deployment-actions" :instance="detail.instance" />
            </div>
          </template>
          <el-alert v-else title="尚未物化部署实例" type="info" show-icon :closable="false" />

          <h3 class="section-title">部署节点</h3>
          <el-table :data="placementRows" size="small" border empty-text="尚无部署节点">
            <el-table-column prop="roleLabel" label="子任务" width="110" />
            <el-table-column prop="hostname" label="物理节点" min-width="150" />
            <el-table-column prop="instance_node_name" label="实例节点" min-width="120" />
            <el-table-column label="业务面 IP" min-width="180">
              <template #default="{ row }">
                <code v-if="row.business_address">{{ row.business_address }}</code>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="容器端口" min-width="180">
              <template #default="{ row }">{{ row.portText || '-' }}</template>
            </el-table-column>
            <el-table-column label="GPU" width="110">
              <template #default="{ row }">
                <span :class="{ 'warning-text': row.requiresGpu && !hasGpuValue(row.gpu) }">
                  {{ gpuDisplay(row) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="statusLabel" label="状态" width="110" />
          </el-table>

          <h3 class="section-title">端口访问</h3>
          <el-table :data="portAccessRows" size="small" border empty-text="暂无可访问端口">
            <el-table-column prop="nodeName" label="子任务" width="110" />
            <el-table-column prop="portName" label="端口名" width="120" />
            <el-table-column label="业务面访问地址" min-width="260">
              <template #default="{ row }"><code>{{ row.url }}</code></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="结果" name="result">
          <h3 class="section-title">本任务在做什么</h3>
          <p class="task-summary">{{ taskSummary }}</p>
          <ol class="pipeline-steps">
            <li v-for="step in pipelineSteps" :key="step.role">
              <strong>{{ step.role }}</strong> — {{ step.title }}：{{ step.detail }}
            </li>
          </ol>

          <template v-if="isVideoTask">
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
                <el-descriptions v-if="inputRows.length" :column="1" border class="detail-desc">
                  <el-descriptions-item v-for="row in inputRows" :key="row.label" :label="row.label">
                    {{ row.value }}
                  </el-descriptions-item>
                </el-descriptions>
                <h3 class="section-title">推理输出</h3>
                <el-descriptions v-if="outputRows.length" :column="1" border class="detail-desc">
                  <el-descriptions-item v-for="row in outputRows" :key="row.label" :label="row.label">
                    {{ row.value }}
                  </el-descriptions-item>
                </el-descriptions>
              </div>
            </div>
            <h3 v-if="videoDetectionRows.length" class="section-title">分类检测结果</h3>
            <el-table v-if="videoDetectionRows.length" :data="videoDetectionRows" size="small" border>
              <el-table-column label="类别" min-width="140">
                <template #default="{ row }">{{ row.display_label || row.label_zh || row.label || '-' }}</template>
              </el-table-column>
              <el-table-column label="置信度" width="100">
                <template #default="{ row }">{{ Number(row.confidence || 0).toFixed(2) }}</template>
              </el-table-column>
              <el-table-column label="画框坐标" min-width="180">
                <template #default="{ row }">{{ Array.isArray(row.bbox_xyxy) ? row.bbox_xyxy.join(', ') : '-' }}</template>
              </el-table-column>
              <el-table-column label="来源" width="110">
                <template #default="{ row }">
                  <el-tag :type="row.fallback ? 'info' : 'success'" size="small">{{ row.fallback ? '检测结果' : '模型输出' }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </template>

          <template v-else>
            <div class="proof-grid">
              <div>
                <h3 class="section-title">输入参数</h3>
                <el-descriptions v-if="inputRows.length" :column="1" border class="detail-desc">
                  <el-descriptions-item v-for="row in inputRows" :key="row.label" :label="row.label">
                    {{ row.value }}
                  </el-descriptions-item>
                </el-descriptions>
              </div>
              <div>
                <h3 class="section-title">计算输出</h3>
                <el-descriptions v-if="outputRows.length" :column="1" border class="detail-desc">
                  <el-descriptions-item v-for="row in outputRows" :key="row.label" :label="row.label">
                    {{ row.value }}
                  </el-descriptions-item>
                </el-descriptions>
              </div>
            </div>
          </template>

          <div v-if="paramConsistency" class="consistency-row">
            <el-tag :type="paramConsistency.ok ? 'success' : 'warning'" size="small">{{ paramConsistency.label }}</el-tag>
            <span>{{ paramConsistency.detail }}</span>
          </div>
          <div class="result-verdict" :class="verdict.statusClass">
            <strong>{{ verdict.title }}</strong>
            <p>{{ verdict.subtitle }}</p>
          </div>

          <el-collapse v-if="evaluation?.result_metadata || resultObjects.length" class="raw-collapse">
            <el-collapse-item v-if="evaluation?.result_metadata" title="指标采集结果 JSON" name="result-metadata">
              <pre class="json-block">{{ prettyJson(evaluation.result_metadata) }}</pre>
            </el-collapse-item>
            <el-collapse-item v-if="resultObjects.length" title="结果文件 URI" name="result-files">
              <el-table :data="resultObjects" size="small">
                <el-table-column prop="name" label="文件名" />
                <el-table-column prop="uri" label="URI" min-width="260" />
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
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
  taskTypeSummary,
  videoDetectionBoxStyle,
  videoDetections,
  videoPreviewDataUrl,
  videoPreviewEvidenceRows,
  videoPreviewNeedsOverlay,
} from '@/constants/businessTaskDisplay'
import { routingPolicyLabel } from '@/constants/routingPolicy'

const props = defineProps({
  detail: { type: Object, default: null },
  resultObjects: { type: Array, default: () => [] },
  activeTab: { type: String, default: 'business' },
})

const emit = defineEmits(['update:activeTab'])

const tab = computed({
  get: () => props.activeTab || 'business',
  set: (value) => emit('update:activeTab', value),
})

const detail = computed(() => props.detail)
const resultObjects = computed(() => props.resultObjects || [])
const businessTask = computed(() => detail.value?.business_task || null)
const routingResult = computed(() => detail.value?.routing_result || null)
const evaluation = computed(() => detail.value?.evaluation || null)
const resultMetadata = computed(() => evaluation.value?.result_metadata || null)
const taskType = computed(() => businessTask.value?.task_type || detail.value?.task_type || '')
const isMatmulTask = computed(() => taskType.value === 'high_throughput_matmul')
const isVideoTask = computed(() => taskType.value === 'low_latency_video_pipeline')
const taskSummary = computed(() => taskTypeSummary(taskType.value))
const dataProfileRows = computed(() => describeDataProfile(taskType.value, businessTask.value?.data_profile))
const runtimePlanRows = computed(() => describeRuntimePlan(taskType.value, businessTask.value?.runtime_plan))
const objectiveForDisplay = computed(() => {
  const objective = { ...(businessTask.value?.business_objective || {}) }
  if (objective.target_value == null && evaluation.value?.target_value != null) objective.target_value = evaluation.value.target_value
  if (!objective.unit && evaluation.value?.unit) objective.unit = evaluation.value.unit
  if (!objective.metric_key && evaluation.value?.metric_key) objective.metric_key = evaluation.value.metric_key
  if (!objective.operator && evaluation.value?.metric_key === 'frame_latency_p90_ms') objective.operator = '<='
  if (!objective.operator && evaluation.value?.metric_key === 'effective_gflops') objective.operator = '>='
  return objective
})
const objectiveSentence = computed(() => formatObjectiveSentence(objectiveForDisplay.value))
const objectiveMeaning = computed(() => describeObjectiveMeaning(taskType.value, objectiveForDisplay.value))
const pipelineSteps = computed(() => {
  if (isMatmulTask.value) return MATMUL_PIPELINE_STEPS
  if (isVideoTask.value) return VIDEO_PIPELINE_STEPS
  return [
    { role: 'source', title: '提交输入', detail: '准备业务输入并发送给计算节点' },
    { role: 'compute', title: '执行业务', detail: '按路由结果在指定节点执行计算' },
    { role: 'sink', title: '上报结果', detail: '汇总业务指标并回传平台用于判定' },
  ]
})

const nodePlacementRows = computed(() => {
  const rows = Array.isArray(detail.value?.node_placements) ? detail.value.node_placements : []
  return rows.map((row) => normalizePlacementRow(row.role, row))
})

const routingPlacementRows = computed(() => {
  const placements = routingResult.value?.placements
  if (!placements) return []
  const rows = []
  if (Array.isArray(placements)) {
    placements.forEach((placement) => rows.push(normalizePlacementRow(placement.task_node_id || placement.role, placement)))
    return rows
  }
  if (typeof placements === 'object') {
    Object.entries(placements).forEach(([role, placement]) => {
      rows.push(normalizePlacementRow(role, placement))
    })
  }
  return rows
})

const placementRows = computed(() => {
  const byRole = new Map()
  routingPlacementRows.value.forEach((row) => byRole.set(row.roleKey, row))
  nodePlacementRows.value.forEach((row) => byRole.set(row.roleKey, { ...(byRole.get(row.roleKey) || {}), ...row }))
  return Array.from(byRole.values())
})

const networkBindingRows = computed(() => {
  const rows = routingResult.value?.network_bindings
  return Array.isArray(rows) ? rows : []
})

const portAccessRows = computed(() => {
  const rows = []
  const seen = new Set()
  const add = (nodeName, portName, url) => {
    if (!url) return
    const key = `${nodeName}|${portName}|${url}`
    if (seen.has(key)) return
    seen.add(key)
    rows.push({ nodeName: roleLabel(nodeName), portName, url })
  }
  placementRows.value.forEach((row) => {
    Object.entries(row.portAccessUrls || {}).forEach(([portName, url]) => add(row.roleKey, portName, url))
    Object.entries(row.portValues || {}).forEach(([portName, port]) => {
      if (row.business_address) add(row.roleKey, portName, formatHostPort(row.business_address, port))
    })
  })
  Object.entries(detail.value?.instance?.port_access_urls || {}).forEach(([key, url]) => {
    const [nodeName, portName = 'default'] = String(key).split('/')
    add(nodeName, portName, url)
  })
  return rows
})

const inputRows = computed(() => {
  const profile = businessTask.value?.data_profile
  if (isMatmulTask.value) return buildMatmulInputRows(profile)
  if (isVideoTask.value) return buildVideoInputRows(profile)
  return describeDataProfile(taskType.value, profile)
})

const outputRows = computed(() => {
  if (isMatmulTask.value) return buildMatmulOutputRows(resultMetadata.value, evaluation.value)
  if (isVideoTask.value) return buildVideoOutputRows(resultMetadata.value, evaluation.value)
  if (evaluation.value) {
    return [{
      label: '上报指标',
      value: `${evaluation.value.metric_key} = ${formatMetric(evaluation.value.actual_value)} ${evaluation.value.unit || ''}`.trim(),
    }]
  }
  return [{ label: '状态', value: '尚未收到业务输出' }]
})

const paramConsistency = computed(() => {
  if (!isMatmulTask.value) return null
  return buildMatmulParamConsistency(businessTask.value?.data_profile, resultMetadata.value)
})

const verdict = computed(() => {
  if (isMatmulTask.value) return buildMatmulVerdict(evaluation.value)
  if (isVideoTask.value) return buildVideoVerdict(evaluation.value)
  if (!evaluation.value) {
    return {
      title: '等待业务结果',
      subtitle: '任务运行并上报指标后，将在这里展示输入、输出和业务目标判定。',
      statusClass: 'pending',
    }
  }
  return {
    title: evaluation.value.business_success ? '业务已完成，目标达标' : '业务已完成，目标未达标',
    subtitle: evaluation.value.failure_reason || `实际 ${formatMetric(evaluation.value.actual_value)} ${evaluation.value.unit || ''}。`,
    statusClass: evaluation.value.business_success ? 'success' : 'danger',
  }
})

const videoPreview = computed(() => videoPreviewDataUrl(resultMetadata.value))
const videoDetectionRows = computed(() => videoDetections(resultMetadata.value))
const videoEvidenceRows = computed(() => videoPreviewEvidenceRows(resultMetadata.value))
const videoNeedsOverlay = computed(() => videoPreviewNeedsOverlay(resultMetadata.value))
const networkReadyText = computed(() => {
  if (!routingResult.value) return '-'
  if (routingResult.value.network_ready_required && !routingResult.value.network_ready) return '等待外部路由系统确认'
  if (routingResult.value.network_ready_required && routingResult.value.network_ready) return '已确认'
  return '无需额外确认'
})
const businessPriorityText = computed(() => {
  const value = detail.value?.routing_input_dag?.priority
    ?? businessTask.value?.priority
    ?? routingResult.value?.priority
    ?? routingResult.value?.metadata?.priority
  return value === null || value === undefined || value === '' ? '-' : String(value)
})

function normalizePlacementRow(role, placement) {
  const roleKey = String(role || '').toLowerCase() || 'unknown'
  const item = typeof placement === 'string' ? { topology_node_id: placement } : (placement || {})
  const gpu = item.gpu_device ?? item.gpu_id ?? (Array.isArray(item.gpu_indices) ? item.gpu_indices[0] : null)
  const portValues = item.port_values || {}
  const portAccessUrls = item.port_access_urls || {}
  return {
    roleKey,
    roleLabel: roleLabel(roleKey),
    instance_node_name: item.instance_node_name || item.node_name || item.template_node_name || roleKey,
    hostname: item.topology_node_id || item.hostname || item.worker_host || item.node_name || item.node_id || '未部署',
    business_address: item.business_address || item.business_ip || item.business_ipv6 || '',
    gpu,
    requiresGpu: ['compute', 'worker', 'inference'].includes(roleKey) && ['high_throughput_matmul', 'low_latency_video_pipeline'].includes(taskType.value),
    portValues,
    portAccessUrls,
    portText: namedPortsText(portValues),
    statusLabel: nodeStatusLabel(item.status),
  }
}

function roleLabel(value) {
  return {
    source: '数据源',
    compute: '计算',
    worker: '计算',
    inference: '推理',
    sink: '汇总',
  }[String(value || '').toLowerCase()] || value || '-'
}

function formatHost(host) {
  if (!host) return '-'
  const text = String(host)
  return text.includes(':') && !text.startsWith('[') ? `[${text}]` : text
}

function formatHostPort(host, port) {
  if (!host || port == null || port === '') return '-'
  return `${formatHost(host)}:${port}`
}

function namedPortsText(value) {
  if (!value || !Object.keys(value).length) return ''
  return Object.entries(value).map(([name, port]) => `${name}:${port}`).join(' / ')
}

function hasGpuValue(value) {
  return value !== null && value !== undefined && String(value) !== ''
}

function gpuDisplay(row) {
  if (hasGpuValue(row.gpu)) return String(row.gpu)
  return row.requiresGpu ? '未记录' : '不需要'
}

function videoBoxStyle(row) {
  return videoDetectionBoxStyle(row, resultMetadata.value)
}

function shortId(value) {
  return value ? String(value).slice(0, 12) : '-'
}

function prettyJson(value) {
  if (value == null) return '暂无数据'
  return JSON.stringify(value, null, 2)
}

function formatMetric(value) {
  if (value == null) return '-'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(2) : String(value)
}

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function orderStatusLabel(value) {
  return {
    pending: '待路由',
    routing: '路由中',
    routed: '已路由',
    materialized: '已物化',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }[value] || value || '-'
}

function orderStatusType(value) {
  return {
    pending: 'info',
    materialized: 'warning',
    running: 'success',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
  }[value] || 'info'
}

function routingStatusLabel(value) {
  return {
    not_required: '无需路由',
    pending: '待路由',
    computing: '计算中',
    network_binding_ready: '等待网络确认',
    completed: '已完成',
    failed: '失败',
  }[value] || value || '-'
}

function instanceStatusLabel(value) {
  return {
    pending: '待启动',
    scheduled: '已调度',
    starting: '启动中',
    running: '运行中',
    stopping: '停止中',
    stopped: '已停止',
    failed: '失败',
    expired: '已过期',
  }[value] || value || '-'
}

function instanceStatusType(value) {
  return {
    running: 'success',
    stopped: 'info',
    failed: 'danger',
    starting: 'warning',
    scheduled: 'info',
    pending: 'info',
  }[value] || 'info'
}

function nodeStatusLabel(value) {
  return {
    pending: '待启动',
    starting: '启动中',
    running: '运行中',
    ready: '就绪',
    stopping: '停止中',
    stopped: '已停止',
    failed: '失败',
  }[value] || value || '-'
}
</script>

<style scoped>
.order-detail-panel {
  min-height: 240px;
}

.overview-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  margin-bottom: 16px;
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 14px;
  background: linear-gradient(135deg, #f8fbff 0%, #f6faf6 100%);
}

.overview-card h2 {
  margin: 0 0 6px;
  font-size: 20px;
  color: var(--text-primary, #1f2937);
}

.eyebrow {
  margin: 0 0 4px;
  color: #1f7a5f;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.summary,
.task-summary {
  margin: 0;
  color: var(--text-secondary, #607085);
  line-height: 1.6;
}

.overview-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-content: flex-start;
  gap: 8px;
}

.section-title {
  margin: 18px 0 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #1f2937);
}

.detail-desc {
  margin-bottom: 8px;
}

.objective-card,
.result-verdict {
  padding: 14px 16px;
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 12px;
  background: var(--bg-tertiary, #f8fafc);
}

.objective-headline,
.result-verdict strong {
  display: block;
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary, #1f2937);
}

.objective-meaning,
.result-verdict p {
  margin: 0;
  color: var(--text-secondary, #607085);
  line-height: 1.6;
}

.deployment-actions {
  display: flex;
  gap: 8px;
  margin: 12px 0;
}

.pipeline-steps {
  margin: 0 0 16px;
  padding-left: 20px;
  color: var(--text-secondary, #607085);
  line-height: 1.75;
  font-size: 13px;
}

.pipeline-steps strong {
  color: var(--accent-secondary, #2563eb);
  text-transform: uppercase;
  font-size: 12px;
}

.proof-grid,
.video-result-card {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  align-items: start;
}

.video-preview {
  min-height: 220px;
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 12px;
  background: var(--bg-tertiary, #f8fafc);
  overflow: hidden;
}

.video-proof-frame {
  position: relative;
}

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

.consistency-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: 12px 0;
  color: var(--text-secondary, #607085);
  font-size: 13px;
}

.result-verdict {
  margin-top: 14px;
}

.result-verdict.success {
  border-color: rgba(34, 197, 94, 0.35);
  background: rgba(34, 197, 94, 0.08);
}

.result-verdict.danger {
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.08);
}

.result-verdict.pending {
  border-color: rgba(59, 130, 246, 0.35);
  background: rgba(59, 130, 246, 0.08);
}

.raw-collapse {
  margin-top: 14px;
}

.json-block {
  max-height: 360px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-tertiary, #f8fafc);
  color: var(--text-secondary, #607085);
  font-size: 12px;
  line-height: 1.5;
}

.muted {
  color: var(--text-muted, #8b95a1);
}

.warning-text {
  color: var(--el-color-warning);
  font-weight: 700;
}

code {
  font-size: 12px;
}
</style>
