<template>
  <el-form :model="form" label-position="top" class="template-editor-form">
    <el-form-item label="模板名称" required>
      <el-input v-model="form.name" :disabled="readonly" placeholder="abc-topology" />
    </el-form-item>
    <el-form-item label="描述">
      <el-input v-model="form.description" :disabled="readonly" type="textarea" :rows="2" placeholder="可选说明" />
    </el-form-item>

    <div class="section-divider">
      <span>宏变量</span>
      <el-button v-if="!readonly" size="small" @click="$emit('add-macro')">
        <el-icon><Plus /></el-icon>
        添加宏
      </el-button>
    </div>
    <div v-if="form.macro_defs.length" class="macro-editor">
      <div v-for="(macro, idx) in form.macro_defs" :key="idx" class="macro-editor-row">
        <el-input v-model="macro.name" :disabled="readonly" placeholder="DB_URL" />
        <el-input v-model="macro.label" :disabled="readonly" placeholder="说明" />
        <el-input v-model="macro.default" :disabled="readonly" placeholder="默认值" />
        <el-button v-if="!readonly" text type="danger" @click="$emit('remove-macro', idx)">
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
    </div>
    <p v-else class="empty-hint">未定义宏变量</p>

    <div class="section-divider">
      <span>节点</span>
      <div v-if="!readonly" class="section-actions">
        <el-button size="small" link type="primary" @click="$emit('abc-topology')">A→B→C 拓扑</el-button>
        <el-button size="small" @click="$emit('add-node')">
          <el-icon><Plus /></el-icon>
          添加节点
        </el-button>
      </div>
    </div>

    <div class="nodes-editor" v-if="form.nodes.length">
      <div v-for="(node, index) in form.nodes" :key="index" class="node-editor-card">
        <div class="node-editor-header">
          <el-input v-model="node.name" :disabled="readonly" placeholder="节点角色名，如 source" class="node-name-input" />
          <el-button v-if="!readonly" text type="danger" @click="$emit('remove-node', index)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
        <div class="node-editor-grid">
          <el-form-item label="默认镜像（可选）">
            <el-input v-model="node.image" :disabled="readonly" :placeholder="DEFAULT_PLACEHOLDER_IMAGE" />
          </el-form-item>
          <el-form-item label="默认 Worker（可选）">
            <el-select v-model="node.node_id" :disabled="readonly" placeholder="不选则自动分配" clearable style="width: 100%">
              <el-option v-for="n in workers" :key="n.id" :label="n.hostname" :value="n.id" />
            </el-select>
          </el-form-item>
        </div>
        <div class="port-defs-block">
          <div class="port-defs-header">
            <span>命名端口（host 模式）</span>
            <el-button v-if="!readonly" size="small" link type="primary" @click="$emit('add-port-def', index)">+ 添加端口变量</el-button>
          </div>
          <div v-for="(portDef, pIdx) in node.port_defs" :key="pIdx" class="port-def-row">
            <el-input v-model="portDef.name" :disabled="readonly" placeholder="api" />
            <el-input v-model="portDef.label" :disabled="readonly" placeholder="说明" />
            <el-input-number v-model="portDef.default" :disabled="readonly" :min="1" :max="65535" controls-position="right" />
            <el-button v-if="!readonly" text type="danger" @click="$emit('remove-port-def', index, pIdx)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <p v-if="!node.port_defs?.length" class="empty-hint">无命名端口</p>
        </div>
      </div>
    </div>
    <p v-else class="empty-hint">暂无节点</p>

    <div class="section-divider">
      <span>依赖关系</span>
      <el-button v-if="!readonly" size="small" @click="$emit('add-edge')">
        <el-icon><Plus /></el-icon>
        添加依赖
      </el-button>
    </div>

    <div class="edges-editor" v-if="form.edges.length">
      <div v-for="(edge, index) in form.edges" :key="index" class="edge-row">
        <template v-if="readonly">
          <span>{{ nodeLabel(edge.from_node_id) }}</span>
          <span>→</span>
          <span>{{ nodeLabel(edge.to_node_id) }}</span>
        </template>
        <template v-else>
          <el-select v-model="edge.from_node_id" placeholder="上游" style="width: 140px">
            <el-option v-for="(n, i) in form.nodes" :key="i" :label="n.name || `节点 ${i + 1}`" :value="n._temp_id" />
          </el-select>
          <span>→</span>
          <el-select v-model="edge.to_node_id" placeholder="下游" style="width: 140px">
            <el-option v-for="(n, i) in form.nodes" :key="i" :label="n.name || `节点 ${i + 1}`" :value="n._temp_id" />
          </el-select>
          <el-button text type="danger" @click="$emit('remove-edge', index)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </div>
    </div>
    <p v-else class="empty-hint">未定义依赖关系</p>
  </el-form>
</template>

<script setup>
import { DEFAULT_PLACEHOLDER_IMAGE } from '@/utils/deployJson'

const props = defineProps({
  form: { type: Object, required: true },
  workers: { type: Array, default: () => [] },
  readonly: { type: Boolean, default: false },
})

defineEmits([
  'add-macro', 'remove-macro', 'add-node', 'remove-node',
  'add-port-def', 'remove-port-def', 'add-edge', 'remove-edge', 'abc-topology',
])

function nodeLabel(tempId) {
  const node = props.form.nodes?.find((n) => n._temp_id === tempId)
  return node?.name || tempId || '-'
}
</script>

<style scoped>
.section-divider {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 0; margin: 8px 0; border-bottom: 1px solid var(--border-subtle);
}
.section-divider span { font-weight: 600; font-size: 14px; color: var(--text-secondary); }
.section-actions { display: flex; align-items: center; gap: 8px; }
.nodes-editor { display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px; }
.node-editor-card {
  background: var(--bg-tertiary); border-radius: 12px; padding: 14px; border: 1px solid var(--border-subtle);
}
.node-editor-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.node-name-input { flex: 1; margin-right: 8px; }
.node-editor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.edges-editor { display: flex; flex-direction: column; gap: 10px; margin-bottom: 8px; }
.edge-row { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-secondary); }
.macro-editor, .port-defs-block { margin-bottom: 12px; }
.macro-editor-row, .port-def-row {
  display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 8px; margin-bottom: 8px;
}
.port-defs-header {
  display: flex; justify-content: space-between; align-items: center;
  margin: 8px 0; font-size: 13px; color: var(--text-secondary);
}
.empty-hint { color: var(--text-muted); font-size: 13px; margin: 0 0 12px; }
</style>
