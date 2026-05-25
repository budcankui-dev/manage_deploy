import assert from 'node:assert/strict'
import {
  buildComputeResultSummary,
  describeObjectiveMeaning,
  formatObjectiveSentence,
  taskTypeLabel,
} from '../src/constants/businessTaskDisplay.js'

assert.equal(taskTypeLabel('high_throughput_matmul'), '高通量矩阵乘法')
assert.equal(
  formatObjectiveSentence({
    metric_key: 'compute_latency_ms',
    operator: '<=',
    target_value: 60000,
    unit: 'ms',
  }),
  '计算耗时 不超过 60000 ms'
)
assert.ok(
  describeObjectiveMeaning('high_throughput_matmul', {
    metric_key: 'compute_latency_ms',
    operator: '<=',
    target_value: 60000,
    unit: 'ms',
  }).includes('验收标准')
)

const summary = buildComputeResultSummary(
  'high_throughput_matmul',
  { data_profile: { matrix_size: 64, batch_count: 1, seed: 42 } },
  {
    actual_value: 12.5,
    target_value: 60000,
    unit: 'ms',
    business_success: true,
  },
  { checksum: '0.123456' }
)
assert.ok(summary.some((row) => row.label === '算了什么'))
assert.ok(summary.some((row) => row.label === '是否达标' && row.value === '达标'))

console.log('businessTaskDisplay: ok')
