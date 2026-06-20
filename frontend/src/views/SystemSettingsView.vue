<template>
  <div class="settings-page">
    <section class="settings-hero">
      <div>
        <p class="eyebrow">系统设置</p>
        <h1>运行配置与系统参数</h1>
        <p>
          在这里统一管理意图解析、业务测评路由方式、页面展示和模态优先级。
          业务页面只展示运行入口、结果和工单证据，配置项集中放在后台维护。
        </p>
      </div>
      <el-tag size="large" type="success">{{ settings.labels?.environment_mode || '标准模式' }}</el-tag>
    </section>

    <el-card class="settings-card" v-loading="loading">
      <template #header>
        <div class="card-header">
          <span>运行配置</span>
          <el-button type="primary" :loading="saving" @click="saveSettings">保存设置</el-button>
        </div>
      </template>

      <el-form label-position="top" class="settings-form">
        <el-form-item label="配置分组">
          <el-radio-group v-model="form.environment_mode">
            <el-radio-button label="production">标准模式</el-radio-button>
            <el-radio-button label="development">联调模式</el-radio-button>
          </el-radio-group>
          <p class="form-hint">
            配置分组仅用于标记当前运行场景；实际链路由下方解析方式、路由方式和展示开关控制。
          </p>
        </el-form-item>

        <div class="setting-grid">
          <el-card shadow="never" class="mode-card">
            <h3>意图解析</h3>
            <el-radio-group v-model="form.intent_parser_mode" class="vertical-radio">
              <el-radio label="llm">大模型/智能体解析</el-radio>
              <el-radio label="rule">系统解析流程</el-radio>
            </el-radio-group>
            <el-checkbox v-model="form.intent_rule_fallback_enabled">
              主解析不可用时允许系统解析流程继续处理
            </el-checkbox>
            <p class="form-hint">
              意图测评页统一展示“意图参数解析准确率”。该设置会影响用户端对话解析和管理端单条解析。
            </p>
          </el-card>

          <el-card shadow="never" class="mode-card">
            <h3>业务测评路由</h3>
            <el-radio-group v-model="form.benchmark_routing_mode" class="vertical-radio">
              <el-radio label="internal_auto">系统自动分配</el-radio>
              <el-radio label="external">外部路由系统</el-radio>
            </el-radio-group>
            <p class="form-hint">
              系统自动分配由平台完成节点放置；外部路由系统由对接服务回写节点和 GPU 分配结果。
              业务测评页只展示统一的“运行测评”入口，由系统按当前配置执行。
            </p>
          </el-card>

          <el-card shadow="never" class="mode-card">
            <h3>业务测评执行</h3>
            <div class="execution-defaults">
              <label>
                <span>默认并发任务数</span>
                <el-input-number
                  v-model="form.benchmark_execution_defaults.max_parallel"
                  :min="1"
                  :max="10"
                  controls-position="right"
                />
              </label>
            </div>
            <p class="form-hint">
              业务测评页默认使用该并发数分批执行；系统会按节点资源、路由结果和当前占用情况自动等待，避免资源争用影响基线判定。
            </p>
          </el-card>

          <el-card shadow="never" class="mode-card">
            <h3>页面展示</h3>
            <el-switch
              v-model="form.expert_mode"
              active-text="简洁展示视图"
              inactive-text="详细展示视图"
            />
            <el-checkbox v-model="form.show_internal_controls">
              显示高级控制项
            </el-checkbox>
            <el-checkbox v-model="form.show_routing_dag_json">
              显示 DAG JSON 详情
            </el-checkbox>
            <p class="form-hint">
              默认关闭。开启后会在任务工单详情的“节点分配”、业务测评工单详情、意图测评单条检测中显示原始 DAG/分配 JSON；常规演示建议保持关闭，只展示参数、节点、端口和业务结果。
            </p>
          </el-card>
        </div>

        <el-card shadow="never" class="priority-card">
          <template #header>
            <div class="priority-header">
              <span>模态优先级字典</span>
              <el-tag type="info" effect="plain">1 最高，8 最低</el-tag>
            </div>
          </template>
          <p class="form-hint priority-hint">
            该优先级会写入提交给外部路由系统的 DAG 顶层 priority 字段，并同步写入链路 flow.priority，供路由系统做业务流优先级或 QoS 策略参考。
          </p>
          <el-table :data="modalityPriorityRows" size="small" border>
            <el-table-column prop="modality" label="业务模态" min-width="220" />
            <el-table-column label="优先级" width="150">
              <template #default="{ row }">
                <el-input-number
                  v-model="form.modality_priority_map[row.modality]"
                  :min="1"
                  :max="8"
                  :step="1"
                  controls-position="right"
                  size="small"
                />
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="260">
              <template #default="{ row }">{{ modalityPriorityHint(row.modality) }}</template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card shadow="never" class="priority-card">
          <template #header>
            <div class="priority-header">
              <span>任务模态映射</span>
              <el-switch
                v-model="form.task_modality_override_enabled"
                active-text="启用覆盖"
                inactive-text="使用默认"
              />
            </div>
          </template>
          <p class="form-hint priority-hint">
            默认按任务类型映射业务模态；启用覆盖后，以这里的设置为准，并同步影响意图解析结果和提交给路由系统的 DAG 优先级。
          </p>
          <el-table :data="taskModalityRows" size="small" border>
            <el-table-column prop="task_label" label="任务类型" min-width="220" />
            <el-table-column prop="default_modality" label="默认模态" min-width="180" />
            <el-table-column label="指定模态" min-width="220">
              <template #default="{ row }">
                <el-select
                  v-model="form.task_modality_overrides[row.task_type]"
                  :disabled="!form.task_modality_override_enabled"
                  placeholder="默认映射"
                  clearable
                  filterable
                >
                  <el-option
                    v-for="modality in modalityOptions"
                    :key="modality"
                    :label="modality"
                    :value="modality"
                  />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card shadow="never" class="priority-card">
          <template #header>
            <div class="priority-header">
              <span>任务资源要求</span>
              <el-switch
                v-model="form.task_resource_override_enabled"
                active-text="启用覆盖"
                inactive-text="使用默认估算"
              />
            </div>
          </template>
          <p class="form-hint priority-hint">
            默认由系统根据任务类型和参数画像估算。若已通过基线或实测确认更合适的资源需求，可在这里覆盖 source、compute、sink 三类子任务角色的资源值。
          </p>
          <div class="resource-task-list">
            <section
              v-for="task in resourceTaskRows"
              :key="task.task_type"
              class="resource-task-card"
            >
              <div class="resource-task-title">
                <strong>{{ task.task_label }}</strong>
                <span>{{ task.default_note }}</span>
              </div>
              <el-table :data="task.roles" size="small" border>
                <el-table-column prop="role_label" label="子任务角色" width="120" />
                <el-table-column label="CPU" width="120">
                  <template #default="{ row }">
                    <el-input-number
                      v-model="form.task_resource_overrides[task.task_type][row.role].cpu_units"
                      :disabled="!form.task_resource_override_enabled"
                      :min="0"
                      :max="64"
                      size="small"
                      controls-position="right"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="内存 MB" width="140">
                  <template #default="{ row }">
                    <el-input-number
                      v-model="form.task_resource_overrides[task.task_type][row.role].mem_mb"
                      :disabled="!form.task_resource_override_enabled"
                      :min="0"
                      :max="131072"
                      :step="256"
                      size="small"
                      controls-position="right"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="磁盘 MB" width="140">
                  <template #default="{ row }">
                    <el-input-number
                      v-model="form.task_resource_overrides[task.task_type][row.role].disk_mb"
                      :disabled="!form.task_resource_override_enabled"
                      :min="0"
                      :max="1048576"
                      :step="256"
                      size="small"
                      controls-position="right"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="GPU" width="120">
                  <template #default="{ row }">
                    <el-input-number
                      v-model="form.task_resource_overrides[task.task_type][row.role].gpu_units"
                      :disabled="!form.task_resource_override_enabled"
                      :min="0"
                      :max="8"
                      size="small"
                      controls-position="right"
                    />
                  </template>
                </el-table-column>
              </el-table>
            </section>
          </div>
        </el-card>

        <el-form-item label="备注">
          <el-input
            v-model="form.notes"
            type="textarea"
            :rows="3"
            placeholder="记录当前配置说明、联调对象、运行前置条件等"
          />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="settings-card">
      <template #header>
        <span>运行建议</span>
      </template>
      <div class="advice-list">
        <div>
          <strong>业务测评页</strong>
          <span>只展示基线、工单创建、运行测评、成功率统计和任务详情证据，减少与操作无关的信息。</span>
        </div>
        <div>
          <strong>基线差距解释</strong>
          <span>若测试值和旧基线差距很大，优先检查 CPU/GPU 口径、镜像版本、节点旧容器和同 GPU 并发争用。</span>
        </div>
        <div>
          <strong>截图前</strong>
          <span>清理旧测评实例，按当前业务 profile 重跑基线，再创建新的测评轮次，确保截图只对应最新轮次。</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'
import { TASK_TYPE_LABELS } from '@/constants/businessTaskDisplay'

const DEFAULT_MODALITY_PRIORITY_MAP = {
  高通量计算模态: 5,
  低时延转发模态: 1,
  智算中心模态: 4,
  分布式存算模态: 7,
  大规模连接模态: 8,
  确定性转发模态: 2,
  高能效边缘计算模态: 6,
  高安全传输模态: 3,
}

const MODALITY_PRIORITY_HINTS = {
  高通量计算模态: '矩阵计算等吞吐型计算任务。',
  低时延转发模态: '视频 AI 推理、工业检测等低时延业务。',
  智算中心模态: '文本生成、模型训练等 AI 计算业务。',
  分布式存算模态: '分布式存储与计算协同业务。',
  大规模连接模态: '大量终端接入与采集类业务。',
  确定性转发模态: '对抖动和确定性要求更强的业务。',
  高能效边缘计算模态: '边缘侧能耗敏感推理业务。',
  高安全传输模态: '安全隔离和传输可靠性优先业务。',
}

const TASK_MODALITY_DEFAULTS = {
  high_throughput_matmul: '高通量计算模态',
  low_latency_video_pipeline: '低时延转发模态',
  llm_text_generation: '智算中心模态',
  ai_model_training: '智算中心模态',
  distributed_storage_compute: '分布式存算模态',
  massive_connection_collect: '大规模连接模态',
  deterministic_forwarding: '确定性转发模态',
  energy_efficient_edge_inference: '高能效边缘计算模态',
  secure_transmission: '高安全传输模态',
}

const DEFAULT_TASK_RESOURCE_OVERRIDES = {
  high_throughput_matmul: {
    source: { cpu_units: 2, mem_mb: 512, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 8, mem_mb: 1024, disk_mb: 1024, gpu_units: 1 },
    sink: { cpu_units: 2, mem_mb: 512, disk_mb: 512, gpu_units: 0 },
  },
  low_latency_video_pipeline: {
    source: { cpu_units: 2, mem_mb: 512, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 4, mem_mb: 2048, disk_mb: 1024, gpu_units: 1 },
    sink: { cpu_units: 2, mem_mb: 512, disk_mb: 512, gpu_units: 0 },
  },
  llm_text_generation: {
    source: { cpu_units: 2, mem_mb: 512, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 8, mem_mb: 4096, disk_mb: 1024, gpu_units: 1 },
    sink: { cpu_units: 2, mem_mb: 512, disk_mb: 512, gpu_units: 0 },
  },
  ai_model_training: {
    source: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    sink: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
  },
  distributed_storage_compute: {
    source: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    sink: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
  },
  massive_connection_collect: {
    source: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    sink: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
  },
  deterministic_forwarding: {
    source: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    sink: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
  },
  energy_efficient_edge_inference: {
    source: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    sink: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
  },
  secure_transmission: {
    source: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    compute: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
    sink: { cpu_units: 4, mem_mb: 1024, disk_mb: 512, gpu_units: 0 },
  },
}

const DEFAULT_BENCHMARK_EXECUTION_DEFAULTS = {
  default_task_count: 30,
  max_parallel: 3,
  per_compute_slot_limit: 1,
}

const ROLE_ROWS = [
  { role: 'source', role_label: 'source' },
  { role: 'compute', role_label: 'compute' },
  { role: 'sink', role_label: 'sink' },
]

const loading = ref(false)
const saving = ref(false)
const settings = ref({})
const form = reactive({
  environment_mode: 'production',
  intent_parser_mode: 'llm',
  intent_rule_fallback_enabled: true,
  benchmark_routing_mode: 'internal_auto',
  expert_mode: true,
  show_internal_controls: false,
  show_routing_dag_json: false,
  modality_priority_map: { ...DEFAULT_MODALITY_PRIORITY_MAP },
  task_modality_override_enabled: false,
  task_modality_overrides: { ...TASK_MODALITY_DEFAULTS },
  task_resource_override_enabled: false,
  task_resource_overrides: cloneTaskResources(DEFAULT_TASK_RESOURCE_OVERRIDES),
  benchmark_execution_defaults: { ...DEFAULT_BENCHMARK_EXECUTION_DEFAULTS },
  notes: '',
})

const modalityPriorityRows = computed(() => {
  const rows = settings.value?.modality_priority_rows
  if (Array.isArray(rows) && rows.length) return rows
  return Object.entries(DEFAULT_MODALITY_PRIORITY_MAP).map(([modality, priority]) => ({ modality, priority }))
})

const modalityOptions = computed(() => Object.keys(DEFAULT_MODALITY_PRIORITY_MAP))

const taskModalityRows = computed(() => Object.entries(TASK_MODALITY_DEFAULTS).map(([taskType, modality]) => ({
  task_type: taskType,
  task_label: TASK_TYPE_LABELS[taskType] || taskType,
  default_modality: modality,
})))

const resourceTaskRows = computed(() => Object.keys(DEFAULT_TASK_RESOURCE_OVERRIDES).map((taskType) => ({
  task_type: taskType,
  task_label: TASK_TYPE_LABELS[taskType] || taskType,
  default_note: '覆盖值会写入 DAG nodes[].resources',
  roles: ROLE_ROWS,
})))

function normalizePriorityMap(value) {
  return {
    ...DEFAULT_MODALITY_PRIORITY_MAP,
    ...(value && typeof value === 'object' ? value : {}),
  }
}

function modalityPriorityHint(modality) {
  return MODALITY_PRIORITY_HINTS[modality] || '供路由系统识别业务流优先级。'
}

function cloneTaskResources(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function normalizeTaskModalityOverrides(value) {
  return {
    ...TASK_MODALITY_DEFAULTS,
    ...(value && typeof value === 'object' ? value : {}),
  }
}

function normalizeTaskResourceOverrides(value) {
  const merged = cloneTaskResources(DEFAULT_TASK_RESOURCE_OVERRIDES)
  const incoming = value && typeof value === 'object' ? value : {}
  Object.entries(incoming).forEach(([taskType, roleMap]) => {
    if (!merged[taskType] || !roleMap || typeof roleMap !== 'object') return
    Object.entries(roleMap).forEach(([role, resources]) => {
      if (!merged[taskType][role] || !resources || typeof resources !== 'object') return
      merged[taskType][role] = {
        ...merged[taskType][role],
        ...resources,
      }
    })
  })
  return merged
}

function clampInteger(value, fallback, min, max) {
  const number = Number.parseInt(value, 10)
  if (!Number.isFinite(number)) return fallback
  return Math.min(max, Math.max(min, number))
}

function normalizeBenchmarkExecutionDefaults(value) {
  const incoming = value && typeof value === 'object' ? value : {}
  return {
    default_task_count: clampInteger(incoming.default_task_count, DEFAULT_BENCHMARK_EXECUTION_DEFAULTS.default_task_count, 1, 30),
    max_parallel: clampInteger(incoming.max_parallel, DEFAULT_BENCHMARK_EXECUTION_DEFAULTS.max_parallel, 1, 10),
    per_compute_slot_limit: clampInteger(incoming.per_compute_slot_limit, DEFAULT_BENCHMARK_EXECUTION_DEFAULTS.per_compute_slot_limit, 1, 4),
  }
}

function applySettings(data) {
  settings.value = data || {}
  const loadedNotes = data?.notes || ''
  const hasLegacyEnvironmentNote = ['真实', '开发'].some((word) => loadedNotes.includes(`${word}环境`))
  const notes = hasLegacyEnvironmentNote
    ? '标准模式用于常规运行；联调模式用于接口联调、排障和快速回归。'
    : loadedNotes
  Object.assign(form, {
    environment_mode: data?.environment_mode || 'production',
    intent_parser_mode: data?.intent_parser_mode || 'llm',
    intent_rule_fallback_enabled: data?.intent_rule_fallback_enabled ?? true,
    benchmark_routing_mode: data?.benchmark_routing_mode || 'internal_auto',
    expert_mode: data?.expert_mode ?? true,
    show_internal_controls: data?.show_internal_controls ?? false,
    show_routing_dag_json: data?.show_routing_dag_json ?? false,
    modality_priority_map: normalizePriorityMap(data?.modality_priority_map),
    task_modality_override_enabled: data?.task_modality_override_enabled ?? false,
    task_modality_overrides: normalizeTaskModalityOverrides(data?.task_modality_overrides),
    task_resource_override_enabled: data?.task_resource_override_enabled ?? false,
    task_resource_overrides: normalizeTaskResourceOverrides(data?.task_resource_overrides),
    benchmark_execution_defaults: normalizeBenchmarkExecutionDefaults(data?.benchmark_execution_defaults),
    notes,
  })
}

async function loadSettings() {
  loading.value = true
  try {
    const { data } = await adminApi.getSystemSettings()
    applySettings(data)
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  saving.value = true
  try {
    const payload = {
      ...form,
      modality_priority_map: normalizePriorityMap(form.modality_priority_map),
      task_modality_overrides: normalizeTaskModalityOverrides(form.task_modality_overrides),
      task_resource_overrides: normalizeTaskResourceOverrides(form.task_resource_overrides),
      benchmark_execution_defaults: normalizeBenchmarkExecutionDefaults(form.benchmark_execution_defaults),
    }
    const { data } = await adminApi.updateSystemSettings(payload)
    applySettings(data)
    ElMessage.success('系统设置已保存')
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.settings-page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}

.settings-hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
  padding: 28px;
  border-radius: 24px;
  margin-bottom: 18px;
  background:
    radial-gradient(circle at 12% 20%, rgba(34, 197, 94, 0.18), transparent 30%),
    linear-gradient(135deg, #111827, #1f2937);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.settings-hero h1 {
  margin: 6px 0 10px;
  font-size: 30px;
  color: #f8fafc;
}

.settings-hero p {
  color: #cbd5e1;
  line-height: 1.7;
  max-width: 760px;
}

.eyebrow {
  color: #86efac;
  letter-spacing: 0.16em;
  font-size: 12px;
}

.settings-card {
  margin-bottom: 18px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.settings-form {
  color: #111827;
}

.setting-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 12px 0 18px;
}

.mode-card h3 {
  margin: 0 0 12px;
}

.execution-defaults {
  display: grid;
  gap: 12px;
}

.execution-defaults label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.execution-defaults span {
  color: #334155;
  font-size: 13px;
}

.priority-card {
  margin: 4px 0 18px;
}

.priority-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.priority-hint {
  margin: 0 0 12px;
}

.resource-task-list {
  display: grid;
  gap: 14px;
}

.resource-task-card {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #fbfdff;
}

.resource-task-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  color: #334155;
}

.resource-task-title strong {
  color: #0f172a;
}

.vertical-radio {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
}

.form-hint {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.advice-list {
  display: grid;
  gap: 12px;
}

.advice-list div {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 14px;
  background: #f8fafc;
  color: #334155;
}

.advice-list strong {
  color: #0f172a;
}

@media (max-width: 900px) {
  .setting-grid {
    grid-template-columns: 1fr;
  }

  .settings-hero {
    flex-direction: column;
  }
}
</style>
