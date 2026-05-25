import assert from 'node:assert/strict'
import {
  buildMatmulInputRows,
  buildMatmulOutputRows,
  buildMatmulParamConsistency,
  buildMatmulVerdict,
  describeObjectiveMeaning,
  formatObjectiveSentence,
  taskTypeLabel,
} from '../src/constants/businessTaskDisplay.js'

assert.equal(taskTypeLabel('high_throughput_matmul'), '高通量矩阵乘法')
assert.ok(
  describeObjectiveMeaning('high_throughput_matmul', {
    metric_key: 'compute_latency_ms',
    operator: '<=',
    target_value: 60000,
    unit: 'ms',
  }).includes('不验证')
)

const inputRows = buildMatmulInputRows({ matrix_size: 64, batch_count: 1, seed: 42 })
assert.equal(inputRows.length, 4)

const outputRows = buildMatmulOutputRows(
  { matrix_size: 64, batch_count: 1, compute_latency_ms: 2.5 },
  { metric_key: 'compute_latency_ms', actual_value: 2.5, unit: 'ms' }
)
assert.ok(outputRows.some((r) => r.label === '运行矩阵规模'))

const consistency = buildMatmulParamConsistency(
  { matrix_size: 64, batch_count: 1 },
  { matrix_size: 64, batch_count: 1 }
)
assert.equal(consistency.ok, true)

const verdictOk = buildMatmulVerdict({
  metric_key: 'compute_latency_ms',
  actual_value: 2,
  target_value: 60000,
  unit: 'ms',
  operator: '<=',
  business_success: true,
})
assert.equal(verdictOk.statusClass, 'success')

const verdictFail = buildMatmulVerdict({
  metric_key: 'compute_latency_ms',
  actual_value: 70000,
  target_value: 60000,
  unit: 'ms',
  operator: '<=',
  business_success: false,
  failure_reason: '70000.0 > 60000.0',
})
assert.equal(verdictFail.statusClass, 'danger')

console.log('businessTaskDisplay: ok')
