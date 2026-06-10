import assert from 'node:assert/strict'
import {
  buildMatmulInputRows,
  buildMatmulOutputRows,
  buildMatmulParamConsistency,
  buildMatmulVerdict,
  describeObjectiveMeaning,
  formatObjectiveSentence,
  taskTypeLabel,
  videoDetectionBoxStyle,
  videoPreviewNeedsOverlay,
} from '../src/constants/businessTaskDisplay.js'

assert.equal(taskTypeLabel('high_throughput_matmul'), '矩阵乘法计算任务')
assert.ok(
  describeObjectiveMeaning('high_throughput_matmul', {
    metric_key: 'effective_gflops',
    operator: '>=',
    target_value: 80,
    unit: 'GFLOPS',
  }).includes('有效计算吞吐量')
)

const inputRows = buildMatmulInputRows({ matrix_size: 64, batch_count: 1, seed: 42 })
assert.equal(inputRows.length, 4)

const outputRows = buildMatmulOutputRows(
  { matrix_size: 64, batch_count: 1, compute_latency_ms: 2.5, sample_count: 5 },
  { metric_key: 'effective_gflops', actual_value: 82.5, unit: 'GFLOPS' }
)
assert.ok(outputRows.some((r) => r.label === '运行矩阵规模'))
assert.ok(outputRows.some((r) => r.label === '有效样本数'))

const consistency = buildMatmulParamConsistency(
  { matrix_size: 64, batch_count: 1 },
  { matrix_size: 64, batch_count: 1 }
)
assert.equal(consistency.ok, true)

const verdictOk = buildMatmulVerdict({
  metric_key: 'effective_gflops',
  actual_value: 82,
  target_value: 80,
  unit: 'GFLOPS',
  operator: '>=',
  business_success: true,
})
assert.equal(verdictOk.statusClass, 'success')

const verdictFail = buildMatmulVerdict({
  metric_key: 'effective_gflops',
  actual_value: 60,
  target_value: 80,
  unit: 'GFLOPS',
  operator: '>=',
  business_success: false,
  failure_reason: '60.0 < 80.0',
})
assert.equal(verdictFail.statusClass, 'danger')

assert.equal(videoPreviewNeedsOverlay({ annotated_frame_overlay: 'zh_yolo_v1' }), false)
assert.equal(videoPreviewNeedsOverlay({ annotated_frame_overlay: 'yolo_boxes_v1' }), false)
assert.equal(videoPreviewNeedsOverlay({ annotated_frame_overlay: '' }), true)

assert.deepEqual(
  videoDetectionBoxStyle({ bbox_xyxy: [320, 180, 640, 360] }, { preview_frame_width: 1280, preview_frame_height: 720 }),
  {
    left: '25%',
    top: '25%',
    width: '25%',
    height: '25%',
  }
)

console.log('businessTaskDisplay: ok')
