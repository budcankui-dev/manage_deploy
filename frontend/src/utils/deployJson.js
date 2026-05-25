/**
 * 模板 = DAG 拓扑；实例 = 运行参数（command / ports / env 等）
 */

import { parseHostPortLines, hostPortsToMap } from './dockerFieldHints'

export const DEFAULT_PLACEHOLDER_IMAGE = 'busybox:latest'

function stripJsonComments(text) {
  return text
    .replace(/^\uFEFF/, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .trim()
}

export function parseJsonText(text) {
  const cleaned = stripJsonComments(text)
  if (!cleaned) throw new Error('JSON 内容不能为空')
  try {
    return JSON.parse(cleaned)
  } catch (error) {
    throw new Error(`JSON 格式错误：${error.message}`)
  }
}

export const RUNTIME_SCALAR_FIELDS = [
  'gpu_id',
  'cpu_limit',
  'cpu_reservation',
  'cpu_shares',
  'cpuset_cpus',
  'cpu_quota',
  'cpu_period',
  'memory_limit',
  'memory_reservation',
  'memory_swap_limit',
]

export function defaultFormRuntimeFields(overrides = {}) {
  return {
    gpu_id: '',
    cpu_limit: null,
    cpu_reservation: null,
    cpu_shares: null,
    cpuset_cpus: '',
    cpu_quota: null,
    cpu_period: null,
    memory_limit: '',
    memory_reservation: '',
    memory_swap_limit: '',
    volume_mounts: [],
    ...overrides,
  }
}

export function pickRuntimeScalars(item) {
  const out = {}
  for (const key of RUNTIME_SCALAR_FIELDS) {
    const value = item[key]
    if (value !== undefined && value !== null && value !== '') {
      out[key] = value
    }
  }
  return out
}

export function formatPortsToText(ports, networkMode = 'host') {
  if (!ports || !Object.keys(ports).length) return ''
  if (networkMode === 'host') {
    return Object.keys(ports).join('\n')
  }
  return Object.entries(ports)
    .map(([k, v]) => `${k}:${v}`)
    .join('\n')
}

export function parsePortsFromForm(node, parseLines) {
  if (node.network_mode === 'host') {
    return hostPortsToMap(parseHostPortLines(node.ports_text || ''))
  }
  return parseLines(node.ports_text, ':')
}

export function mapApiNodeToForm(n, { formatObjectLines, parseEnvPorts = true } = {}) {
  const network_mode = n.network_mode || 'host'
  return {
    template_node_id: n.template_node_id || n.id,
    template_node_name: n.template_node_name || n.name,
    image: n.image || '',
    command: n.command || '',
    env_text: formatObjectLines ? formatObjectLines(n.env, '=') : '',
    ports_text: formatPortsToText(n.ports, network_mode),
    port_defs: Array.isArray(n.port_defs) ? [...n.port_defs] : [],
    port_values: { ...(n.port_values || {}) },
    network_mode,
    restart_policy: n.restart_policy || 'on-failure',
    node_id: n.node_id || '',
    ...defaultFormRuntimeFields({
      gpu_id: n.gpu_id || '',
      cpu_limit: n.cpu_limit ?? null,
      cpu_reservation: n.cpu_reservation ?? null,
      cpu_shares: n.cpu_shares ?? null,
      cpuset_cpus: n.cpuset_cpus || '',
      cpu_quota: n.cpu_quota ?? null,
      cpu_period: n.cpu_period ?? null,
      memory_limit: n.memory_limit || '',
      memory_reservation: n.memory_reservation || '',
      memory_swap_limit: n.memory_swap_limit || '',
      volume_mounts: Array.isArray(n.volume_mounts) ? [...n.volume_mounts] : [],
    }),
  }
}

export function mapApiNodeToOverride(n) {
  return {
    template_node_id: n.template_node_id || n.id,
    template_node_name: n.template_node_name || n.name,
    image: n.image || null,
    command: n.command || null,
    env: n.env || {},
    ports: n.ports || {},
    port_values: n.port_values || null,
    volume_mounts: n.volume_mounts?.length ? n.volume_mounts : null,
    node_id: n.node_id || null,
    network_mode: n.network_mode || null,
    restart_policy: n.restart_policy || null,
    ...pickRuntimeScalars(n),
  }
}

export function mapFormNodeToOverride(n, { parseLines }) {
  const mounts = n.volume_mounts?.length ? n.volume_mounts : null
  return {
    template_node_id: n.template_node_id,
    template_node_name: n.template_node_name,
    image: n.image || null,
    command: n.command || null,
    env: parseLines(n.env_text, '='),
    ports: parsePortsFromForm(n, parseLines),
    port_values: Object.keys(n.port_values || {}).length ? n.port_values : null,
    volume_mounts: mounts,
    node_id: n.node_id || null,
    network_mode: n.network_mode || null,
    restart_policy: n.restart_policy || null,
    ...pickRuntimeScalars(n),
  }
}

function resolveNodeId(value, nodes = []) {
  if (!value) return value
  const raw = String(value).trim()
  const byId = nodes.find((n) => n.id === raw)
  if (byId) return byId.id
  const byHostname = nodes.find((n) => n.hostname === raw)
  if (byHostname) return byHostname.id
  return raw
}

function defaultWorkerId(nodes = [], index = 0) {
  return nodes[index]?.id || nodes[0]?.id || ''
}

function normalizeEdges(edges = [], nodes = []) {
  const idByKey = new Map()
  nodes.forEach((node, index) => {
    const key = node.client_id || node.name || node.id || `node_${index + 1}`
    idByKey.set(key, key)
    if (node.id) idByKey.set(node.id, key)
    if (node.name) idByKey.set(node.name, key)
  })

  return edges.map((edge, index) => {
    const from = edge.from_node_id ?? edge.from ?? edge.source
    const to = edge.to_node_id ?? edge.to ?? edge.target
    if (!from || !to) {
      throw new Error(`edges[${index}] 缺少 from_node_id / to_node_id`)
    }
    return {
      from_node_id: idByKey.get(from) || from,
      to_node_id: idByKey.get(to) || to,
    }
  })
}

/** 拓扑模板节点：只需 name；image / node_id 可省略（使用占位默认值） */
function normalizeTemplateNodes(rawNodes = [], nodes = []) {
  if (!Array.isArray(rawNodes) || !rawNodes.length) {
    throw new Error('nodes 不能为空')
  }

  return rawNodes.map((node, index) => {
    const name = node.name || node.template_node_name
    if (!name) throw new Error(`nodes[${index}] 需要 name（节点角色名）`)

    const image = node.image || DEFAULT_PLACEHOLDER_IMAGE
    const nodeId =
      resolveNodeId(node.node_id ?? node.hostname ?? node.worker, nodes) ||
      defaultWorkerId(nodes, index)

    if (!nodeId) {
      throw new Error(`nodes[${index}] 需要 node_id，或先在「节点管理」注册 worker`)
    }

    return {
      client_id: node.client_id || name || `node_${index + 1}`,
      name,
      image,
      command: node.command ?? null,
      env: node.env ?? null,
      volumes: node.volumes ?? null,
      ports: node.ports ?? null,
      gpu_id: node.gpu_id ?? null,
      cpu_limit: node.cpu_limit ?? null,
      cpu_reservation: node.cpu_reservation ?? null,
      cpu_shares: node.cpu_shares ?? null,
      cpuset_cpus: node.cpuset_cpus ?? null,
      cpu_quota: node.cpu_quota ?? null,
      cpu_period: node.cpu_period ?? null,
      memory_limit: node.memory_limit ?? null,
      memory_reservation: node.memory_reservation ?? null,
      memory_swap_limit: node.memory_swap_limit ?? null,
      volume_mounts: node.volume_mounts ?? null,
      port_defs: node.port_defs ?? null,
      network_mode: node.network_mode || 'host',
      restart_policy: node.restart_policy || 'on-failure',
      health_check: node.health_check ?? null,
      node_id: nodeId,
    }
  })
}

export function buildTemplatePayload(raw, { nodes = [] } = {}) {
  const data = typeof raw === 'string' ? parseJsonText(raw) : raw
  if (!data.name) throw new Error('模板 JSON 缺少 name')

  const normalizedNodes = normalizeTemplateNodes(data.nodes, nodes)
  return {
    name: data.name,
    description: data.description ?? null,
    macro_defs: data.macro_defs ?? null,
    nodes: normalizedNodes,
    edges: normalizeEdges(data.edges || [], normalizedNodes),
  }
}

function resolveTemplateId(data, templates = []) {
  if (data.template_id) {
    return templates.find((t) => t.id === data.template_id)?.id || data.template_id
  }
  const name = data.template_name || data.template
  if (!name) throw new Error('需要 template_name 或 template_id')
  const byName = templates.find((t) => t.name === name)
  if (!byName) throw new Error(`找不到拓扑模板：${name}`)
  return byName.id
}

function normalizeNodeOverrides(rawOverrides = [], { nodes = [], templateNodes = [] } = {}) {
  if (!Array.isArray(rawOverrides)) throw new Error('node_overrides 必须是数组')

  return rawOverrides.map((item, index) => {
    const templateNode =
      templateNodes.find((n) => n.id === item.template_node_id) ||
      templateNodes.find((n) => n.name === item.template_node_name) ||
      templateNodes.find((n) => n.name === item.name)

    const template_node_id = item.template_node_id || templateNode?.id || null
    const template_node_name = item.template_node_name || templateNode?.name || item.name || null

    if (!template_node_id && !template_node_name) {
      throw new Error(`node_overrides[${index}] 需要 template_node_name`)
    }

    return {
      template_node_id,
      template_node_name,
      name: item.name ?? null,
      image: item.image ?? null,
      command: item.command ?? null,
      env: item.env ?? null,
      volumes: item.volumes ?? null,
      ports: item.ports ?? null,
      gpu_id: item.gpu_id ?? null,
      cpu_limit: item.cpu_limit ?? null,
      cpu_reservation: item.cpu_reservation ?? null,
      cpu_shares: item.cpu_shares ?? null,
      cpuset_cpus: item.cpuset_cpus ?? null,
      cpu_quota: item.cpu_quota ?? null,
      cpu_period: item.cpu_period ?? null,
      memory_limit: item.memory_limit ?? null,
      memory_reservation: item.memory_reservation ?? null,
      memory_swap_limit: item.memory_swap_limit ?? null,
      volume_mounts: item.volume_mounts ?? null,
      port_values: item.port_values ?? null,
      network_mode: item.network_mode ?? null,
      restart_policy: item.restart_policy ?? null,
      health_check: item.health_check ?? null,
      node_id: (item.node_id || item.hostname)
        ? resolveNodeId(item.node_id ?? item.hostname, nodes)
        : null,
    }
  })
}

export function buildInstancePayload(raw, { nodes = [], templates = [], templateDetail = null } = {}) {
  const data = typeof raw === 'string' ? parseJsonText(raw) : raw
  if (!data.name) throw new Error('实例 JSON 缺少 name')

  const template_id = resolveTemplateId(data, templates)
  const detail = templateDetail || templates.find((t) => t.id === template_id)
  const templateNodes = detail?.nodes || []

  return {
    name: data.name,
    template_id,
    deployment_mode: data.deployment_mode || data.mode || 'immediate',
    scheduled_start_time: data.scheduled_start_time ?? null,
    scheduled_end_time: data.scheduled_end_time ?? null,
    auto_start: Boolean(data.auto_start),
    keep_after_stop: Boolean(data.keep_after_stop),
    macro_values: data.macro_values ?? null,
    node_overrides: normalizeNodeOverrides(data.node_overrides || [], { nodes, templateNodes }),
  }
}

/** 导出拓扑 JSON（不含 command/ports 等运行参数） */
export function templateToImportJson(template) {
  return JSON.stringify(
    {
      name: template.name,
      description: template.description,
      macro_defs: template.macro_defs ?? undefined,
      nodes: (template.nodes || []).map((node) => ({
        client_id: node.name,
        name: node.name,
        port_defs: node.port_defs ?? undefined,
      })),
      edges: (template.edges || []).map((edge) => ({
        from_node_id: edge.from_node_id,
        to_node_id: edge.to_node_id,
      })),
    },
    null,
    2
  )
}

export const TEMPLATE_JSON_EXAMPLE = `{
  "name": "abc-topology",
  "description": "三节点随路计算拓扑 A→B→C",
  "macro_defs": [
    { "name": "DB_URL", "label": "上报数据库", "default": "postgres://db:5432/tasks" },
    { "name": "MINIO_ENDPOINT", "label": "MinIO 地址", "default": "http://minio:9000" }
  ],
  "nodes": [
    {
      "client_id": "source",
      "name": "source",
      "port_defs": [
        { "name": "api", "label": "数据入口 HTTP", "default": 9000 }
      ]
    },
    {
      "client_id": "compute",
      "name": "compute",
      "port_defs": [
        { "name": "api", "label": "计算服务", "default": 8080 }
      ]
    },
    { "client_id": "sink", "name": "sink" }
  ],
  "edges": [
    { "from_node_id": "source", "to_node_id": "compute" },
    { "from_node_id": "compute", "to_node_id": "sink" }
  ]
}`

export const INSTANCE_JSON_EXAMPLE = `{
  "name": "task-001",
  "template_name": "abc-topology",
  "auto_start": true,
  "macro_values": {
    "DB_URL": "postgres://10.0.1.100:5432/tasks",
    "MINIO_ENDPOINT": "http://10.0.1.100:9000"
  },
  "node_overrides": [
    {
      "template_node_name": "source",
      "node_id": "demo-worker-a",
      "image": "busybox:latest",
      "command": "sleep 3600",
      "network_mode": "host",
      "port_values": { "api": 9000 }
    },
    {
      "template_node_name": "compute",
      "node_id": "demo-worker-b",
      "image": "my-app:v1",
      "command": "python run.py --upstream \${PEER_SOURCE_URL_API}",
      "network_mode": "host",
      "port_values": { "api": 8080 },
      "env": { "TASK_ROLE": "compute" }
    },
    {
      "template_node_name": "sink",
      "node_id": "demo-worker-c",
      "image": "busybox:latest",
      "command": "sleep 3600",
      "network_mode": "host"
    }
  ]
}`

export function buildAbcTopologyNodes(workers = []) {
  const roles = [
    { name: 'source', port_defs: [{ name: 'api', label: '数据入口 HTTP', default: 9000 }] },
    { name: 'compute', port_defs: [{ name: 'api', label: '计算服务', default: 8080 }] },
    { name: 'sink', port_defs: [] },
  ]
  return roles.map((role, index) => ({
    _temp_id: role.name,
    name: role.name,
    image: DEFAULT_PLACEHOLDER_IMAGE,
    node_id: defaultWorkerId(workers, index),
    network_mode: 'host',
    restart_policy: 'on-failure',
    showAdvanced: false,
    command: '',
    env_text: '',
    ports_text: '',
    port_defs: role.port_defs,
    port_values: {},
    ...defaultFormRuntimeFields(),
    health_check_type: '',
    health_check_port: null,
    health_check_url: '',
    health_check_keyword: '',
  }))
}

export function buildAbcTopologyEdges() {
  return [
    { from_node_id: 'source', to_node_id: 'compute' },
    { from_node_id: 'compute', to_node_id: 'sink' },
  ]
}
