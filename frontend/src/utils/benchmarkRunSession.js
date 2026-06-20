export const BENCHMARK_RUN_SESSION_KEY = 'manage-deploy:benchmark-run-session'

function safeStorage(storage) {
  if (storage) return storage
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function readBenchmarkRunSession(storage) {
  const target = safeStorage(storage)
  if (!target) return null
  try {
    const raw = target.getItem(BENCHMARK_RUN_SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    if (!parsed.taskType || !parsed.benchmarkRunId) return null
    return parsed
  } catch {
    return null
  }
}

export function writeBenchmarkRunSession(session, storage) {
  const target = safeStorage(storage)
  const value = {
    taskType: session.taskType,
    benchmarkRunId: session.benchmarkRunId,
    phase: session.phase || 'running',
    updatedAt: new Date().toISOString(),
  }
  if (target) {
    target.setItem(BENCHMARK_RUN_SESSION_KEY, JSON.stringify(value))
  }
  return value
}

export function isSameBenchmarkRun(session, taskType, benchmarkRunId) {
  return Boolean(
    session &&
    session.taskType === taskType &&
    session.benchmarkRunId === benchmarkRunId
  )
}

export function clearBenchmarkRunSession(taskType, benchmarkRunId, storage) {
  const target = safeStorage(storage)
  if (!target) return
  const current = readBenchmarkRunSession(target)
  if (!current || isSameBenchmarkRun(current, taskType, benchmarkRunId)) {
    target.removeItem(BENCHMARK_RUN_SESSION_KEY)
  }
}
