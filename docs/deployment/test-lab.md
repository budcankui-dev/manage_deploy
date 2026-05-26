# 测试部署机器清单

本文档记录当前业务端到端测试可用机器。不要在本文件中记录密码、token、私钥或其他凭据；凭据应放在本地密码管理器，或放在被 `.gitignore` 忽略的本地文件，例如 `ops/secrets/test-lab-credentials.local.md`。

## 拓扑角色

| 名称 | 角色 | 管理 IP | SSH 端口 | SSH 用户 | GPU | 数据盘 | 备注 |
|------|------|---------|----------|----------|-----|--------|------|
| admin-server | 管理面主控机器 | `10.112.244.94` | `22` | `bupt` | 未记录 | `/mnt/data` | Task Manager、Frontend、数据库/对象存储等管理面组件优先部署在这里 |
| compute-1 | 业务节点 | `10.112.249.191` | `2345` | `chengyubin` | TITAN X * 1 | `/disk/sdc` | 当前阶段也可作为 source 或 sink |
| compute-2 | 业务节点 | `10.112.150.166` | `2345` | `chengyubin` | TITAN X * 2 | `/data/hdd1` | 当前阶段也可作为 source、compute 或 sink |
| compute-3 | 业务节点 | `10.112.116.165` | `22` | `compute` | Tesla P40 * 8 | `/data` | 当前阶段也可作为 source、compute 或 sink |

## 当前测试原则

- `admin-server` 是管理面主控机器。
- `compute-*` 是业务节点，后续应运行 Node Agent 和业务 worker 容器。
- 当前 matmul 演示不强制使用 GPU，业务节点可先混合作为 source、compute、sink，快速验证网络链路和编排闭环。
- 数据盘下创建本项目目录后，需要确认目录属主和权限，避免 Docker/agent 写入失败。
- 业务数据流仍按 source -> compute -> sink 的 HTTP 网络路径验证，不通过共享文件传递。

## 建议目录

在每台机器的数据盘下创建项目目录：

| 机器 | 建议目录 |
|------|----------|
| admin-server | `/mnt/data/manage_deploy` |
| compute-1 | `/disk/sdc/manage_deploy` |
| compute-2 | `/data/hdd1/manage_deploy` |
| compute-3 | `/data/manage_deploy` |

示例命令，按实际用户调整：

```bash
sudo mkdir -p /path/to/manage_deploy
sudo chown -R "$USER":"$USER" /path/to/manage_deploy
```

## SSH 连通性检查

```bash
ssh -p 22 bupt@10.112.244.94 hostname
ssh -p 2345 chengyubin@10.112.249.191 hostname
ssh -p 2345 chengyubin@10.112.150.166 hostname
ssh -p 22 compute@10.112.116.165 hostname
```

## 给 E2E Deploy Test Agent 的提示

- 先确认 SSH 连通性、数据盘可写、Docker/NVIDIA runtime 状态。
- 不要把密码写入 git tracked 文件。
- 如果需要记录临时凭据位置，只记录本地 ignored 文件路径，不记录具体内容。
- 部署验证应记录每台机器的 `hostname`、`docker --version`、`nvidia-smi` 或无 GPU 可用的原因。
- 注册平台 Node 时，管理地址和业务地址初期可都使用上述 IP；后续如启用业务 IPv6，再更新 `business_ipv6`。
