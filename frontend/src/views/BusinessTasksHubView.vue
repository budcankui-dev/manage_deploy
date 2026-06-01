<template>
  <div class="hub-view">
    <header class="page-header">
      <div>
        <h1>业务工单中心</h1>
        <p class="subtitle">管理业务部署请求、工单状态与业务目标评估。</p>
      </div>
      <div class="actions">
        <el-button @click="refreshAll">刷新</el-button>
        <el-button type="primary" plain :loading="demoRunning" @click="submitSample">
          一键演示矩阵乘法
        </el-button>
      </div>
    </header>

    <div class="success-rate-card" v-if="totalEvaluated > 0">
      <div class="rate-number" :class="{ pass: totalSuccessRate >= 90, fail: totalSuccessRate < 90 }">
        {{ totalSuccessRate.toFixed(1) }}%
      </div>
      <div class="rate-label">业务目标成功率（{{ totalSuccessCount }}/{{ totalEvaluated }}）</div>
    </div>

    <el-collapse v-model="summaryOpen">
      <el-collapse-item title="按任务类型和路由策略统计" name="summary">
        <el-table :data="summary" size="small" v-loading="summaryLoading">
          <el-table-column prop="task_type" label="任务类型" min-width="180" />
          <el-table-column label="路由策略" min-width="140">
            <template #default="{ row }">{{ routingPolicyLabel(row.routing_strategy) }}</template>
          </el-table-column>
          <el-table-column prop="count" label="工单数" width="80" />
          <el-table-column label="已评估" width="80">
            <template #default="{ row }">{{ row.evaluated_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="成功率" min-width="140">
            <template #default="{ row }">
              <span v-if="row.business_success_rate == null">-</span>
              <span v-else>{{ successRateLabel(row) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>

    <el-collapse v-model="baselineOpen" style="margin-bottom: 16px">
      <el-collapse-item title="节点基线性能" name="baseline">
        <div style="margin-bottom: 8px; display: flex; gap: 8px; align-items: center">
          <el-select v-model="baselineFilter.node_id" placeholder="筛选节点" clearable style="width: 180px" @change="loadBaselines">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname || n.display_name" :value="n.id" />
          </el-select>
          <el-button size="small" type="primary" plain @click="showBaselineDialog = true">新增基线</el-button>
          <el-button size="small" type="success" plain @click="showRunBaselineDialog = true">运行基线测试</el-button>
        </div>
        <el-table :data="baselines" size="small" v-loading="baselinesLoading" empty-text="暂无基线数据">
          <el-table-column prop="node_hostname" label="节点" width="140" />
          <el-table-column prop="task_type" label="任务类型" width="200" />
          <el-table-column prop="metric_key" label="指标" width="160" />
          <el-table-column label="基线值" width="120">
            <template #default="{ row }">{{ row.baseline_value?.toFixed(2) }} {{ row.unit || '' }}</template>
          </el-table-column>
          <el-table-column prop="operator" label="方向" width="60">
            <template #default="{ row }">{{ row.operator === '>=' ? '越高越好' : '越低越好' }}</template>
          </el-table-column>
          <el-table-column prop="run_count" label="测试次数" width="80" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button size="small" type="danger" text @click="deleteBaseline(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>

    <section class="card">
      <div class="card-header">
        <h2>工单列表</h2>
        <div class="filters">
          <el-input v-model="filters.q" placeholder="搜索名称/任务ID" clearable style="width: 200px" @keyup.enter="loadList" />
          <el-select v-model="filters.task_type" placeholder="任务类型" clearable style="width: 180px" @change="loadList">
            <el-option v-for="t in taskTypeOptions" :key="t" :label="t" :value="t" />
          </el-select>
          <el-select v-model="filters.routing_policy" placeholder="路由策略" clearable style="width: 150px" @change="loadList">
            <el-option v-for="(label, key) in ROUTING_POLICY_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select v-model="filters.order_status" placeholder="工单状态" clearable style="width: 130px" @change="loadList">
            <el-option v-for="(label, key) in ORDER_STATUS_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select v-model="filters.deployment_status" placeholder="部署状态" clearable style="width: 130px" @change="loadList">
            <el-option v-for="(label, key) in DEPLOYMENT_STATUS_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select v-model="filters.business_success" placeholder="性能达标" clearable style="width: 120px" @change="loadList">
            <el-option label="达标" :value="true" />
            <el-option label="未达标" :value="false" />
          </el-select>
          <el-checkbox v-model="filters.include_cancelled" @change="loadList">显示已取消</el-checkbox>
        </div>
      </div>

      <el-table :data="items" size="small" v-loading="listLoading">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="任务类型" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tooltip v-if="row.task_type" :content="row.task_type" placement="top">
              <span class="task-type-cell">{{ taskTypeLabel(row.task_type) }}</span>
            </el-tooltip>
            <span v-else>-</span>
            <small v-if="row.task_type && taskTypeLabel(row.task_type) !== row.task_type" class="task-type-code">{{ row.task_type }}</small>
          </template>
        </el-table-column>
        <el-table-column label="路由策略" min-width="130">
          <template #default="{ row }">{{ routingPolicyLabel(row.routing_policy) }}</template>
        </el-table-column>
        <el-table-column label="工单状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="orderStatusTag(row.order_status)">{{ ORDER_STATUS_LABELS[row.order_status] || row.order_status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="部署状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.instance_exists === false" size="small" type="warning">实例已删除</el-tag>
            <el-tag v-else-if="row.deployment_status" size="small" :type="deploymentStatusTag(row.deployment_status)">
              {{ DEPLOYMENT_STATUS_LABELS[row.deployment_status] || row.deployment_status }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="目标 / 实际" min-width="160">
          <template #default="{ row }">
            <span v-if="row.target_value != null">
              {{ formatMetric(row.actual_value) }} / {{ formatMetric(row.target_value) }} {{ row.unit || '' }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="性能达标" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.business_success === true" type="success" size="small">达标</el-tag>
            <el-tag v-else-if="row.business_success === false" type="danger" size="small">超标</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="业务指标" min-width="160">
          <template #default="{ row }">
            <span v-if="row.target_value != null">{{ metricMeaningLabel(row) }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="调度开始" min-width="150">
          <template #default="{ row }">
            {{ row.scheduled_start_time ? dayjs(row.scheduled_start_time).format('MM-DD HH:mm') : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="调度结束" min-width="150">
          <template #default="{ row }">
            {{ row.scheduled_end_time ? dayjs(row.scheduled_end_time).format('MM-DD HH:mm') : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="关联实例" width="120">
          <template #default="{ row }">
            <template v-if="row.instance_id && row.instance_exists !== false">
              <el-button link type="primary" @click="$router.push(`/dev/instances/${row.instance_id}`)">
                查看实例
              </el-button>
            </template>
            <el-tag v-else-if="row.instance_id && row.instance_exists === false" size="small" type="warning">
              实例已删除
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row.order_id)">详情</el-button>
            <el-button
              v-if="row.order_status === 'pending' && !row.instance_id"
              link
              type="warning"
              @click="openManualRouting(row)"
            >手动路由</el-button>
            <el-button
              v-if="row.instance_id && row.instance_exists !== false && canStart(row.deployment_status)"
              link
              type="success"
              @click="startInstance(row.instance_id)"
            >启动</el-button>
            <el-button
              v-if="row.instance_id && row.instance_exists !== false && row.deployment_status === 'running'"
              link
              type="warning"
              @click="stopInstance(row.instance_id)"
            >停止</el-button>
            <el-button link type="danger" @click="deleteOrder(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="total" class="pagination-wrap">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[10, 20, 50]"
          :total="total"
          @current-change="loadList"
          @size-change="loadList"
        />
      </div>
    </section>

    <el-drawer v-model="drawerOpen" :title="detailTitle" size="62%" destroy-on-close class="task-detail-drawer">
      <el-tabs v-model="detailTab" v-loading="detailLoading" class="detail-tabs">
        <el-tab-pane label="业务" name="business">
          <template v-if="orderDetail?.business_task">
            <p v-if="detailTaskSummary" class="task-summary">{{ detailTaskSummary }}</p>
            <el-descriptions :column="1" border class="detail-desc">
              <el-descriptions-item label="外部任务ID">{{ orderDetail.external_task_id || '-' }}</el-descriptions-item>
              <el-descriptions-item label="任务类型">{{ taskTypeLabel(orderDetail.business_task.task_type) }}</el-descriptions-item>
              <el-descriptions-item label="模态">{{ orderDetail.business_task.modality || '-' }}</el-descriptions-item>
              <el-descriptions-item label="描述">{{ orderDetail.description || orderDetail.business_task.description || '-' }}</el-descriptions-item>
            </el-descriptions>

            <h3 class="section-title">数据画像</h3>
            <el-descriptions v-if="detailDataProfileRows.length" :column="1" border class="detail-desc">
              <el-descriptions-item v-for="row in detailDataProfileRows" :key="row.label" :label="row.label">
                {{ row.value }}
              </el-descriptions-item>
            </el-descriptions>
            <el-collapse v-if="orderDetail.business_task.data_profile" class="raw-collapse">
              <el-collapse-item title="原始 JSON" name="data_profile">
                <pre class="json-block">{{ pretty(orderDetail.business_task.data_profile) }}</pre>
              </el-collapse-item>
            </el-collapse>

            <h3 class="section-title">业务目标</h3>
            <div class="objective-card">
              <p class="objective-headline">{{ detailObjectiveSentence }}</p>
              <p class="objective-meaning">{{ detailObjectiveMeaning }}</p>
            </div>
            <el-collapse v-if="orderDetail.business_task.business_objective" class="raw-collapse">
              <el-collapse-item title="原始 JSON" name="objective">
                <pre class="json-block">{{ pretty(orderDetail.business_task.business_objective) }}</pre>
              </el-collapse-item>
            </el-collapse>

            <h3 class="section-title">运行计划</h3>
            <el-descriptions v-if="detailRuntimePlanRows.length" :column="1" border class="detail-desc">
              <el-descriptions-item v-for="row in detailRuntimePlanRows" :key="row.label" :label="row.label">
                {{ row.value }}
              </el-descriptions-item>
            </el-descriptions>
            <el-collapse v-if="orderDetail.business_task.runtime_plan" class="raw-collapse">
              <el-collapse-item title="原始 JSON" name="runtime_plan">
                <pre class="json-block">{{ pretty(orderDetail.business_task.runtime_plan) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </template>
          <el-empty v-else description="无业务任务数据" />
        </el-tab-pane>

        <el-tab-pane label="路由" name="routing">
          <template v-if="orderDetail?.routing_result">
            <el-descriptions :column="1" border class="detail-desc">
              <el-descriptions-item label="路由策略">
                {{ routingPolicyLabel(orderDetail.routing_result.strategy || orderDetail.routing_result.routing_policy) }}
              </el-descriptions-item>
            </el-descriptions>
            <h3 class="section-title">节点放置</h3>
            <el-table :data="placementRows" size="small">
              <el-table-column prop="role" label="角色" width="120" />
              <el-table-column prop="node_id" label="节点 ID" min-width="220" />
            </el-table>
          </template>
          <el-empty v-else description="无路由结果" />
        </el-tab-pane>

        <el-tab-pane label="部署" name="deployment">
          <template v-if="orderDetail?.instance">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="实例 ID">{{ orderDetail.instance.id }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="deploymentStatusTag(orderDetail.instance.status)">
                  {{ DEPLOYMENT_STATUS_LABELS[orderDetail.instance.status] || orderDetail.instance.status }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="节点数">{{ orderDetail.instance.node_count }}</el-descriptions-item>
              <el-descriptions-item label="错误">{{ orderDetail.instance.error_message || '-' }}</el-descriptions-item>
            </el-descriptions>
            <div class="deploy-actions">
              <el-button v-if="canStart(instanceDetail?.status)" type="primary" @click="startInstance(orderDetail.instance.id)">启动</el-button>
              <el-button v-if="instanceDetail?.status === 'running'" type="warning" @click="stopInstance(orderDetail.instance.id)">停止</el-button>
              <el-button
                v-if="orderDetail.instance.id"
                @click="$router.push(`/dev/instances/${orderDetail.instance.id}`)"
              >完整实例页</el-button>
            </div>
            <h3 class="section-title">节点列表</h3>
            <el-table v-if="instanceDetail?.nodes?.length" :data="instanceDetail.nodes" size="small">
              <el-table-column prop="name" label="节点" width="120" />
              <el-table-column prop="status" label="状态" width="100" />
              <el-table-column prop="image" label="镜像" min-width="180" />
              <el-table-column prop="container_id" label="容器" min-width="160" />
            </el-table>
            <div v-if="instanceDetail?.nodes?.length" style="margin-top: 12px">
              <h4 style="margin-bottom: 8px">端口访问</h4>
              <el-table :data="portAccessRows" size="small" border>
                <el-table-column prop="nodeName" label="子任务" width="100" />
                <el-table-column prop="portName" label="端口名" width="100" />
                <el-table-column label="访问地址" min-width="240">
                  <template #default="{ row }">
                    <code style="font-size: 12px">{{ row.accessUrl }}</code>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
          <el-empty v-else description="尚未部署实例" />
        </el-tab-pane>

        <el-tab-pane label="结果" name="result">
          <template v-if="isMatmulDetail">
            <h3 class="section-title">本任务在做什么</h3>
            <p class="task-summary">{{ detailTaskSummary }}</p>
            <ol class="pipeline-steps">
              <li v-for="step in matmulPipelineSteps" :key="step.role">
                <strong>{{ step.role }}</strong> — {{ step.title }}：{{ step.detail }}
              </li>
            </ol>

            <h3 class="section-title">输入参数</h3>
            <el-descriptions v-if="detailMatmulInputRows.length" :column="1" border class="detail-desc">
              <el-descriptions-item v-for="row in detailMatmulInputRows" :key="row.label" :label="row.label">
                {{ row.value }}
              </el-descriptions-item>
            </el-descriptions>

            <h3 class="section-title">计算输出</h3>
            <el-descriptions v-if="detailMatmulOutputRows.length" :column="1" border class="detail-desc">
              <el-descriptions-item v-for="row in detailMatmulOutputRows" :key="row.label" :label="row.label">
                {{ row.value }}
              </el-descriptions-item>
            </el-descriptions>

            <div v-if="detailMatmulConsistency" class="consistency-row">
              <el-tag :type="detailMatmulConsistency.ok ? 'success' : 'warning'" size="small">
                {{ detailMatmulConsistency.label }}
              </el-tag>
              <span class="consistency-detail">{{ detailMatmulConsistency.detail }}</span>
            </div>

            <h3 class="section-title">性能验收</h3>
            <div class="result-verdict" :class="detailMatmulVerdict.statusClass">
              <strong>{{ detailMatmulVerdict.title }}</strong>
              <p>{{ detailMatmulVerdict.subtitle }}</p>
            </div>
          </template>
          <template v-else-if="orderDetail?.evaluation">
            <div class="result-verdict" :class="resultVerdictClass">
              <strong>{{ resultVerdictTitle }}</strong>
              <p>{{ resultVerdictSubtitle }}</p>
            </div>
            <el-descriptions :column="1" border class="detail-desc">
              <el-descriptions-item label="指标">{{ orderDetail.evaluation.metric_key }}</el-descriptions-item>
              <el-descriptions-item label="实际 / 目标">
                {{ orderDetail.evaluation.actual_value }} / {{ orderDetail.evaluation.target_value }} {{ orderDetail.evaluation.unit || '' }}
              </el-descriptions-item>
              <el-descriptions-item label="性能达标">
                <el-tag :type="orderDetail.evaluation.business_success ? 'success' : 'danger'">
                  {{ orderDetail.evaluation.business_success ? '达标' : '未达标' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item v-if="orderDetail.evaluation.failure_reason" label="失败原因">
                {{ orderDetail.evaluation.failure_reason }}
              </el-descriptions-item>
            </el-descriptions>
          </template>
          <el-empty v-else description="任务尚未跑完或未上报业务指标" />
          <el-collapse v-if="resultObjects.length" class="raw-collapse">
            <el-collapse-item title="结果文件 URI" name="result_files">
              <el-table :data="resultObjects" size="small">
                <el-table-column prop="name" label="文件名" />
                <el-table-column prop="uri" label="URI" min-width="260" />
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <!-- 手动路由对话框 -->
    <el-dialog v-model="manualRoutingVisible" title="手动分配路由" width="520px" destroy-on-close>
      <p style="margin-bottom:12px">为任务 <strong>{{ manualRoutingOrder?.name || '未命名' }}</strong> 分配计算节点</p>
      <el-form label-width="100px" size="small">
        <el-form-item label="数据源节点">
          <el-select v-model="manualPlacements.source.worker_host" placeholder="选择节点" :disabled="manualPlacements.source.skip_deploy" clearable style="width:200px">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.hostname" />
          </el-select>
          <el-checkbox v-model="manualPlacements.source.skip_deploy" style="margin-left:12px">不部署</el-checkbox>
        </el-form-item>
        <el-form-item label="计算节点">
          <el-select v-model="manualPlacements.worker.worker_host" placeholder="选择节点" style="width:200px">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.hostname" />
          </el-select>
          <el-input v-model="manualPlacements.worker.gpu_device" placeholder="GPU编号" style="width:80px;margin-left:8px" />
        </el-form-item>
        <el-form-item label="汇总节点">
          <el-select v-model="manualPlacements.sink.worker_host" placeholder="选择节点" :disabled="manualPlacements.sink.skip_deploy" clearable style="width:200px">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.hostname" />
          </el-select>
          <el-checkbox v-model="manualPlacements.sink.skip_deploy" style="margin-left:12px">不部署</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualRoutingVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualRoutingLoading" @click="submitManualRouting">确认分配</el-button>
      </template>
    </el-dialog>

    <!-- 运行基线测试对话框 -->
    <el-dialog v-model="showRunBaselineDialog" title="运行基线测试" width="440px" destroy-on-close>
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        在后端本地运行基准测试（矩阵乘法），计算 effective_gflops 中位数作为基线值。
      </el-alert>
      <el-form :model="runBaselineForm" label-width="90px" size="small">
        <el-form-item label="节点">
          <el-select v-model="runBaselineForm.node_id" placeholder="选择节点" style="width:100%">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="runBaselineForm.task_type" style="width:100%">
            <el-option label="矩阵乘法计算任务" value="high_throughput_matmul" />
          </el-select>
        </el-form-item>
        <el-form-item label="运行次数">
          <el-input-number v-model="runBaselineForm.runs" :min="1" :max="10" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRunBaselineDialog = false">取消</el-button>
        <el-button type="primary" :loading="runBaselineLoading" @click="runBaseline">开始测试</el-button>
      </template>
    </el-dialog>

    <!-- 新增基线对话框 -->
    <el-dialog v-model="showBaselineDialog" title="新增节点基线" width="440px" destroy-on-close>
      <el-form :model="newBaseline" label-width="90px" size="small">
        <el-form-item label="节点">
          <el-select v-model="newBaseline.node_id" placeholder="选择节点" style="width:100%">
            <el-option v-for="n in nodes" :key="n.id" :label="n.hostname" :value="n.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务类型">
          <el-input v-model="newBaseline.task_type" placeholder="如 high_throughput_matmul" />
        </el-form-item>
        <el-form-item label="指标">
          <el-input v-model="newBaseline.metric_key" placeholder="如 effective_gflops" />
        </el-form-item>
        <el-form-item label="基线值">
          <el-input-number v-model="newBaseline.baseline_value" :precision="2" :min="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="方向">
          <el-select v-model="newBaseline.operator" style="width:100%">
            <el-option label=">= (越大越好)" value=">=" />
            <el-option label="<= (越小越好)" value="<=" />
          </el-select>
        </el-form-item>
        <el-form-item label="单位">
          <el-input v-model="newBaseline.unit" placeholder="如 GFLOPS" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showBaselineDialog = false">取消</el-button>
        <el-button type="primary" @click="createBaseline">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'
import { businessApi, baselinesApi, instancesApi, nodesApi, ordersApi } from '@/api'
import {
  DEPLOYMENT_STATUS_LABELS,
  ORDER_STATUS_LABELS,
  ROUTING_POLICY_LABELS,
  routingPolicyLabel,
} from '@/constants/routingPolicy'
import {
  MATMUL_PIPELINE_STEPS,
  buildMatmulInputRows,
  buildMatmulOutputRows,
  buildMatmulParamConsistency,
  buildMatmulVerdict,
  describeDataProfile,
  describeObjectiveMeaning,
  describeRuntimePlan,
  formatObjectiveSentence,
  taskTypeLabel,
  taskTypeSummary,
} from '@/constants/businessTaskDisplay'

const route = useRoute()
const router = useRouter()
const demoRunning = ref(false)
const summaryOpen = ref(['summary'])
const baselineOpen = ref([])
const baselines = ref([])
const baselinesLoading = ref(false)
const baselineFilter = reactive({ node_id: '' })
const showBaselineDialog = ref(false)
const showRunBaselineDialog = ref(false)
const runBaselineLoading = ref(false)
const runBaselineForm = reactive({
  node_id: '',
  task_type: 'high_throughput_matmul',
  runs: 3,
})
const summary = ref([])
const summaryLoading = ref(false)
const listLoading = ref(false)
const detailLoading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const nodes = ref([])

const filters = reactive({
  q: '',
  task_type: '',
  routing_policy: '',
  order_status: '',
  deployment_status: '',
  business_success: '',
  include_cancelled: false,
})

const drawerOpen = ref(false)
const detailTab = ref('business')
const orderDetail = ref(null)
const instanceDetail = ref(null)
const resultObjects = ref([])

const taskTypeOptions = computed(() => {
  const fromSummary = summary.value.map((row) => row.task_type).filter(Boolean)
  const fromList = items.value.map((row) => row.task_type).filter(Boolean)
  return [...new Set([...fromSummary, ...fromList])]
})

const totalEvaluated = computed(() => summary.value.reduce((s, r) => s + (r.evaluated_count || 0), 0))
const totalSuccessCount = computed(() => summary.value.reduce((s, r) => s + (r.success_count || 0), 0))
const totalSuccessRate = computed(() => totalEvaluated.value > 0 ? (totalSuccessCount.value / totalEvaluated.value) * 100 : 0)

const detailTitle = computed(() => orderDetail.value?.name || '任务详情')

const manualRoutingVisible = ref(false)
const manualRoutingOrder = ref(null)
const manualRoutingLoading = ref(false)
const manualPlacements = ref({
  source: { worker_host: '', gpu_device: null, skip_deploy: false },
  worker: { worker_host: '', gpu_device: '0', skip_deploy: false },
  sink: { worker_host: '', gpu_device: null, skip_deploy: false },
})

const newBaseline = reactive({
  node_id: '',
  task_type: 'high_throughput_matmul',
  metric_key: 'effective_gflops',
  baseline_value: 0,
  operator: '>=',
  unit: 'GFLOPS',
})

const placementRows = computed(() => {
  const placements = orderDetail.value?.routing_result?.placements || {}
  return Object.entries(placements).map(([role, node_id]) => ({ role, node_id }))
})

const portAccessRows = computed(() => {
  if (!instanceDetail.value?.nodes) return []
  const rows = []
  for (const node of instanceDetail.value.nodes) {
    const addr = node.business_address || ''
    for (const [name, port] of Object.entries(node.port_values || {})) {
      rows.push({
        nodeName: node.name,
        portName: name,
        accessUrl: addr ? (addr.includes(':') ? `http://[${addr}]:${port}` : `http://${addr}:${port}`) : `*:${port}`,
      })
    }
  }
  return rows
})

const detailTaskType = computed(() => orderDetail.value?.business_task?.task_type || '')
const detailTaskSummary = computed(() => taskTypeSummary(detailTaskType.value))
const detailObjectiveSentence = computed(() =>
  formatObjectiveSentence(orderDetail.value?.business_task?.business_objective)
)
const detailObjectiveMeaning = computed(() =>
  describeObjectiveMeaning(detailTaskType.value, orderDetail.value?.business_task?.business_objective)
)
const detailDataProfileRows = computed(() =>
  describeDataProfile(detailTaskType.value, orderDetail.value?.business_task?.data_profile)
)
const detailRuntimePlanRows = computed(() =>
  describeRuntimePlan(detailTaskType.value, orderDetail.value?.business_task?.runtime_plan)
)
const isMatmulDetail = computed(() => detailTaskType.value === 'high_throughput_matmul')
const matmulPipelineSteps = MATMUL_PIPELINE_STEPS
const detailMatmulInputRows = computed(() =>
  buildMatmulInputRows(orderDetail.value?.business_task?.data_profile)
)
const detailMatmulOutputRows = computed(() =>
  buildMatmulOutputRows(
    orderDetail.value?.evaluation?.result_metadata,
    orderDetail.value?.evaluation
  )
)
const detailMatmulConsistency = computed(() =>
  buildMatmulParamConsistency(
    orderDetail.value?.business_task?.data_profile,
    orderDetail.value?.evaluation?.result_metadata
  )
)
const detailMatmulVerdict = computed(() => buildMatmulVerdict(orderDetail.value?.evaluation))
const resultVerdictClass = computed(() => {
  const evaluation = orderDetail.value?.evaluation
  if (!evaluation) return 'pending'
  return evaluation.business_success ? 'success' : 'danger'
})
const resultVerdictTitle = computed(() => {
  const evaluation = orderDetail.value?.evaluation
  if (!evaluation) return '等待计算结果'
  return evaluation.business_success ? '耗时已达标' : '耗时未达标'
})
const resultVerdictSubtitle = computed(() => {
  const evaluation = orderDetail.value?.evaluation
  if (!evaluation) {
    return '任务跑完并上报指标后，将在此展示是否达标。'
  }
  if (evaluation.business_success) {
    return `实际 ${evaluation.actual_value} ${evaluation.unit || ''}，满足目标 ${formatObjectiveSentence(orderDetail.value?.business_task?.business_objective)}。`
  }
  return evaluation.failure_reason || '未满足业务目标阈值。'
})

onMounted(async () => {
  await refreshAll()
  const orderId = route.query.orderId
  if (typeof orderId === 'string' && orderId) {
    await openDetail(orderId, 'result')
    router.replace({ query: {} })
  }
})

watch(
  () => route.query.orderId,
  async (orderId) => {
    if (typeof orderId === 'string' && orderId) {
      await openDetail(orderId, 'result')
      router.replace({ query: {} })
    }
  }
)

watch(baselineOpen, (val) => {
  if (val.includes('baseline') && baselines.value.length === 0) {
    loadBaselines()
  }
})

function percent(value) {
  return value == null ? '-' : `${(Number(value) * 100).toFixed(1)}%`
}

function successRateLabel(row) {
  const rate = percent(row.business_success_rate)
  const evaluated = row.evaluated_count ?? 0
  const success = row.success_count ?? 0
  return `${rate}（${success}/${evaluated}）`
}

function formatMetric(value) {
  return value == null ? '-' : Number(value)
}

function metricMeaningLabel(row) {
  const METRIC_LABELS = {
    compute_latency_ms: '计算耗时',
    end_to_end_latency_ms: '端到端时延',
    effective_gflops: '有效算力',
    tokens_per_second: '推理吞吐',
    frame_latency_p90_ms: '帧延迟P90',
  }
  return METRIC_LABELS[row.metric_key] || row.metric_key || '指标'
}

function formatTime(value) {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-'
}

function pretty(value) {
  if (value == null) return '-'
  return JSON.stringify(value, null, 2)
}

function orderStatusTag(status) {
  return { pending: 'info', materialized: 'success', failed: 'danger', cancelled: 'warning' }[status] || 'info'
}

function deploymentStatusTag(status) {
  return {
    pending: 'info',
    scheduled: 'info',
    starting: 'warning',
    running: 'success',
    stopping: 'warning',
    stopped: 'info',
    failed: 'danger',
    expired: 'warning',
  }[status] || 'info'
}

function canStart(status) {
  return ['pending', 'stopped', 'failed'].includes(status)
}

async function refreshAll() {
  await Promise.all([loadSummary(), loadList(), loadNodes()])
}

async function loadBaselines() {
  baselinesLoading.value = true
  try {
    const params = {}
    if (baselineFilter.node_id) params.node_id = baselineFilter.node_id
    const { data } = await baselinesApi.list(params)
    baselines.value = data
  } finally {
    baselinesLoading.value = false
  }
}

async function deleteBaseline(row) {
  await ElMessageBox.confirm(`确认删除 ${row.node_hostname} / ${row.task_type} 的基线？`, '删除确认')
  await baselinesApi.delete(row.id)
  ElMessage.success('已删除')
  await loadBaselines()
}

async function createBaseline() {
  if (!newBaseline.node_id || !newBaseline.task_type || !newBaseline.metric_key) {
    ElMessage.warning('请填写完整信息')
    return
  }
  try {
    await baselinesApi.create({ ...newBaseline })
    ElMessage.success('基线已创建')
    showBaselineDialog.value = false
    await loadBaselines()
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning('该节点/任务类型/指标的基线已存在')
    }
  }
}

async function runBaseline() {
  if (!runBaselineForm.node_id) {
    ElMessage.warning('请选择节点')
    return
  }
  runBaselineLoading.value = true
  try {
    const { data } = await baselinesApi.run({ ...runBaselineForm })
    ElMessage.success(`基线测试完成: ${data.baseline_value?.toFixed(2)} ${data.unit || ''}`)
    showRunBaselineDialog.value = false
    await loadBaselines()
  } catch (e) {
    // error handled by interceptor
  } finally {
    runBaselineLoading.value = false
  }
}

async function loadSummary() {
  summaryLoading.value = true
  try {
    const { data } = await businessApi.summary()
    summary.value = data
  } finally {
    summaryLoading.value = false
  }
}

async function loadNodes() {
  const { data } = await nodesApi.list()
  nodes.value = data
}

async function loadList() {
  listLoading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      include_cancelled: filters.include_cancelled,
    }
    if (filters.q) params.q = filters.q
    if (filters.task_type) params.task_type = filters.task_type
    if (filters.routing_policy) params.routing_policy = filters.routing_policy
    if (filters.order_status) params.order_status = filters.order_status
    if (filters.deployment_status) params.deployment_status = filters.deployment_status
    if (filters.business_success !== '' && filters.business_success != null) {
      params.business_success = filters.business_success
    }
    const { data } = await businessApi.list(params)
    items.value = data.items
    total.value = data.total
  } finally {
    listLoading.value = false
  }
}

async function openDetail(orderId, tab = 'business') {
  drawerOpen.value = true
  detailTab.value = tab
  detailLoading.value = true
  orderDetail.value = null
  instanceDetail.value = null
  resultObjects.value = []
  try {
    const { data } = await ordersApi.get(orderId)
    orderDetail.value = data
    if (data.instance?.id) {
      const [instResp, objectsResp] = await Promise.all([
        instancesApi.get(data.instance.id),
        businessApi.results(data.instance.id).catch(() => ({ data: [] })),
      ])
      instanceDetail.value = instResp.data
      resultObjects.value = objectsResp.data
    }
  } finally {
    detailLoading.value = false
  }
}

async function startInstance(instanceId) {
  await instancesApi.start(instanceId)
  ElMessage.success('实例已启动')
  await refreshAll()
  if (orderDetail.value?.instance?.id === instanceId) {
    await openDetail(orderDetail.value.id)
  }
}

async function stopInstance(instanceId) {
  await instancesApi.stop(instanceId)
  ElMessage.success('实例已停止')
  await refreshAll()
  if (orderDetail.value?.instance?.id === instanceId) {
    await openDetail(orderDetail.value.id)
  }
}

async function deleteOrder(row) {
  const { order_id, instance_id, instance_exists } = row
  if (instance_id && instance_exists !== false) {
    try {
      await ElMessageBox.confirm(
        '删除工单的同时会删除对应的部署实例，继续吗？',
        '确认删除',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
      )
    } catch {
      return
    }
  }
  await ordersApi.delete(order_id)
  ElMessage.success('工单已删除')
  drawerOpen.value = false
  await refreshAll()
}

function openManualRouting(row) {
  manualRoutingOrder.value = row
  manualPlacements.value = {
    source: { worker_host: '', gpu_device: null, skip_deploy: false },
    worker: { worker_host: '', gpu_device: '0', skip_deploy: false },
    sink: { worker_host: '', gpu_device: null, skip_deploy: false },
  }
  manualRoutingVisible.value = true
}

async function submitManualRouting() {
  if (!manualPlacements.value.worker.worker_host) {
    ElMessage.warning('Worker 节点必须选择')
    return
  }
  manualRoutingLoading.value = true
  try {
    const placements = ['source', 'worker', 'sink']
      .filter(role => !manualPlacements.value[role].skip_deploy && manualPlacements.value[role].worker_host)
      .map(role => ({
        node_id: role,
        worker_host: manualPlacements.value[role].worker_host,
        gpu_device: manualPlacements.value[role].gpu_device || null,
      }))
    await ordersApi.submitRoutingResult(manualRoutingOrder.value.order_id, { placements })
    ElMessage.success('路由分配成功，实例已创建')
    manualRoutingVisible.value = false
    await refreshAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '路由分配失败')
  } finally {
    manualRoutingLoading.value = false
  }
}

async function waitForEvaluation(instanceId, maxAttempts = 80, intervalMs = 3000) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const { data } = await businessApi.evaluation(instanceId)
      if (data && data.actual_value != null) {
        return data
      }
    } catch (error) {
      if (error.response?.status !== 404) {
        throw error
      }
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  return null
}

async function submitSample() {
  if (nodes.value.length < 3) {
    ElMessage.error('至少需要 3 个工作节点才能提交示例任务')
    return
  }
  demoRunning.value = true
  const payload = {
    external_task_id: `matmul-ui-${Date.now()}`,
    task_type: 'high_throughput_matmul',
    modality: 'high_throughput_compute',
    name: '矩阵乘法示例任务',
    description: '演示科学计算流水线：三节点 batched 矩阵乘法，以计算耗时验收是否达标。',
    data_profile: {
      profile_id: 'matmul_dev',
      matrix_size: 64,
      batch_count: 1,
      seed: 42,
    },
    business_objective: {
      metric_key: 'effective_gflops',
      operator: '>=',
      target_value: 100,
      unit: 'GFLOPS',
    },
    runtime_plan: {
      algorithm: 'batched_matmul',
      precision: 'fp32',
      use_gpu: false,
    },
    routing_result: {
      strategy: 'completion_time_first',
      placements: {
        source: nodes.value[0].id,
        compute: nodes.value[1].id,
        sink: nodes.value[2].id,
      },
      estimated_metric: { metric_key: 'effective_gflops', metric_value: 200, unit: 'GFLOPS' },
    },
    result_storage: { backend: 'minio', bucket: 'task-results' },
    auto_start: true,
  }
  try {
    const { data } = await businessApi.submit(payload)
    ElMessage.info('任务已提交并自动启动，等待计算完成…')
    await refreshAll()
    const evaluation = await waitForEvaluation(data.instance_id)
    await refreshAll()
    if (evaluation) {
      ElMessage.success('演示完成，可在结果 Tab 查看计算内容与是否达标')
      await openDetail(data.order_id, 'result')
    } else {
      ElMessage.warning('任务已启动，评估结果尚未就绪，请稍后刷新或打开详情')
      await openDetail(data.order_id, 'deployment')
    }
  } finally {
    demoRunning.value = false
  }
}
</script>

<style scoped>
.hub-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
}

.subtitle {
  color: var(--text-secondary);
  margin-top: 6px;
}

.actions {
  display: flex;
  gap: 10px;
}

.card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 16px;
  background: var(--bg-secondary);
}

.card-header {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.card-header h2 {
  margin: 0;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.task-summary {
  margin: 0 0 14px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.task-type-cell {
  display: block;
}

.task-type-code {
  display: block;
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 11px;
}

.objective-card {
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
}

.objective-headline {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.objective-meaning {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.raw-collapse {
  margin-top: 8px;
}

.result-verdict {
  margin-bottom: 14px;
  padding: 14px 16px;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-tertiary);
}

.result-verdict strong {
  display: block;
  margin-bottom: 6px;
  color: var(--text-primary);
  font-size: 15px;
}

.result-verdict p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.result-verdict.success {
  border-color: rgba(34, 197, 94, 0.35);
  background: rgba(34, 197, 94, 0.08);
}

.result-verdict.danger {
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.08);
}

.result-verdict.pending {
  border-color: rgba(59, 130, 246, 0.35);
  background: rgba(59, 130, 246, 0.08);
}

.field-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.pipeline-steps {
  margin: 0 0 16px;
  padding-left: 20px;
  color: var(--text-secondary);
  line-height: 1.7;
  font-size: 13px;
}

.pipeline-steps strong {
  color: var(--accent-secondary);
  text-transform: uppercase;
  font-size: 12px;
}

.consistency-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: 12px 0 4px;
}

.consistency-detail {
  color: var(--text-secondary);
  font-size: 13px;
}

.text-success {
  color: var(--success);
  font-weight: 600;
}

.text-danger {
  color: var(--danger);
  font-weight: 600;
}

.json-block {
  background: var(--bg-tertiary);
  border-radius: 8px;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
}

.success-rate-card {
  text-align: center;
  padding: 24px;
  margin-bottom: 16px;
  background: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
}
.rate-number {
  font-size: 48px;
  font-weight: 700;
  line-height: 1.2;
}
.rate-number.pass { color: #67c23a; }
.rate-number.fail { color: #f56c6c; }
.rate-label {
  font-size: 14px;
  color: #606266;
  margin-top: 8px;
}

.deploy-actions {
  display: flex;
  gap: 10px;
  margin: 16px 0;
}
</style>

<style>
.task-detail-drawer.el-drawer {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.task-detail-drawer .el-drawer__header {
  margin-bottom: 0;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-primary);
}

.task-detail-drawer .el-drawer__title {
  color: var(--text-primary);
}

.task-detail-drawer .el-drawer__body {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.task-detail-drawer .el-tabs__item {
  color: var(--text-secondary);
}

.task-detail-drawer .el-tabs__item.is-active {
  color: var(--accent-secondary);
}

.task-detail-drawer .detail-desc .el-descriptions__label,
.task-detail-drawer .detail-desc .el-descriptions__content {
  background: var(--bg-tertiary) !important;
  color: var(--text-primary) !important;
  border-color: var(--border-subtle) !important;
}

.task-detail-drawer .raw-collapse .el-collapse-item__header {
  background: transparent;
  color: var(--text-secondary);
  border-color: var(--border-subtle);
}

.task-detail-drawer .raw-collapse .el-collapse-item__wrap,
.task-detail-drawer .raw-collapse .el-collapse-item__content {
  background: transparent;
  border-color: var(--border-subtle);
}
</style>
