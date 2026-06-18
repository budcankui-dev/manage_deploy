# 管理节点跳板与网络迁移 Runbook

本文记录当前调试网络和正式验收网络的访问方案。目标是提前把“本机只能访问总控管理节点”的模式跑通，后续从 10.112 校园网切到 172.16 管理网段时，减少临场改动。

## 1. 网络口径

当前开发调试阶段：

- 本机可以访问管理节点和部分拓扑节点的 10.112 IPv4。
- 管理节点、计算节点、终端节点都同时有 10.112 IPv4 和对应校园网 IPv6。
- 业务数据面暂时使用校园网 IPv6 模拟，`PREFER_BUSINESS_IPV6=true` 时容器之间通过 `http://[IPv6]:port` 通信。

正式验收阶段：

- 本机只直接访问管理节点。
- 管理面从 10.112 IPv4 切换为 172.16 网段，Manager、Node Agent、MySQL、MinIO、Registry 走管理面。
- 本机访问拓扑内其它节点时，必须以管理节点作为 SSH 跳板。
- 业务数据面使用验收环境分配的独立 IPv6 网段，由路由系统基于 `nodes.business_ipv6` 和端口建立路径。

系统设计上必须保持：

| 字段 | 当前调试 | 验收切换后 | 用途 |
|------|----------|------------|------|
| `nodes.management_ip` | 10.112 IPv4 | 172.16 IPv4 | Manager 调 Node Agent、SSH 运维 |
| `nodes.agent_address` | `http://10.112.x.x:8001` | `http://172.16.x.x:8001` | 控制面容器生命周期 API |
| `nodes.business_ip` | 10.112 IPv4，可保留辅助显示 | 可为空或填业务 IPv4 | 非 IPv6 调试兜底 |
| `nodes.business_ipv6` | 校园网 IPv6 | 数据面 IPv6 | 业务容器通信和路由系统选路 |
| `MANAGER_PUBLIC_URL` | `http://10.112.244.94:8181` | `http://<管理节点172.16地址>:8181` | worker 指标回写 Manager |
| `PREFER_BUSINESS_IPV6` | `true` | `true` | 优先向容器注入 IPv6 PEER URL |

不要把 10.112 写成协议前提。10.112 只是当前调试网络，正式验收时应只作为历史示例或临时回退。

## 2. 推荐 SSH 配置

本机 `~/.ssh/config` 推荐采用两套 alias：

```sshconfig
Host manage-admin
  HostName 10.112.244.94
  User bupt
  Port 22
  IdentityFile ~/.ssh/manage_deploy_test_lab_ed25519

Host topo-compute-1
  HostName 10.112.38.25
  User chengyubin
  Port 2345
  IdentityFile ~/.ssh/manage_deploy_test_lab_ed25519
  ProxyJump manage-admin

Host topo-compute-2
  HostName 10.112.17.51
  User chengyubin
  Port 2345
  IdentityFile ~/.ssh/manage_deploy_test_lab_ed25519
  ProxyJump manage-admin

Host topo-compute-3
  HostName 10.112.59.209
  User compute
  Port 22
  IdentityFile ~/.ssh/manage_deploy_test_lab_ed25519
  ProxyJump manage-admin
```

验收切换到 172.16 后，只改 `HostName`：

- `manage-admin.HostName` 改为管理节点 172.16 地址。
- `topo-* .HostName` 改为对应节点 172.16 管理面地址。
- 保持 `ProxyJump manage-admin` 不变。

这样本机不需要直接路由到每台拓扑节点，只要能 SSH 到管理节点即可。

## 3. 跳板连通性验证

先验证本机到管理节点：

```bash
ssh manage-admin "hostname; ip -br addr"
```

再验证本机经管理节点到业务节点：

```bash
ssh topo-compute-1 "hostname; ip -br addr"
ssh topo-compute-2 "hostname; ip -br addr"
ssh topo-compute-3 "hostname; ip -br addr"
```

如果暂时没有配置 `topo-*` alias，也可以直接使用一次性命令：

```bash
ssh -J manage-admin -p 2345 chengyubin@10.112.38.25 "hostname"
```

正式验收时把上面的 `10.112.38.25` 换成对应 172.16 管理面地址。

## 4. 通过跳板访问 Node Agent

本机不能直接访问业务节点 `:8001` 时，使用 SSH 本地端口转发：

```bash
ssh -N -L 18001:10.112.38.25:8001 manage-admin
curl -sS http://127.0.0.1:18001/health
```

验收切换后：

```bash
ssh -N -L 18001:<compute-1的172.16管理IP>:8001 manage-admin
curl -sS http://127.0.0.1:18001/health
```

更推荐在管理节点上直接验证所有 Node Agent，因为 Manager 真实调用路径也是管理节点到业务节点：

```bash
ssh manage-admin "curl -sS http://10.112.38.25:8001/health"
ssh manage-admin "curl -sS http://10.112.17.51:8001/health"
ssh manage-admin "curl -sS http://10.112.59.209:8001/health"
```

验收切换后把地址替换为 172.16 管理 IP。

## 5. 通过跳板访问业务容器 IPv6 UI

业务容器 UI 和容器间通信应走数据面 IPv6。由于本机可能没有到数据面 IPv6 的路由，浏览器访问容器 UI 时使用管理节点作为跳板做端口转发。

示例：访问 h2 上视频接收端 `9100`：

```bash
ssh -N -L 19100:[2001:da8:215:6a01:250:56ff:fe8b:f0ec]:9100 manage-admin
```

然后本机浏览器打开：

```text
http://127.0.0.1:19100/?order_id=<工单ID>
```

说明：

- `-L 本地端口:[IPv6]:远端端口` 中 IPv6 必须用方括号。
- 该方式只解决“本机看不到数据面 IPv6”的浏览器访问问题，不改变容器真实通信路径。
- 容器之间仍应使用系统注入的 `PEER_*_URL=http://[业务IPv6]:动态端口`。

如果 SSH 客户端对 IPv6 转发兼容性不好，可以先登录管理节点再从管理节点发起 curl 验证：

```bash
ssh manage-admin "curl -g -sS 'http://[2001:da8:215:6a01:250:56ff:fe8b:f0ec]:9100/health'"
```

## 6. 切换到验收网络时要改什么

切换时优先改配置和数据库，不改代码：

1. 更新管理节点 `.env`：

```text
MANAGER_PUBLIC_URL=http://<管理节点172.16地址>:8181
PREFER_BUSINESS_IPV6=true
BACKEND_PORT=8181
```

2. 更新 `nodes` 表：

- `management_ip` 改为 172.16 管理 IP。
- `agent_address` 改为 `http://<172.16管理IP>:8001`。
- `business_ipv6` 改为验收数据面 IPv6。
- `hostname`、`topology_node_id`、`node_kind`、`is_schedulable`、`is_routable` 保持稳定。

3. 更新私有镜像仓库配置：

- Docker insecure registry 从 `10.112.244.94:5000` 改为 `<管理节点172.16地址>:5000`。
- 任务模板镜像地址同步改为新 registry 地址。

4. 重启后端和 Node Agent：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy/backend && pids=\$(pgrep -f '[u]vicorn main:app.*8181' || true); [ -n \"\$pids\" ] && kill \$pids || true; nohup /home/bupt/miniconda3/bin/python3.13 -m uvicorn main:app --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 &"
```

5. 重新跑连通性检查：

```bash
ssh manage-admin "curl -sS http://<节点172.16管理IP>:8001/health"
ssh manage-admin "ping -6 -c 2 <节点数据面IPv6>"
```

## 7. 验收前必须确认的现象

- 本机只通过 `manage-admin` 能完成运维，不依赖本机直连拓扑节点。
- 管理节点能访问所有 Node Agent 的管理面地址。
- 管理节点能访问所有业务数据面 IPv6。
- 工单 DAG 同时包含拓扑节点 ID、节点别名、管理面部署结果、业务面 IPv6 和业务端口。
- 路由系统拿到的是数据面 IP/IPv6 和端口，不依赖 10.112 校园网。
- 容器内 `PEER_*_URL` 是 IPv6 URL，形如 `http://[2001:...]:18000`。
- 本机查看容器 UI 时可以通过 SSH 本地转发访问，不要求本机有数据面 IPv6 路由。

## 8. 常见问题

**为什么不让本机直接访问所有节点？**

正式验收网络里，本机通常只在管理域外，只能访问总控管理节点。提前使用跳板模式，可以逼近正式网络边界，减少切网后的故障。

**跳板访问容器 UI 会不会破坏随路计算？**

不会。SSH 本地端口转发只用于浏览器查看结果页面。业务容器之间的 source -> compute -> sink 通信仍然走数据面 IPv6 和路由系统建立的路径。

**10.112 IPv4 和校园网 IPv6 现在还能不能用？**

可以，当前开发调试继续使用它们。但文档和代码不要把它们当成正式验收假设；正式切换时用 172.16 管理面和新的数据面 IPv6 替代。

**路由同学需要关心跳板机吗？**

一般不需要。跳板机是我们运维和演示访问方式。路由同学只需要读取数据库中的拓扑节点 ID、业务面 IPv6、端口、模态和策略，并按协议回写 placements / network-ready。
