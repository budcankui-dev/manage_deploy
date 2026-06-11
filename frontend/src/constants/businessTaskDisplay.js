export const TASK_TYPE_LABELS = {
  high_throughput_matmul: '矩阵乘法计算任务',
  low_latency_video_pipeline: '视频AI推理任务',
  llm_text_generation: '大模型文本生成任务',
  ai_model_training: '文本模型训练任务',
  distributed_storage_compute: '分布式存算任务',
  massive_connection_collect: '大规模连接采集任务',
  deterministic_forwarding: '确定性转发任务',
  energy_efficient_edge_inference: '高能效边缘推理任务',
  secure_transmission: '高安全传输任务',
}

const VIDEO_LABEL_ZH = {
  person: '人员',
  bicycle: '自行车',
  car: '车辆',
  motorcycle: '摩托车',
  bus: '公交车',
  truck: '卡车',
  bottle: '瓶子',
  cup: '杯子',
  chair: '椅子',
  laptop: '笔记本电脑',
  'cell phone': '手机',
  inspection_target: '检测目标',
  none: '无目标',
}

export const MODALITY_LABELS = {
  high_throughput_compute: '高通量计算模态',
  low_latency_forwarding: '低时延转发模态',
  llm_text: '智算中心模态',
  高通量计算模态: '高通量计算模态',
  低时延转发模态: '低时延转发模态',
  智算中心模态: '智算中心模态',
  分布式存算模态: '分布式存算模态',
  大规模连接模态: '大规模连接模态',
  确定性转发模态: '确定性转发模态',
  高能效边缘计算模态: '高能效边缘计算模态',
  高安全传输模态: '高安全传输模态',
}

export const TASK_TYPE_SUMMARIES = {
  high_throughput_matmul:
    '在 source → compute → sink 三节点流水线中通过 HTTP 传递任务与结果，以有效计算吞吐量作为矩阵乘法计算任务的验收指标。',
  low_latency_video_pipeline:
    '在 source → compute → sink 链路上读取固定测试视频并按帧间隔抽样，使用 YOLOv5n 进行工业检测推理，以帧推理时延 P90 作为验收指标。',
  llm_text_generation:
    '在 source → inference → sink 链路上完成提示词分发、文本生成和结果归档，以生成速率或响应时延作为验收指标。',
}

const METRIC_LABELS = {
  compute_latency_ms: '计算耗时',
  end_to_end_latency_ms: '端到端时延',
  effective_gflops: '计算性能',
  tokens_per_second: '生成速率',
  frame_latency_p90_ms: '帧推理时延 P90',
}

const OPERATOR_LABELS = {
  '<=': '不超过',
  '>=': '不低于',
  '==': '等于',
}

export const MATMUL_PIPELINE_STEPS = [
  { role: 'source', title: '准备输入', detail: '根据 data_profile 生成矩阵乘法任务并通过 HTTP 发给 compute' },
  { role: 'compute', title: '执行计算', detail: '按路由分配的 CPU/GPU 后端执行 batched FP32 矩阵乘法，并通过 HTTP 发给 sink' },
  { role: 'sink', title: '上报结果', detail: '接收计算结果，向 Manager 上报 effective_gflops 和采样元数据' },
]

export const VIDEO_PIPELINE_STEPS = [
  { role: 'source', title: '读取固定视频', detail: '使用验收镜像内置 bottle-detection.mp4，按 frame_stride 抽帧发送给 compute' },
  { role: 'compute', title: 'YOLO 检测推理', detail: '加载镜像内置 yolov5n-fp32.onnx，对抽样帧执行检测并生成分类画框预览图' },
  { role: 'sink', title: '汇总时延与结果', detail: '上报 frame_latency_p90_ms、检测框、模型信息和带框图片，用于业务目标判定与演示' },
]

export function taskTypeLabel(taskType) {
  if (!taskType) return '-'
  return TASK_TYPE_LABELS[taskType] || taskType
}

export function modalityLabel(modality) {
  if (!modality) return '-'
  return MODALITY_LABELS[modality] || modality
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
    return `验收标准：${sentence}。数值越小表示推理越快；以有效推理阶段的 P90 帧处理时延和节点历史基线对比判定。`
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
      { label: '画像 ID', value: profile.profile_id || '-' },
      { label: '分辨率', value: profile.resolution || '-' },
      { label: '总帧数', value: String(profile.frame_count ?? '-') },
      { label: '抽帧间隔', value: profile.frame_stride != null ? `每 ${profile.frame_stride} 帧取 1 帧` : '-' },
      { label: '预热帧数', value: String(profile.warmup_frames ?? '-') },
      { label: '有效统计帧', value: String(profile.measured_frames ?? '-') },
      { label: '计算强度', value: String(profile.work_units ?? '-') },
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
  if (meta.backend) {
    rows.push({ label: '执行后端', value: String(meta.backend) })
  }
  if (meta.gpu_device !== undefined && meta.gpu_device !== null && String(meta.gpu_device) !== '') {
    rows.push({ label: 'GPU 设备', value: String(meta.gpu_device) })
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

export function buildVideoInputRows(dataProfile) {
  const rows = describeDataProfile('low_latency_video_pipeline', dataProfile || {})
  const profile = dataProfile || {}
  if (profile.video_asset) rows.push({ label: '固定测试视频', value: profile.video_asset })
  if (profile.model_name) rows.push({ label: '检测模型', value: profile.model_name })
  if (profile.inference_mode) rows.push({ label: '推理模式', value: profile.inference_mode })
  return rows
}

export function buildVideoOutputRows(resultMetadata, evaluation) {
  const rows = []
  const meta = resultMetadata || {}
  if (meta.model_name) rows.push({ label: '检测模型', value: String(meta.model_name) })
  if (meta.video_asset) rows.push({ label: '测试视频', value: String(meta.video_asset) })
  if (meta.detector_backend) rows.push({ label: '推理后端', value: String(meta.detector_backend) })
  if (meta.actual_backend) rows.push({ label: '实际执行后端', value: String(meta.actual_backend) })
  if (meta.device) rows.push({ label: '运行设备', value: String(meta.device) })
  if (meta.gpu_device !== undefined && meta.gpu_device !== null && String(meta.gpu_device) !== '') {
    rows.push({ label: 'GPU 设备', value: String(meta.gpu_device) })
  }
  if (meta.gpu_requested !== undefined) {
    rows.push({ label: '请求 GPU', value: meta.gpu_requested ? '是' : '否' })
  }
  if (meta.gpu_available !== undefined) {
    rows.push({ label: 'GPU 可用', value: meta.gpu_available ? '是' : '否' })
  }
  if (meta.gpu_assigned !== undefined) {
    rows.push({ label: 'GPU 分配', value: meta.gpu_assigned ? '已分配' : '未检测到 GPU 分配' })
  }
  if (meta.gpu_error) rows.push({ label: 'GPU 诊断', value: String(meta.gpu_error) })
  if (meta.measured_frames != null) rows.push({ label: '有效推理帧数', value: String(meta.measured_frames) })
  if (meta.annotated_frame_index != null) rows.push({ label: '预览帧序号', value: String(meta.annotated_frame_index) })
  if (meta.annotated_frame_latency_ms != null) {
    rows.push({ label: '预览帧时延', value: `${Number(meta.annotated_frame_latency_ms).toFixed(2)} ms` })
  }
  if (meta.frame_latency_avg_ms != null) rows.push({ label: '平均帧时延', value: `${Number(meta.frame_latency_avg_ms).toFixed(2)} ms` })
  if (meta.frame_latency_p90_ms != null) rows.push({ label: 'P90 帧时延', value: `${Number(meta.frame_latency_p90_ms).toFixed(2)} ms` })
  if (meta.detection_count != null) rows.push({ label: '预览图检测数量', value: String(meta.detection_count) })
  if (meta.top_label) {
    const confidence = meta.top_confidence != null ? ` (${Number(meta.top_confidence).toFixed(2)})` : ''
    const label = meta.top_label_zh || VIDEO_LABEL_ZH[meta.top_label] || meta.top_label
    const raw = label !== meta.top_label ? ` / ${meta.top_label}` : ''
    rows.push({ label: '最高置信类别', value: `${label}${raw}${confidence}` })
  }
  if (evaluation) {
    rows.push({
      label: '上报指标',
      value: `${evaluation.metric_key} = ${Number(evaluation.actual_value).toFixed(2)} ${evaluation.unit || ''}`.trim(),
    })
  }
  if (!rows.length) rows.push({ label: '状态', value: '尚未收到视频推理输出' })
  return rows
}

export function buildVideoVerdict(evaluation) {
  if (!evaluation) {
    return {
      title: '等待视频推理完成',
      subtitle: '任务运行后将展示 P90 帧推理时延、检测框和带框预览图。',
      statusClass: 'pending',
    }
  }
  const actual = Number(evaluation.actual_value).toFixed(2)
  const unit = evaluation.unit || 'ms'
  if (evaluation.business_success) {
    return {
      title: '视频推理已完成，时延达标',
      subtitle: `实际 P90 ${actual} ${unit}，满足目标 ${formatObjectiveSentence({ metric_key: evaluation.metric_key, operator: evaluation.operator || '<=', target_value: evaluation.target_value, unit })}。`,
      statusClass: 'success',
    }
  }
  return {
    title: '视频推理已完成，时延未达标',
    subtitle: evaluation.failure_reason || `实际 P90 ${actual} ${unit}，未达到目标 ${evaluation.target_value} ${unit}。`,
    statusClass: 'danger',
  }
}

export function videoPreviewDataUrl(resultMetadata) {
  const value = resultMetadata?.annotated_frame_data_url
  return typeof value === 'string' && value.startsWith('data:image/') ? value : ''
}

function previewFrameLatency(resultMetadata) {
  const meta = resultMetadata || {}
  if (meta.annotated_frame_latency_ms != null) return Number(meta.annotated_frame_latency_ms)
  if (Array.isArray(meta.samples) && meta.annotated_frame_index != null) {
    const sample = meta.samples.find(item => Number(item.frame_index) === Number(meta.annotated_frame_index))
    if (sample?.latency_ms != null) return Number(sample.latency_ms)
  }
  if (Array.isArray(meta.samples) && meta.samples[0]?.latency_ms != null) {
    return Number(meta.samples[0].latency_ms)
  }
  return null
}

export function videoPreviewEvidenceRows(resultMetadata) {
  const meta = resultMetadata || {}
  const rows = []
  if (meta.annotated_frame_index != null) rows.push(`帧序号 ${meta.annotated_frame_index}`)
  const latency = previewFrameLatency(meta)
  if (latency != null && Number.isFinite(latency)) rows.push(`单帧推理 ${latency.toFixed(2)} ms`)
  if (meta.frame_latency_p90_ms != null) rows.push(`P90 ${Number(meta.frame_latency_p90_ms).toFixed(2)} ms`)
  if (meta.measured_frames != null) rows.push(`有效帧 ${meta.measured_frames}`)
  if (meta.gpu_assigned !== undefined) rows.push(`GPU ${meta.gpu_assigned ? '已分配' : '未分配'}`)
  return rows
}

export function videoPreviewNeedsOverlay(resultMetadata) {
  const overlay = resultMetadata?.annotated_frame_overlay
  return !['zh_yolo_v1', 'yolo_boxes_v1', 'embedded_boxes_v1'].includes(overlay)
}

export function videoDetectionBoxStyle(row, resultMetadata) {
  const bbox = row?.bbox_xyxy
  if (!Array.isArray(bbox) || bbox.length < 4) return { display: 'none' }
  const meta = resultMetadata || {}
  const frameWidth = Number(meta.preview_frame_width || meta.frame_width || meta.image_width || 640)
  const frameHeight = Number(meta.preview_frame_height || meta.frame_height || meta.image_height || 360)
  const [x1, y1, x2, y2] = bbox.map(Number)
  if (![x1, y1, x2, y2, frameWidth, frameHeight].every(Number.isFinite) || frameWidth <= 0 || frameHeight <= 0) {
    return { display: 'none' }
  }
  const pct = (value, total) => `${Math.min(100, Math.max(0, (value / total) * 100))}%`
  return {
    left: pct(x1, frameWidth),
    top: pct(y1, frameHeight),
    width: pct(x2 - x1, frameWidth),
    height: pct(y2 - y1, frameHeight),
  }
}

export function videoDetections(resultMetadata) {
  if (!Array.isArray(resultMetadata?.detections)) return []
  return resultMetadata.detections.map((item) => {
    const label = item?.label || ''
    const labelZh = item?.label_zh || VIDEO_LABEL_ZH[label] || label
    return {
      ...item,
      label_zh: labelZh,
      display_label: label && labelZh !== label ? `${labelZh} / ${label}` : labelZh,
    }
  })
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
