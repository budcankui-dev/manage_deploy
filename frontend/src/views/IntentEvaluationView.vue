<template>
  <div class="intent-eval-page">
    <header class="page-hero">
      <div>
        <p class="eyebrow">意图解析评测</p>
        <h1>数据集意图解析参数提取准确率</h1>
        <p class="subtitle">
          数据集由模板和槽位替换构造，覆盖八类模态、多种路由策略倾向、口语化表达、缺字段、错误节点和噪声文本。
          页面按统一解析流程展示一个正式准确率，便于专家按测试方案核对结果。
        </p>
      </div>
      <div class="hero-actions">
        <div>
          <h2>验收评测入口</h2>
          <p>运行固定数据集的意图参数解析评测，完成后在下方生成准确率、样本明细和下载文件。</p>
        </div>
        <div class="model-picker">
          <span>评测模型</span>
          <el-select
            v-model="selectedModel"
            placeholder="选择大模型"
            :disabled="batchSubmitting || !dashscopeConfigured"
          >
            <el-option
              v-for="model in evalModelOptions"
              :key="model"
              :label="model"
              :value="model"
            />
          </el-select>
        </div>
        <el-button
          type="success"
          size="large"
          @click="runOfficialEvaluation"
          :loading="officialRunning"
          :disabled="isBatchActive || (dashscopeConfigured && !selectedModel)"
        >
          运行意图参数解析准确率评测
        </el-button>
        <div class="secondary-actions">
          <el-button @click="loadLatest" :loading="loading">更新评测看板</el-button>
        </div>
      </div>
    </header>

    <el-alert
      v-if="latest && !dashscopeConfigured"
      class="top-alert"
      type="info"
      show-icon
      :closable="false"
      title="当前将使用与用户端一致的意图解析流程完成评测。"
    />
    <el-alert
      v-if="hasStaleReport"
      class="top-alert"
      type="warning"
      show-icon
      :closable="false"
      title="当前数据集已更新，历史评测报告不会作为当前准确率展示。请重新运行意图参数解析准确率评测。"
    />

    <section class="stat-grid">
      <el-card class="stat-card">
        <span class="stat-label">固定数据集</span>
        <strong>{{ dataset.total || 0 }}</strong>
        <small>{{ dataset.path || '-' }}</small>
      </el-card>
      <el-card class="stat-card">
        <span class="stat-label">验收目标</span>
        <strong>≥ 90%</strong>
        <small>完全匹配才算正确</small>
      </el-card>
      <el-card class="stat-card">
        <span class="stat-label">意图参数解析准确率</span>
        <strong :class="accuracyClass(officialReport)">{{ formatAccuracy(officialReport) }}</strong>
        <small class="report-summary">
          <span>{{ reportSummary(officialReport).ratio }}</span>
          <span>{{ reportSummary(officialReport).date }}</span>
          <span>{{ reportSummary(officialReport).id }}</span>
        </small>
      </el-card>
      <el-card class="stat-card">
        <span class="stat-label">当前评测来源</span>
        <strong class="source-text">{{ officialSourceLabel }}</strong>
        <small>{{ officialSourceHint }}</small>
      </el-card>
    </section>

    <el-card class="panel-card helper-workbench">
      <template #header>
        <div class="card-header">
          <div>
            <span>评测辅助信息</span>
            <small class="report-caption">核心准确率和样本列表保持在主页面，说明、单条检测和过程文件按页内标签查看。</small>
          </div>
          <el-tag size="small" type="info">辅助功能</el-tag>
        </div>
      </template>
      <el-tabs v-model="activeHelperTab" class="helper-tabs">
        <el-tab-pane label="数据集说明" name="dataset">
          <div class="dataset-breadcrumb">
            <span>固定数据集</span>
            <span>八种模态</span>
            <span>节点槽位 h1-h13 / compute-1~3</span>
            <span>字段完全匹配评分</span>
          </div>
          <p class="panel-hint">
            固定评测数据集覆盖 {{ dataset.total || 0 }} 条样本，节点槽位使用
            {{ validNodeText }}。每条样本包含任务类型、所属模态、业务源/目的节点、运行时间、路由策略倾向和业务参数。
          </p>
          <div class="node-chip-row">
            <el-tag v-for="node in visibleValidNodes" :key="node" size="small" effect="plain">{{ node }}</el-tag>
            <el-tag v-if="hiddenValidNodeCount > 0" size="small" type="info" effect="plain">
              +{{ hiddenValidNodeCount }} 个节点
            </el-tag>
          </div>
          <div class="modality-example-grid">
            <article v-for="item in modalityExampleRows" :key="item.modality" class="modality-example-card">
              <div class="modality-example-title">
                <strong>{{ modalityLabel(item.modality) }}</strong>
                <el-tag size="small" type="info" effect="plain">{{ taskTypeLabel(item.task_type) }}</el-tag>
              </div>
              <p class="example-utterance">{{ item.utterance }}</p>
              <dl class="example-fields">
                <div>
                  <dt>节点</dt>
                  <dd>{{ item.source_name || '-' }} → {{ item.destination_name || '-' }}</dd>
                </div>
                <div>
                  <dt>参数</dt>
                  <dd>{{ compactObjectText(item.data_profile) }}</dd>
                </div>
                <div>
                  <dt>策略倾向</dt>
                  <dd>{{ routeStrategyLabel(item.runtime_plan?.routing_strategy) }}</dd>
                </div>
              </dl>
            </article>
          </div>
          <div class="coverage-grid">
            <section>
              <h3 class="subsection-title">样本类型覆盖</h3>
              <el-table :data="caseCountRows" size="small" border>
                <el-table-column label="样本类型" min-width="230" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span>{{ row.case_label }}</span>
                    <small class="raw-value">{{ row.case_type }}</small>
                  </template>
                </el-table-column>
                <el-table-column prop="count" label="数量" width="100" />
                <el-table-column label="占比" width="180">
                  <template #default="{ row }">
                    <el-progress :percentage="percentage(row.count, dataset.total)" :show-text="false" />
                  </template>
                </el-table-column>
              </el-table>
            </section>
            <section>
              <h3 class="subsection-title">模态覆盖</h3>
              <el-table :data="modalityCountRows" size="small" border>
                <el-table-column prop="modality_label" label="所属模态" min-width="180" />
                <el-table-column prop="count" label="数量" width="100" />
                <el-table-column label="占比" width="180">
                  <template #default="{ row }">
                    <el-progress :percentage="percentage(row.count, dataset.total)" :show-text="false" />
                  </template>
                </el-table-column>
              </el-table>
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane label="单条检测" name="single">
          <div class="parser-check">
            <el-select
              v-model="selectedSampleId"
              filterable
              clearable
              placeholder="可选：从评测样本中选择一条用例"
              class="sample-select"
              @change="applySelectedSample"
            >
              <el-option
                v-for="sample in sampleRows"
                :key="sample.sample_id"
                :label="`${sample.sample_id} · ${sample.modality_label} · ${sample.utterance.slice(0, 42)}`"
                :value="sample.sample_id"
              />
            </el-select>
            <el-input
              v-model="parserInput"
              type="textarea"
              :rows="3"
              placeholder="输入一句业务需求，例如：创建视频AI推理任务，从 h1 到 h2，处理 720p 视频 100 帧，立即运行60分钟"
            />
            <div class="parser-actions">
              <el-button type="primary" :loading="parserLoading" @click="testParse">解析这一条</el-button>
              <small class="report-caption">用于抽查单个样本或手工输入；页面会展示中文字段、字段判定和必要的原始数据。</small>
            </div>
          </div>
          <div v-if="parserResult" class="parser-result">
            <el-descriptions :column="2" size="small" border>
              <el-descriptions-item label="解析流程">{{ parserEngineLabel(parserResult.engine) }}</el-descriptions-item>
              <el-descriptions-item label="模型/版本">{{ parserResult.model || parserResult.parser_version || '-' }}</el-descriptions-item>
              <el-descriptions-item :label="fieldLabel('task_type')">
                {{ taskTypeLabel(parserResult.task_type) }}
                <small class="raw-value">{{ parserResult.task_type || '-' }}</small>
              </el-descriptions-item>
              <el-descriptions-item :label="fieldLabel('modality')">
                <el-tag size="small" type="success">{{ modalityLabel(parserResult.modality) }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item :label="fieldLabel('source_name')">{{ formatEndpoint(parserResult.source_endpoint, parserResult.source_name) }}</el-descriptions-item>
              <el-descriptions-item :label="fieldLabel('destination_name')">{{ formatEndpoint(parserResult.destination_endpoint, parserResult.destination_name) }}</el-descriptions-item>
              <el-descriptions-item :label="fieldLabel('business_start_time')">{{ formatDateText(parserResult.business_start_time) || '-' }}</el-descriptions-item>
              <el-descriptions-item :label="fieldLabel('business_end_time')">{{ formatDateText(parserResult.business_end_time) || '-' }}</el-descriptions-item>
              <el-descriptions-item :label="fieldLabel('parse_status')">
                <el-tag :type="parseStatusType(parserResult.parse_status)" size="small">
                  {{ parseStatusLabel(parserResult.parse_status) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item :label="fieldLabel('assistant_message')">{{ parserResult.assistant_message || '-' }}</el-descriptions-item>
            </el-descriptions>
            <div v-if="parserResult.validation_errors?.length" class="validation-errors">
              <el-alert
                v-for="(item, index) in parserResult.validation_errors"
                :key="index"
                type="warning"
                show-icon
                :closable="false"
                :title="item"
              />
            </div>
            <div class="json-grid">
              <section v-if="parserResult.scoring">
                <h3>单样本字段判定</h3>
                <el-table :data="parserScoringRows" size="small" border>
                  <el-table-column label="字段" width="150">
                    <template #default="{ row }">
                      {{ fieldLabel(row.field) }}
                      <small class="raw-value">{{ row.field }}</small>
                    </template>
                  </el-table-column>
                  <el-table-column label="人工标注值" min-width="160">
                    <template #default="{ row }">{{ stringifyValue(row.expected) }}</template>
                  </el-table-column>
                  <el-table-column label="系统解析值" min-width="160">
                    <template #default="{ row }">{{ stringifyValue(row.got) }}</template>
                  </el-table-column>
                  <el-table-column label="是否正确" width="100">
                    <template #default="{ row }">
                      <el-tag :type="row.ok ? 'success' : 'danger'" size="small">{{ row.ok ? '正确' : '错误' }}</el-tag>
                    </template>
                  </el-table-column>
                </el-table>
              </section>
              <section>
                <h3>{{ fieldLabel('data_profile') }}</h3>
                <el-table :data="parserProfileRows" size="small" border>
                  <el-table-column label="字段" width="150">
                    <template #default="{ row }">
                      {{ row.label }}
                      <small class="raw-value">{{ row.key }}</small>
                    </template>
                  </el-table-column>
                  <el-table-column prop="value" label="值" show-overflow-tooltip />
                </el-table>
              </section>
              <section>
                <h3>{{ fieldLabel('runtime_plan') }}</h3>
                <el-table :data="parserPlanRows" size="small" border>
                  <el-table-column label="字段" width="150">
                    <template #default="{ row }">
                      {{ row.label }}
                      <small class="raw-value">{{ row.key }}</small>
                    </template>
                  </el-table-column>
                  <el-table-column prop="value" label="值" show-overflow-tooltip />
                </el-table>
              </section>
              <section>
                <h3>{{ fieldLabel('business_objective') }}</h3>
                <el-table :data="parserObjectiveRows" size="small" border>
                  <el-table-column label="字段" width="150">
                    <template #default="{ row }">
                      {{ row.label }}
                      <small class="raw-value">{{ row.key }}</small>
                    </template>
                  </el-table-column>
                  <el-table-column prop="value" label="值" show-overflow-tooltip />
                </el-table>
              </section>
            </div>
            <el-collapse class="evidence-collapse">
              <el-collapse-item title="查看单条解析原始 JSON（排障用）" name="single-json">
                <pre class="details-json">{{ JSON.stringify(parserResult || {}, null, 2) }}</pre>
              </el-collapse-item>
              <el-collapse-item v-if="showRoutingDagJson && parserResult.routing_dag" title="查看路由 DAG JSON（管理员调试）" name="single-dag">
                <pre class="details-json">{{ JSON.stringify(parserResult.routing_dag || {}, null, 2) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-tab-pane>

        <el-tab-pane label="评测流程与文件" name="process">
          <div class="process-grid">
            <article v-for="step in evaluationFlowSteps" :key="step.title" class="process-step-card">
              <span>{{ step.no }}</span>
              <strong>{{ step.title }}</strong>
              <p>{{ step.detail }}</p>
            </article>
          </div>
          <div class="content-grid compact-grid">
            <el-card class="inner-card">
              <template #header>
                <div class="card-header">
                  <span>异步评测进度</span>
                  <el-tag v-if="batchJob" size="small" :type="batchStatusType(batchJob.status)">
                    {{ batchStatusLabel(batchJob.status) }}
                  </el-tag>
                  <el-tag v-else size="small" type="info">未提交</el-tag>
                </div>
              </template>
              <el-descriptions :column="1" size="small" border>
                <el-descriptions-item label="评测编号">{{ batchJob?.job_id || '-' }}</el-descriptions-item>
                <el-descriptions-item label="本次评测模型">{{ batchJob?.model || config.dashscope_model || '-' }}</el-descriptions-item>
                <el-descriptions-item label="提交时间">{{ formatDateText(batchJob?.created_at) || '-' }}</el-descriptions-item>
                <el-descriptions-item label="更新时间">{{ formatDateText(batchJob?.updated_at) || '-' }}</el-descriptions-item>
                <el-descriptions-item label="请求计数">{{ batchRequestCountsText }}</el-descriptions-item>
              </el-descriptions>
              <div class="download-row">
                <el-button size="small" type="warning" plain @click="refreshBatch" :loading="batchRefreshing" :disabled="!batchJob">
                  同步评测进度
                </el-button>
                <el-button size="small" type="danger" plain @click="cancelBatch" :loading="batchCancelling" :disabled="!isBatchActive">
                  取消当前评测
                </el-button>
              </div>
            </el-card>
            <el-card class="inner-card">
              <template #header>
                <div class="card-header">
                  <span>评测文件下载</span>
                  <el-tag size="small" type="success">验收留档</el-tag>
                </div>
              </template>
              <p class="panel-hint">用于复核数据集来源、当前评测结果和批处理过程文件。</p>
              <div class="file-download-list">
                <el-button plain @click="downloadEvalFile('dataset')">下载原始数据集</el-button>
                <el-button type="success" plain @click="downloadCurrentReport" :disabled="!officialReport">
                  下载意图解析评测结果
                </el-button>
                <el-button plain @click="downloadEvalFile('batch-job')" :disabled="!batchJob">下载评测任务状态</el-button>
                <el-button plain @click="downloadEvalFile('batch-input')" :disabled="!batchJob">下载评测请求文件</el-button>
                <el-button plain @click="downloadEvalFile('batch-output')" :disabled="!batchJob?.output_jsonl_path">下载模型返回文件</el-button>
              </div>
            </el-card>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-card class="panel-card">
      <template #header>
        <div class="card-header">
          <div>
            <span>按样本类型准确率</span>
            <small class="report-caption">{{ activeReportMeta.caption }}</small>
          </div>
        </div>
      </template>
      <div v-if="activeReport" class="case-bars">
        <div v-for="row in caseAccuracyRows" :key="row.case_type" class="case-row">
          <div class="case-row-title">
            <span>
              {{ row.case_label }}
              <small class="raw-value">{{ row.case_type }}</small>
            </span>
            <strong>{{ row.correct }}/{{ row.total }} · {{ toPercent(row.accuracy) }}</strong>
          </div>
          <el-progress :percentage="Math.round((row.accuracy || 0) * 100)" :status="row.accuracy >= 0.9 ? 'success' : 'exception'" />
        </div>
      </div>
      <el-empty v-else description="暂无评测报告，请先运行意图参数解析准确率评测" :image-size="80" />
    </el-card>

    <el-card class="panel-card">
      <template #header>
        <div class="card-header">
          <div>
            <span>评测样本</span>
            <small class="report-caption">{{ activeReportMeta.caption }}</small>
          </div>
          <div class="sample-toolbar">
            <el-radio-group v-model="resultFilter" size="small">
              <el-radio-button value="all">全部 {{ sampleResultCounts.total }}</el-radio-button>
              <el-radio-button value="success">成功 {{ sampleResultCounts.success }}</el-radio-button>
              <el-radio-button value="failure">失败 {{ sampleResultCounts.failure }}</el-radio-button>
            </el-radio-group>
            <el-button size="small" plain @click="downloadCurrentReport" :disabled="!officialReport">
              下载当前评测报告
            </el-button>
          </div>
        </div>
      </template>
      <el-table :data="pagedSampleRows" size="small" border>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="sample-expand">
              <section>
                <h3>字段判定</h3>
                <el-table :data="detailRows(row.details)" size="small" border>
                  <el-table-column label="字段" width="180">
                    <template #default="{ row: detail }">
                      {{ fieldLabel(detail.field) }}
                      <small class="raw-value">{{ detail.field }}</small>
                    </template>
                  </el-table-column>
                  <el-table-column label="期望值" min-width="180">
                    <template #default="{ row: detail }">{{ stringifyValue(detail.expected) }}</template>
                  </el-table-column>
                  <el-table-column label="解析值" min-width="180">
                    <template #default="{ row: detail }">{{ stringifyValue(detail.got) }}</template>
                  </el-table-column>
                  <el-table-column label="是否正确" width="100">
                    <template #default="{ row: detail }">
                      <el-tag :type="detail.ok ? 'success' : 'danger'" size="small">{{ detail.ok ? '正确' : '错误' }}</el-tag>
                    </template>
                  </el-table-column>
                </el-table>
              </section>
              <section class="sample-overview">
                <h3>中文标签概览</h3>
                <el-descriptions :column="2" size="small" border>
                  <el-descriptions-item label="样本编号">{{ row.sample_id }}</el-descriptions-item>
                  <el-descriptions-item label="样本类型">{{ row.case_label }}</el-descriptions-item>
                  <el-descriptions-item label="业务源节点">{{ row.parsed_result?.source_name || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="业务目的节点">{{ row.parsed_result?.destination_name || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="解析状态">{{ parseStatusLabel(row.parsed_result?.parse_status) }}</el-descriptions-item>
                  <el-descriptions-item label="任务类型">{{ taskTypeLabel(row.parsed_result?.task_type) }}</el-descriptions-item>
                  <el-descriptions-item label="所属模态">{{ row.modality_label }}</el-descriptions-item>
                </el-descriptions>
              </section>
              <section class="sample-evidence">
                <h3>评测证据说明</h3>
                <div class="evidence-card-grid">
                  <article>
                    <strong>样本输入</strong>
                    <p>本条用例的自然语言输入、样本类型和编号，用于说明系统实际解析了什么。</p>
                  </article>
                  <article>
                    <strong>系统解析输出</strong>
                    <p>本次评测运行后系统实际提取出的任务类型、节点、模态和业务参数。</p>
                  </article>
                  <article>
                    <strong>人工标注答案</strong>
                    <p>数据集预先标好的标准答案，是字段判定和准确率统计的评分基准。</p>
                  </article>
                  <article>
                    <strong>字段判定</strong>
                    <p>逐字段比较人工标注值和系统解析值，全部关键字段匹配才计为成功。</p>
                  </article>
                  <article v-if="row.has_raw_response">
                    <strong>原始响应</strong>
                    <p>仅在存在大模型或解析器原始返回时展示，主要用于技术排障。</p>
                  </article>
                </div>
                <el-collapse class="evidence-collapse">
                  <el-collapse-item title="样本输入 JSON（自然语言输入 + 样本元信息）" name="sample-input">
                    <pre class="details-json">{{ JSON.stringify(row.sample_input_payload || {}, null, 2) }}</pre>
                  </el-collapse-item>
                  <el-collapse-item title="系统解析输出 JSON（本次实际结果）" name="parsed">
                    <pre class="details-json">{{ JSON.stringify(row.parsed_result || {}, null, 2) }}</pre>
                  </el-collapse-item>
                  <el-collapse-item title="人工标注答案 JSON（评分基准）" name="expected">
                    <pre class="details-json">{{ JSON.stringify(row.expected_result || {}, null, 2) }}</pre>
                  </el-collapse-item>
                  <el-collapse-item v-if="row.has_raw_response" title="原始响应 JSON（排障用）" name="raw">
                    <pre class="details-json">{{ JSON.stringify(row.raw_llm_response || {}, null, 2) }}</pre>
                  </el-collapse-item>
                </el-collapse>
              </section>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="sample_id" label="样本" width="120" />
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag :type="resultTagType(row.match)" size="small">{{ row.result_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="190">
          <template #default="{ row }">
            {{ row.case_label }}
            <small class="raw-value">{{ row.case_type }}</small>
          </template>
        </el-table-column>
        <el-table-column label="所属模态" width="170">
          <template #default="{ row }">
            <el-tag size="small" type="success" effect="plain">{{ row.modality_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="utterance" label="输入" min-width="320" show-overflow-tooltip />
        <el-table-column prop="parsed_summary" label="解析结果" min-width="300" show-overflow-tooltip />
        <el-table-column label="失败字段" min-width="200">
          <template #default="{ row }">{{ row.failed_fields.join(', ') || '-' }}</template>
        </el-table-column>
      </el-table>
      <div class="pagination-row">
        <el-pagination
          v-model:current-page="samplePage"
          v-model:page-size="samplePageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="filteredSampleRows.length"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'
import { modalityLabel, taskTypeLabel } from '@/constants/businessTaskDisplay'
import { routingPolicyLabel } from '@/constants/routingPolicy'

const latest = ref(null)
const loading = ref(false)
const ruleRunning = ref(false)
const batchSubmitting = ref(false)
const batchRefreshing = ref(false)
const batchCancelling = ref(false)
const resultFilter = ref('all')
const samplePage = ref(1)
const samplePageSize = ref(20)
const parserInput = ref('')
const parserResult = ref(null)
const parserLoading = ref(false)
const selectedModel = ref('')
const selectedSampleId = ref('')
const autoRefreshTimer = ref(null)
const showRoutingDagJson = ref(false)
const activeHelperTab = ref('process')
const evaluationFlowSteps = [
  {
    no: '01',
    title: '准备固定数据集',
    detail: '数据集覆盖八种模态、有效节点槽位、路由策略倾向和异常表达，作为验收时固定输入。',
  },
  {
    no: '02',
    title: '运行统一解析流程',
    detail: '点击评测按钮后，系统按用户端同一套意图解析链路逐条生成结构化参数。',
  },
  {
    no: '03',
    title: '逐字段评分',
    detail: '将系统解析输出与人工标注答案逐字段比较，关键字段全部匹配才计为该样本成功。',
  },
  {
    no: '04',
    title: '查看证据与留档',
    detail: '在样本列表展开查看字段判定和 JSON 证据，也可以下载数据集与评测结果文件。',
  },
]

const dataset = computed(() => latest.value?.dataset || {})
const config = computed(() => latest.value?.config || {})
const ruleReport = computed(() => latest.value?.rule_report || null)
const llmReport = computed(() => latest.value?.llm_report || null)
const batchJob = computed(() => latest.value?.batch_job || null)
const dashscopeConfigured = computed(() => !!config.value.dashscope_configured)
const evalModelOptions = computed(() => config.value.dashscope_models || config.value.dashscope_eval_models || [])
const ACTIVE_BATCH_STATUSES = ['validating', 'in_progress', 'finalizing', 'submitted', 'cancelling']
const isBatchActive = computed(() => ACTIVE_BATCH_STATUSES.includes(batchJob.value?.status))
const officialRunning = computed(() => batchSubmitting.value || ruleRunning.value)
const batchRequestCountsText = computed(() => {
  const counts = batchJob.value?.request_counts
  if (!counts) return '-'
  return `总数 ${counts.total ?? 0}，完成 ${counts.completed ?? 0}，失败 ${counts.failed ?? 0}`
})
const isLlmReportCurrent = computed(() => {
  if (!llmReport.value || !batchJob.value) return true
  const reportId = llmReport.value.evaluation_id || llmReport.value.batch_job_id
  return reportId === batchJob.value.job_id && isReportDatasetCurrent(llmReport.value, dataset.value)
})
const hasCurrentLlmReport = computed(() =>
  Boolean(llmReport.value && isReportDatasetCurrent(llmReport.value, dataset.value))
)
const hasCurrentRuleReport = computed(() =>
  Boolean(ruleReport.value && isReportDatasetCurrent(ruleReport.value, dataset.value))
)
const hasStaleReport = computed(() =>
  Boolean(
    !officialReport.value &&
    (
      (ruleReport.value && !isReportDatasetCurrent(ruleReport.value, dataset.value)) ||
      (llmReport.value && !isReportDatasetCurrent(llmReport.value, dataset.value))
    )
  )
)
const officialReportType = computed(() => {
  if (hasCurrentLlmReport.value) return 'llm'
  if (hasCurrentRuleReport.value) return 'fallback'
  return ''
})
const officialReport = computed(() => {
  if (officialReportType.value === 'llm') return llmReport.value
  if (officialReportType.value === 'fallback') return ruleReport.value
  return null
})
const activeReport = computed(() => officialReport.value)
const officialSourceLabel = computed(() => {
  if (officialReportType.value) return '意图解析流程'
  return '尚未评测'
})
const officialSourceHint = computed(() => {
  if (officialReportType.value) return '与用户端对话解析链路一致'
  return '运行评测后生成'
})
const activeReportMeta = computed(() => {
  const report = activeReport.value
  if (!report) return { id: '-', caption: '当前评测报告：暂无数据' }
  const id = report.evaluation_id || report.batch_job_id || report.batch_id || '-'
  const date = formatDateText(report.generated_at) || '-'
  const model = report.model || report.parser_version || report.parser_name || '-'
  return {
    id,
    caption: `当前评测报告 · 评测编号 ${id} · 生成时间 ${date} · 模型/解析器 ${model}`,
  }
})

const caseCountRows = computed(() =>
  Object.entries(dataset.value.case_counts || {}).map(([case_type, count]) => ({
    case_type,
    case_label: caseTypeLabel(case_type),
    count,
  }))
)

const modalityCountRows = computed(() =>
  Object.entries(dataset.value.modality_counts || {}).map(([modality, count]) => ({
    modality,
    modality_label: modalityLabel(modality),
    count,
  }))
)

const caseAccuracyRows = computed(() => {
  const byCase = activeReport.value?.summary?.by_case || {}
  return Object.entries(byCase).map(([case_type, row]) => ({
    case_type,
    case_label: caseTypeLabel(case_type),
    ...row,
  }))
})

const sampleRows = computed(() => {
  const results = activeReport.value?.results || []
  return results.map(item => {
    const details = item.runs?.[0]?.details || item.details || {}
    const parsedResult = item.runs?.[0]?.parsed_result || item.parsed_result || null
    const expectedResult = item.runs?.[0]?.expected_result || item.expected || null
    const rawLlmResponse = item.runs?.[0]?.raw_llm_response || item.raw_llm_response || null
    const samplePayload = item.runs?.[0]?.sample_payload || item.sample_payload || {
      case_type: item.case_type,
      utterance: item.utterance,
      expected: expectedResult,
    }
    const sampleInputPayload = {
      sample_id: item.sample_id,
      case_type: item.case_type,
      case_label: caseTypeLabel(item.case_type),
      utterance: item.utterance,
    }
    const modality = parsedResult?.modality || expectedResult?.modality || samplePayload?.expected?.modality
    const failed = Object.entries(details)
      .filter(([field, detail]) => !isDetailOk(detail, field))
      .map(([field]) => fieldLabel(field, true))
    return {
      sample_id: item.sample_id,
      case_type: item.case_type,
      case_label: caseTypeLabel(item.case_type),
      utterance: item.utterance,
      match: !!item.match,
      result_label: item.match ? '成功' : '失败',
      details,
      parsed_result: parsedResult,
      expected_result: expectedResult,
      raw_llm_response: rawLlmResponse,
      has_raw_response: hasMeaningfulRawResponse(rawLlmResponse),
      sample_payload: samplePayload,
      sample_input_payload: sampleInputPayload,
      parsed_summary: buildParsedSummary(parsedResult),
      modality,
      modality_label: modalityLabel(modality),
      failed_fields: failed,
    }
  })
})

function hasMeaningfulRawResponse(value) {
  if (value == null) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return true
}

const modalityExampleRows = computed(() => {
  const examples = dataset.value.modality_examples
  if (Array.isArray(examples) && examples.length) return examples
  const byModality = new Map()
  for (const item of sampleRows.value) {
    const expected = item.expected_result || item.sample_payload?.expected || {}
    const modality = expected.modality || item.modality
    if (!modality || byModality.has(modality)) continue
    byModality.set(modality, {
      modality,
      task_type: expected.task_type,
      source_name: expected.source_name,
      destination_name: expected.destination_name,
      data_profile: expected.data_profile || {},
      runtime_plan: expected.runtime_plan || {},
      business_objective: expected.business_objective || {},
      utterance: item.utterance,
    })
  }
  return [...byModality.values()]
})
const visibleValidNodes = computed(() => (dataset.value.valid_nodes || []).slice(0, 16))
const hiddenValidNodeCount = computed(() => Math.max(0, (dataset.value.valid_nodes || []).length - visibleValidNodes.value.length))
const validNodeText = computed(() => {
  const nodes = dataset.value.valid_nodes || []
  if (!nodes.length) return '当前配置的有效节点'
  const terminalCount = nodes.filter(node => /^h\d+$/.test(node)).length
  const computeCount = nodes.filter(node => /^compute-\d+$/.test(node)).length
  return `${terminalCount} 个终端节点 h1-h${terminalCount}，以及 ${computeCount} 个计算节点 compute-1-compute-${computeCount}`
})

const filteredSampleRows = computed(() => {
  if (resultFilter.value === 'success') return sampleRows.value.filter(item => item.match)
  if (resultFilter.value === 'failure') return sampleRows.value.filter(item => !item.match)
  return sampleRows.value
})

const pagedSampleRows = computed(() => {
  const start = (samplePage.value - 1) * samplePageSize.value
  return filteredSampleRows.value.slice(start, start + samplePageSize.value)
})

const sampleResultCounts = computed(() => {
  const success = sampleRows.value.filter(item => item.match).length
  const failure = sampleRows.value.length - success
  return { success, failure, total: sampleRows.value.length }
})

const parserProfileRows = computed(() => describeObject(parserResult.value?.data_profile))
const parserPlanRows = computed(() => describeObject(parserResult.value?.runtime_plan))
const parserObjectiveRows = computed(() => describeObject(parserResult.value?.business_objective))
const parserScoringRows = computed(() => detailRows(parserResult.value?.scoring?.details || {}))
const selectedSample = computed(() => sampleRows.value.find(item => item.sample_id === selectedSampleId.value) || null)

const CASE_TYPE_LABELS = {
  valid: '有效样本',
  clean: '标准表达',
  colloquial: '口语表达',
  mixed_language: '中英文混写',
  mixed_language_noise: '中英文混写噪声',
  missing_field: '缺字段',
  missing_source: '缺少源节点',
  missing_destination: '缺少目的节点',
  missing_time: '缺少时间',
  wrong_node: '错误节点',
  wrong_source_node: '错误源节点',
  wrong_destination_node: '错误目的节点',
  noisy: '噪声文本',
  boundary: '边界值',
  llm_text_generation: '文本生成',
}

const PARSE_STATUS_LABELS = {
  valid: '有效',
  incomplete: '信息不完整',
  invalid: '无效',
  partial: '部分有效',
  needs_clarification: '需要补充',
  rejected: '已拒绝',
}

const FIELD_LABELS = {
  task_type: '任务类型',
  modality: '所属模态',
  parse_status: '解析状态',
  source_name: '业务源节点',
  destination_name: '业务目的节点',
  business_start_time: '开始时间',
  business_end_time: '结束时间',
  data_profile: '数据画像',
  runtime_plan: '运行计划',
  business_objective: '业务目标',
  validation_errors: '校验错误',
  parser_name: '解析器',
  parser_version: '解析器版本',
  assistant_message: '助手消息',
  matrix_size: '矩阵规模',
  batch_count: '批次数',
  frame_count: '帧数',
  resolution: '分辨率',
  fps: '帧率',
  prompt_tokens: '提示词 Tokens',
  max_new_tokens: '生成 Tokens',
  batch_size: '批大小',
  seed: '随机种子',
  profile_id: '画像 ID',
  routing_strategy: '路由策略',
  metric_key: '指标',
  operator: '比较符',
  target_value: '目标值',
  unit: '单位',
  missing_params: '缺失字段键',
  routing_dag: '路由 DAG',
}

function caseTypeLabel(value) {
  if (!value) return '-'
  return CASE_TYPE_LABELS[value] || value
}

function parseStatusLabel(value) {
  if (!value) return '-'
  return PARSE_STATUS_LABELS[value] || value
}

function parserEngineLabel(value) {
  return {
    llm_qwen: '大模型/智能体解析',
    rule_parser: '系统解析流程',
  }[value] || value || '-'
}

function fieldLabel(value, includeRaw = false) {
  if (!value) return '-'
  const label = FIELD_LABELS[value] || value
  return includeRaw && label !== value ? `${label} (${value})` : label
}

function parseStatusType(status) {
  return {
    valid: 'success',
    incomplete: 'warning',
    invalid: 'danger',
    rejected: 'danger',
    partial: 'warning',
    needs_clarification: 'warning',
  }[status] || 'info'
}

function resultTagType(match) {
  return match ? 'success' : 'danger'
}

function isDetailOk(detail, field = '') {
  if (detail?.expected === 'present') return detail.got != null
  if (field === 'modality') return modalityLabel(detail?.expected) === modalityLabel(detail?.got)
  return JSON.stringify(detail?.expected) === JSON.stringify(detail?.got)
}

function detailRows(details) {
  return Object.entries(details || {}).map(([field, detail]) => ({
    field,
    expected: detail.expected,
    got: detail.got,
    ok: isDetailOk(detail, field),
  }))
}

function stringifyValue(value) {
  if (value == null) return '-'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '[]'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function compactObjectText(value) {
  const entries = Object.entries(value || {})
  if (!entries.length) return '-'
  return entries.map(([key, val]) => `${fieldLabel(key)}=${stringifyValue(val)}`).join('，')
}

function routeStrategyLabel(value) {
  return routingPolicyLabel(value)
}

function formatEndpoint(endpoint, fallback) {
  if (!fallback) return '-'
  if (!endpoint) return fallback
  const address = endpoint.business_ipv6 || endpoint.business_ip
  const zone = endpoint.topology_zone ? ` / ${endpoint.topology_zone}` : ''
  return address ? `${fallback}（${address}${zone}）` : fallback
}

function buildParsedSummary(result) {
  if (!result) return '-'
  const profile = result.data_profile || {}
  const plan = result.runtime_plan || {}
  const parts = [
    taskTypeLabel(result.task_type),
    modalityLabel(result.modality),
    result.parse_status ? parseStatusLabel(result.parse_status) : '',
    result.source_name && result.destination_name ? `${result.source_name} → ${result.destination_name}` : '',
  ].filter(Boolean)
  const profileParts = Object.entries(profile)
    .filter(([key]) => key !== 'profile_id' && key !== 'source')
    .map(([key, value]) => `${fieldLabel(key)}=${stringifyValue(value)}`)
  if (plan.routing_strategy) profileParts.push(`${fieldLabel('routing_strategy')}=${plan.routing_strategy}`)
  return [...parts, ...profileParts].join('；')
}

function describeObject(obj) {
  if (!obj) return []
  return Object.entries(obj).map(([key, value]) => ({
    key,
    label: fieldLabel(key),
    value: typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '-'),
  }))
}

function toPercent(value) {
  if (value == null) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function formatAccuracy(report) {
  if (!report) return '-'
  return toPercent(report.accuracy)
}

function reportSummary(report) {
  if (!report) return { ratio: '尚未生成', date: '-', id: '评测编号 -' }
  const id = report.evaluation_id || report.batch_job_id || report.batch_id || '-'
  const staleText = isReportDatasetCurrent(report, dataset.value) ? '' : ' · 数据集已更新'
  return {
    ratio: `${report.correct}/${report.total}`,
    date: formatDateText(report.generated_at) || '-',
    id: `评测编号 ${id}${staleText}`,
  }
}

function isReportDatasetCurrent(report, currentDataset) {
  const currentHash = currentDataset?.sha256
  const reportHash = report?.dataset?.sha256
  if (!currentHash || !reportHash) return !currentHash && !reportHash
  return currentHash === reportHash
}

function formatDateText(value) {
  if (!value) return value
  const text = String(value).replace(/\.\d+/, '').replace('T', ' ')
  return text.slice(0, 19)
}

function percentage(count, total) {
  return total ? Math.round((count / total) * 100) : 0
}

function accuracyClass(report) {
  if (!report) return ''
  return report.accuracy >= 0.9 ? 'ok' : 'bad'
}

function batchStatusType(status) {
  return {
    completed: 'success',
    failed: 'danger',
    expired: 'danger',
    cancelled: 'info',
    cancelling: 'warning',
    in_progress: 'warning',
    validating: 'warning',
    submitted: 'warning',
  }[status] || 'info'
}

function batchStatusLabel(status) {
  return {
    completed: '已完成',
    failed: '失败',
    expired: '已过期',
    cancelled: '已取消',
    cancelling: '取消中',
    in_progress: '评测中',
    validating: '校验中',
    submitted: '已提交',
  }[status] || status || '未知'
}

const FILE_NAMES = {
  dataset: 'intent_eval_dataset.jsonl',
  'rule-report': 'intent_eval_rule_report.json',
  'llm-report': 'intent_eval_llm_report.json',
  'batch-job': 'intent_eval_batch_job.json',
  'batch-input': 'intent_eval_batch_input.jsonl',
  'batch-output': 'intent_eval_batch_output.jsonl',
}

async function downloadEvalFile(type) {
  try {
    const { data } = await adminApi.downloadIntentEvalFile(type)
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = FILE_NAMES[type] || `${type}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    // API interceptor already displays the concrete error.
  }
}

async function loadLatest() {
  loading.value = true
  try {
    const { data } = await adminApi.intentEvalLatest()
    latest.value = data
    if (!selectedModel.value) {
      selectedModel.value = evalModelOptions.value.includes(data.batch_job?.model)
        ? data.batch_job.model
        : evalModelOptions.value[0] || ''
    }
  } finally {
    loading.value = false
  }
}

async function loadSystemSettings() {
  try {
    const { data } = await adminApi.getSystemSettings()
    showRoutingDagJson.value = Boolean(data?.show_routing_dag_json)
  } catch {
    showRoutingDagJson.value = false
  }
}

async function runOfficialEvaluation() {
  if (dashscopeConfigured.value) {
    await submitBatch()
  } else {
    await runRule()
  }
}

async function runRule() {
  ruleRunning.value = true
  try {
    const { data } = await adminApi.runIntentEvalRule()
    latest.value = { ...(latest.value || {}), rule_report: data }
    ElMessage.success(`意图参数解析评测完成：${data.correct}/${data.total}`)
  } finally {
    ruleRunning.value = false
  }
}

async function submitBatch() {
  if (!selectedModel.value) {
    ElMessage.warning('请先选择评测模型')
    return
  }
  if (isBatchActive.value) {
    ElMessage.warning('已有大模型评测正在运行，请先同步状态或取消当前评测')
    return
  }
  batchSubmitting.value = true
  try {
    const { data } = await adminApi.submitIntentEvalBatch({ model: selectedModel.value })
    latest.value = { ...(latest.value || {}), batch_job: data }
    startAutoRefresh()
    ElMessage.success(`大模型意图解析评测已提交：${selectedModel.value}`)
  } finally {
    batchSubmitting.value = false
  }
}

async function cancelBatch() {
  if (!isBatchActive.value) {
    ElMessage.info('当前没有运行中的大模型评测')
    return
  }
  batchCancelling.value = true
  try {
    const { data } = await adminApi.cancelIntentEvalBatch()
    latest.value = { ...(latest.value || {}), batch_job: data }
    stopAutoRefresh()
    ElMessage.success('已提交取消请求')
  } finally {
    batchCancelling.value = false
  }
}

async function refreshBatch() {
  await syncBatch({ silent: false })
}

async function syncBatch({ silent = false } = {}) {
  batchRefreshing.value = true
  try {
    const { data } = await adminApi.refreshIntentEvalBatch()
    latest.value = { ...(latest.value || {}), batch_job: data }
    await loadLatest()
    if (data.summary) {
      stopAutoRefresh()
      if (!silent) ElMessage.success(`意图参数解析评测已评分：${data.summary.correct}/${data.summary.total}`)
    } else if (!silent) {
      ElMessage.info(`Batch 状态：${data.status}`)
    }
  } finally {
    batchRefreshing.value = false
  }
}

function startAutoRefresh() {
  if (autoRefreshTimer.value || !isBatchActive.value) return
  autoRefreshTimer.value = window.setInterval(() => {
    if (isBatchActive.value && !batchRefreshing.value) {
      syncBatch({ silent: true })
    } else if (!isBatchActive.value) {
      stopAutoRefresh()
    }
  }, 15000)
}

function stopAutoRefresh() {
  if (!autoRefreshTimer.value) return
  window.clearInterval(autoRefreshTimer.value)
  autoRefreshTimer.value = null
}

async function testParse() {
  const utterance = parserInput.value.trim()
  if (!utterance) {
    ElMessage.warning('请输入要检测的自然语言描述')
    return
  }
  parserLoading.value = true
  try {
    const payload = { utterance }
    if (selectedSample.value?.expected_result) payload.expected = selectedSample.value.expected_result
    const { data } = await adminApi.parseOne(payload)
    parserResult.value = data
  } finally {
    parserLoading.value = false
  }
}

function applySelectedSample() {
  if (!selectedSample.value) return
  parserInput.value = selectedSample.value.utterance
  parserResult.value = null
}

function downloadCurrentReport() {
  const type = officialReportType.value === 'llm' ? 'llm-report' : 'rule-report'
  downloadEvalFile(type)
}

watch([officialReportType, resultFilter, samplePageSize], () => {
  samplePage.value = 1
})

watch(isBatchActive, active => {
  if (active) startAutoRefresh()
  else stopAutoRefresh()
})

onMounted(async () => {
  await Promise.all([loadLatest(), loadSystemSettings()])
  startAutoRefresh()
})

onUnmounted(stopAutoRefresh)
</script>

<style scoped>
.intent-eval-page {
  padding: 28px;
  max-width: 1360px;
  margin: 0 auto;
}

.page-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 24px;
  border-radius: 18px;
  background:
    radial-gradient(circle at 12% 20%, rgba(40, 126, 255, 0.18), transparent 28%),
    linear-gradient(135deg, #f7fbff 0%, #eef5ef 100%);
  border: 1px solid #dce8f1;
  margin-bottom: 18px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #1f7a5f;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.page-hero h1 {
  margin: 0;
  font-size: 28px;
  color: #17212b;
}

.subtitle {
  max-width: 760px;
  color: #5d6b78;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-start;
  gap: 10px;
  width: 360px;
  padding: 18px;
  border: 1px solid rgba(46, 98, 164, 0.16);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 16px 36px rgba(38, 73, 106, 0.08);
}

.hero-actions h2 {
  margin: 0 0 6px;
  color: #17212b;
  font-size: 17px;
}

.hero-actions p {
  margin: 0;
  color: #697887;
  font-size: 13px;
  line-height: 1.6;
}

.hero-actions .el-button {
  margin-left: 0;
}

.model-picker {
  display: grid;
  gap: 6px;
}

.model-picker span {
  color: #5d6b78;
  font-size: 13px;
  font-weight: 700;
}

.secondary-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.top-alert {
  margin-bottom: 16px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.stat-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stat-label {
  color: #6b7785;
  font-size: 13px;
}

.stat-card strong {
  font-size: 28px;
  color: #1d2b38;
}

.stat-card strong.ok {
  color: #1f9d70;
}

.stat-card strong.bad {
  color: #d64b4b;
}

.stat-card small {
  color: #8693a0;
}

.report-summary {
  display: grid;
  gap: 2px;
}

.report-summary span:first-child {
  color: #667584;
  font-weight: 700;
}

.report-summary span:last-child {
  color: #98a3af;
}

.report-caption {
  display: block;
  margin-top: 4px;
  color: #7a8794;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.panel-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.report-caption {
  display: block;
  margin-top: 4px;
  color: #8794a3;
  font-size: 12px;
  font-weight: 400;
  line-height: 1.5;
}

.helper-workbench :deep(.el-card__body) {
  padding-top: 8px;
}

.helper-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
}

.helper-tabs :deep(.el-tabs__item) {
  font-weight: 700;
}

.dataset-breadcrumb {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.dataset-breadcrumb span {
  position: relative;
  padding: 7px 12px;
  border: 1px solid #d9e7f1;
  border-radius: 999px;
  background: #f7fbff;
  color: #31536d;
  font-size: 12px;
  font-weight: 700;
}

.dataset-breadcrumb span:not(:last-child)::after {
  content: '>';
  margin-left: 10px;
  color: #91a4b5;
}

.coverage-grid,
.content-grid,
.compact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.coverage-grid {
  margin-top: 16px;
}

.subsection-title {
  margin: 0 0 10px;
  color: #24384a;
  font-size: 15px;
}

.process-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.process-step-card {
  display: grid;
  gap: 8px;
  padding: 16px;
  border: 1px solid #e0e9f1;
  border-radius: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #f7fafc 100%);
}

.process-step-card span {
  width: fit-content;
  padding: 3px 8px;
  border-radius: 999px;
  background: #eaf4ff;
  color: #1e6da8;
  font-size: 12px;
  font-weight: 800;
}

.process-step-card strong {
  color: #203447;
}

.process-step-card p {
  margin: 0;
  color: #687786;
  font-size: 13px;
  line-height: 1.65;
}

.inner-card {
  min-height: 100%;
}

.case-bars {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.case-row-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  color: #344254;
}

.raw-value {
  display: block;
  margin-top: 2px;
  color: #93a0ad;
  font-size: 11px;
  line-height: 1.25;
}

.parser-check {
  display: grid;
  gap: 10px;
}

.parser-actions {
  display: flex;
  justify-content: flex-end;
}

.parser-result {
  display: grid;
  gap: 14px;
  margin-top: 14px;
}

.validation-errors {
  display: grid;
  gap: 8px;
}

.json-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.json-grid h3 {
  margin: 0 0 8px;
  color: #344254;
  font-size: 14px;
}

.json-grid .details-json {
  margin-top: 8px;
}

.sample-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}

.download-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.download-row .el-button,
.file-download-list .el-button,
.secondary-actions .el-button {
  margin-left: 0;
}

.panel-hint {
  margin: 0 0 14px;
  color: #667584;
  font-size: 13px;
  line-height: 1.7;
}

.node-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.modality-example-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.modality-example-card {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid #e3ebf2;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbfd 100%);
}

.modality-example-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.modality-example-title strong {
  color: #1e3142;
}

.example-utterance {
  margin: 0;
  color: #445467;
  line-height: 1.6;
}

.example-fields {
  display: grid;
  gap: 6px;
  margin: 0;
}

.example-fields div {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  gap: 8px;
}

.example-fields dt {
  color: #7a8794;
  font-weight: 700;
}

.example-fields dd {
  margin: 0;
  color: #2f3e4f;
  word-break: break-word;
}

.file-download-list {
  display: grid;
  gap: 10px;
}

.sample-expand {
  display: grid;
  gap: 14px;
}

.sample-overview {
  display: grid;
  gap: 8px;
}

.sample-evidence {
  display: grid;
  gap: 10px;
}

.evidence-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.evidence-card-grid article {
  padding: 12px;
  border: 1px solid #e4edf4;
  border-radius: 12px;
  background: #fbfdff;
}

.evidence-card-grid strong {
  display: block;
  margin-bottom: 6px;
  color: #24384a;
}

.evidence-card-grid p {
  margin: 0;
  color: #687786;
  font-size: 12px;
  line-height: 1.6;
}

.evidence-collapse {
  border-top: 1px solid #e8eef4;
}

.sample-expand h3 {
  margin: 0 0 8px;
  color: #344254;
  font-size: 14px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.details-json {
  white-space: pre-wrap;
  word-break: break-word;
  background: #f6f8fa;
  border-radius: 8px;
  padding: 12px;
  max-height: 360px;
  overflow: auto;
}

@media (max-width: 980px) {
  .page-hero,
  .content-grid,
  .compact-grid,
  .coverage-grid {
    grid-template-columns: 1fr;
    display: grid;
  }

  .stat-grid,
  .case-bars,
  .json-grid,
  .modality-example-grid,
  .process-grid,
  .evidence-card-grid {
    grid-template-columns: 1fr;
  }

  .hero-actions {
    justify-content: flex-start;
    min-width: 0;
  }

  .card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .sample-toolbar {
    justify-content: flex-start;
    width: 100%;
  }
}
</style>
