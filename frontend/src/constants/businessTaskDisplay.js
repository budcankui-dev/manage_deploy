export const TASK_TYPE_LABELS = {
  high_throughput_matmul: '矩阵乘法计算任务',
  low_latency_video_pipeline: '低时延视频链路',
  llm_text_generation: '大模型文本生成任务',
}

export const TASK_TYPE_SUMMARIES = {
  high_throughput_matmul:
    '在 source → compute → sink 三节点流水线中通过 HTTP 传递任务与结果，以有效计算吞吐量作为矩阵乘法计算任务的验收指标。',
  low_latency_video_pipeline:
    '在 source → compute → sink 链路上处理视频帧流，以端到端时延作为体验验收指标。',
  llm_text_generation:
    '在 source → inference → sink 链路上完成提示词分发、文本生成和结果归档，以生成速率或响应时延作为验收指标。',
}

const METRIC_LABELS = {
  compute_latency_ms: '计算耗时',
  end_to_end_latency_ms: '端到端时延',
  effective_gflops: '计算性能',
  tokens_per_second: '生成速率',
  avg_frame_latency_ms: '帧推理时延',
}

const OPERATOR_LABELS = {
  '<=': '不超过',
  '>=': '不低于',
  '==': '等于',
}

export const MATMUL_PIPELINE_STEPS = [
  { role: 'source', title: '准备输入', detail: '根据 data_profile 生成矩阵乘法任务并通过 HTTP 发给 compute' },
  { role: 'compute', title: '执行计算', detail: 'NumPy 执行 batched FP32 矩阵乘法，并通过 HTTP 发给 sink' },
  { role: 'sink', title: '上报结果', detail: '接收计算结果，向 Manager 上报 effective_gflops 和采样元数据' },
]

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
    return `验收标准：${sentence}。以有效计算吞吐量和节点历史基线对比判定业务目标是否达标；计算跑通并上报指标后即可参与成功率统计。`
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
      { label: '矩阵规模', value: `${size} × ${size}` },
      { label: '批次数', value: String(batch) },
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

export function buildMatmulInputRows(dataProfile) {
  return describeDataProfile('high_throughput_matmul', dataProfile || {})
}

export function buildMatmulOutputRows(resultMetadata, evaluation) {
  const rows = []
  const meta = resultMetadata || {}
  if (meta.matrix_size != null) {
    rows.push({ label: '运行矩阵规模', value: `${meta.matrix_size} × ${meta.matrix_size}` })
  }
  if (meta.batch_count != null) {
    rows.push({ label: '运行批次数', value: String(meta.batch_count) })
  }
  if (meta.compute_latency_ms != null) {
    rows.push({ label: '观测窗口耗时', value: `${Number(meta.compute_latency_ms).toFixed(2)} ms` })
  }
  if (meta.sample_count != null) {
    rows.push({ label: '有效样本数', value: String(meta.sample_count) })
  }
  if (evaluation) {
    const unit = evaluation.unit || 'ms'
    rows.push({
      label: '上报指标',
      value: `${evaluation.metric_key} = ${Number(evaluation.actual_value).toFixed(2)} ${unit}`,
    })
  }
  if (!rows.length) {
    rows.push({ label: '状态', value: '尚未收到计算输出' })
  }
  return rows
}

export function buildMatmulParamConsistency(dataProfile, resultMetadata) {
  const profile = dataProfile || {}
  const meta = resultMetadata || {}
  const checks = []
  if (profile.matrix_size != null && meta.matrix_size != null) {
    checks.push(Number(profile.matrix_size) === Number(meta.matrix_size))
  }
  if (profile.batch_count != null && meta.batch_count != null) {
    checks.push(Number(profile.batch_count) === Number(meta.batch_count))
  }
  if (!checks.length) {
    return null
  }
  const ok = checks.every(Boolean)
  return {
    ok,
    label: ok ? '输入与运行规模一致' : '输入与运行规模不一致',
    detail: ok
      ? '提交的 data_profile 与 compute 实际执行的规模一致。'
      : '请检查 source/compute 是否使用了不同的 job 参数。',
  }
}

export function buildMatmulVerdict(evaluation) {
  if (!evaluation) {
    return {
      title: '等待计算完成',
      subtitle: '启动实例并完成矩阵乘法后，sink 将上报 effective_gflops。',
      statusClass: 'pending',
    }
  }
  const unit = evaluation.unit || 'GFLOPS'
  const actual = Number(evaluation.actual_value).toFixed(2)
  const target = evaluation.target_value
  if (evaluation.business_success === null || evaluation.business_success === undefined) {
    return {
      title: '计算已完成，待评估',
      subtitle: evaluation.failure_reason || `实际 ${actual} ${unit}，尚无基线数据，无法判定是否达标。`,
      statusClass: 'warning',
    }
  }
  if (evaluation.business_success) {
    return {
      title: '计算已完成，性能达标',
      subtitle: `实际 ${actual} ${unit}，满足目标 ${formatObjectiveSentence({ metric_key: evaluation.metric_key, operator: evaluation.operator || '>=', target_value: target, unit })}。`,
      statusClass: 'success',
    }
  }
  return {
    title: '计算已完成，性能未达标',
    subtitle: evaluation.failure_reason || `实际 ${actual} ${unit}，未达到目标 ${target} ${unit}。`,
    statusClass: 'danger',
  }
}

/** @deprecated 使用 buildMatmul* 分块展示；保留供非 matmul 或简易列表 */
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
    ...buildMatmulOutputRows(resultMetadata, evaluation),
  ]
  if (evaluation) {
    lines.push({
      label: '性能达标',
      value: evaluation.business_success ? '是' : '否',
      highlight: evaluation.business_success ? 'success' : 'danger',
    })
  }
  return lines
}
