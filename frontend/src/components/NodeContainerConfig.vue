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
          <div v-else class="field-block">
            <div class="field-label">
              {{ docs.host_ports.label }}
              <code class="docker-tag">{{ docs.host_ports.dockerApi }}</code>
            </div>
            <template v-if="node.port_defs?.length">
              <div v-for="def in node.port_defs" :key="def.name" class="named-port-row">
                <code class="port-var">{{ def.name }}</code>
                <span class="port-label">{{ def.label || def.name }}</span>
                <el-input-number
                  :model-value="node.port_values?.[def.name] ?? def.default ?? null"
                  :disabled="disabled"
                  :min="1"
                  :max="65535"
                  controls-position="right"
                  @update:model-value="(v) => setNamedPort(def.name, v)"
                />
              </div>
              <p class="field-hint">本节点注入 <code>PORT_&lt;变量大写&gt;</code>；互访 URL 为 <code>PEER_&lt;角色&gt;_URL_&lt;变量大写&gt;</code>（业务 IPv6 优先）。</p>
            </template>
            <template v-else>
              <div v-for="(row, idx) in portRows" :key="idx" class="mapping-row">
                <el-input v-model="row.left" :disabled="disabled" placeholder="9000" />
                <el-button :disabled="disabled" type="danger" text @click="removePortRow(idx)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <el-button :disabled="disabled" link type="primary" @click="addPortRow">+ 添加监听端口</el-button>
              <p class="field-hint">{{ docs.host_ports.hint }}</p>
            </template>
          </div>
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
              {{ docs.volume_mount.label }}
              <code class="docker-tag">{{ docs.volume_mount.dockerApi }}</code>
            </div>
            <p class="field-hint">{{ docs.volume_mount.hint }}</p>
            <div v-for="(row, idx) in mountRows" :key="idx" class="mount-row">
              <el-select v-model="row.type" :disabled="disabled" style="width: 120px">
                <el-option v-for="t in MOUNT_TYPES" :key="t.value" :value="t.value" :label="t.value" />
              </el-select>
              <el-input v-model="row.target" :disabled="disabled" placeholder="容器路径 /app/data" />
              <el-input v-model="row.source" :disabled="disabled" :placeholder="mountSourcePlaceholder(row.type)" />
              <el-checkbox v-model="row.auto_create" :disabled="disabled">自动创建</el-checkbox>
              <el-button :disabled="disabled" type="danger" text @click="removeMountRow(idx)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button :disabled="disabled" link type="primary" @click="addMountRow">+ 添加挂载</el-button>
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
            <p class="field-hint">{{ docs.cpu_limit.hint }}</p>
          </div>

          <div class="field-block">
            <div class="field-label">
              {{ docs.cpu_reservation.label }}
              <code class="docker-tag">{{ docs.cpu_reservation.dockerApi }}</code>
            </div>
            <el-input-number
              :model-value="node.cpu_reservation"
              :disabled="disabled"
              :min="0"
              :step="0.5"
              :precision="2"
              controls-position="right"
              style="width: 100%"
              @update:model-value="(v) => (node.cpu_reservation = v ?? null)"
            />
            <p class="field-hint">{{ docs.cpu_reservation.hint }}</p>
          </div>

          <div class="field-block">
            <div class="field-label">{{ docs.cpu_shares.label }}</div>
            <el-input-number
              :model-value="node.cpu_shares"
              :disabled="disabled"
              :min="2"
              :step="128"
              controls-position="right"
              style="width: 100%"
              @update:model-value="(v) => (node.cpu_shares = v ?? null)"
            />
            <p class="field-hint">{{ docs.cpu_shares.hint }}</p>
          </div>

          <div class="field-block">
            <div class="field-label">{{ docs.cpuset_cpus.label }}</div>
            <el-input v-model="node.cpuset_cpus" :disabled="disabled" :placeholder="docs.cpuset_cpus.example" />
            <p class="field-hint">{{ docs.cpuset_cpus.hint }}</p>
          </div>

          <div class="field-block">
            <div class="field-label">{{ docs.cpu_quota.label }} / {{ docs.cpu_period.label }}</div>
            <div class="mapping-row">
              <el-input-number
                :model-value="node.cpu_quota"
                :disabled="disabled"
                :min="0"
                controls-position="right"
                style="width: 100%"
                @update:model-value="(v) => (node.cpu_quota = v ?? null)"
              />
              <el-input-number
                :model-value="node.cpu_period"
                :disabled="disabled"
                :min="0"
                controls-position="right"
                style="width: 100%"
                @update:model-value="(v) => (node.cpu_period = v ?? null)"
              />
            </div>
            <p class="field-hint">{{ docs.cpu_quota.hint }}</p>
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
          </div>

          <div class="field-block">
            <div class="field-label">{{ docs.memory_reservation.label }}</div>
            <el-input
              v-model="node.memory_reservation"
              :disabled="disabled"
              :placeholder="docs.memory_reservation.example"
            />
            <p class="field-hint">{{ docs.memory_reservation.hint }}</p>
          </div>

          <div class="field-block">
            <div class="field-label">{{ docs.memory_swap_limit.label }}</div>
            <el-input
              v-model="node.memory_swap_limit"
              :disabled="disabled"
              :placeholder="docs.memory_swap_limit.example"
            />
            <p class="field-hint">{{ docs.memory_swap_limit.hint }}</p>
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
              placeholder="all | 0 | 0,1,2"
            />
            <p class="field-hint">{{ docs.gpu_id.hint }}</p>
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
import { ref, watch, onMounted } from 'vue'
import {
  DOCKER_PARAM_DOCS,
  RUNTIME_TAB_NOTE,
  MOUNT_TYPES,
  parsePortLines,
  formatPortLines,
  parseEnvLines,
  formatEnvLines,
  parseHostPortLines,
  formatHostPortLines,
  defaultMountRow,
  serializeVolumeMounts,
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
const mountRows = ref([])

function mountSourcePlaceholder(type) {
  if (type === 'managed') return '逻辑名 input'
  if (type === 'volume') return '卷名 my-vol'
  return '/data/host/path'
}

function syncPortRowsFromNode(n) {
  portRows.value =
    n.network_mode === 'host'
      ? parseHostPortLines(n.ports_text || '')
      : parsePortLines(n.ports_text || '')
  if (!portRows.value.length) portRows.value = [{ left: '', right: '' }]
}

function syncRowsFromNode() {
  const n = props.node
  syncPortRowsFromNode(n)
  if (!n.port_values) n.port_values = {}
  for (const def of n.port_defs || []) {
    if (n.port_values[def.name] == null && def.default != null) {
      n.port_values[def.name] = def.default
    }
  }
  envRows.value = parseEnvLines(n.env_text || '')
  mountRows.value = (n.volume_mounts?.length ? [...n.volume_mounts] : [defaultMountRow()])
  if (!envRows.value.length) envRows.value = [{ left: '', right: '' }]
  ;['cpu_reservation', 'cpu_shares', 'cpu_quota', 'cpu_period', 'memory_reservation', 'memory_swap_limit'].forEach((k) => {
    if (n[k] === undefined) n[k] = null
  })
  if (n.cpuset_cpus === undefined) n.cpuset_cpus = ''
}

function syncNodeFromRows() {
  props.node.ports_text =
    props.node.network_mode === 'host'
      ? formatHostPortLines(portRows.value)
      : formatPortLines(portRows.value)
  props.node.env_text = formatEnvLines(envRows.value)
  props.node.volume_mounts = serializeVolumeMounts(mountRows.value)
}

function setNamedPort(name, value) {
  if (!props.node.port_values) props.node.port_values = {}
  if (value == null || value === '') {
    delete props.node.port_values[name]
  } else {
    props.node.port_values[name] = value
  }
}

function addPortRow() { portRows.value.push({ left: '', right: '' }) }
function removePortRow(idx) { portRows.value.splice(idx, 1); syncNodeFromRows() }
function addEnvRow() { envRows.value.push({ left: '', right: '' }) }
function removeEnvRow(idx) { envRows.value.splice(idx, 1); syncNodeFromRows() }
function addMountRow() { mountRows.value.push(defaultMountRow()) }
function removeMountRow(idx) { mountRows.value.splice(idx, 1); syncNodeFromRows() }

watch([portRows, envRows, mountRows], syncNodeFromRows, { deep: true })
watch(() => props.node.template_node_id, syncRowsFromNode)
watch(() => props.node.network_mode, syncRowsFromNode)
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
.mount-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.mount-row .el-input {
  flex: 1;
  min-width: 120px;
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
.named-port-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.port-var {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-tertiary);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  min-width: 48px;
}
.port-label {
  flex: 1;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
