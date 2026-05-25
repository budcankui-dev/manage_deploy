export const TASK_TYPE_LABELS = {
  high_throughput_matmul: '高通量矩阵乘法',
  low_latency_video_pipeline: '低时延视频链路',
}

export const TASK_TYPE_SUMMARIES = {
  high_throughput_matmul:
    '在 source → compute → sink 三节点流水线中执行 batched 矩阵乘法，以计算耗时作为吞吐/性能验收指标。',
  low_latency_video_pipeline:
    '在 source → compute → sink 链路上处理视频帧流，以端到端时延作为体验验收指标。',
}

const METRIC_LABELS = {
  compute_latency_ms: '计算耗时',
  end_to_end_latency_ms: '端到端时延',
}

const OPERATOR_LABELS = {
  '<=': '不超过',
  '>=': '不低于',
  '==': '等于',
}

export function taskTypeLabel(taskType) {
  if (!taskType) return '-'
  return TASK_TYPE_LABELS[taskType] || taskType
}

export function taskTypeSummary(taskType) {
  return TASK_TYPE_SUMMARIES[taskType] || '按业务目标指标验收任务是否达标。'
}

export function formatObjectiveSentence(objective) {
  if (!objective?.metric_key) return '-'
  const metric = METRIC_LABELS[objective.metric_key] || objective.metric_key
  const op = OPERATOR_LABELS[objective.operator] || objective.operator || '不超过'
  const unit = objective.unit ? ` ${objective.unit}` : ''
  const target = objective.target_value ?? '-'
  return `${metric} ${op} ${target}${unit}`
}

export function describeObjectiveMeaning(taskType, objective) {
  if (!objective) return '-'
  const sentence = formatObjectiveSentence(objective)
  if (taskType === 'high_throughput_matmul') {
    return `验收标准：${sentence}。数值越小表示计算越快；任务跑完后由 sink 上报实际耗时并与目标对比。`
  }
  if (taskType === 'low_latency_video_pipeline') {
    return `验收标准：${sentence}。数值越小表示链路响应越快；从源到汇总的处理全链路时延需满足阈值。`
  }
  return `验收标准：${sentence}。`
}

export function describeDataProfile(taskType, profile) {
  if (!profile) return []
  if (taskType === 'high_throughput_matmul') {
    const size = profile.matrix_size ?? '?'
    const batch = profile.batch_count ?? 1
    const seed = profile.seed ?? '?'
    return [
      { label: '计算内容', value: `${batch} 批 ${size}×${size} 随机矩阵乘法（FP32）` },
      { label: '随机种子', value: String(seed) },
      { label: '画像 ID', value: profile.profile_id || '-' },
    ]
  }
  if (taskType === 'low_latency_video_pipeline') {
    return [
      { label: '视频文件', value: profile.file || '-' },
      { label: '数据集', value: profile.dataset || '-' },
      { label: '画像 ID', value: profile.profile_id || '-' },
    ]
  }
  return Object.entries(profile).map(([key, value]) => ({
    label: key,
    value: typeof value === 'object' ? JSON.stringify(value) : String(value),
  }))
}

export function describeRuntimePlan(taskType, plan) {
  if (!plan) return []
  if (taskType === 'high_throughput_matmul') {
    return [
      { label: '算法', value: plan.algorithm || 'batched_matmul' },
      { label: '精度', value: plan.precision || '-' },
      { label: 'GPU', value: plan.use_gpu ? '是' : '否' },
    ]
  }
  if (taskType === 'low_latency_video_pipeline') {
    return [
      { label: '编码', value: plan.codec || '-' },
      { label: '预设', value: plan.preset || '-' },
      { label: '模式', value: plan.process_mode || '-' },
    ]
  }
  return Object.entries(plan).map(([key, value]) => ({
    label: key,
    value: typeof value === 'object' ? JSON.stringify(value) : String(value),
  }))
}

export function buildComputeResultSummary(taskType, businessTask, evaluation, resultMetadata) {
  if (taskType !== 'high_throughput_matmul') return null
  const profile = businessTask?.data_profile || {}
  const size = profile.matrix_size
  const batch = profile.batch_count ?? 1
  const seed = profile.seed
  const lines = [
    {
      label: '算了什么',
      value: size
        ? `执行 ${batch} 批 ${size}×${size} 矩阵乘法（seed=${seed ?? '?'})`
        : '矩阵乘法批处理（参数见数据画像）',
    },
  ]
  if (evaluation) {
    const unit = evaluation.unit || 'ms'
    lines.push({
      label: '实际耗时',
      value: `${Number(evaluation.actual_value).toFixed(2)} ${unit}`,
    })
    lines.push({
      label: '目标阈值',
      value: `${evaluation.target_value} ${unit}`,
    })
    lines.push({
      label: '是否达标',
      value: evaluation.business_success ? '达标' : '未达标',
      highlight: evaluation.business_success ? 'success' : 'danger',
    })
  } else {
    lines.push({ label: '运行状态', value: '尚未上报计算结果' })
  }
  if (resultMetadata?.checksum) {
    lines.push({
      label: '结果校验和',
      value: resultMetadata.checksum,
      hint: '由 compute 节点对结果矩阵首元素取 6 位小数，用于核对计算已产出且可复现。',
    })
  }
  return lines
}
