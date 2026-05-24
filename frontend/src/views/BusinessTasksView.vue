<template>
  <div class="business-view">
    <header class="page-header">
      <div>
        <h1>业务任务与指标</h1>
        <p class="subtitle">面向意图解析/路由系统的标准任务接入、业务目标评估和结果文件查询。</p>
      </div>
      <div class="actions">
        <el-button @click="loadSummary">刷新统计</el-button>
        <el-button type="primary" @click="submitSample">提交示例业务任务</el-button>
      </div>
    </header>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card>
          <template #header>按任务类型和路由策略统计</template>
          <el-table :data="summary" size="small" v-loading="loading">
            <el-table-column prop="task_type" label="任务类型" min-width="190" />
            <el-table-column prop="routing_strategy" label="路由策略" min-width="160" />
            <el-table-column prop="count" label="数量" width="80" />
            <el-table-column label="成功率" width="120">
              <template #default="{ row }">{{ percent(row.business_success_rate) }}</template>
            </el-table-column>
            <el-table-column label="平均估算误差" width="130">
              <template #default="{ row }">{{ row.avg_estimation_error_ratio == null ? '-' : percent(row.avg_estimation_error_ratio) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>实例结果查询</template>
          <el-input v-model="instanceId" placeholder="输入 instance_id 查询评估和结果文件">
            <template #append>
              <el-button @click="loadInstanceResult">查询</el-button>
            </template>
          </el-input>
          <el-descriptions v-if="evaluation" :column="1" border class="result-box">
            <el-descriptions-item label="任务类型">{{ evaluation.task_type }}</el-descriptions-item>
            <el-descriptions-item label="业务指标">{{ evaluation.metric_key }}</el-descriptions-item>
            <el-descriptions-item label="实际/目标">{{ evaluation.actual_value }} / {{ evaluation.target_value }} {{ evaluation.unit || '' }}</el-descriptions-item>
            <el-descriptions-item label="是否成功">
              <el-tag :type="evaluation.business_success ? 'success' : 'danger'">
                {{ evaluation.business_success ? '成功' : '失败' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <el-table v-if="objects.length" :data="objects" size="small" class="result-box">
            <el-table-column prop="name" label="文件名" />
            <el-table-column prop="uri" label="对象 URI" min-width="260" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { businessApi } from '@/api'

const loading = ref(false)
const summary = ref([])
const instanceId = ref('')
const evaluation = ref(null)
const objects = ref([])

const sampleTask = {
  external_task_id: `intent-${Date.now()}`,
  task_type: 'low_latency_video_pipeline',
  modality: 'low_latency_forwarding',
  name: '低时延视频随路处理示例',
  data_profile: {
    profile_id: 'video_720p_frame_stream',
    source: 'preset',
    dataset: 'demo_videos',
    file: 'traffic_720p_5s.mp4'
  },
  business_objective: {
    metric_key: 'end_to_end_latency_ms',
    operator: '<=',
    target_value: 200,
    unit: 'ms'
  },
  runtime_plan: {
    codec: 'h264',
    preset: 'ultrafast',
    process_mode: 'streaming'
  },
  routing_result: {
    strategy: 'completion_time_first',
    placements: {
      source: 'node-a-id',
      compute: 'node-b-id',
      sink: 'node-c-id'
    },
    estimated_metric: {
      metric_key: 'end_to_end_latency_ms',
      metric_value: 180,
      unit: 'ms'
    }
  },
  result_storage: {
    backend: 'minio',
    bucket: 'task-results'
  },
  auto_start: false
}

onMounted(loadSummary)

function percent(value) {
  return value == null ? '-' : `${(Number(value) * 100).toFixed(1)}%`
}

async function loadSummary() {
  loading.value = true
  try {
    const { data } = await businessApi.summary()
    summary.value = data
  } finally {
    loading.value = false
  }
}

async function loadInstanceResult() {
  if (!instanceId.value) return
  const [evaluationResp, objectsResp] = await Promise.all([
    businessApi.evaluation(instanceId.value),
    businessApi.results(instanceId.value)
  ])
  evaluation.value = evaluationResp.data
  objects.value = objectsResp.data
}

async function submitSample() {
  await businessApi.submit({ ...sampleTask, external_task_id: `intent-${Date.now()}` })
  ElMessage.success('示例任务已提交。请确认模板目录和节点 ID 已按环境配置。')
  await loadSummary()
}
</script>

<style scoped>
.business-view {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.subtitle {
  color: var(--text-secondary);
}

.actions {
  display: flex;
  gap: 10px;
}

.result-box {
  margin-top: 16px;
}
</style>
