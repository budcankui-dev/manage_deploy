import assert from 'node:assert/strict'

import {
  BENCHMARK_RUN_SESSION_KEY,
  clearBenchmarkRunSession,
  isSameBenchmarkRun,
  readBenchmarkRunSession,
  writeBenchmarkRunSession,
} from '../src/utils/benchmarkRunSession.js'

function createMemoryStorage() {
  const data = new Map()
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
  }
}

const storage = createMemoryStorage()
const session = writeBenchmarkRunSession(
  {
    taskType: 'high_throughput_matmul',
    benchmarkRunId: 'high_throughput_matmul-20260620193000',
    phase: 'running',
  },
  storage
)

assert.equal(storage.getItem(BENCHMARK_RUN_SESSION_KEY).includes('high_throughput_matmul'), true)
assert.equal(readBenchmarkRunSession(storage).benchmarkRunId, 'high_throughput_matmul-20260620193000')
assert.equal(isSameBenchmarkRun(session, 'high_throughput_matmul', 'high_throughput_matmul-20260620193000'), true)
assert.equal(isSameBenchmarkRun(session, 'low_latency_video_pipeline', 'high_throughput_matmul-20260620193000'), false)

clearBenchmarkRunSession('low_latency_video_pipeline', 'high_throughput_matmul-20260620193000', storage)
assert.equal(readBenchmarkRunSession(storage).benchmarkRunId, 'high_throughput_matmul-20260620193000')

clearBenchmarkRunSession('high_throughput_matmul', 'high_throughput_matmul-20260620193000', storage)
assert.equal(readBenchmarkRunSession(storage), null)

storage.setItem(BENCHMARK_RUN_SESSION_KEY, '{bad json')
assert.equal(readBenchmarkRunSession(storage), null)

console.log('benchmarkRunSession: ok')
