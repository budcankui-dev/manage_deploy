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
        <el-button type="primary" @click="openCreatePage">
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
                <el-dropdown-item @click.stop="editTemplate(template.id)">编辑</el-dropdown-item>
                <el-dropdown-item @click.stop="duplicateTemplate(template.id)">复制</el-dropdown-item>
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
      <el-button type="primary" @click="openCreatePage">
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
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useTemplatesStore } from '@/stores/templates'
import { ElMessageBox, ElMessage } from 'element-plus'
import { templateToImportJson } from '@/utils/deployJson'
import { extractErrorMessage } from '@/utils/errorMessage'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'

dayjs.extend(relativeTime)
dayjs.extend(utc)

const router = useRouter()
const templatesStore = useTemplatesStore()
const { templates } = storeToRefs(templatesStore)
const { fetchTemplates, deleteTemplate } = templatesStore

const selectedIds = ref([])
const currentPage = ref(1)
const pageSize = ref(8)

const paginatedTemplates = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return (templates.value || []).slice(start, start + pageSize.value)
})

onMounted(fetchTemplates)

function openCreatePage() {
  router.push('/templates/new')
}

function toggleSelected(id) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function viewTemplate(id) {
  router.push(`/templates/${id}`)
}

function editTemplate(id) {
  router.push({ path: `/templates/${id}`, query: { edit: '1' } })
}

function duplicateTemplate(id) {
  router.push({ path: '/templates/new', state: { duplicateFrom: id } })
}

async function exportTemplateJson(template) {
  const detail = template.nodes?.length ? template : await templatesStore.fetchTemplate(template.id)
  if (!detail) return
  const text = templateToImportJson(detail)
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('模板 JSON 已复制到剪贴板')
  } catch {
    ElMessage.info(text)
  }
}

async function confirmDelete(template) {
  try {
    await ElMessageBox.confirm(`确认删除模板「${template.name}」吗？`, '删除模板', { type: 'warning' })
    await deleteTemplate(template.id, { silentError: true })
    selectedIds.value = selectedIds.value.filter((id) => id !== template.id)
    ElMessage.success('模板已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(extractErrorMessage(error, '删除模板失败'))
  }
}

async function batchDeleteTemplates() {
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${selectedIds.value.length} 个模板吗？`, '批量删除', { type: 'warning' })
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    throw error
  }

  const byId = Object.fromEntries((templates.value || []).map((item) => [item.id, item.name]))
  const failed = []
  let succeeded = 0
  for (const id of [...selectedIds.value]) {
    try {
      await deleteTemplate(id, { silentError: true })
      selectedIds.value = selectedIds.value.filter((selectedId) => selectedId !== id)
      succeeded += 1
    } catch (error) {
      failed.push({
        name: byId[id] || id,
        reason: extractErrorMessage(error, '删除失败'),
      })
    }
  }

  if (!failed.length) {
    ElMessage.success(`删除完成：${succeeded} 个模板`)
    return
  }
  ElMessage.warning(`已删除 ${succeeded} 个，${failed.length} 个未删除`)
  ElMessageBox.alert(
    failed.map((item) => `「${item.name}」：${item.reason}`).join('\n'),
    '未删除的模板',
    { type: 'warning' }
  )
}

function formatDate(date) {
  return date ? dayjs(date).fromNow() : '-'
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
</style>
