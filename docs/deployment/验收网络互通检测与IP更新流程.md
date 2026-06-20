# 验收网络互通检测与 IP 更新流程

本文是验收网络排障和交接的固定流程。目标是把“检测事实、更新清单、交给拓扑侧修复”分清楚，避免在排查时临时改路由表、临时加地址或把不稳定 IPv6 写进平台。

## 安全边界

默认只允许执行只读检测：

- `ping` / `ping6`
- `ip addr show` / `ip -br addr`
- `ip -6 route show`
- `curl /health`
- `ssh <host> "只读命令"`

以下操作必须先单独确认，不能在验收检测脚本里自动执行：

- `ip route add|del|replace`
- `ip -6 route add|del|replace`
- `ip addr add|flush|del`
- `sysctl -w net.ipv4.ip_forward=...`
- `sysctl -w net.ipv6.conf.*.forwarding=...`
- `iptables` / `nft` / `firewall-cmd` 规则变更
- 重启 Docker、Node Agent、网卡、NetworkManager

如果检测发现不通，先记录源节点、目标节点、地址和时间，把现象交给拓扑/路由侧确认。不要为了让某一次 `ping` 通而临时添加路由。

## 验收目标

管理面目标：

- `admin`、`compute-1~compute-3`、`h1~h13` 共 17 个节点。
- 地址来自 `ops/inventory/topology_nodes.json` 的 `acceptance_management_ip`。
- 目标是 17 个源到 17 个目标都可达。

数据面目标：

- `compute-1~compute-3`、`h1~h13` 共 16 个节点。
- 地址来自 `ops/inventory/topology_nodes.json` 的 `acceptance_business_ipv6`。
- `admin` 没有数据面，不参与数据面矩阵。
- 目标是 16 个源到 16 个目标都可达。

## 快速检测

快速矩阵默认只从 `compute-1~compute-3` 作为源节点发起探测，适合日常排障：

```bash
cd /Users/yanjia/codes/manage_deploy
python3 ops/network/acceptance/check_connectivity.py --plane management --matrix --timeout 1
python3 ops/network/acceptance/check_connectivity.py --plane data --matrix --timeout 1
```

当前 2026-06-20 实测基线：

```text
management matrix:
compute-1 ok=17 fail=0
compute-2 ok=17 fail=0
compute-3 ok=17 fail=0

data matrix:
compute-1 ok=14 fail=2  failed=[compute-2, compute-3]
compute-2 ok=2  fail=14 failed=[compute-1, compute-3, h1, h2, h3, h5, h6, h7, h8, h9, h10, h11, h12, h13]
compute-3 ok=1  fail=15 failed=[compute-1, compute-2, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13]
```

解释：

- 管理面从 3 台计算节点看是全通的。
- 数据面还不满足验收目标，尤其 compute-2/compute-3 侧大面积不通。
- 该现象应交给拓扑/路由侧排查上游端口、RA/路由下发、转发表或数据面接线，不要在节点上临时加路由规避。

## 全量两两互通检测

先预览脚本将要登录哪些源节点：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane both \
  --matrix \
  --source-scope plane \
  --source-profile acceptance \
  --list-sources
```

正式验收现场，如果本机已经接入管理网，或 WireGuard 已经让本机可访问 `172.16.0.0/24`，运行：

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

开发阶段如果还依赖 `10.112` 入口，使用：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane management \
  --matrix \
  --source-scope plane \
  --source-profile current \
  --timeout 1
```

注意：

- 自动生成源使用 `BatchMode=yes`，不会在脚本里等待输入 SSH 密码。
- h1-h13 如果还没有配置免密登录，脚本会输出 `SOURCE_FAIL`，这表示源节点没能登录，不代表目标网络一定不通。
- 全量数据面矩阵会比较慢，因为每个源要 ping 16 个 IPv6 目标。

## 单源定位

从某个源节点单独检查管理面：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane management \
  --ssh '-p 2345 chengyubin@10.112.38.25'
```

从某个源节点单独检查数据面：

```bash
python3 ops/network/acceptance/check_connectivity.py \
  --plane data \
  --ssh '-p 2345 chengyubin@10.112.38.25'
```

如果需要确认某台机器上的地址状态，只执行只读命令：

```bash
ssh <node> 'hostname; ip -br addr; ip -6 addr show dev <数据面网卡>; ip -6 route show'
```

## IPv6 地址判定

更新 `acceptance_business_ipv6` 前，必须先确认地址稳定且可达。

在目标节点上查看：

```bash
ip -6 addr show dev <数据面网卡>
```

不要把以下地址写成主数据面地址：

- 包含 `temporary` 的临时隐私地址。
- 包含 `deprecated` 的地址。
- 只在本机存在、但其它数据面节点无法 ping 通的地址。
- `fe80::/64` 链路本地地址。

可以作为候选记录但不能直接启用：

- `temporary dynamic`
- `mngtmpaddr`
- 新出现但尚未完成多源可达性验证的地址。

推荐流程：

1. 在目标节点读取数据面网卡地址。
2. 从至少 `compute-1~compute-3` 三个源节点 ping 新 IPv6。
3. 如果目标是终端节点，再抽测同一拓扑区和跨拓扑区的终端源。
4. 通过后，把新地址写入 `ops/inventory/topology_nodes.json` 的 `acceptance_business_ipv6`。
5. 旧地址保留在 `acceptance_business_ipv6_candidates`，便于追溯。
6. 运行注册脚本 dry-run，确认将写入平台的字段正确。

示例：

```bash
python3 scripts/register_topology_nodes.py \
  --network-profile acceptance \
  --include-compute \
  --include-admin \
  --dry-run
```

确认无误后再由负责人执行真实注册：

```bash
export MANAGER_API_BASE=http://172.16.0.254:8181
export MANAGER_USERNAME=admin
export MANAGER_PASSWORD='<本地输入，不提交>'
python3 scripts/register_topology_nodes.py \
  --network-profile acceptance \
  --include-compute \
  --include-admin
```

## 当前已有修复脚本边界

`ops/network/acceptance/config_ens224.ps1`：

- 作用：给 h1-h13 的 `ens224` 配置 `172.16.0.151-163/24`。
- 会修改远端网卡地址。
- 只有当 h1-h13 管理面地址丢失，且负责人确认需要恢复时再执行。

`ops/network/acceptance/verify_ens224.ps1`：

- 作用：只读验证 h1-h13 的 `ens224` 管理面地址。
- 可安全用于日常检查。

`ops/network/acceptance/reset_ens192_ipv6.ps1`：

- 作用：重置 h1-h13 的 `ens192` 并触发重新获取 IPv6。
- 会 down/up 网卡并 flush IPv6 地址。
- 只适合终端节点数据面地址缺失或异常时，在负责人确认后执行。

这些脚本不处理 compute-2/compute-3 的数据面互通问题。compute 节点的数据面不通时，优先交给拓扑/路由侧确认，不要套用终端节点脚本。

## 结果记录模板

每次验收或排障建议记录：

```text
时间：
执行人：
本机接入方式：管理网直连 / WireGuard / 10.112 备用入口
inventory commit：

管理面矩阵命令：
管理面结果：

数据面矩阵命令：
数据面结果：

失败源：
失败目标：
失败地址：
是否 SOURCE_FAIL：
下一步责任方：平台 / 节点运维 / 拓扑路由
```

只有当矩阵结果和平台 `nodes` 表一致后，才进入业务部署验收。
