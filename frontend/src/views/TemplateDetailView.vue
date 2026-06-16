<template>
  <div class="template-detail">
    <header class="page-header">
      <div class="title-section">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <h1>{{ pageTitle }}</h1>
      </div>
      <div class="header-actions">
        <template v-if="isNew || isEditing">
          <el-button @click="cancelEdit">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitSave">
            {{ isNew ? '创建' : '保存' }}
          </el-button>
        </template>
        <template v-else-if="template">
          <el-button @click="startEdit">
            <el-icon><Edit /></el-icon>
            编辑
          </el-button>
          <el-button type="danger" plain @click="confirmDelete">删除</el-button>
          <el-button type="primary" @click="goCreateInstance">创建实例</el-button>
        </template>
      </div>
    </header>

    <el-alert
      v-if="!isEditing && !isNew"
      type="info"
      :closable="false"
      show-icon
      title="运行参数（命令、端口、宏变量填值等）在创建任务实例时配置。"
      style="margin-bottom: 16px;"
    />

    <div v-if="loading" class="loading-wrap"><el-skeleton :rows="8" animated /></div>

    <TemplateEditorForm
      v-else
      :form="form"
      :workers="workers"
      :readonly="!isEditing && !isNew"
      @add-macro="addMacroDef(form)"
      @remove-macro="(idx) => removeMacroDef(form, idx)"
      @add-node="addTemplateNode(form, workers)"
      @remove-node="(idx) => removeTemplateNode(form, idx)"
      @add-port-def="(idx) => addPortDef(form, idx)"
      @remove-port-def="(n, p) => removePortDef(form, n, p)"
      @add-edge="onAddEdge"
      @remove-edge="(idx) => removeTemplateEdge(form, idx)"
      @abc-topology="applyAbcTopologyToForm(form, workers)"
    />

    <div v-if="template && !isNew && !isEditing" class="meta-footer">
      <span>创建于 {{ formatDate(template.created_at) }}</span>
      <span>{{ template.nodes?.length || 0 }} 个节点</span>
      <span>{{ template.edges?.length || 0 }} 条依赖</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useTemplatesStore } from '@/stores/templates'
import { useNodesStore } from '@/stores/nodes'
import { ElMessage, ElMessageBox } from 'element-plus'
import TemplateEditorForm from '@/components/TemplateEditorForm.vue'
import { extractErrorMessage } from '@/utils/errorMessage'
import {
  emptyTemplateForm,
  mapTemplateToForm,
  buildTemplateFormPayload,
  applyAbcTopologyToForm,
  addMacroDef,
  removeMacroDef,
  addTemplateNode,
  removeTemplateNode,
  addPortDef,
  removePortDef,
  addTemplateEdge,
  removeTemplateEdge,
} from '@/utils/templateForm'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'

dayjs.extend(relativeTime)
dayjs.extend(utc)

const route = useRoute()
const router = useRouter()
const templatesStore = useTemplatesStore()
const nodesStore = useNodesStore()
const { templates } = storeToRefs(templatesStore)
const { nodes: workers } = storeToRefs(nodesStore)

const template = ref(null)
const form = ref(emptyTemplateForm())
const formSnapshot = ref(null)
const loading = ref(true)
const submitting = ref(false)
const isEditing = ref(false)

const isNew = computed(() => route.name === 'TemplateNew')
const pageTitle = computed(() => {
  if (isNew.value) return '新建拓扑模板'
  if (isEditing.value) return `编辑 · ${template.value?.name || ''}`
  return template.value?.name || '拓扑详情'
})

onMounted(async () => {
  await Promise.all([templatesStore.fetchTemplates(), nodesStore.fetchNodes()])
  await loadPage()
})

watch(() => route.fullPath, loadPage)

async function loadPage() {
  loading.value = true
  try {
    if (isNew.value) {
      template.value = null
      form.value = emptyTemplateForm()
      isEditing.value = true
      const duplicateFrom = history.state?.duplicateFrom
      if (duplicateFrom) {
        const detail = await templatesStore.fetchTemplate(duplicateFrom)
        if (detail) {
          form.value = mapTemplateToForm(detail)
          form.value.name = `${detail.name} - 副本`
        }
      }
      return
    }
    const id = route.params.id
    template.value = await templatesStore.fetchTemplate(id)
    if (!template.value) {
      ElMessage.error('模板不存在')
      router.push('/templates')
      return
    }
    form.value = mapTemplateToForm(template.value)
    formSnapshot.value = JSON.stringify(form.value)
    isEditing.value = route.query.edit === '1'
  } finally {
    loading.value = false
  }
}

function startEdit() {
  formSnapshot.value = JSON.stringify(form.value)
  isEditing.value = true
  router.replace({ path: route.path, query: { edit: '1' } })
}

function cancelEdit() {
  if (isNew.value) {
    router.push('/templates')
    return
  }
  form.value = JSON.parse(formSnapshot.value || '{}')
  isEditing.value = false
  router.replace({ path: route.path, query: {} })
}

function goBack() {
  if (isEditing.value && !isNew.value) {
    cancelEdit()
  } else {
    router.push('/templates')
  }
}

function onAddEdge() {
  try {
    addTemplateEdge(form.value)
  } catch (error) {
    ElMessage.warning(error.message)
  }
}

async function submitSave() {
  submitting.value = true
  try {
    const payload = buildTemplateFormPayload(form.value, workers.value, {
      excludeTemplateId: template.value?.id,
      existingTemplates: templates.value,
    })
    if (isNew.value) {
      const created = await templatesStore.createTemplate(payload)
      ElMessage.success('模板已创建')
      router.replace(`/templates/${created.id}`)
    } else {
      await templatesStore.updateTemplate(template.value.id, payload)
      ElMessage.success('模板已保存')
      template.value = await templatesStore.fetchTemplate(template.value.id)
      form.value = mapTemplateToForm(template.value)
      formSnapshot.value = JSON.stringify(form.value)
      isEditing.value = false
      router.replace({ path: route.path, query: {} })
    }
    await templatesStore.fetchTemplates()
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '保存失败'))
  } finally {
    submitting.value = false
  }
}

function goCreateInstance() {
  if (!template.value?.id) return
  router.push({
    path: '/dev/instances',
    query: { create: '1', template_id: template.value.id },
  })
}

async function confirmDelete() {
  if (!template.value?.id) return
  try {
    await ElMessageBox.confirm(`确认删除模板「${template.value.name}」吗？`, '删除模板', { type: 'warning' })
    await templatesStore.deleteTemplate(template.value.id)
    ElMessage.success('模板已删除')
    router.push('/templates')
  } catch {
    /* cancelled */
  }
}

function formatDate(date) {
  return date ? dayjs.utc(date).local().fromNow() : '-'
}
</script>

<style scoped>
.template-detail { max-width: 960px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.title-section { display: flex; align-items: center; gap: 16px; }
.title-section h1 { font-size: 24px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; }
.loading-wrap { padding: 24px; }
.meta-footer {
  display: flex; gap: 20px; margin-top: 24px; padding-top: 16px;
  border-top: 1px solid var(--border-subtle); font-size: 12px; color: var(--text-muted);
}
</style>
