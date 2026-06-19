<template>
  <div class="intent-app">
    <!-- Top navigation bar -->
    <header class="top-bar">
      <div class="top-bar-left">
        <span class="top-logo">智联计算系统</span>
      </div>
      <div class="top-bar-center">
        <span v-if="conversation?.title" class="top-conv-title">{{ conversation.title }}</span>
      </div>
      <div class="top-bar-right">
        <el-tag size="small" type="info" class="model-badge">智能解析服务</el-tag>
        <div class="user-chip">{{ auth.username || 'user' }}</div>
      </div>
    </header>

    <div class="intent-workspace" :style="showOrders ? 'grid-template-columns: 260px 1fr 0px' : ''">
    <aside class="conversation-sidebar">
      <div class="sidebar-top">
        <div class="sidebar-nav">
          <div class="nav-item" :class="{ active: showOrders }" @click="toggleOrders">
            <el-icon><List /></el-icon>
            <span>我的工单</span>
          </div>
        </div>

        <div class="conv-list-header">
          <span>对话列表</span>
          <el-button size="small" circle @click="startNewConversation">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <div class="sidebar-conversations">
          <div
            v-for="item in conversations"
            :key="item.id"
            class="conversation-item"
            :class="{ active: !showOrders && item.id === conversation?.id }"
            @click="selectConversation(item.id)"
          >
            <div class="conversation-item-body">
              <span>{{ (item.title || ('#' + item.id.slice(0, 8))).slice(0, 20) }}</span>
              <small>{{ formatStatus(item.status) }}</small>
            </div>
            <el-button
              class="delete-btn"
              link
              type="danger"
              :icon="DeleteIcon"
              size="small"
              @click.stop="deleteConversation(item)"
              title="删除对话"
            />
          </div>
        </div>
      </div>

      <div class="sidebar-bottom">
        <div class="user-info">
          <div class="user-avatar-sm">{{ (auth.username || 'U')[0].toUpperCase() }}</div>
          <span class="username-label">{{ auth.username || 'user' }}</span>
        </div>
        <el-button text @click="logout" class="logout-btn">退出登录</el-button>
      </div>
    </aside>

    <main class="chat-column">
      <header v-if="!showOrders" class="chat-header">
        <div>
          <h1>{{ conversation?.title ? conversation.title.slice(0, 30) : '新对话' }}</h1>
          <p v-if="conversation?.materialized_order_id">
            <el-tooltip :content="conversation.id" placement="top">
              <span>任务 <code>#{{ conversation.id.slice(0, 8) }}...</code></span>
            </el-tooltip>
          </p>
          <p v-else><el-tag type="info" size="small">草稿中</el-tag></p>
        </div>
        <div class="chat-header-right">
          <el-tag>{{ formatStatus(conversation?.status) }}</el-tag>
        </div>
      </header>

      <!-- Orders panel (shown when showOrders=true) -->
      <div v-if="showOrders" class="orders-panel">
        <div class="orders-panel-toolbar">
          <span class="orders-panel-title">我的工单</span>
          <div class="orders-toolbar-right">
            <el-select v-model="orderStatusFilter" placeholder="全部" clearable size="small" style="width: 130px">
              <el-option label="全部" value="" />
              <el-option label="待分配" value="pending" />
              <el-option label="已部署" value="materialized" />
              <el-option label="已完成" value="completed" />
              <el-option label="失败" value="failed" />
              <el-option label="已取消" value="cancelled" />
            </el-select>
            <el-button size="small" @click="loadOrders">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
        </div>
        <el-table
          :data="filteredOrders"
          v-loading="ordersLoading"
          stripe
          size="small"
          class="orders-table"
          @row-click="(row) => openOrderDetail(row)"
        >
          <el-table-column label="任务 ID" width="110">
            <template #default="{ row }">
              <el-tooltip v-if="row.order_id" :content="row.order_id" placement="top">
                <code style="font-size:12px;cursor:pointer">{{ row.order_id.slice(0, 8) }}...</code>
              </el-tooltip>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="任务类型" min-width="150">
            <template #default="{ row }">
              {{ taskTypeLabel(row.task_type) || row.task_type || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="所属模态" min-width="140">
            <template #default="{ row }">
              {{ modalityLabel(row.modality) }}
            </template>
          </el-table-column>
          <el-table-column label="路由策略" min-width="120">
            <template #default="{ row }">
              {{ routingPolicyLabel(row.routing_policy) || row.routing_policy || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="工单状态" width="110">
            <template #default="{ row }">
              <el-tag :type="orderStatusType(row.order_status)" size="small">{{ ORDER_STATUS_LABELS[row.order_status] || row.order_status || '-' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="部署状态" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.deployment_status" :type="deploymentStatusTag(row.deployment_status)" size="small">{{ DEPLOYMENT_STATUS_LABELS[row.deployment_status] || row.deployment_status }}</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="业务指标" min-width="140">
            <template #default="{ row }">
              {{ formatMetricValue(row.actual_value) }} / {{ formatMetricValue(row.target_value) }} {{ row.unit || '' }}
            </template>
          </el-table-column>
          <el-table-column label="达标" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.business_success === true" type="success" size="small">达标</el-tag>
              <el-tag v-else-if="row.business_success === false" type="danger" size="small">未达标</el-tag>
              <span v-else>待评估</span>
            </template>
          </el-table-column>
          <el-table-column label="调度开始" min-width="150">
            <template #default="{ row }">
              {{ row.scheduled_start_time ? formatTime(row.scheduled_start_time) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="调度结束" min-width="150">
            <template #default="{ row }">
              {{ row.scheduled_end_time ? formatTime(row.scheduled_end_time) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="160">
            <template #default="{ row }">
              {{ row.created_at ? formatTime(row.created_at) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click.stop="openOrderDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- Chat view (shown when showOrders=false) -->
      <template v-else>
        <section class="messages" ref="messagesRef">
        <!-- Empty state welcome screen -->
        <div v-if="!displayMessages.length" class="empty-state">
          <div class="empty-avatar">智</div>
          <h2 class="empty-title">智算意图解析助手</h2>
          <p class="empty-subtitle">请描述您想要部署的计算任务</p>
          <div class="example-chips">
            <button
              v-for="chip in exampleChips"
              :key="chip"
              class="chip"
              @click="useChip(chip)"
            >{{ chip }}</button>
          </div>
        </div>

        <div
          v-for="(message, idx) in displayMessages"
          :key="message.id || idx"
          class="message-row"
          :class="message.role"
        >
          <!-- Assistant message (left) -->
          <template v-if="message.role === 'assistant'">
            <div class="avatar assistant-avatar">智</div>
            <div class="bubble-wrap">
              <div class="bubble-name">智算助手</div>
              <div class="bubble assistant-bubble">
                <span class="bubble-text">{{ message.content }}</span><span v-if="message.streaming" class="streaming-cursor">▋</span>
              </div>
              <div class="bubble-time">{{ formatBubbleTime(message.created_at) }}</div>
            </div>
          </template>
          <!-- User message (right) -->
          <template v-else>
            <div class="bubble-wrap user-bubble-wrap">
              <div class="bubble-name user-name">{{ auth.username || '我' }}</div>
              <div class="bubble user-bubble">{{ message.content }}</div>
              <div class="bubble-time user-time">{{ formatBubbleTime(message.created_at) }}</div>
            </div>
            <div class="avatar user-avatar">{{ (auth.username || 'U')[0].toUpperCase() }}</div>
          </template>
        </div>

        <div v-if="draft && draft.parse_status !== 'rejected' && !conversation?.materialized_order_id && !isStreaming && !isDraftSubmittable" class="confirm-card pending-card">
          <div class="confirm-card-inner">
            <el-icon class="pending-icon"><WarningFilled /></el-icon>
            <div class="confirm-text">
              <strong>参数待补充</strong>
              <p>请继续在对话框里补充以下信息，补全后系统才会允许提交任务。</p>
              <div class="missing-list">
                <span v-for="item in draftValidationErrors" :key="item">{{ item }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="isDraftSubmittable" class="confirm-card">
          <div v-if="!conversation?.materialized_order_id && !isStreaming" class="confirm-card-inner">
            <el-icon class="confirm-icon"><CircleCheck /></el-icon>
            <div class="confirm-text">
              <strong>参数已完整</strong>
              <div class="confirm-params">
                <p v-if="draft?.task_type"><span class="param-label">任务类型：</span>{{ taskTypeLabel(draft.task_type) }}</p>
                <p v-if="draft?.modality"><span class="param-label">所属模态：</span>{{ modalityLabel(draft.modality) }}</p>
                <p v-if="draft?.source_name || draft?.destination_name"><span class="param-label">节点：</span>{{ formatDraftEndpoint('source') }} → {{ formatDraftEndpoint('destination') }}</p>
                <p v-if="draft?.business_start_time"><span class="param-label">时间：</span>{{ formatTime(draft.business_start_time) }}{{ draft.business_end_time ? ' ~ ' + formatTime(draft.business_end_time) : '' }}</p>
                <p v-for="row in draftDataProfileRows" :key="row.label"><span class="param-label">{{ row.label }}：</span>{{ row.value }}</p>
                <p v-if="destinationReceiverText"><span class="param-label">结果接收：</span>{{ destinationReceiverText }}</p>
                <p v-if="effectiveCallbackUrl"><span class="param-label">回调地址：</span>{{ effectiveCallbackUrl }}</p>
              </div>
              <el-collapse class="submit-options-collapse">
                <el-collapse-item title="高级提交选项" name="submit-options">
                  <div class="submit-options-form">
                    <el-form label-position="top" size="small">
                      <el-row :gutter="10">
                        <el-col :span="12">
                          <el-form-item label="源端点">
                            <el-input v-model="endpointForm.source_endpoint_input" placeholder="例如 h1 或 2001:da8:..." />
                          </el-form-item>
                        </el-col>
                        <el-col :span="12">
                          <el-form-item label="目的端点">
                            <el-input v-model="endpointForm.destination_endpoint_input" placeholder="例如 h2 或 2001:da8:..." />
                          </el-form-item>
                        </el-col>
                      </el-row>
                      <el-row :gutter="10">
                        <el-col :span="10">
                          <el-form-item label="目的端接收端口">
                            <el-input-number
                              v-model="endpointForm.destination_port"
                              :min="1"
                              :max="65535"
                              :controls="false"
                              placeholder="按任务类型默认"
                              style="width: 100%"
                            />
                          </el-form-item>
                        </el-col>
                        <el-col :span="14">
                          <el-form-item label="目的端回调地址">
                            <el-input
                              v-model="endpointForm.callback_url"
                              placeholder="默认按目的端 IP 和端口生成"
                              @input="endpointForm.callback_url_customized = true"
                            />
                          </el-form-item>
                        </el-col>
                      </el-row>
                    </el-form>
                    <el-checkbox v-model="endpointForm.route_only">只生成节点分配方案，暂不启动计算节点</el-checkbox>
                    <p class="submit-options-note">一般无需修改。源/目的端点可填节点别名、拓扑 ID 或业务面 IP；端口默认按任务类型固定。</p>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>
            <el-button type="success" :loading="isConfirming" :disabled="isConfirming || !canConfirm" @click="confirmIntent">确认提交任务</el-button>
          </div>
          <div v-else-if="conversation?.materialized_order_id" class="confirm-card-inner submitted">
            <el-icon class="confirm-icon" style="color:var(--el-color-success)"><SuccessFilled /></el-icon>
            <div class="confirm-text">
              <strong>任务已提交</strong>
              <p>{{ conversationStatusLabel }}</p>
            </div>
            <el-button v-if="canDemoRoute" type="primary" plain size="small" :loading="isDemoRouting" @click="demoRoute">启动计算节点</el-button>
          </div>
        </div>
      </section>

      <footer class="composer">
        <div v-if="conversationInputLocked" class="composer-lock-tip">
          <div>
            <strong>{{ conversationInputLockTitle }}</strong>
            <span>{{ conversationInputLockMessage }}</span>
          </div>
          <el-button size="small" type="primary" plain @click="startNewConversation">新建对话</el-button>
        </div>
        <el-input
          v-model="utterance"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
          :disabled="isStreaming || conversationInputLocked"
          :placeholder="conversationInputLocked ? '当前对话已生成工单，请新建对话继续提交新任务' : '描述您的计算任务需求，例如：从 h1 到 h2 运行矩阵计算，或从 h3 到 h4 做视频推理...'"
          @keydown.ctrl.enter="sendMessage"
        />
        <div class="composer-actions">
          <div class="composer-tools">
            <span class="composer-hint">Ctrl + Enter 发送</span>
            <el-popover placement="top-start" width="340" trigger="click" popper-class="node-popover">
              <template #reference>
                <el-button size="small" plain>
                  <el-icon><List /></el-icon>
                  可用节点
                </el-button>
              </template>
              <div class="node-popover-body">
                <strong>可用拓扑节点</strong>
                <p>源节点和目的节点请使用已登记的运营商节点别名、拓扑节点 ID 或业务面 IP，系统会按数据库校验。</p>
                <div class="node-popover-tags">
                  <span>运营商节点：{{ operatorNodeHint }}</span>
                  <span>计算节点：{{ computeNodeHint }}（由系统或路由模块选择，不作为源/目的输入）</span>
                </div>
              </div>
            </el-popover>
            <el-popover placement="top-start" width="360" trigger="click" popper-class="node-popover">
              <template #reference>
                <el-button size="small" plain>
                  <el-icon><CircleCheck /></el-icon>
                  支持任务
                </el-button>
              </template>
              <div class="node-popover-body">
                <strong>当前支持的业务任务</strong>
                <p>提交前请在对话中说明任务类型、源节点、目的节点和关键参数；系统会追问缺失项并校验节点是否合法。</p>
                <div class="task-popover-list">
                  <div v-for="item in supportedTaskHints" :key="item.type" class="task-popover-item">
                    <strong>{{ item.label }}</strong>
                    <span>{{ item.hint }}</span>
                  </div>
                </div>
              </div>
            </el-popover>
          </div>
          <div class="composer-btns">
            <el-button v-if="isStreaming" type="danger" @click="stopStreaming">
              <el-icon><VideoPause /></el-icon>
              停止
            </el-button>
            <el-button
              v-else
              type="primary"
              :loading="loading"
              :disabled="isStreaming || conversationInputLocked"
              @click="sendMessage"
            >
              <el-icon><Promotion /></el-icon>
              {{ conversationInputLocked ? '请新建对话' : '发送' }}
            </el-button>
          </div>
        </div>
      </footer>
      </template>
    </main>

    <!-- Order detail drawer (outside v-if/v-else, always mounted) -->
    <el-drawer
      v-model="orderDrawerVisible"
      size="50%"
      direction="rtl"
      destroy-on-close
      class="order-detail-drawer"
    >
      <template #header>
        <div class="drawer-header">
          <div class="drawer-title-row">
            <span>任务工单详情</span>
            <el-tag
              v-if="selectedOrderDetail?.business_task?.task_type || selectedOrderDetail?.task_type"
              size="small"
              type="info"
              effect="plain"
            >
              {{ taskTypeLabel(selectedOrderDetail?.business_task?.task_type || selectedOrderDetail?.task_type) }}
            </el-tag>
            <el-tag v-if="selectedOrderDetail?.status" :type="orderStatusType(selectedOrderDetail.status)" size="small">
              {{ formatOrderStatus(selectedOrderDetail.status) }}
            </el-tag>
          </div>
          <div v-if="selectedOrderDetail" class="drawer-actions">
            <el-button
              v-if="canCancelSelectedOrder"
              type="warning"
              plain
              size="small"
              :loading="orderActionLoading === 'cancel'"
              @click.stop="cancelSelectedOrder"
            >
              取消工单
            </el-button>
            <el-button
              type="danger"
              plain
              size="small"
              :loading="orderActionLoading === 'delete'"
              @click.stop="deleteSelectedOrder"
            >
              删除工单
            </el-button>
          </div>
        </div>
      </template>
      <div v-if="orderDetailLoading" class="orders-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      <OrderDetailPanel
        v-else-if="selectedOrderDetail"
        v-model:active-tab="orderDetailTab"
        :detail="selectedOrderDetail"
        :result-objects="orderResultObjects"
        :show-routing-dag-json="showRoutingDagJson"
      />
    </el-drawer>

    <aside class="intent-panel" v-show="!showOrders" :style="showOrders ? 'overflow: hidden; padding: 0;' : ''">
      <el-card class="panel-card" :class="{ 'valid-border': effectiveParseStatus === 'valid' }">
        <template #header>
          意图参数
          <el-tag v-if="draft" :type="parseStatusType(effectiveParseStatus)" size="small" style="margin-left:8px">{{ formatParseStatus(effectiveParseStatus) }}</el-tag>
          <el-tag v-if="conversation?.materialized_order_id" type="success" size="small" style="margin-left:8px">已提交</el-tag>
        </template>
        <template v-if="draft">
          <div class="intent-summary-list" aria-label="意图参数摘要">
            <div v-for="row in intentSummaryRows" :key="row.label" class="intent-summary-row">
              <span class="intent-summary-label">{{ row.label }}</span>
              <span class="intent-summary-value">{{ row.value }}</span>
            </div>
          </div>
          <div v-if="showClientCommands" class="client-command-panel">
            <div class="client-command-header">
              <strong>用户端启动步骤</strong>
              <span>目的端可稍后启动，计算节点会保留较长回调重试窗口；节点分配完成后再从源端提交输入。</span>
            </div>
            <ol class="client-step-list">
              <li>{{ destinationExecutionHint }} 启动接收程序，监听固定业务端口。</li>
              <li>提交工单后查看“计算服务接入地址”，再由 {{ sourceExecutionHint }} 发起输入。</li>
              <li>接收器会按工单 ID 区分结果，同类任务无需重复占用新端口。</li>
            </ol>
            <el-collapse class="advanced-command-collapse">
              <el-collapse-item title="高级启动命令（演示人员使用）" name="commands">
                <div v-if="receiverCommand" class="command-block">
                  <div class="command-title">{{ destinationExecutionHint }} 先启动接收程序</div>
                  <pre>{{ receiverCommand }}</pre>
                </div>
                <div v-if="sourceCommand" class="command-block">
                  <div class="command-title">{{ sourceExecutionHint }} 在节点分配完成后提交输入</div>
                  <pre>{{ sourceCommand }}</pre>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </template>
        <el-empty v-else description="发送消息后查看解析结果" :image-size="60" />
        <div v-if="draftValidationErrors.length" class="errors">
          <el-alert v-for="(item, index) in draftValidationErrors" :key="index" :title="item" type="warning" show-icon :closable="false" />
        </div>
        <el-collapse v-if="showRoutingDagJson && draft?.routing_dag_preview" class="raw-collapse">
          <el-collapse-item title="路由 DAG JSON 预览" name="draft-dag">
            <pre class="json-block">{{ pretty(draft.routing_dag_preview) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </el-card>

    </aside>
  </div>

    <!-- Bottom status bar -->
    <footer class="bottom-bar">
      <span class="bottom-left">智联计算系统</span>
      <span class="bottom-right">服务状态：在线</span>
    </footer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete as DeleteIcon, Loading, VideoPause, Plus, Promotion, List, Refresh, CircleCheck, SuccessFilled, WarningFilled } from '@element-plus/icons-vue'
import { adminApi, conversationApi, ordersApi, businessApi, nodesApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { handleAuthExpired } from '@/utils/authExpired'
import { extractErrorMessage } from '@/utils/errorMessage'
import { getLastConversationId, setLastConversationId } from '@/utils/sessionState'
import OrderDetailPanel from '@/components/OrderDetailPanel.vue'
import {
  modalityLabel,
  taskTypeLabel,
  describeDataProfile,
  formatMetricValue,
} from '@/constants/businessTaskDisplay'
import { routingPolicyLabel, DEPLOYMENT_STATUS_LABELS, ORDER_STATUS_LABELS } from '@/constants/routingPolicy'

const router = useRouter()
const auth = useAuthStore()
const conversations = ref([])
const conversation = ref(null)
const localMessages = ref([])  // temporary messages during streaming only
const utterance = ref('')
const loading = ref(false)
const isStreaming = ref(false)
const isConfirming = ref(false)
const isDemoRouting = ref(false)
const messagesRef = ref(null)
const myOrders = ref([])
const ordersLoading = ref(false)
const showOrders = ref(false)
const orderDrawerVisible = ref(false)
const selectedOrderId = ref(null)
const selectedOrderDetail = ref(null)
const orderDetailLoading = ref(false)
const orderActionLoading = ref('')
const orderStatusFilter = ref('')
const orderDetailTab = ref('business')
const orderResultObjects = ref([])
const showRoutingDagJson = ref(false)
const availableNodes = ref([])
const endpointForm = ref({
  source_endpoint_input: '',
  destination_endpoint_input: '',
  destination_port: null,
  callback_url: '',
  callback_url_customized: false,
  route_only: false,
})

const DEFAULT_DESTINATION_PORT_BY_TASK_TYPE = {
  high_throughput_matmul: 9000,
  low_latency_video_pipeline: 9100,
}

const ENDPOINT_IMAGE_BY_TASK_TYPE = {
  high_throughput_matmul: '10.112.244.94:5000/scientific-matmul-endpoint:dev',
  low_latency_video_pipeline: '10.112.244.94:5000/low-latency-video-endpoint:dev',
}

let routingTimer = null
let abortController = null

const filteredOrders = computed(() => {
  if (!orderStatusFilter.value) return myOrders.value
  return myOrders.value.filter(o => o.order_status === orderStatusFilter.value)
})

const displayMessages = computed(() => {
  const backendMsgs = conversation.value?.messages || []
  return [...backendMsgs, ...localMessages.value]
})

function toggleOrders() { showOrders.value = !showOrders.value }

const exampleChips = [
  '矩阵乘法任务，从 h1 到 h2，1024阶矩阵，50批，现在开始跑2小时，资源保障策略',
  '视频AI推理任务，从 h3 到 h4，720p视频，100帧，30fps，现在开始跑2小时，低时延策略',
  '从 h5 到 h6 跑 matmul，2048x2048，batch 20，立即运行60分钟，尽快完成',
  '从 h6 到 h7 做工业检测视频推理，720p，抽取100帧，要求低时延，马上运行60分钟',
  '矩阵计算，源节点 h8 目的节点 h9，规模 512，80批次，马上开始跑3小时，负载均衡',
]
const supportedTaskHints = [
  {
    type: 'high_throughput_matmul',
    label: taskTypeLabel('high_throughput_matmul'),
    hint: '适合表达为“矩阵乘法、矩阵计算、高通量计算”，需给出源节点、目的节点、矩阵规模和批次数。',
  },
  {
    type: 'low_latency_video_pipeline',
    label: taskTypeLabel('low_latency_video_pipeline'),
    hint: '适合表达为“视频AI推理、工业检测、低时延转发”，需给出源节点、目的节点、分辨率、帧数和帧率。',
  },
]

const draft = computed(() => conversation.value?.latest_draft || null)
const draftDataProfileRows = computed(() => describeDataProfile(draft.value?.task_type, draft.value?.data_profile) || [])
const intentSummaryRows = computed(() => {
  if (!draft.value) return []
  const rows = [
    { label: '任务类型', value: taskTypeLabel(draft.value.task_type) || draft.value.task_type || '-' },
    { label: '所属模态', value: modalityLabel(draft.value.modality) },
    { label: '源节点', value: formatDraftEndpoint('source') },
    { label: '目的节点', value: formatDraftEndpoint('destination') },
    ...(destinationReceiverText.value ? [{ label: '结果接收', value: destinationReceiverText.value }] : []),
    { label: '开始时间', value: formatTime(draft.value.business_start_time) },
    { label: '结束时间', value: formatTime(draft.value.business_end_time) },
    ...draftDataProfileRows.value,
    { label: '路由策略', value: formatRoutingStrategy(draft.value.runtime_plan?.routing_strategy) },
  ]
  return rows.filter(row => !isBlankValue(row.value))
})
const effectiveDraftForValidation = computed(() => buildDraftWithEndpointForm(draft.value))
const draftValidationErrors = computed(() => getDraftValidationErrors(effectiveDraftForValidation.value))
const effectiveParseStatus = computed(() => {
  if (!draft.value) return ''
  if (draft.value.parse_status === 'rejected') return 'rejected'
  return draftValidationErrors.value.length ? 'incomplete' : draft.value.parse_status
})
const destinationPort = computed(() => {
  const explicitPort = endpointForm.value.destination_port ?? draft.value?.runtime_plan?.destination_port
  if (explicitPort) return Number(explicitPort)
  return DEFAULT_DESTINATION_PORT_BY_TASK_TYPE[draft.value?.task_type] || null
})
const destinationHost = computed(() =>
  draft.value?.destination_endpoint?.business_ipv6
  || draft.value?.destination_endpoint?.business_ip
  || draft.value?.destination_name
  || ''
)
const destinationReceiverText = computed(() => {
  if (!destinationHost.value || !destinationPort.value) return ''
  const name = draft.value?.destination_name || '目的端'
  return `${name}（${destinationHost.value}:${destinationPort.value}）`
})
const effectiveCallbackUrl = computed(() => {
  if (endpointForm.value.callback_url_customized && endpointForm.value.callback_url) {
    return endpointForm.value.callback_url
  }
  if (destinationHost.value && destinationPort.value) {
    return `http://${formatCallbackHost(destinationHost.value)}:${destinationPort.value}/callback`
  }
  return draft.value?.callback_url || draft.value?.runtime_plan?.callback_url || ''
})
const sourceExecutionHint = computed(() => formatExecutionHint('源端', draft.value?.source_name, draft.value?.source_endpoint))
const destinationExecutionHint = computed(() => formatExecutionHint('目的端', draft.value?.destination_name, draft.value?.destination_endpoint))
const endpointImage = computed(() => ENDPOINT_IMAGE_BY_TASK_TYPE[draft.value?.task_type] || '')
const isRouteOnlyDraft = computed(() =>
  Boolean(endpointForm.value.route_only || draft.value?.runtime_plan?.route_only)
)
const showClientCommands = computed(() =>
  isDraftSubmittable.value && !isRouteOnlyDraft.value
)
const receiverCommand = computed(() => {
  if (!showClientCommands.value || !endpointImage.value || !destinationPort.value) return ''
  const destinationEndpoint = draft.value?.destination_endpoint || {}
  const envLines = [
    `  -e ENDPOINT_NODE_ALIAS=${draft.value?.destination_name || 'destination'} \\`,
    `  -e ENDPOINT_TOPOLOGY_NODE_ID=${destinationEndpoint.topology_node_id || draft.value?.destination_name || 'destination'} \\`,
  ]
  if (destinationEndpoint.business_ip) envLines.push(`  -e ENDPOINT_BUSINESS_IP=${destinationEndpoint.business_ip} \\`)
  if (destinationEndpoint.business_ipv6) envLines.push(`  -e ENDPOINT_BUSINESS_IPV6=${destinationEndpoint.business_ipv6} \\`)
  return [
    'docker run --rm --network host \\',
    ...envLines,
    `  ${endpointImage.value} \\`,
    `  python /app/src/receiver_main.py --port ${destinationPort.value}`,
  ].join('\n')
})
const sourceCommand = computed(() => {
  if (!showClientCommands.value || !endpointImage.value) return ''
  const profile = JSON.stringify(draft.value.data_profile || {})
  const lines = [
    '# 节点分配完成后，在工单详情中复制真实“计算服务接入地址”再启动源端',
    'docker run --rm --network host \\',
    '  -e PEER_COMPUTE_URL=<工单详情中的计算服务接入地址> \\',
    '  -e SOURCE_LISTEN=false \\',
  ]
  if (draft.value?.task_type === 'low_latency_video_pipeline') {
    lines.push('  -e WAIT_FOR_COMPUTE_READY=false \\')
  }
  lines.push(
    `  -e DATA_PROFILE='${profile}' \\`,
    `  ${endpointImage.value} \\`,
    '  python /app/src/source_main.py',
  )
  return lines.join('\n')
})
const isDraftSubmittable = computed(() =>
  draft.value?.parse_status === 'valid' && draftValidationErrors.value.length === 0
)
const canConfirm = computed(() =>
  isDraftSubmittable.value && conversation.value?.status === 'drafting' && !conversation.value?.materialized_order_id
)
const conversationStatusLabel = computed(() => {
  const s = conversation.value?.status
  return { drafting: '草稿', awaiting_routing: '待分配', ready_to_submit: '待网络就绪', submitted: '已提交', failed: '失败', cancelled: '已取消' }[s] || s || ''
})
const conversationInputLocked = computed(() =>
  Boolean(conversation.value?.materialized_order_id)
  || ['submitted', 'awaiting_routing', 'ready_to_submit'].includes(conversation.value?.status)
)
const conversationInputLockTitle = computed(() =>
  conversation.value?.materialized_order_id ? '当前对话已生成工单' : '当前对话正在处理中'
)
const conversationInputLockMessage = computed(() =>
  conversation.value?.materialized_order_id
    ? '为了避免一个对话重复提交多个任务，请点击“新建对话”继续输入新的业务需求。'
    : '系统正在处理该任务，请稍后在“我的工单”查看进度，或新建对话提交其他任务。'
)
const canDemoRoute = computed(() =>
  auth.isAdmin && conversation.value?.status === 'awaiting_routing' && !!conversation.value?.materialized_order_id
)
const canCancelSelectedOrder = computed(() => selectedOrderDetail.value?.status === 'pending')
const operatorNodeHint = computed(() => nodeHintByKinds(['terminal'], 'h1-h13'))
const computeNodeHint = computed(() => nodeHintByKinds(['worker', 'compute', 'both'], 'compute-1、compute-2、compute-3'))

watch(draft, syncEndpointFormFromDraft, { immediate: true })
watch(orderDrawerVisible, (visible) => {
  if (!visible) {
    orderDetailLoading.value = false
  }
})

function cleanupStaleElementOverlays() {
  if (orderDrawerVisible.value) return
  orderDetailLoading.value = false
  document.querySelectorAll('.el-overlay, .el-loading-mask').forEach((element) => {
    const text = element.textContent || ''
    const hasDialog = element.querySelector('.el-drawer, .el-dialog, .el-message-box')
    if (!hasDialog && !text.includes('加载中')) {
      element.remove()
    }
  })
  document.body.classList.remove('el-popup-parent--hidden')
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    cleanupStaleElementOverlays()
  }
}

function buildDraftWithEndpointForm(currentDraft) {
  if (!currentDraft) return null
  const runtimePlan = {
    ...(currentDraft.runtime_plan || {}),
    source_endpoint_input: endpointForm.value.source_endpoint_input || currentDraft.source_name,
    destination_endpoint_input: endpointForm.value.destination_endpoint_input || currentDraft.destination_name,
    destination_port: endpointForm.value.destination_port,
    route_only: Boolean(endpointForm.value.route_only),
  }
  if (endpointForm.value.callback_url_customized) {
    runtimePlan.callback_url = endpointForm.value.callback_url?.trim() || ''
  }
  return {
    ...currentDraft,
    source_name: endpointForm.value.source_endpoint_input || currentDraft.source_name,
    destination_name: endpointForm.value.destination_endpoint_input || currentDraft.destination_name,
    callback_url: runtimePlan.callback_url ?? currentDraft.callback_url,
    runtime_plan: runtimePlan,
  }
}

function syncEndpointFormFromDraft(currentDraft) {
  const runtimePlan = currentDraft?.runtime_plan || {}
  const savedCallbackUrl = currentDraft?.callback_url || runtimePlan.callback_url || ''
  const defaultCallbackUrl = buildDefaultCallbackUrlForDraft(currentDraft, runtimePlan)
  const callbackCustomized = Boolean(savedCallbackUrl && savedCallbackUrl !== defaultCallbackUrl)
  endpointForm.value = {
    source_endpoint_input: runtimePlan.source_endpoint_input || currentDraft?.source_name || '',
    destination_endpoint_input: runtimePlan.destination_endpoint_input || currentDraft?.destination_name || '',
    destination_port: runtimePlan.destination_port ?? DEFAULT_DESTINATION_PORT_BY_TASK_TYPE[currentDraft?.task_type] ?? null,
    callback_url: callbackCustomized ? savedCallbackUrl : '',
    callback_url_customized: callbackCustomized,
    route_only: Boolean(runtimePlan.route_only),
  }
}

function nodeHintByKinds(kinds, fallback) {
  const names = availableNodes.value
    .filter(node => {
      if (node.is_routable === false) return false
      const kind = String(node.node_kind || '').toLowerCase()
      return kinds.includes(kind)
    })
    .map(node => node.hostname || node.topology_node_id)
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN', { numeric: true }))
  if (!names.length) return fallback
  if (names.length <= 8) return names.join('、')
  return `${names.slice(0, 8).join('、')} 等 ${names.length} 个`
}

function formatTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatBubbleTime(value) {
  if (!value) return ''
  const d = new Date(value)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function pretty(value) {
  if (!value) return '{}'
  return JSON.stringify(value, null, 2)
}

function parseStatusType(status) {
  return { valid: 'success', incomplete: 'warning', rejected: 'danger' }[status] || 'info'
}

function formatRoutingStrategy(strategy) {
  return routingPolicyLabel(strategy)
}

function isBlankValue(value) {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') {
    return ['', '?', '-', '未知', 'null', 'None'].includes(value.trim())
  }
  return false
}

function asInteger(value) {
  if (isBlankValue(value) || typeof value === 'boolean') return null
  const number = Number(value)
  if (!Number.isInteger(number)) return null
  return number
}

function pushRangeError(errors, value, missingMessage, invalidMessage, minValue, maxValue) {
  const pushOnce = (message) => {
    if (!errors.includes(message)) errors.push(message)
  }
  if (isBlankValue(value)) {
    pushOnce(missingMessage)
    return
  }
  const number = asInteger(value)
  if (number === null || number < minValue || number > maxValue) {
    pushOnce(invalidMessage)
  }
}

function getDraftValidationErrors(currentDraft) {
  if (!currentDraft) return []
  const errors = [...(currentDraft.validation_errors || [])]
  const add = (message) => {
    if (!errors.includes(message)) errors.push(message)
  }
  const dp = currentDraft.data_profile || {}
  if (isBlankValue(currentDraft.task_type)) add('任务类型不能为空')
  if (currentDraft.task_type === 'high_throughput_matmul') {
    pushRangeError(errors, dp.matrix_size, '矩阵规模不能为空（例如：1024阶矩阵）', '矩阵规模需要是 128-32768 之间的整数', 128, 32768)
    pushRangeError(errors, dp.batch_count, '批次数不能为空（例如：50批）', '批次数需要是 1-10000 之间的整数', 1, 10000)
  } else if (currentDraft.task_type === 'low_latency_video_pipeline') {
    pushRangeError(errors, dp.frame_count, '视频帧数不能为空（例如：100帧）', '视频帧数需要是 1-100000 之间的整数', 1, 100000)
    if (isBlankValue(dp.resolution)) {
      add('视频分辨率不能为空（例如：720p 或 1080p）')
    } else if (!['480p', '720p', '1080p', '2k', '4k', '8k'].includes(String(dp.resolution).toLowerCase())) {
      add('视频分辨率请使用 480p、720p、1080p、2k、4k 或 8k')
    }
    pushRangeError(errors, dp.fps, '帧率不能为空（例如：30fps）', 'fps 需要是 1-240 之间的整数', 1, 240)
  } else if (currentDraft.task_type === 'llm_text_generation') {
    pushRangeError(errors, dp.prompt_tokens, '输入 token 数不能为空（例如：prompt 512 tokens）', '输入 token 数需要是 1-1000000 之间的整数', 1, 1000000)
    pushRangeError(errors, dp.max_new_tokens, '生成 token 数不能为空（例如：生成 256 tokens）', '生成 token 数需要是 1-1000000 之间的整数', 1, 1000000)
    pushRangeError(errors, dp.batch_size, '批大小不能为空（例如：batch 2）', '批大小需要是 1-10000 之间的整数', 1, 10000)
  }
  if (isBlankValue(currentDraft.source_name)) add('源节点不能为空')
  if (isBlankValue(currentDraft.destination_name)) add('目的节点不能为空')
  const runtimePlan = currentDraft.runtime_plan || {}
  const port = runtimePlan.destination_port ?? DEFAULT_DESTINATION_PORT_BY_TASK_TYPE[currentDraft.task_type]
  if (!runtimePlan.route_only && port !== null && port !== undefined && port !== '') {
    const numericPort = asInteger(port)
    if (numericPort === null || numericPort < 1 || numericPort > 65535) add('目的端口需要是 1-65535 之间的整数')
  }
  const callbackUrl = runtimePlan.callback_url || currentDraft.callback_url
  if (callbackUrl && !isHttpUrl(callbackUrl)) add('目的端回调地址需要是 http:// 或 https:// 开头的完整地址')
  if (isBlankValue(currentDraft.business_start_time)) add('开始时间不能为空')
  if (isBlankValue(currentDraft.business_end_time)) add('结束时间不能为空')
  if (!isBlankValue(currentDraft.business_start_time) && !isBlankValue(currentDraft.business_end_time)) {
    const start = new Date(currentDraft.business_start_time).getTime()
    const end = new Date(currentDraft.business_end_time).getTime()
    if (!Number.isFinite(start) || !Number.isFinite(end)) add('开始时间和结束时间格式不正确')
    else if (end <= start) add('结束时间需要晚于开始时间')
  }
  if (isBlankValue(currentDraft.runtime_plan?.routing_strategy)) add('路由策略不能为空')
  return errors
}

function isHttpUrl(value) {
  try {
    const parsed = new URL(String(value))
    return ['http:', 'https:'].includes(parsed.protocol) && Boolean(parsed.host)
  } catch {
    return false
  }
}

function formatCallbackHost(host) {
  const text = String(host || '')
  return text.includes(':') && !text.startsWith('[') ? `[${text}]` : text
}

function buildDefaultCallbackUrlForDraft(currentDraft, runtimePlan = {}) {
  const endpoint = currentDraft?.destination_endpoint || {}
  const host = endpoint.business_ipv6 || endpoint.business_ip || currentDraft?.destination_name
  const port = runtimePlan.destination_port ?? DEFAULT_DESTINATION_PORT_BY_TASK_TYPE[currentDraft?.task_type]
  return host && port ? `http://${formatCallbackHost(host)}:${port}/callback` : ''
}

function formatEndpoint(endpoint, fallback) {
  if (!fallback) return '-'
  if (!endpoint) return fallback
  const address = endpoint.business_ipv6 || endpoint.business_ip
  const fullId = endpoint.topology_node_id || endpoint.display_name || ''
  const idText = fullId && fullId !== fallback ? ` / ${fullId}` : ''
  return address ? `${fallback}（${address}${idText}）` : fallback
}

function formatDraftEndpoint(role) {
  if (role === 'source') return formatEndpoint(draft.value?.source_endpoint, draft.value?.source_name)
  return formatEndpoint(draft.value?.destination_endpoint, draft.value?.destination_name)
}

function formatExecutionHint(label, fallbackName, endpoint) {
  const address = endpoint?.business_ipv6 || endpoint?.business_ip
  const name = fallbackName || label
  return address ? `${label} ${name} / ${address}` : `${label} ${name}`
}

function orderStatusType(status) {
  return {
    pending: 'warning',
    awaiting_routing: 'warning',
    materialized: 'primary',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
    orphaned: 'info',
  }[status] || 'info'
}

const ORDER_STATUS_LABEL = {
  pending: '待分配',
  awaiting_routing: '待分配',
  materialized: '已部署',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  orphaned: '孤立',
}

const TASK_STATUS_LABEL = {
  pending: '待启动',
  scheduled: '已调度',
  starting: '启动中',
  running: '运行中',
  stopping: '停止中',
  stopped: '已停止',
  failed: '失败',
  expired: '已过期',
}

const PARSE_STATUS_LABEL = {
  incomplete: '参数不全',
  valid: '参数完整',
  rejected: '已拒绝',
}

function formatOrderStatus(status) {
  if (isRouteOnlyWaitingOrder(selectedOrderDetail.value)) return '待启动'
  return ORDER_STATUS_LABEL[status] || status || '-'
}

function combinedStatusType(row) {
  if (row.status === 'materialized') return 'primary'
  if (row.status === 'completed') return 'success'
  if (row.status === 'failed') return 'danger'
  if (row.status === 'cancelled') return 'info'
  if (row.routing_status === 'network_binding_ready') return 'primary'
  if (row.routing_status === 'computing') return 'warning'
  return 'warning'
}

function combinedStatusLabel(row) {
  if (isRouteOnlyWaitingOrder(row)) return '待启动'
  if (row.status === 'materialized') return '已部署'
  if (row.status === 'completed') return '已完成'
  if (row.status === 'failed') return '失败'
  if (row.status === 'cancelled') return '已取消'
  if (row.routing_status === 'network_binding_ready') return '网络准备中'
  if (row.routing_status === 'computing') return '分配中'
  return '待分配'
}

function isRouteOnlyWaitingOrder(order) {
  const deployment = order?.runtime_config?.platform_deployment
  return order?.status === 'pending'
    && order?.routing_status === 'completed'
    && deployment?.mode === 'route_only'
    && order?.materialized_instance_id == null
}

function formatTaskStatus(status) {
  return TASK_STATUS_LABEL[status] || status || '-'
}

function deploymentStatusTag(status) {
  return { running: 'success', failed: 'danger', stopped: 'info', expired: 'info' }[status] || 'warning'
}

function formatParseStatus(status) {
  return PARSE_STATUS_LABEL[status] || status || '-'
}

function formatStatus(status) {
  return ({
    drafting: '草稿中',
    awaiting_routing: '待分配',
    ready_to_submit: '待网络就绪',
    submitted: '已提交',
    rejected: '已拒绝',
    failed: '失败',
  }[status] || status || '未开始')
}

async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

async function refreshList() {
  const { data } = await conversationApi.list()
  conversations.value = data
}

async function refreshConversation() {
  if (!conversation.value?.id) return
  const { data } = await conversationApi.get(conversation.value.id)
  conversation.value = data
  await refreshList()
  await scrollToBottom()
  updateRoutingPolling()
}

async function loadConversation(id) {
  localMessages.value = []  // clear any streaming state
  const { data } = await conversationApi.get(id)
  conversation.value = data
  utterance.value = ''
  await scrollToBottom()
  updateRoutingPolling()
}

function selectConversation(id) {
  showOrders.value = false
  setLastConversationId(id)
  loadConversation(id)
}

async function startNewConversation() {
  localMessages.value = []
  const { data } = await conversationApi.create({})
  conversation.value = data
  utterance.value = ''
  setLastConversationId(data.id)
  // Prepend to list immediately so it appears highlighted at the top
  conversations.value = [data, ...conversations.value.filter(c => c.id !== data.id)]
  updateRoutingPolling()
}

async function deleteConversation(item) {
  try {
    await ElMessageBox.confirm(
      `确认删除对话「${item.title || item.id.slice(0, 8)}」？`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  try {
    await conversationApi.delete(item.id)
    conversations.value = conversations.value.filter(c => c.id !== item.id)
    ElMessage.success('对话已删除')
    if (item.id === conversation.value?.id) {
      if (conversations.value.length) {
        await loadConversation(conversations.value[0].id)
      } else {
        await startNewConversation()
      }
    }
  } catch (err) {
    ElMessage.error(extractErrorMessage(err, '删除失败'))
  }
}

async function loadOrders() {
  ordersLoading.value = true
  try {
    const { data } = await businessApi.list({ include_cancelled: true, page: 1, page_size: 100 })
    myOrders.value = data.items || data
  } catch (e) {
    ElMessage.error('加载任务列表失败')
    myOrders.value = []
  } finally {
    ordersLoading.value = false
  }
}

async function loadSystemSettings() {
  if (!auth.isAdmin) {
    showRoutingDagJson.value = false
    return
  }
  try {
    const { data } = await adminApi.getSystemSettings()
    showRoutingDagJson.value = Boolean(data?.show_routing_dag_json)
  } catch {
    showRoutingDagJson.value = false
  }
}

async function loadAvailableNodes() {
  try {
    const { data } = await nodesApi.list()
    availableNodes.value = Array.isArray(data) ? data : []
  } catch {
    availableNodes.value = []
  }
}

watch(showOrders, (val) => {
  if (val) loadOrders()
})

async function openOrderDetail(order) {
  const id = order.order_id || order.id
  if (!id) return
  selectedOrderId.value = id
  selectedOrderDetail.value = null
  orderDetailTab.value = 'business'
  orderResultObjects.value = []
  orderDrawerVisible.value = true
  orderDetailLoading.value = true
  try {
    const { data } = await ordersApi.get(id)
    selectedOrderDetail.value = data
    const evidenceInstanceId = data.instance?.id || data.materialized_instance_id
    if (evidenceInstanceId) {
      try {
        const { data: objs } = await businessApi.results(evidenceInstanceId, { silentError: true })
        orderResultObjects.value = objs || []
      } catch { /* ignore */ }
    }
  } catch {
    // keep null
  } finally {
    orderDetailLoading.value = false
  }
}

async function refreshSelectedOrderDetail() {
  if (!selectedOrderId.value) return
  await openOrderDetail({ id: selectedOrderId.value })
}

async function cancelSelectedOrder() {
  if (!selectedOrderId.value || orderActionLoading.value) return
  try {
    await ElMessageBox.confirm('确定取消此工单？取消后不会继续分配或启动计算节点。', '确认取消工单', {
      confirmButtonText: '取消工单',
      cancelButtonText: '返回',
      type: 'warning',
    })
  } catch {
    return
  }

  orderActionLoading.value = 'cancel'
  try {
    await ordersApi.cancel(selectedOrderId.value)
    ElMessage.success('工单已取消')
    await loadOrders()
    await refreshSelectedOrderDetail()
    if (conversation.value?.materialized_order_id === selectedOrderId.value) {
      await loadConversation(conversation.value.id)
    }
  } catch (err) {
    ElMessage.error(extractErrorMessage(err, '取消失败'))
  } finally {
    orderActionLoading.value = ''
  }
}

async function deleteSelectedOrder() {
  if (!selectedOrderId.value || orderActionLoading.value) return
  const deletingOrderId = selectedOrderId.value
  try {
    await ElMessageBox.confirm(
      '删除工单前会先停止并清理该工单关联的部署实例；如果容器清理失败，工单不会被删除。继续吗？',
      '确认删除工单',
      {
        confirmButtonText: '删除工单',
        cancelButtonText: '返回',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  orderActionLoading.value = 'delete'
  try {
    await ordersApi.delete(deletingOrderId)
    ElMessage.success('工单已删除')
    orderDrawerVisible.value = false
    selectedOrderId.value = null
    selectedOrderDetail.value = null
    orderResultObjects.value = []
    await loadOrders()
    if (conversation.value?.materialized_order_id === deletingOrderId) {
      await loadConversation(conversation.value.id)
    }
  } catch (err) {
    ElMessage.error(extractErrorMessage(err, '删除失败'))
  } finally {
    orderActionLoading.value = ''
  }
}

function useChip(text) {
  utterance.value = text
}

async function sendMessage() {
  if (conversationInputLocked.value) {
    ElMessage.warning('当前对话已生成工单，请新建对话继续提交新任务')
    return
  }
  if (!utterance.value.trim() || loading.value || isStreaming.value) return
  loading.value = true
  const text = utterance.value.trim()
  utterance.value = ''

  try {
    if (!conversation.value?.id) {
      await startNewConversation()
    }

    // Add to LOCAL messages only — never touch conversation.value.messages
    localMessages.value = [
      { role: 'user', content: text, id: '_local_user_' + Date.now() },
      { role: 'assistant', content: '', id: '_stream', streaming: true },
    ]
    await nextTick()
    await scrollToBottom()

    const token = localStorage.getItem('access_token')
    abortController = new AbortController()
    isStreaming.value = true

    const response = await fetch(`/api/conversations/${conversation.value.id}/messages/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ content: text }),
      signal: abortController.signal,
    })

    if (response.status === 401) {
      handleAuthExpired()
      return
    }

    if (!response.ok) throw new Error(`HTTP ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const raw = line.slice(5).trim()
        try {
          const event = JSON.parse(raw)
          if (event.type === 'token') {
            // Update the streaming placeholder in localMessages
            const idx = localMessages.value.findIndex(m => m.id === '_stream')
            if (idx !== -1) {
              localMessages.value = [
                ...localMessages.value.slice(0, idx),
                { ...localMessages.value[idx], content: localMessages.value[idx].content + event.content },
                ...localMessages.value.slice(idx + 1),
              ]
            }
            await scrollToBottom()
          } else if (event.type === 'done') {
            isStreaming.value = false
            // Clear local messages BEFORE loading from backend to avoid flash
            localMessages.value = []
            await loadConversation(conversation.value.id)
            await refreshList()
          } else if (event.type === 'error') {
            const idx = localMessages.value.findIndex(m => m.id === '_stream')
            if (idx !== -1) {
              localMessages.value = [
                ...localMessages.value.slice(0, idx),
                { ...localMessages.value[idx], content: localMessages.value[idx].content || '解析失败，请重试', streaming: false },
                ...localMessages.value.slice(idx + 1),
              ]
            }
          }
        } catch { /* ignore malformed SSE */ }
      }
    }

    // Stream ended naturally without 'done' event
    isStreaming.value = false
    if (localMessages.value.some(m => m.id === '_stream')) {
      localMessages.value = []
      await loadConversation(conversation.value.id)
      await refreshList()
    }

  } catch (err) {
    isStreaming.value = false
    if (err.name === 'AbortError') {
      // User stopped — keep accumulated content, mark as done
      localMessages.value = localMessages.value.map(m =>
        m.id === '_stream' ? { ...m, streaming: false } : m
      )
      // Reload to get persisted state
      if (conversation.value?.id) {
        await loadConversation(conversation.value.id)
        localMessages.value = []
      }
    } else {
      localMessages.value = localMessages.value.map(m =>
        m.id === '_stream' ? { ...m, content: m.content || '解析失败，请重试', streaming: false } : m
      )
    }
  } finally {
    loading.value = false
    isStreaming.value = false
    abortController = null
  }
}

function stopStreaming() {
  abortController?.abort()
}

async function confirmIntent() {
  if (isConfirming.value) return
  if (!canConfirm.value) {
    const hint = draftValidationErrors.value.length
      ? draftValidationErrors.value.join('；')
      : '请先补全任务参数'
    ElMessage.warning(hint)
    return
  }
  isConfirming.value = true
  try {
    const updated = await syncEndpointDraftBeforeConfirm()
    if (updated) conversation.value = updated
    const { data } = await conversationApi.confirmIntent(conversation.value.id)
    conversation.value = data
    await refreshList()
    const routeOnly = isRouteOnlyDraft.value
    const autoRouted = data.status === 'submitted'
    ElMessage.success(
      routeOnly
        ? '已提交，节点分配方案生成后将等待手动启动'
        : autoRouted
          ? '任务已提交，系统已完成节点分配'
          : '任务已提交，系统将继续处理'
    )
    localMessages.value.push({
      id: 'submit-success',
      role: 'assistant',
      content: routeOnly
        ? `任务已提交，任务 ID：${data.id.slice(0, 8)}。本次只生成节点分配方案，方案生成后状态为“待启动”，可手动启动计算节点。`
        : autoRouted
          ? `任务已提交，任务 ID：${data.id.slice(0, 8)}。系统已完成节点分配并生成计算节点接入信息，您可以在“我的工单”查看详情。`
        : `任务已提交，任务 ID：${data.id.slice(0, 8)}。系统将等待节点分配并部署计算节点，您可以在“我的工单”查看进度。`,
      created_at: new Date().toISOString(),
    })
    await scrollToBottom()
    updateRoutingPolling()
    if (showOrders.value) loadOrders()
  } catch (err) {
    const detail = err.response?.data?.detail
    if (detail?.validation_errors) {
      ElMessage.warning('参数不完整：' + detail.validation_errors.join('；'))
    } else {
      ElMessage.error(extractErrorMessage(err, '确认失败'))
    }
  } finally {
    isConfirming.value = false
  }
}

function normalizedEndpointFormPayload() {
  const port = endpointForm.value.destination_port
  const callbackUrl = endpointForm.value.callback_url_customized
    ? endpointForm.value.callback_url?.trim() || null
    : undefined
  return {
    source_endpoint_input: endpointForm.value.source_endpoint_input?.trim() || null,
    destination_endpoint_input: endpointForm.value.destination_endpoint_input?.trim() || null,
    destination_port: port === '' || port === null || port === undefined ? null : Number(port),
    callback_url: callbackUrl,
    route_only: Boolean(endpointForm.value.route_only),
  }
}

function endpointPayloadChanged(payload) {
  const runtimePlan = draft.value?.runtime_plan || {}
  const currentPort = runtimePlan.destination_port ?? DEFAULT_DESTINATION_PORT_BY_TASK_TYPE[draft.value?.task_type] ?? null
  return (
    payload.source_endpoint_input !== (runtimePlan.source_endpoint_input || draft.value?.source_name || null)
    || payload.destination_endpoint_input !== (runtimePlan.destination_endpoint_input || draft.value?.destination_name || null)
    || payload.destination_port !== currentPort
    || (endpointForm.value.callback_url_customized && payload.callback_url !== (runtimePlan.callback_url || null))
    || payload.route_only !== Boolean(runtimePlan.route_only)
  )
}

async function syncEndpointDraftBeforeConfirm() {
  const payload = normalizedEndpointFormPayload()
  if (!endpointPayloadChanged(payload)) return null
  const { data } = await conversationApi.updateDraft(conversation.value.id, payload)
  const errors = getDraftValidationErrors(data.latest_draft)
  if (errors.length) {
    throw { response: { data: { detail: { validation_errors: errors } } } }
  }
  return data
}

async function demoRoute() {
  if (!conversation.value?.id || isDemoRouting.value) return
  isDemoRouting.value = true
  try {
    const { data } = await conversationApi.demoRoute(conversation.value.id)
    conversation.value = data
    await refreshList()
    if (showOrders.value) await loadOrders()
    ElMessage.success('计算节点已启动')
  } catch (err) {
    ElMessage.error(extractErrorMessage(err, '启动计算节点失败'))
  } finally {
    isDemoRouting.value = false
  }
}

function updateRoutingPolling() {
  stopRoutingPolling()
  const status = conversation.value?.latest_routing_request?.status
  if (status === 'pending' || status === 'computing') {
    routingTimer = setInterval(refreshConversation, 3000)
  }
}

function stopRoutingPolling() {
  if (routingTimer) {
    clearInterval(routingTimer)
    routingTimer = null
  }
}

function logout() {
  auth.logout()
  router.push('/login')
}

onMounted(async () => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  try {
    await loadSystemSettings()
    await loadAvailableNodes()
    await refreshList()
    const lastId = getLastConversationId()
    const target = lastId && conversations.value.find(c => c.id === lastId)
    const editableTarget = conversations.value.find(item =>
      item.status === 'drafting' && !item.materialized_order_id
    )
    if (target && target.status === 'drafting' && !target.materialized_order_id) {
      await loadConversation(lastId)
    } else if (editableTarget) {
      setLastConversationId(editableTarget.id)
      await loadConversation(editableTarget.id)
    } else {
      await startNewConversation()
    }
  } catch (err) {
    if (!err?.__authExpired) {
      ElMessage.error(extractErrorMessage(err, '页面初始化失败，请刷新重试'))
    }
  } finally {
    loading.value = false
    isStreaming.value = false
    ordersLoading.value = false
    orderDetailLoading.value = false
  }
})

onBeforeUnmount(() => {
  stopRoutingPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
/* ── App shell (top bar + workspace + bottom bar) ── */
.intent-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── Top bar ── */
.top-bar {
  flex-shrink: 0;
  height: 48px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 16px;
  z-index: 10;
}

.top-bar-left { display: flex; align-items: center; width: 260px; flex-shrink: 0; }
.top-logo { font-size: 15px; font-weight: 700; color: var(--text-primary); letter-spacing: 0.02em; }

.top-bar-center { flex: 1; min-width: 0; text-align: center; }
.top-conv-title {
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  max-width: 400px;
}

.top-bar-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.model-badge { font-size: 11px; }
.user-chip {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 12px;
}

/* ── Bottom status bar ── */
.bottom-bar {
  flex-shrink: 0;
  height: 32px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  font-size: 11px;
  color: #b8c0d6;
}

.intent-workspace {
  display: grid;
  grid-template-columns: 260px minmax(520px, 1fr) 340px;
  flex: 1;
  min-height: 0;
  background: var(--bg-primary);
  color: var(--text-primary);
}

/* ── Sidebar ── */
.conversation-sidebar {
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.sidebar-top {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 20px 20px 0;
}

.sidebar-conversations {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-bottom: 12px;
}

.sidebar-bottom {
  flex-shrink: 0;
  padding: 12px 16px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.new-conv-btn {
  width: 100%;
  margin-bottom: 4px;
  justify-content: center;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar-sm {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.username-label {
  font-size: 13px;
  color: #d7dded;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-btn {
  width: 100%;
  justify-content: flex-start;
  color: #d7dded !important;
  font-size: 13px;
}

.brand {
  display: none;
}

.brand-title {
  display: none;
}

.brand-subtitle {
  display: none;
}

.sidebar-nav {
  margin-bottom: 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  cursor: pointer;
  border-radius: 8px;
  color: rgba(255,255,255,0.82);
  transition: all 0.2s;
}

.nav-item:hover, .nav-item.active {
  background: rgba(255,255,255,0.15);
  color: white;
}

.conv-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0 4px;
  font-size: 12px;
  color: rgba(255,255,255,0.78);
  margin: 18px 0 6px;
}

.history-title {
  color: var(--text-secondary);
  font-size: 12px;
  margin: 18px 0 10px;
}

.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 10px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
}

.conversation-item:hover { border-color: var(--el-color-primary-light-5); }
.conversation-item.active {
  border-color: var(--accent-primary);
  background: rgba(255,255,255,0.15);
  border-left: 3px solid var(--el-color-primary);
}

.conversation-item-body { flex: 1; min-width: 0; }
.conversation-item-body span,
.conversation-item-body small { display: block; }
.conversation-item-body span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conversation-item-body small {
  margin-top: 4px;
  color: #bcc5da;
}

.delete-btn { flex-shrink: 0; opacity: 0; transition: opacity 0.15s; }
.conversation-item:hover .delete-btn { opacity: 1; }

/* orders */
.orders-section {
  margin-top: 20px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 12px;
}
.orders-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 4px 0;
  user-select: none;
}
.orders-header:hover { color: var(--text-primary); }
.orders-arrow { transition: transform 0.2s; }
.orders-arrow.expanded { transform: rotate(90deg); }
.orders-list { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.orders-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 8px 0;
}
.order-item {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--bg-tertiary);
}
.order-name {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}
.order-meta { display: flex; align-items: center; gap: 6px; }
.order-time { font-size: 11px; color: var(--text-muted); }

/* ── Chat header right ── */
.chat-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

/* ── Inline orders panel ── */
.orders-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  height: 100%;
  background: var(--el-bg-color, white);
}

.orders-panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.orders-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.orders-panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.orders-table {
  flex: 1;
  overflow-y: auto;
}

.orders-detail-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 0;
}

.detail-desc-block {
  margin: 0;
}

/* ── Chat column ── */
.chat-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  overflow: hidden;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 14px 24px;
  border-bottom: 1px solid var(--border-subtle);
}
.chat-header h1 { font-size: 20px; margin-bottom: 4px; }
.chat-header p { color: #d7dded; font-size: 13px; }

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 24px;
}

/* ── Empty state ── */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 28px 24px;
  text-align: center;
  gap: 12px;
}

.empty-avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 28px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}

.empty-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.empty-subtitle {
  font-size: 14px;
  color: #d7dded;
  margin: 0;
}

.example-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
}

.chip {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-subtle);
  border-radius: 20px;
  padding: 6px 14px;
  font-size: 13px;
  color: #d7dded;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.chip:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

/* ── Message bubbles ── */
.message-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.message-row.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.assistant-avatar {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
}

.user-avatar {
  background: linear-gradient(135deg, #0ea5e9, #6366f1);
  color: #fff;
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 75%;
}

.user-bubble-wrap {
  align-items: flex-end;
}

.bubble-name {
  font-size: 11px;
  color: #bdc6dd;
  padding: 0 4px;
}

.user-name {
  text-align: right;
}

.bubble {
  padding: 10px 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-bubble {
  background: #f0f7ff;
  color: #1e293b;
  border-radius: 4px 16px 16px 16px;
}

.user-bubble {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  border-radius: 16px 4px 16px 16px;
}

.bubble-text { display: inline; }

.bubble-time {
  font-size: 11px;
  color: #aeb8d0;
  padding: 0 4px;
}

.user-time {
  text-align: right;
}

.streaming-cursor {
  display: inline-block;
  margin-left: 2px;
  animation: blink 0.8s step-end infinite;
  color: #6366f1;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ── Confirm card ── */
.confirm-card {
  margin: 10px 24px;
  padding: 14px 18px;
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: 12px;
}
.confirm-card-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.confirm-icon {
  font-size: 24px;
  color: #22c55e;
}
.confirm-text {
  flex: 1 1 220px;
  min-width: 0;
}
.confirm-text p {
  margin: 4px 0 0;
  font-size: 13px;
  color: #334155;
}
.confirm-params {
  margin: 8px 0;
  font-size: 13px;
  color: #243447;
  line-height: 1.8;
}
.confirm-params .param-label {
  color: #475569;
  font-weight: 600;
}

.pending-card {
  background: #fff7ed;
  border-color: #fdba74;
}

.pending-icon {
  color: #ea580c;
  font-size: 24px;
}

.missing-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.missing-list span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #fed7aa;
  color: #7c2d12;
  font-size: 12px;
  font-weight: 600;
}

.submit-options-collapse {
  margin-top: 8px;
}

.submit-options-collapse :deep(.el-collapse-item__header) {
  height: 30px;
  color: #334155;
  background: transparent;
  border-bottom: 0;
  font-size: 12px;
}

.submit-options-collapse :deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom: 0;
}

.submit-options-form {
  padding: 2px 0 6px;
}

.submit-options-form :deep(.el-form-item) {
  margin-bottom: 8px;
}

.submit-options-form :deep(.el-form-item__label) {
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}

.submit-options-note {
  margin: 6px 0 0;
  color: #334155;
  font-size: 12px;
  line-height: 1.5;
}

.client-command-panel {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.client-command-header {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: 8px;
}

.client-command-header strong {
  color: var(--text-primary);
  font-size: 13px;
}

.client-command-header span,
.command-note {
  color: #334155;
  font-size: 12px;
  line-height: 1.5;
}

.client-step-list {
  margin: 0 0 8px 18px;
  color: #1f2937;
  font-size: 12px;
  line-height: 1.7;
}

.advanced-command-collapse {
  --el-collapse-header-height: 34px;
  border-top: 0;
  border-bottom: 0;
}

.advanced-command-collapse :deep(.el-collapse-item__header) {
  color: #1f2937;
  font-size: 12px;
  font-weight: 700;
}

.advanced-command-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
}

.command-block {
  margin-top: 8px;
}

.command-title {
  margin-bottom: 4px;
  color: #1f2937;
  font-size: 12px;
  font-weight: 600;
}

.command-block pre {
  margin: 0;
  padding: 8px;
  overflow-x: auto;
  border-radius: 8px;
  background: #0f172a;
  color: #e5e7eb;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ── Composer ── */
.composer {
  flex-shrink: 0;
  padding: 12px 24px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-secondary);
}

.composer-lock-tip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(99, 102, 241, 0.28);
  border-radius: 10px;
  background: #eef4ff;
  color: #1e293b;
}

.composer-lock-tip strong {
  display: block;
  margin-bottom: 3px;
  font-size: 13px;
  color: #111827;
}

.composer-lock-tip span {
  display: block;
  font-size: 12px;
  line-height: 1.5;
  color: #334155;
}

.composer-actions {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.composer-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.composer-hint {
  font-size: 12px;
  color: #bdc6dd;
}

.composer-btns {
  display: flex;
  gap: 8px;
}

.drawer-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.drawer-title-row,
.drawer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.drawer-title-row {
  min-width: 0;
  font-weight: 700;
  color: #111827;
}

.drawer-actions {
  flex-shrink: 0;
}

:global(.node-popover) {
  color: #1f2937;
}

:global(.node-popover .node-popover-body) {
  display: flex;
  flex-direction: column;
  gap: 8px;
  line-height: 1.55;
}

:global(.node-popover .node-popover-body strong) {
  color: #111827;
  font-size: 14px;
}

:global(.node-popover .node-popover-body p) {
  margin: 0;
  color: #334155;
  font-size: 13px;
}

:global(.node-popover .node-popover-tags) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:global(.node-popover .node-popover-tags span) {
  padding: 5px 9px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
}

:global(.node-popover .task-popover-list) {
  display: grid;
  gap: 8px;
}

:global(.node-popover .task-popover-item) {
  padding: 9px 10px;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  background: #f8fbff;
}

:global(.node-popover .task-popover-item strong) {
  display: block;
  margin-bottom: 3px;
  color: #0f172a;
  font-size: 13px;
}

:global(.node-popover .task-popover-item span) {
  display: block;
  color: #334155;
  font-size: 12px;
  line-height: 1.5;
}

/* ── Right panel ── */
.intent-panel {
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-subtle);
  padding: 14px;
  overflow-y: auto;
}

.panel-card { margin-bottom: 12px; }
.panel-card.valid-border { border-color: var(--el-color-success); }

.intent-summary-list {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #d8e2ef;
  border-radius: 12px;
  background: #fff;
}

.intent-summary-row {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid #e6edf5;
}

.intent-summary-row:last-child {
  border-bottom: 0;
}

.intent-summary-label {
  min-width: 0;
  color: #1f2937;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.5;
  white-space: nowrap;
}

.intent-summary-value {
  min-width: 0;
  color: #111827;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.65;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.errors {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.raw-collapse {
  margin-top: 12px;
}

.json-block {
  max-height: 320px;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: #0f172a;
  color: #dbeafe;
  font-size: 12px;
  line-height: 1.55;
}

.verdict-block.success { background: var(--el-color-success-light-9); border: 1px solid var(--el-color-success-light-5); }
.verdict-block.danger  { background: var(--el-color-danger-light-9);  border: 1px solid var(--el-color-danger-light-5); }
.verdict-block.warning { background: var(--el-color-warning-light-9); border: 1px solid var(--el-color-warning-light-5); }

.video-result-card {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  align-items: start;
  margin-bottom: 12px;
}

.video-preview {
  min-height: 220px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  background: var(--el-fill-color-light);
  overflow: hidden;
}

.video-proof-frame {
  position: relative;
}

.video-preview img,
.video-proof-frame img {
  display: block;
  width: 100%;
  height: auto;
}

.video-proof-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.video-proof-badge {
  position: absolute;
  left: 10px;
  bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: calc(100% - 20px);
}

.video-proof-badge span,
.video-proof-box span {
  color: #fff;
  background: rgba(15, 23, 42, 0.88);
  border-radius: 6px;
  padding: 3px 7px;
  font-size: 12px;
  line-height: 1.4;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.28);
}

.video-proof-box {
  position: absolute;
  border: 2px solid #22c55e;
  box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.3);
}

.video-proof-box span {
  position: absolute;
  left: -2px;
  top: -28px;
  background: rgba(22, 163, 74, 0.94);
  white-space: nowrap;
}

.video-result-side {
  min-width: 0;
}

@media (max-width: 900px) {
  .intent-workspace {
    grid-template-columns: 220px 1fr;
  }
  .intent-panel { display: none; }
}
</style>
