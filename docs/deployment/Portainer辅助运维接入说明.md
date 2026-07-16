# Portainer 辅助运维接入说明

本文记录验收拓扑里 Portainer 的辅助管理方案。Portainer 只用于观察真实 Docker 容器、镜像、日志和节点状态，不替代本系统的任务编排、删除和状态机。

官方参考：

- Portainer CE Server Docker 安装文档：`https://docs.portainer.io/start/install-ce/server/docker/linux`
- Portainer Agent Docker Standalone 接入文档：`https://docs.portainer.io/admin/environments/add/docker/agent`

## 当前部署方式

| 组件 | 节点 | 地址 | 说明 |
| --- | --- | --- | --- |
| Portainer Server | `admin` | `https://172.16.0.254:9443` | 已存在并复用，已挂载总控 `/var/run/docker.sock`，当前版本接口返回 `2.39.1` |
| Portainer Agent | `compute-1~3`、`h1~h13` | `tcp://<管理面IP>:9001` | 通过现有 Node Agent API 启动 `portainer-mgmt_agent` |
| Portainer Agent 镜像 | 管理节点私有仓库 | `172.16.0.254:5000/portainer-agent:latest` | 从管理节点已有 `portainer/agent:latest` 标记并推送 |

Agent 只走 `172.16` 管理面。不要把 Portainer 接入建立在 `10.112` 临时校园网地址上。总控节点不需要额外跑 Portainer Agent：Server 容器已经直接挂载本机 Docker socket，可直接管理总控 Docker。

## 复用脚本

脚本位置：

```bash
python3 ops/portainer/deploy_portainer_agents.py --check-only
```

补齐或重建 Agent：

```bash
python3 ops/portainer/deploy_portainer_agents.py
```

如果修改了节点的 `docker_root_dir`，或者需要用新的挂载参数重建容器：

```bash
python3 ops/portainer/deploy_portainer_agents.py --force-recreate
```

脚本行为：

- 读取 `ops/inventory/topology_nodes.json` 中的 `compute_nodes` 和 `terminal_nodes`。
- 调用每台节点已有的 `http://<172.16管理IP>:8001/containers/portainer-mgmt/agent/start`。
- 创建或重建容器名 `portainer-mgmt_agent`，映射宿主 `9001 -> 容器 9001`。
- 挂载 `/var/run/docker.sock` 和 Docker Root Dir 下的 `volumes` 目录。
- 不改路由、不改 IP、不重启 Docker、不保存密码。

如果节点 Docker Root Dir 不是 `/var/lib/docker`，在清单里给节点补 `docker_root_dir`。当前计算节点：

| 节点 | Docker Root Dir |
| --- | --- |
| `compute-1` | `/data/hdd1/docker` |
| `compute-2` | `/disk/sdb/docker` |
| `compute-3` | `/data/docker` |

## Portainer 页面接入

如果没有 Portainer API Token，可在页面手动添加环境：

1. 打开 `https://172.16.0.254:9443`。
2. 进入 `Environments` / `环境`，选择 `Add environment`。
3. 环境类型选择 `Docker Standalone`，连接方式选择 `Agent`。
4. 地址填写 `172.16.0.101:9001`、`172.16.0.102:9001`、`172.16.0.103:9001`、`172.16.0.151:9001` 到 `172.16.0.163:9001`。
5. 名称建议使用 `compute-1`、`compute-2`、`compute-3`、`h1` 到 `h13`。

也可以用脚本自动注册。密码只从环境变量或交互输入读取，不写入仓库：

```bash
PORTAINER_PASSWORD='<管理员密码>' \
python3 ops/portainer/register_portainer_endpoints.py
```

脚本会注册 `compute-1~3` 和 `h1~h13`，地址统一为 `tcp://<172.16管理IP>:9001`；已存在同名环境时跳过。

## 节点镜像口径

验收管理网下，真实运行的基础容器应统一使用管理节点仓库：

| 容器 | 镜像 |
| --- | --- |
| compute 节点系统 Node Agent | `172.16.0.254:5000/node-agent:dev` |
| h1-h13 系统 Node Agent | `172.16.0.254:5000/node-agent:dev` |
| Portainer Agent | `172.16.0.254:5000/portainer-agent:latest` |

如果在 Portainer 里看到 `10.112.73.149:5000/...`，通常是旧校园网阶段残留容器或旧镜像。验收前应清理已退出的旧业务容器，并重建系统 Node Agent 到 `172.16.0.254:5000/node-agent:dev`。

## 验证标准

从本机或总控执行：

```bash
python3 ops/portainer/deploy_portainer_agents.py --check-only
```

期望 `compute-1~3` 和 `h1~h13` 均为：

```text
OK <节点名> <管理面IP>:9001 tcp=True status=running
```

也可以从总控验证端口：

```bash
for ip in 172.16.0.101 172.16.0.102 172.16.0.103 172.16.0.151 172.16.0.152 172.16.0.153 172.16.0.154 172.16.0.155 172.16.0.156 172.16.0.157 172.16.0.158 172.16.0.159 172.16.0.160 172.16.0.161 172.16.0.162 172.16.0.163; do
  nc -vz -w 2 "$ip" 9001
done
```

## 注意事项

- Portainer Agent 需要挂载 Docker socket，权限很高，只应该暴露在管理面 `172.16`，不要对校园网或公网开放。
- 旧的 `portainer_agent` 可删除；本方案使用独立的 `portainer-mgmt_agent`，避免影响历史环境。不要删除总控 `portainer` Server 容器。
- Portainer 中删除容器不会自动同步本系统数据库状态。任务容器仍应优先通过本系统页面或 API 停止/删除。
