# 终端拓扑节点扩展接入说明

本文记录 `h1-h13` 终端节点接入方式。所有拓扑机器统一登记在 `nodes` 表：

- `nodes.hostname`：平台和路由系统统一使用的节点名，也是用户输入别名，如 `h1`、`compute-1`。
- `nodes.topology_node_id`：实验拓扑或资产主机 ID，如 `h18001001`。
- `nodes.display_name`：真实主机名，如 `s15-Ubuntu-Host-1`。
- `nodes.topology_zone`：拓扑区域，如 `h180`、`h400`、`h410`。
- `nodes.node_kind`：节点类型，终端为 `terminal`，计算节点为 `worker`，管理节点为 `admin`。

当前终端节点清单见：

```bash
ops/inventory/topology_nodes.json
```

## 接入原则

1. `h1-h13`、`compute-1~compute-3`、管理节点都作为拓扑节点统一管理，只是 `node_kind` 不同。
2. 终端节点也部署 Docker 和 Node Agent，默认 `is_schedulable=true`、`is_routable=true`。
3. 某个任务的 source/sink 是否部署容器，由工单的 `platform_deployment.deployable_roles` 决定，不由路由系统决定。
4. 目前控制面和业务面暂用 10.112 IPv4；后续拓扑业务面网络确定后，只更新 `business_ip` / `business_ipv6` 和路由系统网络规则。
5. 敏感信息不入库、不入仓库。SSH 密码、sudo 密码、API token 只通过本地环境变量或本地临时 inventory 传入。

## 批量注册 nodes 表

先确认管理端后端可访问，然后执行：

```bash
cd /Users/yanjia/codes/manage_deploy
export MANAGER_API_BASE=http://10.112.244.94:8181
export MANAGER_USERNAME=admin
export MANAGER_PASSWORD='<本地输入，不提交到仓库>'
python3 scripts/register_topology_nodes.py
```

默认只注册或更新 `terminal_nodes`。如需同时补齐清单里的计算节点或管理节点：

```bash
python3 scripts/register_topology_nodes.py --include-compute --include-admin
```

预览待写入内容：

```bash
python3 scripts/register_topology_nodes.py --dry-run
```

## 批量部署 Docker / Node Agent

建议先构建并推送 Node Agent 镜像到管理节点私有仓库：

```bash
NODE_AGENT_IMAGE=10.112.244.94:5000/node-agent \
NODE_AGENT_TAG=dev \
NODE_AGENT_PUSH=1 \
NODE_AGENT_PLATFORM=linux/amd64 \
./scripts/build_node_agent.sh
```

每台终端节点需要完成：

1. 安装 Docker。
2. 配置 Docker registry mirror，例如阿里云镜像源。
3. 配置私有仓库 `10.112.244.94:5000` 为 insecure registry。
4. 拉取 `10.112.244.94:5000/node-agent:dev`。
5. 使用 host 网络启动 Node Agent，监听 `8001`，挂载 `/var/run/docker.sock`。
6. 从管理节点验证 `http://<节点IP>:8001/health` 可访问。

单机 Node Agent 容器示例：

```bash
docker run -d --name manage-node-agent --restart unless-stopped \
  --network host --privileged \
  -e AGENT_PORT=8001 \
  -e DOCKER_SOCKET=unix:///var/run/docker.sock \
  -v /var/run/docker.sock:/var/run/docker.sock \
  10.112.244.94:5000/node-agent:dev
```

如果后续将 Docker/containerd 数据目录迁移到非系统盘，先停止 Docker/containerd，再修改对应配置并迁移数据，最后重启服务。迁移完成后用 `docker info` 和 `systemctl status docker containerd` 验证。

## 联通性检查

控制面至少需要：

```bash
curl -sS http://h节点管理IP:8001/health
```

业务面需要业务容器之间访问动态端口。迁移到新网络后，路由系统应基于新的 `nodes.business_ip` / `nodes.business_ipv6` 下发路径或流表。

## 给路由系统的影响

新增终端节点不改变接口。路由系统只需要动态读取 `nodes` 表：

- `hostname` 是回写 `topology_node_id` 时使用的节点名。
- `topology_node_id` / `display_name` / `topology_zone` 只用于展示、审计和辅助理解。
- source/sink 的真实节点来自 DAG 的 `fixed_topology_node_id`，例如 `h1`。
- compute 仍从 `node_kind in ('worker','both') and is_schedulable=1` 的节点中选择。
