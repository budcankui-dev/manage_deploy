/**
 * Node Agent → docker-py 参数映射说明
 */

export const MOUNT_TYPES = [
  { value: 'managed', label: 'managed — Agent 自动路径（跨节点一致）' },
  { value: 'volume', label: 'volume — Docker 命名卷（自动创建）' },
  { value: 'bind', label: 'bind — 宿主机目录绑定' },
]

export const DOCKER_PARAM_DOCS = {
  image: {
    label: '镜像',
    dockerApi: 'Config.Image',
    example: 'nginx:latest',
    hint: '容器镜像名与标签。',
  },
  command: {
    label: '启动命令',
    dockerApi: 'Config.Cmd',
    example: 'python /app/run.py --batch 32',
    hint: '覆盖镜像默认 CMD。',
  },
  env: {
    label: '环境变量',
    dockerApi: 'Config.Env',
    example: 'APP_ENV=prod',
    hint: 'KEY=VALUE，每行一条。',
  },
  ports: {
    label: '端口',
    dockerApi: 'HostConfig.PortBindings / manage_deploy.host_ports',
    example: '9000',
    hint: 'host：填写宿主机监听端口（每行一个，如 9000）；bridge：宿主机端口 → 容器端口。会写入实例并注入 PEER_* 变量供其他节点引用。',
  },
  host_ports: {
    label: '宿主机监听端口',
    dockerApi: 'manage_deploy.host_ports',
    example: '9000',
    hint: 'host 模式下进程直接占用宿主机端口；填写后用于冲突检查，并生成 PEER_<角色>_PORT/HOST/URL。',
  },
  network_mode: {
    label: '网络模式',
    dockerApi: 'HostConfig.NetworkMode',
    example: 'host',
    hint: 'host 共享宿主机网络；bridge 可映射端口。',
  },
  restart_policy: {
    label: '重启策略',
    dockerApi: 'HostConfig.RestartPolicy',
    example: 'on-failure',
    hint: 'on-failure | always | no',
  },
  gpu_id: {
    label: 'GPU',
    dockerApi: 'HostConfig.DeviceRequests',
    dockerCli: '--gpus',
    example: 'all / 0 / 0,1',
    hint: 'all = 全部 GPU；0 = 单卡；0,1,2 = 多卡（逗号分隔）。需 nvidia-container-toolkit。',
  },
  cpu_limit: {
    label: 'CPU 上限',
    dockerApi: 'HostConfig.NanoCPUs',
    dockerCli: '--cpus',
    example: '2',
    hint: '最多可用逻辑核数（可为小数）→ NanoCPUs。',
  },
  cpu_reservation: {
    label: 'CPU 预留（下限）',
    dockerApi: 'HostConfig.CpuShares',
    dockerCli: '--cpu-shares',
    example: '1',
    hint: '任务资源需求下限。未设 cpu_shares 时按预留核数×1024 映射权重；可配合 cpuset 绑核。',
  },
  cpu_shares: {
    label: 'CPU 权重',
    dockerApi: 'HostConfig.CpuShares',
    dockerCli: '--cpu-shares',
    example: '1024',
    hint: '相对调度权重，默认 1024。显式设置时覆盖由 cpu_reservation 推导的值。',
  },
  cpuset_cpus: {
    label: '绑核',
    dockerApi: 'HostConfig.CpusetCpus',
    dockerCli: '--cpuset-cpus',
    example: '0-3',
    hint: '限定容器可用的 CPU 编号，如 0-3 或 0,2,4。',
  },
  cpu_quota: {
    label: 'CPU 配额',
    dockerApi: 'HostConfig.CpuQuota',
    dockerCli: '--cpu-quota',
    example: '50000',
    hint: '与 cpu_period 联用；未设 cpu_limit 时作为上限替代方案。',
  },
  cpu_period: {
    label: 'CPU 周期',
    dockerApi: 'HostConfig.CpuPeriod',
    dockerCli: '--cpu-period',
    example: '100000',
    hint: '默认 100000 微秒；quota/period ≈ 可用核数。',
  },
  memory_limit: {
    label: '内存上限',
    dockerApi: 'HostConfig.Memory',
    dockerCli: '--memory',
    example: '4g',
    hint: '硬上限，超出 OOM。',
  },
  memory_reservation: {
    label: '内存预留（下限）',
    dockerApi: 'HostConfig.MemoryReservation',
    dockerCli: '--memory-reservation',
    example: '512m',
    hint: '软下限/预留，调度器尽量保证的最小内存。',
  },
  memory_swap_limit: {
    label: 'Swap 上限',
    dockerApi: 'HostConfig.MemorySwap',
    dockerCli: '--memory-swap',
    example: '-1',
    hint: '-1 表示与 memory_limit 相同（禁用 swap 扩展）；或填如 8g。',
  },
  volume_mount: {
    label: '挂载',
    dockerApi: 'HostConfig.Mounts',
    example: 'managed /data/input',
    hint: 'managed：Agent 在 {data_root}/{task}/{node}/ 下自动建目录；volume：Docker 命名卷自动 create；bind：宿主机路径。',
  },
}

export const RUNTIME_TAB_NOTE =
  '资源下限用 cpu_reservation / memory_reservation；上限用 cpu_limit / memory_limit。GPU 支持 all、单卡、多卡三种格式。'

export const GPU_FORMAT_HINT = '示例：all | 0 | 0,1,2'

export function parsePairLines(text, sep = ':') {
  if (!text?.trim()) return []
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf(sep)
      if (idx <= 0) return { left: line, right: '' }
      return { left: line.slice(0, idx).trim(), right: line.slice(idx + 1).trim() }
    })
}

export function formatPairLines(rows, sep = ':') {
  return rows
    .filter((r) => r.left && r.right)
    .map((r) => `${r.left}${sep}${r.right}`)
    .join('\n')
}

export function parseEnvLines(text) {
  return parsePairLines(text, '=')
}

export function formatEnvLines(rows) {
  return formatPairLines(rows, '=')
}

export function parseHostPortLines(text) {
  if (!text?.trim()) return []
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf(':')
      const port = (idx > 0 ? line.slice(0, idx) : line).trim()
      return { left: port, right: port }
    })
}

export function formatHostPortLines(rows) {
  return rows
    .filter((r) => (r.left || r.right)?.trim())
    .map((r) => (r.left || r.right).trim())
    .join('\n')
}

export function hostPortsToMap(rows) {
  const ports = {}
  for (const row of rows) {
    const port = (row.left || row.right || '').trim()
    if (port) ports[port] = port
  }
  return ports
}

export function parsePortLines(text) {
  return parsePairLines(text, ':')
}

export function formatPortLines(rows) {
  return formatPairLines(rows, ':')
}

export function defaultMountRow() {
  return { target: '', type: 'managed', source: '', auto_create: true, read_only: false }
}

export function serializeVolumeMounts(rows) {
  return (rows || [])
    .filter((r) => r.target?.trim())
    .map((r) => ({
      target: r.target.trim(),
      type: r.type || 'bind',
      source: (r.source || '').trim(),
      auto_create: r.auto_create !== false,
      read_only: Boolean(r.read_only),
    }))
}
