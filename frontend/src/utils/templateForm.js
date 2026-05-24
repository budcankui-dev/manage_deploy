import {
  DEFAULT_PLACEHOLDER_IMAGE,
  buildAbcTopologyNodes,
  buildAbcTopologyEdges,
} from './deployJson'

let nodeCounter = 0

export function emptyTemplateForm() {
  return { name: '', description: '', macro_defs: [], nodes: [], edges: [] }
}

export function mapTemplateToForm(template) {
  const idMap = new Map()
  const nodes = (template.nodes || []).map((n) => {
    const tempId = n.name || n.id || `temp_${nodeCounter++}`
    idMap.set(n.id, tempId)
    idMap.set(n.name, tempId)
    return {
      _temp_id: tempId,
      name: n.name,
      image: n.image === DEFAULT_PLACEHOLDER_IMAGE ? '' : (n.image || ''),
      node_id: n.node_id || '',
      port_defs: (n.port_defs || []).map((p) => ({
        name: p.name || '',
        label: p.label || '',
        default: p.default ?? null,
      })),
    }
  })
  const edges = (template.edges || []).map((e) => ({
    from_node_id: idMap.get(e.from_node_id) || e.from_node_id,
    to_node_id: idMap.get(e.to_node_id) || e.to_node_id,
  }))
  return {
    name: template.name,
    description: template.description || '',
    macro_defs: (template.macro_defs || []).map((m) => ({
      name: m.name || '',
      label: m.label || '',
      default: m.default || '',
    })),
    nodes,
    edges,
  }
}

export function buildTemplateFormPayload(form, workers = [], { excludeTemplateId = null, existingTemplates = [] } = {}) {
  const name = form.name?.trim()
  if (!name) throw new Error('模板名称不能为空')
  if (!form.nodes.length) throw new Error('至少添加一个节点')

  const duplicate = (existingTemplates || []).find(
    (t) => t.name === name && t.id !== excludeTemplateId
  )
  if (duplicate) throw new Error(`模板名称「${name}」已存在`)

  const nodesPayload = form.nodes.map((n, index) => {
    if (!n.name?.trim()) throw new Error(`节点 ${index + 1} 需要角色名`)
    const nodeId = n.node_id || workers[index]?.id || workers[0]?.id
    if (!nodeId) throw new Error('请先在「节点管理」注册 worker，或为节点指定默认 Worker')
    return {
      client_id: n._temp_id || n.name,
      name: n.name.trim(),
      image: n.image?.trim() || DEFAULT_PLACEHOLDER_IMAGE,
      command: null,
      env: null,
      ports: null,
      volumes: null,
      gpu_id: null,
      cpu_limit: null,
      memory_limit: null,
      port_defs: (n.port_defs || []).filter((p) => p.name?.trim()).map((p) => ({
        name: p.name.trim(),
        label: p.label?.trim() || null,
        default: p.default ?? null,
      })),
      node_id: nodeId,
      network_mode: 'host',
      restart_policy: 'on-failure',
      health_check: null,
    }
  })

  return {
    name,
    description: form.description?.trim() || null,
    macro_defs: form.macro_defs.filter((m) => m.name?.trim()).map((m) => ({
      name: m.name.trim(),
      label: m.label?.trim() || null,
      default: m.default?.trim() || null,
    })),
    nodes: nodesPayload,
    edges: form.edges.map((e) => ({
      from_node_id: e.from_node_id,
      to_node_id: e.to_node_id,
    })),
  }
}

export function applyAbcTopologyToForm(form, workers = []) {
  form.nodes = buildAbcTopologyNodes(workers)
  form.edges = buildAbcTopologyEdges()
  if (!form.name) form.name = 'abc-topology'
  if (!form.macro_defs.length) {
    form.macro_defs = [
      { name: 'DB_URL', label: '上报数据库', default: 'postgres://db:5432/tasks' },
      { name: 'MINIO_ENDPOINT', label: 'MinIO 地址', default: 'http://minio:9000' },
    ]
  }
}

export function addMacroDef(form) {
  form.macro_defs.push({ name: '', label: '', default: '' })
}

export function removeMacroDef(form, index) {
  form.macro_defs.splice(index, 1)
}

export function addTemplateNode(form, workers = []) {
  const id = `temp_${nodeCounter++}`
  form.nodes.push({
    _temp_id: id,
    name: '',
    image: '',
    node_id: workers[0]?.id || '',
    port_defs: [],
  })
}

export function removeTemplateNode(form, index) {
  const node = form.nodes[index]
  form.edges = form.edges.filter(
    (e) => e.from_node_id !== node._temp_id && e.to_node_id !== node._temp_id
  )
  form.nodes.splice(index, 1)
}

export function addPortDef(form, nodeIndex) {
  const node = form.nodes[nodeIndex]
  if (!node.port_defs) node.port_defs = []
  node.port_defs.push({ name: '', label: '', default: null })
}

export function removePortDef(form, nodeIndex, portIndex) {
  form.nodes[nodeIndex].port_defs.splice(portIndex, 1)
}

export function addTemplateEdge(form) {
  if (form.nodes.length < 2) throw new Error('至少需要 2 个节点')
  form.edges.push({ from_node_id: '', to_node_id: '' })
}

export function removeTemplateEdge(form, index) {
  form.edges.splice(index, 1)
}

export function formatJson(value) {
  if (value == null || value === '') return '-'
  if (typeof value === 'object') {
    if (Array.isArray(value) && !value.length) return '-'
    if (!Array.isArray(value) && !Object.keys(value).length) return '-'
    return JSON.stringify(value, null, 2)
  }
  return String(value)
}
