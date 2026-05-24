<template>
  <div class="templates-view">
    <header class="page-header">
      <div class="title-section">
        <h1>拓扑模板</h1>
        <p class="subtitle">只定义节点角色与 DAG 依赖；命令、端口、环境变量在「任务实例」创建时填写</p>
      </div>
      <div class="header-actions">
        <span class="selected-count" v-if="selectedIds.length">已选 {{ selectedIds.length }} 项</span>
        <el-button type="danger" plain :disabled="!selectedIds.length" @click="batchDeleteTemplates">删除</el-button>
        <el-button type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon>
          新建
        </el-button>
      </div>
    </header>

    <div class="templates-grid" v-if="templates.length">
      <div
        v-for="template in paginatedTemplates"
        :key="template.id"
        class="template-card"
        @click="viewTemplate(template.id)"
      >
        <div class="template-header">
          <el-checkbox :model-value="selectedIds.includes(template.id)" @click.stop @change="toggleSelected(template.id)" />
          <div class="template-icon">
            <el-icon><Document /></el-icon>
          </div>
          <div class="template-info">
            <h3>{{ template.name }}</h3>
            <span class="node-count">{{ template.nodes?.length || 0 }} 个节点</span>
          </div>
          <el-dropdown trigger="click" @click.stop>
            <el-button text circle>
              <el-icon><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click.stop="editTemplate(template)">编辑</el-dropdown-item>
                <el-dropdown-item @click.stop="duplicateTemplate(template)">复制</el-dropdown-item>
                <el-dropdown-item @click.stop="exportTemplateJson(template)">导出 JSON</el-dropdown-item>
                <el-dropdown-item divided @click.stop="confirmDelete(template)">删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <p class="template-description" v-if="template.description">{{ template.description }}</p>
        <div class="template-meta">
          <span>创建于 {{ formatDate(template.created_at) }}</span>
        </div>
      </div>
    </div>

    <div class="empty-state" v-else>
      <div class="empty-icon"><el-icon><Folder /></el-icon></div>
      <h3>还没有拓扑模板</h3>
      <p>先创建拓扑（如 source → compute → sink），再在任务实例中填写运行参数</p>
      <el-button type="primary" @click="openCreateDialog">
        <el-icon><Plus /></el-icon>
        新建
      </el-button>
    </div>

    <div v-if="templates.length" class="pagination-wrap">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        background
        layout="total, sizes, prev, pager, next"
        :page-sizes="[8, 12, 20, 50]"
        :total="templates.length"
      />
    </div>

    <el-dialog
      v-model="showEditor"
      :title="editingTemplate ? '编辑拓扑模板' : '新建拓扑模板'"
      width="720px"
      :close-on-click-modal="false"
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="模板只管拓扑结构。镜像、命令、端口等请在创建任务实例时配置。"
        style="margin-bottom: 16px;"
      />
      <el-tabs v-model="editorMode">
        <el-tab-pane label="JSON 粘贴" name="json">
          <p class="json-hint">只需 name、nodes 角色名与 edges；node_id 可省略。</p>
          <el-input v-model="jsonText" type="textarea" :rows="16" placeholder="粘贴拓扑 JSON..." />
          <div class="json-actions">
            <el-button link type="primary" @click="loadTemplateExample">填入示例</el-button>
            <el-button link type="primary" @click="addAbcTopologyToJson">填入 A→B→C 拓扑</el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="可视化" name="form">
          <el-form :model="form" label-position="top">
            <el-form-item label="模板名称" required>
              <el-input v-model="form.name" placeholder="abc-topology" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选说明" />
            </el-form-item>

            <div class="section-divider">
              <span>节点</span>
              <div class="section-actions">
                <el-button size="small" link type="primary" @click="addAbcTopologyToForm">A→B→C 拓扑</el-button>
                <el-button size="small" @click="addNode">
                  <el-icon><Plus /></el-icon>
                  添加节点
                </el-button>
              </div>
            </div>

            <div class="nodes-editor" v-if="form.nodes.length">
              <div v-for="(node, index) in form.nodes" :key="index" class="node-editor-card">
                <div class="node-editor-header">
                  <el-input v-model="node.name" placeholder="节点角色名，如 source" class="node-name-input" />
                  <el-button text type="danger" @click="removeNode(index)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
                <div class="node-editor-grid">
                  <el-form-item label="默认镜像（可选）">
                    <el-input v-model="node.image" :placeholder="DEFAULT_PLACEHOLDER_IMAGE" />
                  </el-form-item>
                  <el-form-item label="默认 Worker（可选）">
                    <el-select v-model="node.node_id" placeholder="不选则自动分配" clearable style="width: 100%">
                      <el-option v-for="n in availableNodes" :key="n.id" :label="n.hostname" :value="n.id" />
                    </el-select>
                  </el-form-item>
                </div>
              </div>
            </div>

            <div class="section-divider">
              <span>依赖关系</span>
              <el-button size="small" @click="addEdge">
                <el-icon><Plus /></el-icon>
                添加依赖
              </el-button>
            </div>

            <div class="edges-editor" v-if="form.edges.length">
              <div v-for="(edge, index) in form.edges" :key="index" class="edge-row">
                <el-select v-model="edge.from_node_id" placeholder="上游" style="width: 140px">
                  <el-option v-for="(n, i) in form.nodes" :key="i" :label="n.name || `节点 ${i + 1}`" :value="n._temp_id" />
                </el-select>
                <span>→</span>
                <el-select v-model="edge.to_node_id" placeholder="下游" style="width: 140px">
                  <el-option v-for="(n, i) in form.nodes" :key="i" :label="n.name || `节点 ${i + 1}`" :value="n._temp_id" />
                </el-select>
                <el-button text type="danger" @click="removeEdge(index)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="showEditor = false">取消</el-button>
        <el-button type="primary" @click="submitEditor" :loading="submitting">
          {{ editingTemplate ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter, useRoute } from 'vue-router'
import { useTemplatesStore } from '@/stores/templates'
import { useNodesStore } from '@/stores/nodes'
import { ElMessageBox, ElMessage } from 'element-plus'
import {
  buildTemplatePayload,
  TEMPLATE_JSON_EXAMPLE,
  templateToImportJson,
  DEFAULT_PLACEHOLDER_IMAGE,
  buildAbcTopologyNodes,
  buildAbcTopologyEdges,
} from '@/utils/deployJson'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'

dayjs.extend(relativeTime)
dayjs.extend(utc)

const router = useRouter()
const route = useRoute()
const templatesStore = useTemplatesStore()
const nodesStore = useNodesStore()

const { templates } = storeToRefs(templatesStore)
const { nodes: availableNodes } = storeToRefs(nodesStore)
const { fetchTemplates, createTemplate: apiCreateTemplate, updateTemplate, deleteTemplate } = templatesStore
const { fetchNodes } = nodesStore

const showEditor = ref(false)
const editorMode = ref('json')
const jsonText = ref('')
const editingTemplate = ref(null)
const submitting = ref(false)
const selectedIds = ref([])
const currentPage = ref(1)
const pageSize = ref(8)

const form = ref({ name: '', description: '', nodes: [], edges: [] })

let nodeCounter = 0

const paginatedTemplates = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return (templates.value || []).slice(start, start + pageSize.value)
})

onMounted(async () => {
  await fetchTemplates()
  await fetchNodes()
  await openEditorFromRoute()
})

watch(
  () => route.query.edit,
  async () => {
    await openEditorFromRoute()
  }
)

function resetForm() {
  form.value = { name: '', description: '', nodes: [], edges: [] }
}

function openCreateDialog() {
  editingTemplate.value = null
  editorMode.value = 'json'
  jsonText.value = TEMPLATE_JSON_EXAMPLE
  resetForm()
  showEditor.value = true
}

function loadTemplateExample() {
  jsonText.value = TEMPLATE_JSON_EXAMPLE
}

function addAbcTopologyToJson() {
  jsonText.value = TEMPLATE_JSON_EXAMPLE
}

function addAbcTopologyToForm() {
  form.value.nodes = buildAbcTopologyNodes(availableNodes.value)
  form.value.edges = buildAbcTopologyEdges()
  if (!form.value.name) form.value.name = 'abc-topology'
}

function addNode() {
  const id = `temp_${nodeCounter++}`
  form.value.nodes.push({
    _temp_id: id,
    name: '',
    image: '',
    node_id: availableNodes.value[0]?.id || '',
  })
}

function removeNode(index) {
  const node = form.value.nodes[index]
  form.value.edges = form.value.edges.filter(
    (e) => e.from_node_id !== node._temp_id && e.to_node_id !== node._temp_id
  )
  form.value.nodes.splice(index, 1)
}

function addEdge() {
  if (form.value.nodes.length < 2) {
    ElMessage.warning('至少需要 2 个节点')
    return
  }
  form.value.edges.push({ from_node_id: '', to_node_id: '' })
}

function removeEdge(index) {
  form.value.edges.splice(index, 1)
}

function buildFormPayload() {
  if (!form.value.name) throw new Error('模板名称不能为空')
  if (!form.value.nodes.length) throw new Error('至少添加一个节点')

  const nodesPayload = form.value.nodes.map((n, index) => {
    if (!n.name?.trim()) throw new Error(`节点 ${index + 1} 需要角色名`)
    const nodeId = n.node_id || availableNodes.value[index]?.id || availableNodes.value[0]?.id
    if (!nodeId) throw new Error('请先在「节点管理」注册 worker，或为节点指定默认 Worker')
    return {
      client_id: n._temp_id || n.name,
      name: n.name.trim(),
      image: n.image?.trim() || DEFAULT_PLACEHOLDER_IMAGE,
      command: null,
      env: null,
      ports: null,
      volumes: null,
      gpu_id: null,
      cpu_limit: null,
      memory_limit: null,
      node_id: nodeId,
      network_mode: 'host',
      restart_policy: 'on-failure',
      health_check: null,
    }
  })

  return {
    name: form.value.name.trim(),
    description: form.value.description?.trim() || null,
    nodes: nodesPayload,
    edges: form.value.edges.map((e) => ({
      from_node_id: e.from_node_id,
      to_node_id: e.to_node_id,
    })),
  }
}

async function submitEditor() {
  submitting.value = true
  try {
    let payload
    if (editorMode.value === 'json') {
      if (editingTemplate.value) {
        ElMessage.warning('编辑请使用「可视化」标签页')
        return
      }
      payload = buildTemplatePayload(jsonText.value, { nodes: availableNodes.value })
    } else {
      payload = buildFormPayload()
    }

    if (editingTemplate.value) {
      await updateTemplate(editingTemplate.value.id, payload)
      ElMessage.success('模板已保存')
    } else {
      await apiCreateTemplate(payload)
      ElMessage.success('模板已创建')
    }
    showEditor.value = false
    await fetchTemplates()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function exportTemplateJson(template) {
  const detail = template.nodes?.length ? template : await templatesStore.fetchTemplate(template.id)
  if (!detail) return
  jsonText.value = templateToImportJson(detail)
  editingTemplate.value = null
  editorMode.value = 'json'
  showEditor.value = true
}

function toggleSelected(id) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function viewTemplate(id) {
  router.push(`/templates/${id}`)
}

async function openEditorFromRoute() {
  const editId = route.query.edit
  if (!editId || typeof editId !== 'string') return
  const detail = await templatesStore.fetchTemplate(editId)
  if (!detail) return
  editTemplate(detail)
  router.replace({ path: '/templates' })
}

function mapTemplateToForm(template) {
  const idMap = new Map()
  const nodes = (template.nodes || []).map((n) => {
    const tempId = n.name || n.id || `temp_${nodeCounter++}`
    idMap.set(n.id, tempId)
    idMap.set(n.name, tempId)
    return {
      _temp_id: tempId,
      name: n.name,
      image: n.image === DEFAULT_PLACEHOLDER_IMAGE ? '' : (n.image || ''),
      node_id: n.node_id || '',
    }
  })
  const edges = (template.edges || []).map((e) => ({
    from_node_id: idMap.get(e.from_node_id) || e.from_node_id,
    to_node_id: idMap.get(e.to_node_id) || e.to_node_id,
  }))
  return { name: template.name, description: template.description || '', nodes, edges }
}

function editTemplate(template) {
  editingTemplate.value = template
  editorMode.value = 'form'
  form.value = mapTemplateToForm(template)
  showEditor.value = true
}

function duplicateTemplate(template) {
  editingTemplate.value = null
  editorMode.value = 'form'
  const mapped = mapTemplateToForm(template)
  form.value = { ...mapped, name: `${template.name} - 副本` }
  showEditor.value = true
}

async function confirmDelete(template) {
  try {
    await ElMessageBox.confirm(`确认删除模板「${template.name}」吗？`, '删除模板', { type: 'warning' })
    await deleteTemplate(template.id)
    selectedIds.value = selectedIds.value.filter((id) => id !== template.id)
    ElMessage.success('模板已删除')
  } catch {
    /* cancelled */
  }
}

async function batchDeleteTemplates() {
  await ElMessageBox.confirm(`确认删除选中的 ${selectedIds.value.length} 个模板吗？`, '批量删除', { type: 'warning' })
  for (const id of [...selectedIds.value]) {
    await deleteTemplate(id)
  }
  selectedIds.value = []
  ElMessage.success('删除完成')
}

function formatDate(date) {
  return date ? dayjs.utc(date).local().fromNow() : '-'
}
</script>

<style scoped>
.templates-view { max-width: 1400px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 32px; }
.title-section h1 { font-size: 28px; font-weight: 600; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); font-size: 14px; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.selected-count { color: var(--text-secondary); font-size: 13px; }
.templates-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
.template-card {
  background: var(--bg-secondary); border: 1px solid var(--border-subtle); border-radius: 16px;
  padding: 20px; cursor: pointer; transition: all 0.2s ease;
}
.template-card:hover { border-color: var(--accent-primary); transform: translateY(-2px); }
.template-header { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }
.template-icon {
  width: 44px; height: 44px; background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 12px; display: flex; align-items: center; justify-content: center; color: white; font-size: 20px;
}
.template-info { flex: 1; }
.template-info h3 { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.node-count { font-size: 12px; color: var(--text-muted); }
.template-description { font-size: 13px; color: var(--text-secondary); margin-bottom: 16px; line-height: 1.5; }
.template-meta { font-size: 11px; color: var(--text-muted); padding-top: 12px; border-top: 1px solid var(--border-subtle); }
.empty-state {
  text-align: center; padding: 80px 40px; background: var(--bg-secondary);
  border-radius: 20px; border: 1px dashed var(--border-subtle);
}
.empty-icon {
  width: 72px; height: 72px; background: var(--bg-tertiary); border-radius: 20px;
  display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; font-size: 32px; color: var(--text-muted);
}
.empty-state h3 { font-size: 18px; margin-bottom: 8px; }
.empty-state p { color: var(--text-secondary); margin-bottom: 24px; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 18px; }
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
.json-hint { color: var(--text-secondary); font-size: 13px; margin-bottom: 12px; }
.json-actions { margin-top: 12px; display: flex; gap: 16px; }
</style>
