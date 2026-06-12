<template>
  <div class="settings-page">
    <section class="settings-hero">
      <div>
        <p class="eyebrow">系统设置</p>
        <h1>运行环境与系统配置</h1>
        <p>
          在这里区分开发环境和真实环境，并统一管理意图解析、业务测评路由方式与模态优先级。
          面向专家的页面只展示正式流程和结果，配置项集中放在后台维护。
        </p>
      </div>
      <el-tag size="large" type="success">{{ settings.labels?.environment_mode || '真实环境' }}</el-tag>
    </section>

    <el-card class="settings-card" v-loading="loading">
      <template #header>
        <div class="card-header">
          <span>运行模式</span>
          <el-button type="primary" :loading="saving" @click="saveSettings">保存设置</el-button>
        </div>
      </template>

      <el-form label-position="top" class="settings-form">
        <el-form-item label="当前环境">
          <el-radio-group v-model="form.environment_mode">
            <el-radio-button label="production">真实环境</el-radio-button>
            <el-radio-button label="development">开发环境</el-radio-button>
          </el-radio-group>
          <p class="form-hint">
            真实环境用于专家验收和外部路由联调；开发环境用于本地验证、排障和快速回归。
          </p>
        </el-form-item>

        <div class="setting-grid">
          <el-card shadow="never" class="mode-card">
            <h3>意图解析</h3>
            <el-radio-group v-model="form.intent_parser_mode" class="vertical-radio">
              <el-radio label="llm">大模型/智能体解析</el-radio>
              <el-radio label="rule">规则解析（开发）</el-radio>
            </el-radio-group>
            <el-checkbox v-model="form.intent_rule_fallback_enabled">
              大模型不可用时允许规则解析接管
            </el-checkbox>
            <p class="form-hint">
              验收页面统一展示“意图参数解析准确率”。规则解析仅用于开发验证和异常排查，不在专家页面单独暴露为另一套指标。
            </p>
          </el-card>

          <el-card shadow="never" class="mode-card">
            <h3>业务测评路由</h3>
            <el-radio-group v-model="form.benchmark_routing_mode" class="vertical-radio">
              <el-radio label="internal_auto">自动路由</el-radio>
              <el-radio label="external">外部路由系统</el-radio>
            </el-radio-group>
            <p class="form-hint">
              自动路由用于演示部署与评估闭环；外部路由系统用于联调真实路由算法回写节点和 GPU 分配结果。
              业务测评页只展示统一的“运行测评”入口，由系统按当前配置执行。
            </p>
          </el-card>

          <el-card shadow="never" class="mode-card">
            <h3>页面展示</h3>
            <el-switch
              v-model="form.expert_mode"
              active-text="正式展示视图"
              inactive-text="开发调试视图"
            />
            <el-checkbox v-model="form.show_internal_controls">
              显示内部调试信息
            </el-checkbox>
            <p class="form-hint">
              建议正式验收时开启正式展示视图并关闭内部调试信息，让页面聚焦业务目标成功率和工单证据。
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

        <el-form-item label="备注">
          <el-input
            v-model="form.notes"
            type="textarea"
            :rows="3"
            placeholder="记录当前环境、联调对象、演示前置条件等"
          />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="settings-card">
      <template #header>
        <span>正式验收建议</span>
      </template>
      <div class="advice-list">
        <div>
          <strong>业务测评页</strong>
          <span>只展示基线、工单创建、运行测评、成功率统计和任务详情证据，不出现内部实现细节。</span>
        </div>
        <div>
          <strong>基线差距解释</strong>
          <span>若测试值和旧基线差距很大，优先检查 CPU/GPU 口径、镜像版本、节点旧容器和同 GPU 并发争用。</span>
        </div>
        <div>
          <strong>正式截图前</strong>
          <span>清理旧测评实例，按当前业务 profile 重跑 3 次基线，再创建新的验收轮次，确保截图只对应最新轮次。</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

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
  modality_priority_map: { ...DEFAULT_MODALITY_PRIORITY_MAP },
  notes: '',
})

const modalityPriorityRows = computed(() => {
  const rows = settings.value?.modality_priority_rows
  if (Array.isArray(rows) && rows.length) return rows
  return Object.entries(DEFAULT_MODALITY_PRIORITY_MAP).map(([modality, priority]) => ({ modality, priority }))
})

function normalizePriorityMap(value) {
  return {
    ...DEFAULT_MODALITY_PRIORITY_MAP,
    ...(value && typeof value === 'object' ? value : {}),
  }
}

function modalityPriorityHint(modality) {
  return MODALITY_PRIORITY_HINTS[modality] || '供路由系统识别业务流优先级。'
}

function applySettings(data) {
  settings.value = data || {}
  Object.assign(form, {
    environment_mode: data?.environment_mode || 'production',
    intent_parser_mode: data?.intent_parser_mode || 'llm',
    intent_rule_fallback_enabled: data?.intent_rule_fallback_enabled ?? true,
    benchmark_routing_mode: data?.benchmark_routing_mode || 'internal_auto',
    expert_mode: data?.expert_mode ?? true,
    show_internal_controls: data?.show_internal_controls ?? false,
    modality_priority_map: normalizePriorityMap(data?.modality_priority_map),
    notes: data?.notes || '',
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin: 12px 0 18px;
}

.mode-card h3 {
  margin: 0 0 12px;
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
