export const TERMINAL_NODE_ALIASES = Array.from({ length: 13 }, (_, index) => `h${index + 1}`)
export const COMPUTE_NODE_ALIASES = ['compute-1', 'compute-2', 'compute-3']

const terminalSet = new Set(TERMINAL_NODE_ALIASES)
const computeSet = new Set(COMPUTE_NODE_ALIASES)

export function isOfficialTerminalNodeName(name) {
  return terminalSet.has(String(name || '').trim())
}

export function isOfficialComputeNodeName(name) {
  return computeSet.has(String(name || '').trim())
}

export function isOfficialTopologyNodeName(name) {
  return isOfficialTerminalNodeName(name) || isOfficialComputeNodeName(name)
}

export function officialNodeSort(a, b) {
  return String(a || '').localeCompare(String(b || ''), 'zh-Hans-CN', { numeric: true })
}
