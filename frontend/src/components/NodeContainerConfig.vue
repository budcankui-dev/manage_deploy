<template>
  <div class="node-config-panel">
    <div class="panel-header">
      <span class="node-badge">{{ node.template_node_name || '节点' }}</span>
      <span class="panel-subtitle">容器运行配置</span>
    </div>

    <!-- Image（Portainer 风格首屏） -->
    <section class="config-section">
      <div class="section-label">
        {{ docs.image.label }}
        <code class="docker-tag">{{ docs.image.dockerApi }}</code>
      </div>
      <div class="image-row">
        <el-select
          v-if="showWorker"
          v-model="node.node_id"
          placeholder="Worker"
          :disabled="disabled"
          class="worker-select"
        >
          <el-option v-for="w in workers" :key="w.id" :label="w.hostname" :value="w.id" />
        </el-select>
        <el-input
          v-model="node.image"
          :disabled="disabled"
          :placeholder="docs.image.example"
          class="image-input"
        />
      </div>
      <p class="field-hint">{{ docs.image.hint }}</p>
    </section>

    <!-- Advanced settings card + tabs -->
    <el-card shadow="never" class="advanced-card">
      <template #header>
        <div class="advanced-title">
          <el-icon><Setting /></el-icon>
          <span>高级容器设置</span>
        </div>
      </template>

      <el-tabs v-model="activeTab" class="config-tabs">
        <!-- Command -->
        <el-tab-pane label="命令" name="command">
          <div class="field-block">
            <div class="field-label">
              {{ docs.command.label }}
              <code class="docker-tag">{{ docs.command.dockerApi }}</code>
            </div>
            <el-input
              v-model="node.command"
              :disabled="disabled"
              :placeholder="docs.command.example"
            />
            <p class="field-hint">{{ docs.command.hint }}</p>
          </div>
        </el-tab-pane>

        <!-- Network -->
        <el-tab-pane label="网络" name="network">
          <div class="field-block">
            <div class="field-label">
              {{ docs.network_mode.label }}
              <code class="docker-tag">{{ docs.network_mode.dockerApi }}</code>
            </div>
            <el-radio-group v-model="node.network_mode" :disabled="disabled">
              <el-radio label="host">host（共享宿主机网络）</el-radio>
              <el-radio label="bridge">bridge（独立网络 + 端口映射）</el-radio>
            </el-radio-group>
            <p class="field-hint">{{ docs.network_mode.hint }}</p>
          </div>

          <div v-if="node.network_mode === 'bridge'" class="field-block">
            <div class="field-label">
              {{ docs.ports.label }}
              <code class="docker-tag">{{ docs.ports.dockerApi }}</code>
            </div>
            <div v-for="(row, idx) in portRows" :key="idx" class="mapping-row">
              <el-input v-model="row.left" :disabled="disabled" placeholder="宿主机 8080" />
              <span class="arrow">→</span>
              <el-input v-model="row.right" :disabled="disabled" placeholder="容器 80" />
              <el-button
                :disabled="disabled"
                type="danger"
                text
                @click="removePortRow(idx)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button :disabled="disabled" link type="primary" @click="addPortRow">+ 添加端口映射</el-button>
            <p class="field-hint">{{ docs.ports.hint }}</p>
          </div>
          <el-alert v-else type="info" :closable="false" show-icon class="inline-alert">
            host 模式下端口映射不生效，容器直接使用宿主机端口。
          </el-alert>
        </el-tab-pane>

        <!-- Env -->
        <el-tab-pane label="环境变量" name="env">
          <div class="field-block">
            <div class="field-label">
              {{ docs.env.label }}
              <code class="docker-tag">{{ docs.env.dockerApi }}</code>
            </div>
            <div v-for="(row, idx) in envRows" :key="idx" class="mapping-row env-row">
              <el-input v-model="row.left" :disabled="disabled" placeholder="KEY" />
              <span class="arrow">=</span>
              <el-input v-model="row.right" :disabled="disabled" placeholder="VALUE" />
              <el-button :disabled="disabled" type="danger" text @click="removeEnvRow(idx)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button :disabled="disabled" link type="primary" @click="addEnvRow">+ 添加变量</el-button>
            <p class="field-hint">{{ docs.env.hint }}</p>
          </div>
        </el-tab-pane>

        <!-- Volumes -->
        <el-tab-pane label="挂载" name="volumes">
          <div class="field-block">
            <div class="field-label">
              {{ docs.volumes.label }}
              <code class="docker-tag">{{ docs.volumes.dockerApi }}</code>
            </div>
            <div v-for="(row, idx) in volumeRows" :key="idx" class="mapping-row">
              <el-input v-model="row.left" :disabled="disabled" placeholder="/data/host" />
              <span class="arrow">→</span>
              <el-input v-model="row.right" :disabled="disabled" placeholder="/app/data" />
              <el-button :disabled="disabled" type="danger" text @click="removeVolumeRow(idx)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button :disabled="disabled" link type="primary" @click="addVolumeRow">+ 添加挂载</el-button>
            <p class="field-hint">{{ docs.volumes.hint }}</p>
          </div>
        </el-tab-pane>

        <!-- Runtime & Resources -->
        <el-tab-pane label="资源" name="runtime">
          <el-alert type="info" :closable="false" show-icon class="inline-alert">
            {{ runtimeNote }}
          </el-alert>

          <div class="field-block">
            <div class="field-label">
              {{ docs.cpu_limit.label }}
              <code class="docker-tag">{{ docs.cpu_limit.dockerApi }}</code>
              <code v-if="docs.cpu_limit.dockerCli" class="docker-cli">{{ docs.cpu_limit.dockerCli }}</code>
            </div>
            <el-input-number
              :model-value="node.cpu_limit"
              :disabled="disabled"
              :min="0"
              :step="0.5"
              :precision="2"
              controls-position="right"
              style="width: 100%"
              @update:model-value="(v) => (node.cpu_limit = v ?? null)"
            />
            <p class="field-hint">
              示例：<code>{{ docs.cpu_limit.example }}</code> 表示最多 {{ docs.cpu_limit.example }} 核
              → NanoCPUs = {{ cpuNanoExample }}
            </p>
            <p class="unsupported-hint">{{ docs.cpu_limit.unsupported }}</p>
          </div>

          <div class="field-block">
            <div class="field-label">
              {{ docs.memory_limit.label }}
              <code class="docker-tag">{{ docs.memory_limit.dockerApi }}</code>
              <code class="docker-cli">{{ docs.memory_limit.dockerCli }}</code>
            </div>
            <el-input
              v-model="node.memory_limit"
              :disabled="disabled"
              :placeholder="docs.memory_limit.example"
            />
            <p class="field-hint">{{ docs.memory_limit.hint }}</p>
            <p class="unsupported-hint">{{ docs.memory_limit.unsupported }}</p>
          </div>

          <div class="field-block">
            <div class="field-label">
              {{ docs.gpu_id.label }}
              <code class="docker-tag">{{ docs.gpu_id.dockerApi }}</code>
              <code class="docker-cli">{{ docs.gpu_id.dockerCli }}</code>
            </div>
            <el-input
              v-model="node.gpu_id"
              :disabled="disabled"
              :placeholder="docs.gpu_id.example"
            />
            <p class="field-hint">{{ docs.gpu_id.hint }}</p>
            <p class="unsupported-hint">{{ docs.gpu_id.unsupported }}</p>
          </div>
        </el-tab-pane>

        <!-- Restart -->
        <el-tab-pane label="重启" name="restart">
          <div class="field-block">
            <div class="field-label">
              {{ docs.restart_policy.label }}
              <code class="docker-tag">{{ docs.restart_policy.dockerApi }}</code>
            </div>
            <el-select v-model="node.restart_policy" :disabled="disabled" style="width: 100%">
              <el-option label="on-failure — 失败时重启" value="on-failure" />
              <el-option label="always — 总是重启" value="always" />
              <el-option label="no — 不自动重启" value="no" />
            </el-select>
            <p class="field-hint">{{ docs.restart_policy.hint }}</p>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import {
  DOCKER_PARAM_DOCS,
  RUNTIME_TAB_NOTE,
  parsePortLines,
  formatPortLines,
  parseEnvLines,
  formatEnvLines,
  parseVolumeLines,
  formatVolumeLines,
} from '@/utils/dockerFieldHints'

const props = defineProps({
  node: { type: Object, required: true },
  workers: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  showWorker: { type: Boolean, default: true },
})

const docs = DOCKER_PARAM_DOCS
const runtimeNote = RUNTIME_TAB_NOTE
const activeTab = ref('command')

const portRows = ref([])
const envRows = ref([])
const volumeRows = ref([])

const cpuNanoExample = computed(() => {
  const v = parseFloat(docs.cpu_limit.example)
  if (!v || Number.isNaN(v)) return '-'
  return `${Math.round(v * 1_000_000_000)}`
})

function syncRowsFromNode() {
  const n = props.node
  portRows.value = parsePortLines(n.ports_text || '')
  envRows.value = parseEnvLines(n.env_text || '')
  volumeRows.value = parseVolumeLines(n.volumes_text || '')
  if (!portRows.value.length && n.network_mode === 'bridge') portRows.value = [{ left: '', right: '' }]
  if (!envRows.value.length) envRows.value = [{ left: '', right: '' }]
  if (!volumeRows.value.length) volumeRows.value = [{ left: '', right: '' }]
}

function syncNodeFromRows() {
  props.node.ports_text = formatPortLines(portRows.value)
  props.node.env_text = formatEnvLines(envRows.value)
  props.node.volumes_text = formatVolumeLines(volumeRows.value)
}

function addPortRow() {
  portRows.value.push({ left: '', right: '' })
}
function removePortRow(idx) {
  portRows.value.splice(idx, 1)
  syncNodeFromRows()
}
function addEnvRow() {
  envRows.value.push({ left: '', right: '' })
}
function removeEnvRow(idx) {
  envRows.value.splice(idx, 1)
  syncNodeFromRows()
}
function addVolumeRow() {
  volumeRows.value.push({ left: '', right: '' })
}
function removeVolumeRow(idx) {
  volumeRows.value.splice(idx, 1)
  syncNodeFromRows()
}

watch([portRows, envRows, volumeRows], syncNodeFromRows, { deep: true })

watch(
  () => props.node.template_node_id,
  () => syncRowsFromNode(),
)

onMounted(syncRowsFromNode)

defineExpose({ syncNodeFromRows })
</script>

<style scoped>
.node-config-panel {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
  background: var(--bg-secondary);
}
.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.node-badge {
  font-weight: 600;
  font-size: 14px;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--accent-primary);
  color: #fff;
}
.panel-subtitle {
  color: var(--text-muted);
  font-size: 13px;
}
.config-section {
  margin-bottom: 16px;
}
.section-label,
.field-label {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary);
}
.docker-tag {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-tertiary);
  color: var(--text-muted);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.docker-cli {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.12);
  color: var(--accent-primary);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.image-row {
  display: flex;
  gap: 10px;
}
.worker-select {
  width: 160px;
  flex-shrink: 0;
}
.image-input {
  flex: 1;
}
.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.field-hint code {
  font-size: 11px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--bg-tertiary);
}
.unsupported-hint {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--text-muted);
  font-style: italic;
}
.advanced-card {
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
}
.advanced-card :deep(.el-card__header) {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
}
.advanced-card :deep(.el-card__body) {
  padding: 0 16px 16px;
}
.advanced-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
}
.config-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.field-block {
  margin-bottom: 16px;
}
.mapping-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.mapping-row .el-input {
  flex: 1;
}
.arrow {
  color: var(--text-muted);
  font-size: 14px;
  flex-shrink: 0;
}
.env-row .arrow {
  font-weight: 600;
}
.inline-alert {
  margin-bottom: 12px;
}
</style>
