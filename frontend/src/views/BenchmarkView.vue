<template>
  <div class="benchmark-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">业务目标验收</p>
        <h1>业务目标成功率闭环验证</h1>
        <p class="hero-subtitle">按基线、批量压测、路由执行、成功率统计四步完成专家验收演示；正式判定要求已评估任务 ≥ 30 且成功率 ≥ 90%。</p>
        <div class="run-strip">
          <span>当前验收轮次</span>
          <strong>{{ currentBenchmarkRunId || '历史全部数据' }}</strong>
          <small>{{ currentBenchmarkRunId ? '本页列表、自动执行按钮和结果统计均限定在该轮次。' : '旧数据未带轮次标记，当前按全部历史压测工单统计。' }}</small>
        </div>
      </div>
      <div class="hero-actions">
        <span class="field-label">任务类型</span>
        <el-select v-model="taskType" class="task-select">
          <el-option label="矩阵乘法计算任务" value="high_throughput_matmul" />
          <el-option label="视频AI推理任务" value="low_latency_video_pipeline" />
        </el-select>
        <el-button type="primary" :loading="fullFlowLoading" @click="startFullFlow">
          开始完整测试流程
        </el-button>
      </div>
    </section>

    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">1</span>
          <div>
            <div class="step-title">基线</div>
            <div class="step-desc">直接列出所有可调度节点，未测试节点标红。</div>
          </div>
          <el-button
            class="header-action"
            size="small"
            type="warning"
            plain
            :loading="batchBaselineLoading"
            @click="runBatchBaseline"
          >
            批量测试所有节点
          </el-button>
        </div>
      </template>
      <el-table
        :data="nodeBaselineRows"
        size="small"
        v-loading="nodesLoading || baselinesLoading"
        :row-class-name="baselineRowClass"
      >
        <el-table-column prop="hostname" label="节点" min-width="150" />
        <el-table-column label="基线值" min-width="180">
          <template #default="{ row }">
            <span v-if="row.baseline_value != null" class="baseline-value">
              {{ row.baseline_value.toFixed(2) }} {{ row.unit }}
            </span>
            <el-tag v-else type="danger" size="small">未测试</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="稳定性" min-width="120">
          <template #default="{ row }">
            <el-tag v-if="row.stable === true" type="success" size="small">稳定</el-tag>
            <el-tag v-else-if="row.stable === false" type="warning" size="small">波动大</el-tag>
            <span v-else class="muted">未测试</span>
          </template>
        </el-table-column>
        <el-table-column label="上次更新" min-width="150">
          <template #default="{ row }">{{ row.updated_at ? formatTime(row.updated_at) : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              plain
              :loading="testingNodes.get(row.node_id)"
              @click="runSingleBaseline(row)"
            >
              {{ row.baseline_value != null ? '重测' : '测试' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="excludedNodeRows.length" class="excluded-node-note">
        <strong>未纳入基线的节点：</strong>
        <span v-for="node in excludedNodeRows" :key="node.id">
          {{ node.hostname }}（{{ excludedNodeReason(node) }}）
        </span>
      </div>
    </el-card>

    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">2</span>
          <div>
            <div class="step-title">批量压测</div>
            <div class="step-desc">创建带 is_benchmark 标记的验收工单。</div>
          </div>
        </div>
      </template>
      <div class="pressure-row">
        <div class="pressure-form">
          <span>任务数</span>
          <el-input-number v-model="benchmarkForm.count" :min="1" :max="30" controls-position="right" />
          <template v-if="taskType === 'high_throughput_matmul'">
            <span>矩阵</span>
            <el-input-number v-model="benchmarkForm.matrix_size" :min="256" :step="256" controls-position="right" />
            <span>批次</span>
            <el-input-number v-model="benchmarkForm.batch_count" :min="1" controls-position="right" />
            <span>观测秒数</span>
            <el-input-number v-model="benchmarkForm.observation_duration_sec" :min="0" :max="120" controls-position="right" />
            <span>最少样本</span>
            <el-input-number v-model="benchmarkForm.min_samples" :min="1" :max="30" controls-position="right" />
          </template>
          <template v-else-if="taskType === 'low_latency_video_pipeline'">
            <span>帧数</span>
            <el-input-number v-model="benchmarkForm.frame_count" :min="30" :step="10" controls-position="right" />
            <span>抽帧间隔</span>
            <el-input-number v-model="benchmarkForm.frame_stride" :min="1" controls-position="right" />
            <span>有效帧</span>
            <el-input-number v-model="benchmarkForm.measured_frames" :min="10" :max="300" controls-position="right" />
            <span>计算强度</span>
            <el-input-number v-model="benchmarkForm.work_units" :min="1000" :step="5000" controls-position="right" />
          </template>
          <el-button type="primary" :loading="batchCreateLoading" @click="createBatch">创建压测工单</el-button>
        </div>
        <div class="pending-pill">
          当前待处理工单：<strong>{{ pendingWorkCount }}</strong> 个
        </div>
      </div>
      <p class="metric-note">{{ currentTaskConfig.objectiveText }}</p>
      <p class="status-note">创建压测工单会生成新的验收轮次 ID，后续路由、启动、统计和工单证据表默认只针对这一轮，避免历史数据影响验收截图。</p>
    </el-card>

    <el-card class="step-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">3</span>
          <div>
            <div class="step-title">执行</div>
            <div class="step-desc">实时查看待路由、已路由、运行中和已评估数量；点击自动执行后，系统会按资源槽位分批运行直到本轮完成。</div>
          </div>
          <div class="header-actions">
            <el-button size="small" type="primary" :loading="routeLoading" @click="doAutoRoute">一键路由</el-button>
            <el-button size="small" type="success" :loading="startLoading" @click="doStartAll">自动执行</el-button>
            <el-button size="small" plain @click="loadOrders">刷新</el-button>
          </div>
        </div>
      </template>
      <div class="execution-control-row">
        <span class="control-label">执行槽位设置</span>
        <span>总并发上限</span>
        <el-input-number v-model="executionForm.max_parallel" :min="1" :max="10" controls-position="right" />
        <span>单槽位并发</span>
        <el-input-number v-model="executionForm.per_compute_slot_limit" :min="1" :max="4" controls-position="right" />
        <span class="muted">槽位 = 计算节点 + GPU 编号；正式测评建议单槽位并发 = 1。</span>
      </div>
      <div class="status-grid">
        <div class="status-cell waiting">
          <div class="status-num">{{ executionStats.waitingRoute }}</div>
          <div class="status-label">待路由</div>
        </div>
        <div class="status-cell routed">
          <div class="status-num">{{ executionStats.routed }}</div>
          <div class="status-label">已路由</div>
        </div>
        <div class="status-cell running">
          <div class="status-num">{{ executionStats.running }}</div>
          <div class="status-label">运行中</div>
        </div>
        <div class="status-cell done">
          <div class="status-num">{{ executionStats.completed }}</div>
          <div class="status-label">已评估完成</div>
        </div>
        <div class="status-cell failed">
          <div class="status-num">{{ executionStats.failed }}</div>
          <div class="status-label">失败</div>
        </div>
      </div>
      <p class="status-note">说明：点一次“自动执行”即可自动跑完整轮；系统会按计算节点/GPU 槽位限流，避免批量压测互相抢占资源导致业务目标误判。</p>
      <p v-if="controlledStartStatus" class="status-note strong-note">{{ controlledStartStatus }}</p>
    </el-card>

    <el-card class="step-card evidence-card">
      <template #header>
        <div class="step-header">
          <span class="step-num muted-step">证</span>
          <div>
            <div class="step-title">{{ currentTaskConfig.label }}运行证据</div>
            <div class="step-desc">查看当前任务类型的压测工单、路由放置、实例状态、节点/GPU 分配和业务输入输出，证明任务真实运行。</div>
          </div>
          <div class="header-actions">
            <el-button
              size="small"
              type="warning"
              plain
              :disabled="!selectedOrderIds.length"
              :loading="cleanupLoading"
              @click="cleanupSelectedOrderInstances"
            >
              清理实例保留工单
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!selectedOrderIds.length"
              :loading="deleteLoading"
              @click="deleteSelectedOrders"
            >
              删除选中工单
            </el-button>
            <el-button size="small" plain @click="loadOrders">刷新工单列表</el-button>
          </div>
        </div>
      </template>
      <el-table
        :data="orders"
        size="small"
        empty-text="暂无压测工单"
        @selection-change="handleOrderSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column prop="name" label="工单" min-width="210" show-overflow-tooltip />
        <el-table-column label="任务状态" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ orderStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="路由状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.routing_status === 'completed' ? 'success' : 'warning'">
              {{ routingStatusLabel(row.routing_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="实例状态" width="110">
          <template #default="{ row }">{{ instanceStatusLabel(row.deployment_status || row.instance_status) }}</template>
        </el-table-column>
        <el-table-column label="实例" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">{{ row.materialized_instance_id || '未物化' }}</template>
        </el-table-column>
        <el-table-column label="业务目标判定" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.business_success === true" type="success" size="small">达标</el-tag>
            <el-tag v-else-if="row.business_success === false" type="danger" size="small">未达标</el-tag>
            <el-tag v-else type="info" size="small">未评估</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="实际 / 阈值" min-width="180">
          <template #default="{ row }">
            <span v-if="row.actual_value != null && row.target_value != null">
              {{ formatMetric(row.actual_value, row.unit) }} / {{ formatMetric(row.target_value, row.unit) }}
            </span>
            <span v-else class="muted">等待指标上报</span>
          </template>
        </el-table-column>
        <el-table-column label="指标含义" min-width="150">
          <template #default="{ row }">{{ metricMeaningLabel(row.metric_key) }}</template>
        </el-table-column>
        <el-table-column label="路由放置" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ summarizePlacements(row.runtime_config?.routing_result?.placements) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :loading="detailLoading && selectedOrderId === row.id" @click="openOrderDetail(row)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="step-card result-card">
      <template #header>
        <div class="step-header">
          <span class="step-num">4</span>
          <div>
            <div class="step-title">结果</div>
            <div class="step-desc">业务目标成功率需达到 90%。</div>
          </div>
          <el-button
            class="header-action"
            size="small"
            type="primary"
            plain
            :loading="resultRefreshing"
            @click="refreshAcceptanceResult"
          >
            计算/更新成功率
          </el-button>
        </div>
      </template>
      <div v-if="!summaryAggregate" class="empty-hint">暂无统计数据，完成压测后查看。</div>
      <div v-else class="result-block">
        <div class="result-title">{{ currentTaskConfig.label }}</div>
        <div class="result-meta-grid">
          <div>
            <span>统计口径</span>
            <strong>{{ currentBenchmarkRunId ? '当前验收轮次' : '全部历史压测工单' }}</strong>
          </div>
          <div>
            <span>总工单数</span>
            <strong>{{ summaryAggregate.count }}</strong>
          </div>
          <div>
            <span>已评估数</span>
            <strong>{{ summaryAggregate.evaluated_count }} / {{ formalEvaluationCount }}</strong>
          </div>
          <div>
            <span>看板更新时间</span>
            <strong>{{ dashboardUpdatedAt || '—' }}</strong>
          </div>
        </div>
        <div class="rate-row">
          <el-progress
            class="rate-progress"
            :percentage="successPercent"
            :status="resultProgressStatus"
            :stroke-width="16"
          />
          <div class="rate-text" :class="{ pass: isPassing, fail: !isPassing }">
            {{ successPercent.toFixed(1) }}%
          </div>
        </div>
        <div class="result-detail">
          {{ summaryAggregate.success_count }} / {{ summaryAggregate.evaluated_count }} 任务达标
          <span class="target-text" :class="{ pass: isPassing, fail: !isPassing }">
            目标：≥ 90% 且 ≥ {{ formalEvaluationCount }} 个已评估任务，{{ resultVerdictText }}
          </span>
        </div>
        <div v-if="!hasEnoughEvaluations" class="sample-warning">
          当前已评估 {{ summaryAggregate.evaluated_count }} 个任务，仍不足正式验收所需 {{ formalEvaluationCount }} 个；请完成批量压测后再截图作为最终结果。
        </div>
      </div>
    </el-card>

    <el-drawer v-model="detailDrawerVisible" title="压测工单详情" size="64%">
      <div v-if="!selectedOrderDetail" class="empty-hint">请选择一个工单查看详情。</div>
      <div v-else class="detail-drawer-body">
        <div class="detail-toolbar">
          <div>
            <strong>{{ taskTypeLabel(selectedOrderDetail.task_type) }}</strong>
            <span>{{ detailTaskSummary }}</span>
          </div>
          <el-button type="primary" plain size="small" @click="openBusinessTaskDetail">
            在业务任务中心查看完整详情
          </el-button>
        </div>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="工单 ID">{{ selectedOrderDetail.id }}</el-descriptions-item>
          <el-descriptions-item label="实例 ID">{{ selectedOrderDetail.materialized_instance_id || '未物化' }}</el-descriptions-item>
          <el-descriptions-item label="任务状态">{{ selectedOrderDetail.status }}</el-descriptions-item>
          <el-descriptions-item label="部署状态">{{ selectedOrderDetail.deployment_status || selectedOrderDetail.instance?.status || '—' }}</el-descriptions-item>
          <el-descriptions-item label="业务类型">{{ taskTypeLabel(selectedOrderDetail.task_type) }}</el-descriptions-item>
          <el-descriptions-item label="路由策略">{{ routingPolicyLabel(selectedOrderDetail.routing_policy) }}</el-descriptions-item>
        </el-descriptions>

        <section class="detail-section">
          <h3>实际节点 / GPU 分配</h3>
          <el-table :data="selectedOrderDetail.node_placements || []" size="small" empty-text="暂无节点分配信息">
            <el-table-column prop="role" label="子任务" width="100" />
            <el-table-column prop="hostname" label="物理节点" min-width="140" />
            <el-table-column prop="instance_node_name" label="实例节点" min-width="120" />
            <el-table-column label="GPU" width="90">
              <template #default="{ row }">
                <span :class="{ 'warning-text': isGpuMissingForCompute(row) }">{{ gpuDisplay(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="节点状态" width="110" />
          </el-table>
        </section>

        <section class="detail-section business-proof-card">
          <h3>业务输入与结果展示</h3>
          <p class="proof-summary">{{ detailObjectiveMeaning }}</p>
          <ol class="pipeline-steps">
            <li v-for="step in detailPipelineSteps" :key="step.role">
              <strong>{{ step.role }}</strong>
              <span>{{ step.title }}：{{ step.detail }}</span>
            </li>
          </ol>

          <div class="proof-grid">
            <div>
              <h4>输入参数</h4>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item v-for="row in detailInputRows" :key="row.label" :label="row.label">
                  {{ row.value }}
                </el-descriptions-item>
              </el-descriptions>
            </div>
            <div>
              <h4>计算输出</h4>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item v-for="row in detailOutputRows" :key="row.label" :label="row.label">
                  {{ row.value }}
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </div>

          <div v-if="detailVideoPreview || detailVideoDetections.length" class="benchmark-video-proof">
            <div class="benchmark-video-preview">
              <h4>视频推理分类画框结果</h4>
              <img v-if="detailVideoPreview" :src="detailVideoPreview" alt="视频推理分类画框结果" />
              <el-empty v-else description="等待带框预览图" :image-size="80" />
            </div>
            <div v-if="detailVideoDetections.length" class="benchmark-video-detections">
              <h4>分类检测结果</h4>
              <el-table :data="detailVideoDetections" size="small" border>
                <el-table-column prop="label" label="类别" min-width="120" />
                <el-table-column label="置信度" width="100">
                  <template #default="{ row }">{{ Number(row.confidence || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column label="画框坐标" min-width="180">
                  <template #default="{ row }">{{ Array.isArray(row.bbox_xyxy) ? row.bbox_xyxy.join(', ') : '-' }}</template>
                </el-table-column>
                <el-table-column label="来源" width="110">
                  <template #default="{ row }">
                    <el-tag :type="row.fallback ? 'warning' : 'success'" size="small">
                      {{ row.fallback ? '兜底框' : '模型输出' }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>

          <div v-if="detailParamConsistency" class="consistency-row">
            <el-tag :type="detailParamConsistency.ok ? 'success' : 'warning'" size="small">
              {{ detailParamConsistency.label }}
            </el-tag>
            <span>{{ detailParamConsistency.detail }}</span>
          </div>
          <div class="result-verdict" :class="detailVerdict.statusClass">
            <strong>{{ detailVerdict.title }}</strong>
            <p>{{ detailVerdict.subtitle }}</p>
          </div>
        </section>

        <section class="detail-section">
          <h3>业务目标评估</h3>
          <div v-if="selectedOrderDetail.evaluation" class="metric-grid">
            <div><span>实测指标</span><strong>{{ formatMetric(selectedOrderDetail.evaluation.actual_value, selectedOrderDetail.evaluation.unit) }}</strong></div>
            <div><span>达标阈值</span><strong>{{ formatMetric(selectedOrderDetail.evaluation.target_value, selectedOrderDetail.evaluation.unit) }}</strong></div>
            <div><span>是否达标</span><strong :class="selectedOrderDetail.evaluation.business_success ? 'success-text' : 'danger-text'">{{ selectedOrderDetail.evaluation.business_success ? '达标' : '未达标' }}</strong></div>
            <div><span>指标键</span><strong>{{ selectedOrderDetail.evaluation.metric_key }}</strong></div>
          </div>
          <div v-else class="empty-hint compact">尚未收到业务指标上报，任务完成后会生成评估结果。</div>
        </section>

        <section class="detail-section json-grid">
          <div>
            <h3>业务参数 JSON</h3>
            <pre>{{ prettyJson(selectedOrderDetail.business_task) }}</pre>
          </div>
          <div>
            <h3>提交给路由系统的 DAG JSON</h3>
            <pre>{{ prettyJson(selectedOrderDetail.routing_input_dag) }}</pre>
          </div>
          <div>
            <h3>路由结果 JSON</h3>
            <pre>{{ prettyJson(selectedOrderDetail.routing_result) }}</pre>
          </div>
          <div>
            <h3>指标采集结果 JSON</h3>
            <pre>{{ prettyJson(selectedOrderDetail.evaluation?.result_metadata) }}</pre>
          </div>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { baselinesApi, businessApi, ordersApi, nodesApi } from '@/api'
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
  formatObjectiveSentence,
  taskTypeSummary,
  videoDetections,
  videoPreviewDataUrl,
} from '@/constants/businessTaskDisplay'

const BENCHMARK_RUN_STORAGE_KEY = 'manage-deploy:benchmark-run-id'
const route = useRoute()
const router = useRouter()
const taskConfigs = {
  high_throughput_matmul: {
    label: '矩阵乘法计算任务',
    unit: 'GFLOPS',
    requiresGpu: true,
    objectiveText: '业务目标：计算节点 effective_gflops 不低于该节点同 profile 历史基线的 0.8 倍。',
  },
  low_latency_video_pipeline: {
    label: '视频AI推理任务',
    unit: 'ms',
    requiresGpu: true,
    objectiveText: '业务目标：工业检测抽帧推理的 frame_latency_p90_ms 不高于该节点同 profile 历史基线的 1.5 倍。',
  },
}
const taskType = ref('high_throughput_matmul')
const nodes = ref([])
const nodesLoading = ref(false)
const baselines = ref([])
const baselinesLoading = ref(false)
const orders = ref([])
const summary = ref([])
const testingNodes = ref(new Map())
const batchBaselineLoading = ref(false)
const batchCreateLoading = ref(false)
const routeLoading = ref(false)
const startLoading = ref(false)
const fullFlowLoading = ref(false)
const resultRefreshing = ref(false)
const controlledStartStatus = ref('')
const dashboardUpdatedAt = ref('')
const detailDrawerVisible = ref(false)
const detailLoading = ref(false)
const cleanupLoading = ref(false)
const deleteLoading = ref(false)
const selectedOrderId = ref('')
const selectedOrderIds = ref([])
const selectedOrderDetail = ref(null)
const dataLoadGeneration = ref(0)
const initialBenchmarkRunId = typeof route.query.benchmark_run_id === 'string'
  ? route.query.benchmark_run_id
  : (localStorage.getItem(BENCHMARK_RUN_STORAGE_KEY) || '')
const currentBenchmarkRunId = ref(initialBenchmarkRunId)
const formalEvaluationCount = 30
const benchmarkForm = reactive({
  count: formalEvaluationCount,
  matrix_size: 1024,
  batch_count: 50,
  observation_duration_sec: 10,
  sample_interval_sec: 1,
  sample_batch_count: 5,
  warmup_batches: 3,
  min_samples: 5,
  max_samples: 12,
  frame_count: 100,
  resolution: '720p',
  fps: 30,
  frame_stride: 30,
  warmup_frames: 10,
  measured_frames: 30,
  work_units: 45000,
})
const executionForm = reactive({
  max_parallel: 2,
  per_compute_slot_limit: 1,
})

const currentTaskConfig = computed(() =>
  taskConfigs[taskType.value] || { label: taskType.value, unit: '', objectiveText: '' }
)

const nodeBaselineRows = computed(() =>
  nodes.value.filter(n => n.is_schedulable).map(n => {
    const bl = baselines.value.find(b => b.node_id === n.id)
    return {
      node_id: n.id,
      hostname: n.hostname,
      baseline_value: bl?.baseline_value ?? null,
      unit: bl?.unit || currentTaskConfig.value.unit,
      stable: bl?.stable ?? null,
      updated_at: bl?.updated_at ?? bl?.created_at ?? null,
    }
  })
)

const excludedNodeRows = computed(() =>
  nodes.value.filter(n => !n.is_schedulable || n.node_kind === 'admin')
)

const missingBaselineCount = computed(() =>
  nodeBaselineRows.value.filter(row => row.baseline_value == null || row.stable === false).length
)

const orderStats = computed(() => {
  const stats = { waitingRoute: 0, routed: 0, running: 0, completed: 0, failed: 0 }
  orders.value.forEach(order => {
    const deploymentStatus = order.deployment_status || order.instance_status || ''
    if (order.status === 'failed' || deploymentStatus === 'failed') {
      stats.failed += 1
    } else if (deploymentStatus === 'running' || order.status === 'running') {
      stats.running += 1
    } else if (deploymentStatus === 'stopped' || order.status === 'completed' || order.status === 'stopped') {
      stats.completed += 1
    } else if (order.materialized_instance_id || order.status === 'materialized' || order.routing_status === 'completed') {
      stats.routed += 1
    } else {
      stats.waitingRoute += 1
    }
  })
  return stats
})

const summaryRowsForTask = computed(() =>
  summary.value.filter(row => row.task_type === taskType.value)
)

const summaryAggregate = computed(() => {
  if (!summaryRowsForTask.value.length) return null
  const aggregate = summaryRowsForTask.value.reduce((acc, row) => {
    acc.count += row.count || 0
    acc.evaluated_count += row.evaluated_count || 0
    acc.success_count += row.success_count || 0
    return acc
  }, { count: 0, evaluated_count: 0, success_count: 0 })
  aggregate.business_success_rate = aggregate.evaluated_count
    ? aggregate.success_count / aggregate.evaluated_count
    : null
  return aggregate
})

const executionStats = computed(() => {
  const stats = { ...orderStats.value }
  const aggregate = summaryAggregate.value
  if (!aggregate || !aggregate.count) return stats

  const evaluated = aggregate.evaluated_count || 0
  const total = aggregate.count || 0
  stats.completed = evaluated
  stats.running = Math.max(0, total - evaluated - stats.failed)
  if (evaluated > 0) {
    stats.waitingRoute = 0
    stats.routed = 0
  }
  return stats
})

const pendingWorkCount = computed(() => {
  const aggregate = summaryAggregate.value
  if (aggregate?.count) {
    return Math.max(0, (aggregate.count || 0) - (aggregate.evaluated_count || 0))
  }
  return orderStats.value.waitingRoute + orderStats.value.routed
})

const successPercent = computed(() =>
  summaryAggregate.value?.business_success_rate != null
    ? summaryAggregate.value.business_success_rate * 100
    : 0
)

const hasEnoughEvaluations = computed(() =>
  (summaryAggregate.value?.evaluated_count || 0) >= formalEvaluationCount
)

const isPassing = computed(() =>
  summaryAggregate.value?.business_success_rate != null &&
  summaryAggregate.value.business_success_rate >= 0.9 &&
  hasEnoughEvaluations.value
)

const resultProgressStatus = computed(() =>
  hasEnoughEvaluations.value ? (isPassing.value ? 'success' : 'exception') : 'warning'
)

const resultVerdictText = computed(() =>
  hasEnoughEvaluations.value ? (isPassing.value ? '验收通过' : '未达标') : '样本不足'
)

const detailTaskType = computed(() => selectedOrderDetail.value?.business_task?.task_type || selectedOrderDetail.value?.task_type || '')
const detailTaskSummary = computed(() => taskTypeSummary(detailTaskType.value))
const detailResultMetadata = computed(() => selectedOrderDetail.value?.evaluation?.result_metadata || null)
const detailObjectiveForDisplay = computed(() => {
  const objective = { ...(selectedOrderDetail.value?.business_task?.business_objective || {}) }
  const evaluation = selectedOrderDetail.value?.evaluation
  if (objective.target_value == null && evaluation?.target_value != null) {
    objective.target_value = evaluation.target_value
  }
  if (!objective.unit && evaluation?.unit) {
    objective.unit = evaluation.unit
  }
  if (!objective.operator && evaluation?.metric_key === 'frame_latency_p90_ms') {
    objective.operator = '<='
  }
  if (!objective.operator && evaluation?.metric_key === 'effective_gflops') {
    objective.operator = '>='
  }
  if (!objective.metric_key && evaluation?.metric_key) {
    objective.metric_key = evaluation.metric_key
  }
  return objective
})
const detailObjectiveMeaning = computed(() =>
  describeObjectiveMeaning(detailTaskType.value, detailObjectiveForDisplay.value)
)
const detailPipelineSteps = computed(() => {
  if (detailTaskType.value === 'high_throughput_matmul') return MATMUL_PIPELINE_STEPS
  if (detailTaskType.value === 'low_latency_video_pipeline') return VIDEO_PIPELINE_STEPS
  return [
    { role: 'source', title: '提交输入', detail: '准备业务输入并发送给计算节点' },
    { role: 'compute', title: '执行业务', detail: '按路由结果在指定节点执行计算' },
    { role: 'sink', title: '上报结果', detail: '汇总业务指标并回传平台用于判定' },
  ]
})
const detailInputRows = computed(() => {
  const profile = selectedOrderDetail.value?.business_task?.data_profile
  if (detailTaskType.value === 'high_throughput_matmul') return buildMatmulInputRows(profile)
  if (detailTaskType.value === 'low_latency_video_pipeline') return buildVideoInputRows(profile)
  return describeDataProfile(detailTaskType.value, profile)
})
const detailOutputRows = computed(() => {
  const evaluation = selectedOrderDetail.value?.evaluation
  const meta = detailResultMetadata.value || {}
  if (detailTaskType.value === 'high_throughput_matmul') return buildMatmulOutputRows(meta, evaluation)
  if (detailTaskType.value === 'low_latency_video_pipeline') return buildVideoOutputRows(meta, evaluation)
  if (evaluation) {
    return [{ label: '上报指标', value: `${evaluation.metric_key} = ${Number(evaluation.actual_value).toFixed(2)} ${evaluation.unit || ''}`.trim() }]
  }
  return [{ label: '状态', value: '尚未收到计算输出' }]
})
const detailParamConsistency = computed(() => {
  if (detailTaskType.value === 'high_throughput_matmul') {
    return buildMatmulParamConsistency(
      selectedOrderDetail.value?.business_task?.data_profile,
      detailResultMetadata.value
    )
  }
  return null
})
const detailVerdict = computed(() => {
  const evaluation = selectedOrderDetail.value?.evaluation
  if (detailTaskType.value === 'high_throughput_matmul') return buildMatmulVerdict(evaluation)
  if (detailTaskType.value === 'low_latency_video_pipeline') return buildVideoVerdict(evaluation)
  if (!evaluation) {
    return {
      title: '等待业务结果',
      subtitle: '任务运行并上报指标后，将在这里展示输入、输出和业务目标判定。',
      statusClass: 'pending',
    }
  }
  const actual = Number(evaluation.actual_value).toFixed(2)
  const unit = evaluation.unit || ''
  const target = evaluation.target_value != null ? Number(evaluation.target_value).toFixed(2) : '-'
  return {
    title: evaluation.business_success ? '业务已完成，目标达标' : '业务已完成，目标未达标',
    subtitle: evaluation.business_success
      ? `实际 ${actual} ${unit}，满足 ${formatObjectiveSentence({ metric_key: evaluation.metric_key, operator: evaluation.metric_key === 'frame_latency_p90_ms' ? '<=' : '>=', target_value: target, unit })}。`
      : (evaluation.failure_reason || `实际 ${actual} ${unit}，未达到目标 ${target} ${unit}。`),
    statusClass: evaluation.business_success ? 'success' : 'danger',
  }
})
const detailVideoPreview = computed(() => videoPreviewDataUrl(detailResultMetadata.value))
const detailVideoDetections = computed(() => videoDetections(detailResultMetadata.value))

function formatTime(value) {
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function taskTypeLabel(value) {
  if (taskConfigs[value]) return taskConfigs[value].label
  if (value === 'text_model_training') return '文本模型训练任务'
  return value || '—'
}

function formatMetric(value, unit = '') {
  if (value == null) return '—'
  const numeric = Number(value)
  const text = Number.isFinite(numeric) ? numeric.toFixed(2) : String(value)
  return `${text} ${unit || ''}`.trim()
}

function metricMeaningLabel(metricKey) {
  const labels = {
    effective_gflops: '计算速率',
    frame_latency_p90_ms: 'P90 帧推理时延',
    frame_latency_avg_ms: '平均帧推理时延',
    tokens_per_second: '生成吞吐',
    samples_per_second: '训练吞吐',
  }
  return labels[metricKey] || metricKey || '尚未上报'
}

function orderStatusLabel(value) {
  const labels = {
    pending: '待提交',
    routing: '路由中',
    routed: '已路由',
    materialized: '已物化',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[value] || value || '—'
}

function routingStatusLabel(value) {
  const labels = {
    not_required: '无需路由',
    pending: '待路由',
    computing: '计算中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[value] || value || '—'
}

function instanceStatusLabel(value) {
  const labels = {
    pending: '待启动',
    scheduled: '已调度',
    starting: '启动中',
    running: '运行中',
    stopping: '停止中',
    stopped: '已停止',
    failed: '失败',
    expired: '已过期',
  }
  return labels[value] || value || '—'
}

function requiresGpu(row) {
  const config = taskConfigs[detailTaskType.value]
  return Boolean(config?.requiresGpu) && row?.role === 'compute'
}

function hasGpuValue(value) {
  return value !== null && value !== undefined && String(value) !== ''
}

function selectedGpuValue(row) {
  if (hasGpuValue(row?.gpu_device)) return row.gpu_device
  if (hasGpuValue(row?.gpu_id)) return row.gpu_id
  return null
}

function isGpuMissingForCompute(row) {
  return requiresGpu(row) && !hasGpuValue(selectedGpuValue(row))
}

function gpuDisplay(row) {
  const gpu = selectedGpuValue(row)
  if (hasGpuValue(gpu)) return gpu
  if (requiresGpu(row)) return '未记录（GPU任务）'
  return '不需要'
}

function summarizePlacements(placements) {
  if (!placements) return '待路由'
  if (Array.isArray(placements)) {
    return placements.map(p => {
      const gpu = p.gpu_device != null ? ` GPU ${p.gpu_device}` : ''
      return `${p.node_id || p.role}:${p.worker_host || p.node_name || p.node_id}${gpu}`
    }).join(' / ')
  }
  if (typeof placements === 'object') {
    return Object.entries(placements).map(([role, placement]) => {
      if (typeof placement === 'string') return `${role}:${placement}`
      const node = placement?.node_name || placement?.worker_host || placement?.node_id || '—'
      const gpu = placement?.gpu_device != null
        ? ` GPU ${placement.gpu_device}`
        : Array.isArray(placement?.gpu_indices) && placement.gpu_indices.length
        ? ` GPU ${placement.gpu_indices.join(',')}`
        : ''
      return `${role}:${node}${gpu}`
    }).join(' / ')
  }
  return String(placements)
}

function prettyJson(value) {
  if (!value) return '暂无数据'
  return JSON.stringify(value, null, 2)
}

function baselineRowClass({ row }) {
  if (row.baseline_value == null) return 'baseline-missing-row'
  if (row.stable === false) return 'baseline-unstable-row'
  return ''
}

function excludedNodeReason(node) {
  if (node.node_kind === 'admin') return '管理节点不参与业务调度'
  if (node.is_schedulable === false) return '不可调度或 Node Agent 不可达'
  return '未纳入当前业务调度'
}

function handleOrderSelectionChange(rows) {
  selectedOrderIds.value = rows.map(row => row.id).filter(Boolean)
}

function buildDataLoadSnapshot() {
  return {
    generation: dataLoadGeneration.value,
    taskType: taskType.value,
    benchmarkRunId: currentBenchmarkRunId.value,
  }
}

function isCurrentDataLoad(snapshot) {
  return snapshot.generation === dataLoadGeneration.value &&
    snapshot.taskType === taskType.value &&
    snapshot.benchmarkRunId === currentBenchmarkRunId.value
}

function isGeneratedBenchmarkRunId(runId) {
  return Object.keys(taskConfigs).some(task => runId.startsWith(`${task}-`))
}

async function loadNodes() {
  nodesLoading.value = true
  try {
    const { data } = await nodesApi.list()
    nodes.value = data
  } finally {
    nodesLoading.value = false
  }
}

async function loadBaselines() {
  const snapshot = buildDataLoadSnapshot()
  baselinesLoading.value = true
  try {
    const { data } = await baselinesApi.list({ task_type: taskType.value })
    if (!isCurrentDataLoad(snapshot)) return
    baselines.value = data
  } finally {
    baselinesLoading.value = false
  }
}

async function loadOrders() {
  const snapshot = buildDataLoadSnapshot()
  const params = { is_benchmark: true, task_type: taskType.value, limit: 100 }
  if (currentBenchmarkRunId.value) {
    params.benchmark_run_id = currentBenchmarkRunId.value
  }
  const { data } = await ordersApi.list(params)
  if (!isCurrentDataLoad(snapshot)) return
  orders.value = Array.isArray(data) ? data : (data.items || [])
  if (!currentBenchmarkRunId.value) {
    const latestRunId = orders.value.find(order => order.runtime_config?.benchmark?.run_id)
      ?.runtime_config?.benchmark?.run_id
    if (latestRunId) {
      setCurrentBenchmarkRunId(latestRunId)
      await loadOrders()
    }
  }
}

async function loadSummary() {
  const snapshot = buildDataLoadSnapshot()
  const params = { is_benchmark: true, task_type: taskType.value }
  if (currentBenchmarkRunId.value) {
    params.benchmark_run_id = currentBenchmarkRunId.value
  }
  const { data } = await businessApi.summary(params)
  if (!isCurrentDataLoad(snapshot)) return
  summary.value = data
  dashboardUpdatedAt.value = formatTime(new Date())
}

async function refreshAcceptanceResult() {
  resultRefreshing.value = true
  try {
    await Promise.all([loadOrders(), loadSummary()])
    ElMessage.success('已更新工单指标并重新计算业务目标成功率')
  } finally {
    resultRefreshing.value = false
  }
}

function newBenchmarkRunId() {
  const now = new Date()
  const pad = value => String(value).padStart(2, '0')
  const stamp = [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    pad(now.getHours()),
    pad(now.getMinutes()),
    pad(now.getSeconds()),
  ].join('')
  return `${taskType.value}-${stamp}`
}

function setCurrentBenchmarkRunId(runId) {
  dataLoadGeneration.value += 1
  currentBenchmarkRunId.value = runId || ''
  if (runId) {
    localStorage.setItem(BENCHMARK_RUN_STORAGE_KEY, runId)
  } else {
    localStorage.removeItem(BENCHMARK_RUN_STORAGE_KEY)
  }
  const nextQuery = { ...route.query }
  if (runId) {
    nextQuery.benchmark_run_id = runId
  } else {
    delete nextQuery.benchmark_run_id
  }
  router.replace({ query: nextQuery }).catch(() => {})
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function loadAll() {
  await Promise.all([loadNodes(), loadBaselines()])
  await loadOrders()
  await loadSummary()
}

async function runSingleBaseline(row) {
  testingNodes.value = new Map(testingNodes.value.set(row.node_id, true))
  try {
    const { data } = await baselinesApi.run({ node_id: row.node_id, task_type: taskType.value, runs: 3 })
    ElMessage.success(`基线测试完成：${data.baseline_value?.toFixed(2)} ${data.unit || ''}`)
    await loadBaselines()
  } finally {
    testingNodes.value = new Map(testingNodes.value.set(row.node_id, false))
  }
}

async function runBatchBaseline() {
  batchBaselineLoading.value = true
  try {
    const { data } = await baselinesApi.batchRun({ task_type: taskType.value, runs: 3 })
    ElMessage.success(`批量基线测试完成：${data.succeeded} 个节点成功${data.failed ? `，${data.failed} 个失败` : ''}`)
    await loadBaselines()
  } finally {
    batchBaselineLoading.value = false
  }
}

async function createBatch() {
  batchCreateLoading.value = true
  try {
    const runId = newBenchmarkRunId()
    const { data } = await ordersApi.batchBenchmark({
      task_type: taskType.value,
      count: benchmarkForm.count,
      benchmark_run_id: runId,
      data_profile: buildBenchmarkDataProfile(),
    })
    setCurrentBenchmarkRunId(data.benchmark_run_id || runId)
    ElMessage.success(`已创建 ${data.created} 条压测工单`)
    await Promise.all([loadOrders(), loadSummary()])
    return data
  } finally {
    batchCreateLoading.value = false
  }
}

function buildBenchmarkDataProfile() {
  if (taskType.value === 'low_latency_video_pipeline') {
    return {
      profile_id: 'video_industrial_inspection_720p',
      frame_count: benchmarkForm.frame_count,
      resolution: benchmarkForm.resolution,
      fps: benchmarkForm.fps,
      frame_stride: benchmarkForm.frame_stride,
      warmup_frames: benchmarkForm.warmup_frames,
      measured_frames: benchmarkForm.measured_frames,
      work_units: benchmarkForm.work_units,
      video_asset: 'bottle-detection.mp4',
      inference_mode: 'yolo_onnx',
      model_name: 'yolov5n',
      model_path: 'models/yolov5n.onnx',
      class_names_path: 'models/coco.names',
      confidence_threshold: 0.25,
      nms_threshold: 0.45,
      max_detections: 8,
      seed: 42,
    }
  }
  return {
    profile_id: 'gpu_standard',
    matrix_size: benchmarkForm.matrix_size,
    batch_count: benchmarkForm.batch_count,
    seed: 42,
    warmup_batches: benchmarkForm.warmup_batches,
    observation_duration_sec: benchmarkForm.observation_duration_sec,
    sample_interval_sec: benchmarkForm.sample_interval_sec,
    sample_batch_count: benchmarkForm.sample_batch_count,
    min_samples: benchmarkForm.min_samples,
    max_samples: benchmarkForm.max_samples,
  }
}

async function openOrderDetail(row) {
  selectedOrderId.value = row.id
  detailLoading.value = true
  try {
    const { data } = await ordersApi.get(row.id)
    selectedOrderDetail.value = data
    detailDrawerVisible.value = true
  } finally {
    detailLoading.value = false
  }
}

async function cleanupSelectedOrderInstances() {
  if (!selectedOrderIds.value.length) return
  cleanupLoading.value = true
  try {
    const { data } = await ordersApi.cleanupInstances(selectedOrderIds.value)
    ElMessage.success(`已清理 ${data.succeeded?.length || 0} 个工单实例，工单证据已保留`)
    await Promise.all([loadOrders(), loadSummary()])
  } finally {
    cleanupLoading.value = false
  }
}

async function deleteSelectedOrders() {
  if (!selectedOrderIds.value.length) return
  try {
    await ElMessageBox.confirm(
      `将删除 ${selectedOrderIds.value.length} 个压测工单及其关联实例，删除后不再参与成功率统计，继续吗？`,
      '确认删除工单',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  deleteLoading.value = true
  try {
    const { data } = await ordersApi.batchDelete(selectedOrderIds.value)
    ElMessage.success(`已删除 ${data.succeeded?.length || 0} 个工单`)
    selectedOrderIds.value = []
    await Promise.all([loadOrders(), loadSummary()])
  } finally {
    deleteLoading.value = false
  }
}

function openBusinessTaskDetail() {
  if (!selectedOrderDetail.value?.id) return
  router.push({ path: '/business-tasks', query: { orderId: selectedOrderDetail.value.id } })
}

async function doAutoRoute() {
  routeLoading.value = true
  try {
    const { data } = await ordersApi.batchAutoRoute({
      benchmark_run_id: currentBenchmarkRunId.value || null,
      task_type: taskType.value,
    })
    ElMessage.success(`已路由 ${data.routed} 条工单${data.failed?.length ? `，${data.failed.length} 条失败` : ''}`)
    await loadOrders()
    return data
  } finally {
    routeLoading.value = false
  }
}

async function doStartAll() {
  if (!currentBenchmarkRunId.value) {
    ElMessage.warning('请先创建或选择一个验收轮次，再启动执行。')
    return null
  }
  startLoading.value = true
  controlledStartStatus.value = '正在自动按节点/GPU 槽位分批执行验收任务...'
  try {
    let latest = null
    for (let round = 1; round <= 180; round += 1) {
      const { data } = await ordersApi.startControlledRouted({
        benchmark_run_id: currentBenchmarkRunId.value,
        task_type: taskType.value,
        max_parallel: executionForm.max_parallel,
        per_compute_slot_limit: executionForm.per_compute_slot_limit,
        cleanup_evaluated: true,
      })
      latest = data
      await Promise.all([loadOrders(), loadSummary()])
      const total = Number(data.total || summaryAggregate.value?.count || 0)
      const evaluated = Number(data.evaluated || summaryAggregate.value?.evaluated_count || 0)
      const active = Number(data.active || 0)
      const started = Number(data.started || 0)
      const cleaned = Number(data.cleaned || 0)
      controlledStartStatus.value = `自动执行中：已评估 ${evaluated}/${total}，本轮启动 ${started} 个，运行中 ${active} 个，已释放实例 ${cleaned} 个。`

      if (total > 0 && evaluated >= total) {
        ElMessage.success(`本轮 ${evaluated} 个验收任务已全部完成评估`)
        break
      }
      if (!started && !active && !Number(data.pending_to_start || 0)) {
        ElMessage.warning('当前没有可继续启动的验收任务，请检查失败原因或重新路由。')
        break
      }
      await sleep(started ? 2500 : 5000)
    }
    await Promise.all([loadOrders(), loadSummary()])
    return latest
  } finally {
    startLoading.value = false
  }
}

async function startFullFlow() {
  await loadAll()
  if (missingBaselineCount.value > 0) {
    ElMessage.warning(`还有 ${missingBaselineCount.value} 个节点缺少稳定基线，请先完成 Step 1。`)
    return
  }
  fullFlowLoading.value = true
  try {
    await createBatch()
    await doAutoRoute()
    await doStartAll()
    ElMessage.success('完整测试流程已执行完成，请查看 Step 4 成功率和工单证据。')
  } finally {
    fullFlowLoading.value = false
  }
}

watch(taskType, async () => {
  dataLoadGeneration.value += 1
  selectedOrderDetail.value = null
  detailDrawerVisible.value = false
  if (
    currentBenchmarkRunId.value &&
    isGeneratedBenchmarkRunId(currentBenchmarkRunId.value) &&
    !currentBenchmarkRunId.value.startsWith(`${taskType.value}-`)
  ) {
    setCurrentBenchmarkRunId('')
  }
  await Promise.all([loadBaselines(), loadOrders(), loadSummary()])
})
onMounted(loadAll)
</script>

<style scoped>
.benchmark-page {
  padding: 28px;
  max-width: 1120px;
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: center;
  padding: 26px 28px;
  margin-bottom: 22px;
  border: 1px solid #dcdfe6;
  border-radius: 14px;
  background: linear-gradient(135deg, #f7fbff 0%, #ffffff 48%, #f8faf4 100%);
  box-shadow: 0 12px 30px rgba(40, 62, 90, 0.06);
}

.eyebrow {
  margin: 0 0 6px;
  color: #409eff;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.hero-card h1 {
  margin: 0;
  font-size: 26px;
  font-weight: 800;
  line-height: 1.2;
  color: #1f2d3d;
  letter-spacing: 0.01em;
}

.hero-subtitle {
  margin: 8px 0 0;
  color: #606266;
}

.run-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(64, 158, 255, 0.08);
  color: #425466;
  font-size: 13px;
}

.run-strip strong {
  color: #1f2d3d;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.run-strip small {
  color: #606266;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.field-label {
  color: #606266;
  font-size: 14px;
}

.task-select {
  width: 220px;
}

.step-card {
  margin-bottom: 18px;
  border-radius: 12px;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.muted-step {
  background: #606266;
  font-size: 13px;
}

.step-title {
  font-size: 16px;
  font-weight: 700;
}

.step-desc {
  margin-top: 2px;
  color: #909399;
  font-size: 12px;
}

.header-action,
.header-actions {
  margin-left: auto;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.baseline-value {
  font-weight: 700;
  color: #303133;
}

:deep(.baseline-missing-row) {
  background: #fff4f2;
}

:deep(.baseline-unstable-row) {
  background: #fff9ec;
}

.muted {
  color: #c0c4cc;
}

.excluded-node-note {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f5f7fa;
  color: #606266;
  font-size: 12px;
}

.excluded-node-note strong {
  color: #303133;
}

.pressure-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}

.pressure-form {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: #606266;
}

.pressure-form :deep(.el-input-number) {
  width: 118px;
}

.pending-pill {
  padding: 9px 14px;
  border-radius: 999px;
  background: #f5f7fa;
  color: #606266;
  font-size: 14px;
}

.pending-pill strong {
  color: #303133;
}

.execution-control-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: #f8fbff;
  color: #606266;
  font-size: 13px;
}

.execution-control-row :deep(.el-input-number) {
  width: 118px;
}

.control-label {
  padding: 5px 9px;
  border-radius: 999px;
  background: #ecf5ff;
  color: #1d4ed8;
  font-weight: 700;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 14px;
}

.status-note {
  margin: 12px 0 0;
  color: #606266;
  font-size: 12px;
}

.strong-note {
  color: #1f6f43;
  font-weight: 600;
}

.status-cell {
  padding: 18px 16px;
  border-radius: 12px;
  text-align: center;
  background: #f5f7fa;
}

.status-cell.waiting {
  background: #fff7e6;
}

.status-cell.routed {
  background: #ecf5ff;
}

.status-cell.running {
  background: #f0f9eb;
}

.status-cell.done {
  background: #eef8f4;
}

.status-cell.failed {
  background: #fef0f0;
}

.status-num {
  font-size: 32px;
  font-weight: 800;
  line-height: 1;
}

.status-label {
  margin-top: 8px;
  color: #606266;
  font-size: 13px;
}

.result-card :deep(.el-card__body) {
  padding: 30px 34px;
}

.result-block {
  max-width: 720px;
  margin: 0 auto;
}

.result-title {
  margin-bottom: 18px;
  font-size: 18px;
  font-weight: 800;
  text-align: center;
}

.result-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}

.result-meta-grid div {
  padding: 12px;
  border-radius: 10px;
  background: #f5f7fa;
  text-align: center;
}

.result-meta-grid span {
  display: block;
  color: #909399;
  font-size: 12px;
}

.result-meta-grid strong {
  display: block;
  margin-top: 5px;
  color: #303133;
  font-size: 14px;
}

.rate-row {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 18px;
}

.rate-progress {
  width: 100%;
}

.rate-text {
  min-width: 96px;
  font-size: 34px;
  font-weight: 900;
  text-align: right;
}

.rate-text.pass,
.target-text.pass {
  color: #67c23a;
}

.rate-text.fail,
.target-text.fail {
  color: #f56c6c;
}

.result-detail {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-top: 14px;
  color: #606266;
  font-size: 14px;
}

.target-text {
  font-weight: 700;
}

.sample-warning {
  margin-top: 10px;
  color: #b88230;
  font-size: 13px;
}

.empty-hint {
  text-align: center;
  color: #909399;
  padding: 28px 0;
}

.empty-hint.compact {
  padding: 10px 0;
  text-align: left;
}

.detail-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 14px 16px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: linear-gradient(135deg, #eff6ff 0%, #ffffff 100%);
}

.detail-toolbar strong,
.detail-toolbar span {
  display: block;
}

.detail-toolbar span {
  margin-top: 4px;
  color: #606266;
  font-size: 13px;
}

.detail-section h3 {
  margin: 0 0 10px;
  color: #303133;
  font-size: 15px;
}

.business-proof-card {
  padding: 16px;
  border: 1px solid #ebeef5;
  border-radius: 12px;
  background: #fffdf7;
}

.proof-summary {
  margin: 0 0 12px;
  color: #606266;
  line-height: 1.6;
}

.pipeline-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0 0 14px;
  padding: 0;
  list-style: none;
}

.pipeline-steps li {
  padding: 12px;
  border: 1px solid #f3d19e;
  border-radius: 10px;
  background: #fffaf0;
}

.pipeline-steps strong {
  display: block;
  margin-bottom: 4px;
  color: #b88230;
}

.pipeline-steps span {
  color: #606266;
  font-size: 13px;
}

.proof-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.proof-grid h4 {
  margin: 0 0 8px;
  color: #303133;
}

.benchmark-video-proof {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.15fr);
  gap: 16px;
  align-items: start;
  margin-top: 16px;
}

.benchmark-video-proof h4 {
  margin: 0 0 8px;
  color: #303133;
}

.benchmark-video-preview {
  min-width: 0;
}

.benchmark-video-preview img {
  display: block;
  width: 100%;
  border: 1px solid #dcdfe6;
  border-radius: 10px;
  background: #111827;
}

.benchmark-video-detections {
  min-width: 0;
}

.consistency-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 12px;
  color: #606266;
}

.result-verdict {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid #dcdfe6;
  background: #f8fafc;
}

.result-verdict strong {
  display: block;
}

.result-verdict p {
  margin: 6px 0 0;
  color: #606266;
}

.result-verdict.success {
  border-color: #b3e19d;
  background: #f0f9eb;
}

.result-verdict.danger {
  border-color: #fab6b6;
  background: #fef0f0;
}

.result-verdict.warning,
.result-verdict.pending {
  border-color: #f3d19e;
  background: #fdf6ec;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-grid div {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fafcff;
}

.metric-grid span {
  display: block;
  color: #909399;
  font-size: 12px;
}

.metric-grid strong {
  display: block;
  margin-top: 6px;
  color: #303133;
}

.success-text {
  color: #67c23a !important;
}

.danger-text {
  color: #f56c6c !important;
}

.warning-text {
  color: #e6a23c;
  font-weight: 700;
}

.json-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.json-grid div:last-child {
  grid-column: 1 / -1;
}

.json-grid pre {
  max-height: 280px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-radius: 10px;
  background: #1f2933;
  color: #e5edf5;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .benchmark-page {
    padding: 18px;
  }

  .hero-card {
    align-items: flex-start;
    flex-direction: column;
  }

  .hero-actions {
    justify-content: flex-start;
  }

  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .rate-row {
    grid-template-columns: 1fr;
  }

  .rate-text {
    text-align: left;
  }

  .result-detail {
    flex-direction: column;
  }

  .result-meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-grid,
  .json-grid,
  .proof-grid,
  .benchmark-video-proof,
  .pipeline-steps {
    grid-template-columns: 1fr;
  }

  .json-grid div:last-child {
    grid-column: auto;
  }
}
</style>
