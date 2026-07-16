# 生产拓扑巡检与更新 SOP

本文沉淀生产/验收环境的固定排查和更新流程。目标是保证“检测、定位、更新本地清单、同步远端数据库、复测业务链路”都有明确步骤，避免只改本地文件、忘记更新管理节点数据库，或把临时地址写进业务链路。

## 1. 生产网络口径

### 1.1 节点角色

| 节点类型 | 节点 | 职责 |
| --- | --- | --- |
| 总控/管理节点 | `admin` | 运行 Manager、前端、MySQL、MinIO、Registry、Portainer Server；通过校园网访问 Qwen API；不参与数据面业务转发 |
| 计算节点 | `compute-1~3` | 运行 Node Agent 和业务 compute 容器；同时有管理面、数据面和临时校园网 |
| 终端节点/虚拟机 | `h1~h13` | 运行 Node Agent 和 source/sink/receiver 类业务容器；有管理面和数据面，临时保留校园网入口 |

### 1.2 网络分层

| 网络 | 地址/入口 | 用途 | 是否生产关键路径 |
| --- | --- | --- | --- |
| 管理控制网 | `172.16.0.0/24` | Manager 调 Node Agent、节点 SSH 运维、MySQL、MinIO、Registry、Portainer Agent | 是 |
| 数据面 IPv6 | `3012:*` / `3028:*` / `3029:*` | 工作节点上的业务容器互访，`PEER_*_URL` 注入使用 | 是 |
| 校园网 | `10.112.*` | 总控访问外部 Qwen API；本地远程维护入口；compute-1 WireGuard campus Endpoint | 否，仅维护/兜底 |
| WireGuard | compute-1 `wg-lab` | 人的电脑进入管理面/数据面做调试和演示访问 | 否，不参与系统任务执行 |

固定原则：

- Manager、Node Agent、Registry、MySQL、MinIO 生产口径都走 `172.16` 管理网。
- 工作节点容器之间只把数据面 IPv6 当作业务主链路。
- `10.112` 只作为远程维护和总控访问外部 API 的入口，不应写成生产任务数据链路。
- WireGuard 只服务人的电脑调试，不是平台部署或容器通信依赖。

## 2. 权威数据源

| 层级 | 权威位置 | 用途 |
| --- | --- | --- |
| 本地结构化拓扑 | `ops/inventory/topology_nodes.json` | 管理面 IP、数据面 IPv6、SSH 用户、端口、节点角色 |
| 远端平台数据库 | 管理节点 MySQL `task_manager.nodes` | Manager 实际调度、路由系统查询、前端展示 |
| 运行中服务 | 管理节点 API `/api/nodes` | 验证数据库是否已被后端正确读出 |
| 真实机器状态 | `ip -br addr`、`ip -6 addr`、Node Agent `/health` | 判断 inventory/DB 是否过期 |

任何 IP 变化的最终闭环必须同时满足：

1. 真实机器上地址存在。
2. 多源矩阵验证可达。
3. `ops/inventory/topology_nodes.json` 已更新。
4. 管理节点 API / MySQL `nodes` 已更新。
5. Node Agent、Portainer、业务 E2E 复测通过。

只更新本地文件不算完成；只手工改数据库但不更新 inventory 也不算完成。

## 3. 日常巡检流程

### 3.1 接入方式确认

先确认人的电脑如何接入实验网：

```bash
netstat -rn -f inet | egrep '172\.16|10\.88|default' || true
netstat -rn -f inet6 | egrep '3012|3028|3029|fd88|default' || true
```

预期：

- 直连管理网：本机有到 `172.16.0.0/24` 的物理网卡路由。
- WireGuard：有 `10.88.0.2` / `fd88:88:88::2`，并有 `172.16.0.0/24`、`3012::/16`、`3028::/16`、`3029::/16` 路由。
- 只有校园网：只能访问 `10.112`，不能代表验收管理面和数据面正常。

### 3.2 管理网两两互通

目标：拓扑里所有管理面节点两两互通。

范围：

- 源节点：`admin`、`compute-1~3`、`h1~h13`，共 17 个。
- 目标节点：`admin`、`compute-1~3`、`h1~h13`，共 17 个。
- 目标地址：`ops/inventory/topology_nodes.json` 里的 `acceptance_management_ip`。
- 预期矩阵：17 行，每行 `ok=17 fail=0 total=17`。

先预览实际会登录哪些源节点：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane management \
  --matrix \
  --source-scope plane \
  --source-profile acceptance \
  --list-sources
```

正式检测：

```bash
cd /Users/yanjia/codes/manage_deploy

python3 ops/network/acceptance/check_connectivity.py \
  --plane management \
  --matrix \
  --source-scope plane \
  --source-profile acceptance \
  --timeout 1 \
  --ssh-connect-timeout 5
```

通过标准：

- 所有源节点均成功登录，不出现 `SOURCE_FAIL`。
- 每个源节点行都是 `ok=17 fail=0 total=17`。
- 如果某源显示 `SOURCE_FAIL`，先定位该源 SSH/账号/权限/sshd，不要直接判定目标管理网不通。
- 如果某源能登录但有 `failed=[...]`，记录“源节点、失败目标、目标管理 IP”，交给拓扑维护同学核查管理网交换、网卡或防火墙。

### 3.3 工作节点数据面 IPv6 两两互通

目标：所有工作节点之间数据面 IPv6 两两互通。

范围：

- 源节点：`compute-1~3`、`h1~h13`，共 16 个。`admin` 没有数据面，不参与。
- 目标节点：`compute-1~3`、`h1~h13`，共 16 个。
- 目标地址：`ops/inventory/topology_nodes.json` 里的 `acceptance_business_ipv6`。
- 预期矩阵：16 行，每行 `ok=16 fail=0 total=16`。

先预览实际会登录哪些源节点：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane data \
  --matrix \
  --source-scope plane \
  --source-profile acceptance \
  --list-sources
```

正式检测。若 h1-h13 已配置免密，优先使用验收管理网源地址：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane data \
  --matrix \
  --source-scope plane \
  --source-profile acceptance \
  --timeout 1 \
  --ssh-connect-timeout 5
```

如果 h1-h13 仍需密码登录，可使用本地 ignored 密码文件，通过当前可用入口登录源节点：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane data \
  --matrix \
  --source-scope plane \
  --source-profile current \
  --password-file ops/secrets/terminal-credentials.local.md \
  --timeout 1 \
  --ssh-connect-timeout 5
```

通过标准：

- 所有工作源节点均成功登录，不出现 `SOURCE_FAIL`。
- 每个源节点行都是 `ok=16 fail=0 total=16`。
- 任何一个数据面目标失败，都必须先确认目标节点当前真实 `ip -6 addr`，再判断是地址过期、RA/路由问题，还是拓扑侧转发问题。
- 不能把 `temporary`、`deprecated`、`fe80::/64` 地址临时写入平台绕过问题。

失败记录格式：

```text
源节点：
目标节点：
目标 IPv6：
源是否 SOURCE_FAIL：
目标节点当前 ip -6 addr：
是否只有单源失败：
是否所有源到同一目标失败：
下一步责任方：节点运维 / 拓扑路由 / 平台数据更新
```

判定经验：

- 所有源到同一个目标失败：优先查目标节点数据面地址是否变化、网卡是否有 IPv6、是否被拓扑侧断开。
- 一个源到多个目标失败：优先查源节点数据面网卡、路由、RA、出口链路。
- 只有少数跨域目标失败：优先交给拓扑/路由侧核查转发表或跨域路由。
- 矩阵通但业务不通：再查容器端口、`PEER_*_URL`、路由系统下发、Node Agent 启动参数。

### 3.4 快速抽检

日常快速排障可以只从计算节点作为源发起探测，但快速抽检不能替代两两互通验收：

```bash
python3 ops/network/acceptance/check_connectivity.py --plane management --matrix --timeout 1
python3 ops/network/acceptance/check_connectivity.py --plane data --matrix --timeout 1
```

快速抽检适合判断问题是否明显扩大；正式验收、IP 更新、路由联调前，必须跑 17×17 管理网矩阵和 16×16 数据面矩阵。

### 3.5 服务端口巡检

从管理网可达的位置检查：

```bash
# Manager / 前端 / 基础组件
curl -sS http://172.16.0.254:8181/api/nodes | python3 -m json.tool >/dev/null
curl -sS http://172.16.0.254:9000/minio/health/live
curl -sS http://172.16.0.254:5000/v2/_catalog
curl -k -sS https://172.16.0.254:9443/api/status

# Node Agent / Portainer Agent
for ip in 172.16.0.101 172.16.0.102 172.16.0.103 \
          172.16.0.151 172.16.0.152 172.16.0.153 172.16.0.154 \
          172.16.0.155 172.16.0.156 172.16.0.157 172.16.0.158 \
          172.16.0.159 172.16.0.160 172.16.0.161 172.16.0.162 172.16.0.163; do
  echo "## $ip"
  curl -sS --connect-timeout 2 "http://$ip:8001/health" || true
  curl -k -sS --connect-timeout 2 "https://$ip:9001/ping" || true
  echo
done
```

判定：

- `8001` 失败：Manager 无法部署/停止/查询该节点容器。
- `9001` 失败：Portainer 看不到该节点 Docker，但不一定影响系统任务。
- Registry / MinIO / Manager 失败：先修总控基础组件，再测业务。

## 4. IP 变化后的更新闭环

### 4.1 读取真实地址

只执行只读命令：

```bash
ssh <node> 'hostname; ip -br addr; ip -6 addr; ip -6 route'
```

不要把以下 IPv6 写入主数据面字段：

- `fe80::/64` 链路本地地址。
- 带 `temporary` 的隐私临时地址。
- 带 `deprecated` 的地址。
- 只有本机可见、其它数据面源 ping 不通的地址。

### 4.2 多源验证新地址

至少从 `compute-2`、`compute-3` 和若干 `h` 节点验证新地址。示例：

```bash
NEW_IPV6='3012:9::9e69:d3ff:fe68:d3d'

ssh -p 2345 chengyubin@10.112.17.51 "ping -6 -c 1 -W 1 $NEW_IPV6"
ssh -p 22 compute@10.112.59.209 "ping -6 -c 1 -W 1 $NEW_IPV6"
```

如果是终端节点地址变化，优先用 `check_connectivity.py --plane data --matrix` 做全量验证。

### 4.3 更新本地 inventory

编辑：

```text
ops/inventory/topology_nodes.json
```

字段规则：

- `management_ip`：校园网维护入口，当前调试可用。
- `acceptance_management_ip`：生产管理面 `172.16` 地址。
- `business_ip` / `acceptance_business_ip`：IPv4 兜底/展示，不作为容器主链路。
- `acceptance_business_ipv6`：生产数据面主 IPv6。
- 旧地址如需追溯，放入候选字段或巡检报告，不继续作为主业务地址。

校验：

```bash
python3 -m json.tool ops/inventory/topology_nodes.json >/dev/null
```

### 4.4 Dry-run 核对将写入远端的内容

```bash
export NETWORK_PROFILE=acceptance
export MANAGER_API_BASE=http://172.16.0.254:8181
export PRIVATE_REGISTRY=172.16.0.254:5000

python3 scripts/register_topology_nodes.py \
  --network-profile acceptance \
  --include-compute \
  --include-admin \
  --dry-run
```

必须人工检查 dry-run 输出：

- `management_ip` 是否都是 `172.16`。
- `agent_address` 是否是 `http://<172.16管理IP>:8001`。
- `business_ipv6` 是否是刚验证过的数据面 IPv6。
- `resource_note` 是否包含 `172.16.0.254:5000`。

### 4.5 写入远端数据库

确认 dry-run 无误后，写入管理节点数据库。推荐通过 Manager API，不直接手改 MySQL：

```bash
export NETWORK_PROFILE=acceptance
export MANAGER_API_BASE=http://172.16.0.254:8181
export PRIVATE_REGISTRY=172.16.0.254:5000
export MANAGER_USERNAME=admin
export MANAGER_PASSWORD='<本地输入，不提交>'

python3 scripts/register_topology_nodes.py \
  --network-profile acceptance \
  --include-compute \
  --include-admin
```

如果本机只能访问校园网维护入口，也可以显式指定 API：

```bash
python3 scripts/register_topology_nodes.py \
  --network-profile acceptance \
  --api-base http://10.112.73.149:8181 \
  --include-compute \
  --include-admin
```

注意：即使 API 走 `10.112`，写入的节点字段仍应是 `172.16` 管理面和数据面 IPv6。

### 4.6 验证远端已更新

```bash
curl -sS http://172.16.0.254:8181/api/nodes | \
  python3 -c 'import json,sys; data=json.load(sys.stdin); [print(n["hostname"], n["management_ip"], n["agent_address"], n.get("business_ipv6")) for n in data]'
```

如需直接查 MySQL：

```bash
ssh manage-admin '
mysql -uroot -p task_manager -e "
select hostname, management_ip, agent_address, business_ipv6, node_kind, is_schedulable
from nodes
order by hostname;"
'
```

直接 MySQL 只用于核对；常规更新仍通过 `register_topology_nodes.py`。

### 4.7 复测

更新后必须复测：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane management \
  --matrix \
  --source-scope plane \
  --source-profile acceptance \
  --timeout 1 \
  --ssh-connect-timeout 5

python3 ops/network/acceptance/check_connectivity.py \
  --plane data \
  --matrix \
  --source-scope plane \
  --source-profile acceptance \
  --timeout 1 \
  --ssh-connect-timeout 5
```

如果终端节点免密未配置，再使用 `--source-profile current --password-file ops/secrets/terminal-credentials.local.md` 作为临时登录方式；矩阵目标地址仍必须来自 `acceptance_business_ipv6`。

然后从页面或 API 跑最小业务 E2E：

- `/benchmark` 至少跑一次矩阵乘法和视频推理 baseline。
- 用户接入工单至少验证一个 source -> compute -> sink 的 `network_bindings`，确认 `PEER_*_URL` 使用数据面 IPv6。

## 5. 常见问题处理

### 5.1 compute-1 跳板异常

影响：

- 本机 WireGuard 访问管理面/数据面受影响。
- 如果 compute-1 Node Agent 也不通，平台不能调度任务到 compute-1。

先做只读确认：

```bash
ssh -p 2345 chengyubin@10.112.38.25 '
hostname
uptime
ip -br addr
ss -lntup | egrep ":2345|:8001|:9001|:51820" || true
systemctl status ssh docker wg-quick@wg-lab --no-pager
docker ps --format "{{.Names}} {{.Status}} {{.Image}} {{.Ports}}"
'
```

如果 SSH 端口能连但 session 卡住，应交给节点维护同学检查 compute-1 本机负载、sshd、PAM、磁盘、Docker/firewalld 状态。不要从其它节点给 compute-1 临时加路由。

### 5.2 Node Agent 不通

现象：

```bash
curl http://172.16.0.xxx:8001/health
```

失败时：

- 先确认管理面 ping/SSH 是否通。
- 再确认 Docker 是否正常、`manage-node-agent` 容器是否存在。
- 需要恢复时按《标准化部署与运维流程》的 Node Agent 标准化更新章节执行。

### 5.3 数据面 IPv6 变化

处理顺序固定：

1. 读取目标节点真实数据面地址。
2. 剔除 temporary/deprecated/fe80 地址。
3. 多源 ping 新地址。
4. 更新 inventory。
5. `register_topology_nodes.py --dry-run`。
6. `register_topology_nodes.py` 写入远端。
7. 复测数据面矩阵和业务 E2E。

### 5.4 Portainer 看不到节点

`9001` 不通只影响辅助观察，不等同于系统部署不可用。系统部署以 Node Agent `8001` 为准。

如果需要恢复 Portainer Agent，按《Portainer辅助运维接入说明》通过 Node Agent 重新启动 Agent 容器，再在 Portainer Server 注册/检查 endpoint。

## 6. 禁止事项

- 不在未确认情况下执行 `ip route add|del`、`ip -6 route add|del`。
- 不在巡检脚本里自动 flush 地址、重启网卡、重启 Docker。
- 不把 `temporary` IPv6 写入 `nodes.business_ipv6`。
- 不只改本地 `topology_nodes.json` 而不更新远端数据库。
- 不只手改数据库而不更新 inventory。
- 不把 `10.112` 当作生产业务数据面。
- 不把 WireGuard 当作平台部署依赖。

## 7. 巡检记录模板

```text
时间：
执行人：
本机接入方式：管理网直连 / WireGuard / 校园网
inventory commit：
Manager API：

管理面矩阵命令：
管理面结果：

数据面矩阵命令：
数据面结果：

管理网两两互通是否 17x17 全通：
工作节点数据面 IPv6 两两互通是否 16x16 全通：

Node Agent 8001 异常节点：
Portainer Agent 9001 异常节点：
数据面 IPv6 变化节点：

本地 inventory 是否更新：
远端 nodes 是否更新：
复测业务：

需要拓扑维护同学处理：
```
