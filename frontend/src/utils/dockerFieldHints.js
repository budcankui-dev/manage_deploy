/**
 * 本项目 Node Agent 实际映射到 docker-py 的参数说明。
 * 见 node_agent/docker_handler.py
 */

export const DOCKER_PARAM_DOCS = {
  image: {
    label: '镜像',
    dockerApi: 'Config.Image',
    example: 'nginx:latest',
    hint: '容器镜像名与标签，等价于 docker run 的第一个参数。',
  },
  command: {
    label: '启动命令',
    dockerApi: 'Config.Cmd',
    example: 'python /app/run.py --batch 32',
    hint: '覆盖镜像默认 CMD。留空则使用镜像内置命令。',
  },
  env: {
    label: '环境变量',
    dockerApi: 'Config.Env',
    example: 'APP_ENV=prod',
    hint: '写入容器的环境变量，格式 KEY=VALUE，每行一条。',
  },
  ports: {
    label: '端口映射',
    dockerApi: 'HostConfig.PortBindings',
    example: '8080:80',
    hint: '仅 bridge 网络有效。格式 宿主机端口:容器端口，映射为 TCP。',
  },
  volumes: {
    label: '目录挂载',
    dockerApi: 'HostConfig.Binds',
    example: '/data/input:/app/input',
    hint: '宿主机路径:容器内路径。写入 binds 字典。',
  },
  network_mode: {
    label: '网络模式',
    dockerApi: 'HostConfig.NetworkMode',
    example: 'host',
    hint: 'host = 与宿主机共享网络栈（本项目业务网默认）；bridge = 独立网络，可配置端口映射。',
  },
  restart_policy: {
    label: '重启策略',
    dockerApi: 'HostConfig.RestartPolicy',
    example: 'on-failure',
    hint: 'on-failure（失败重启）| always（总是）| no（不自动重启）。',
  },
  cpu_limit: {
    label: 'CPU 上限',
    dockerApi: 'HostConfig.NanoCPUs',
    dockerCli: '--cpus',
    example: '1.5',
    hint: '单位：逻辑核数，可为小数。1 = 最多 1 核，0.5 = 半核。内部转换为 NanoCPUs（值 × 10⁹）。',
    unsupported: '不支持：CPU 预留（--cpu-reservation）、绑核（--cpuset-cpus）、权重（--cpu-shares）、配额周期（--cpu-quota/--cpu-period）。',
  },
  memory_limit: {
    label: '内存上限',
    dockerApi: 'HostConfig.Memory',
    dockerCli: '--memory',
    example: '512m',
    hint: '硬上限，超出会被 OOM。支持 b/k/m/g 后缀，如 512m、2g、1073741824（字节）。',
    unsupported: '不支持：内存预留（--memory-reservation）、swap 限制（--memory-swap）。',
  },
  gpu_id: {
    label: 'GPU 设备',
    dockerApi: 'HostConfig.DeviceRequests',
    dockerCli: '--gpus device=ID',
    example: '0',
    hint: 'NVIDIA GPU 设备 ID（字符串）。需宿主机已安装 nvidia-container-toolkit。留空则不挂载 GPU。',
    unsupported: '不支持：多卡列表、MIG 分片、capabilities 自定义；当前仅单卡 device_ids。',
  },
}

export const RUNTIME_TAB_NOTE =
  '本项目仅暴露上述三种资源限制。Portainer/Docker 的其他 CPU 分配方式（预留、绑核、shares 等）暂未实现。'

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

export function parsePortLines(text) {
  return parsePairLines(text, ':')
}

export function formatPortLines(rows) {
  return formatPairLines(rows, ':')
}

export function parseVolumeLines(text) {
  return parsePairLines(text, ':')
}

export function formatVolumeLines(rows) {
  return formatPairLines(rows, ':')
}
