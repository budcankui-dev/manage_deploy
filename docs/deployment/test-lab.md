# 测试部署机器清单

本文档记录当前真实验收测试环境。不要在本文件中记录密码、token、私钥或其他凭据；sudo 密码等临时信息只允许放在被 `.gitignore` 忽略的本地文件 `ops/secrets/test-lab-credentials.local.md`。

矩阵乘法业务目标验收的完整迁移、构建、预检和页面操作步骤见 [matmul-acceptance-runbook.md](/Users/yanjia/codes/manage_deploy/docs/deployment/matmul-acceptance-runbook.md)。

后续从当前 10.112 调试网络切换到 172.16 管理网段、并让本机通过管理节点跳板访问拓扑节点和业务 IPv6 容器 UI 的方案见 [管理节点跳板与网络迁移方案](/Users/yanjia/codes/manage_deploy/docs/deployment/管理节点跳板与网络迁移方案.md)。

## 当前拓扑

| 名称 | 角色 | IP | SSH 端口 | SSH 用户 | GPU | 数据盘 | 备注 |
|------|------|----|----------|----------|-----|--------|------|
| admin-server | 管理面主控 | `10.112.244.94` | `22` | `bupt` | - | `/mnt/data` | 部署前端、后端、MySQL、MinIO、私有 Registry |
| compute-1 | 业务节点 | `10.112.38.25` | `2345` | `chengyubin` | TITAN X x 1 | `/disk/sdc` | 可作为 source / compute / sink |
| compute-2 | 业务节点 | `10.112.17.51` | `2345` | `chengyubin` | TITAN X x 1 | `/data/hdd1` | 可作为 source / compute / sink |
| compute-3 | 业务节点 | `10.112.59.209` | `22` | `compute` | Tesla P40 x 8 | `/data` | 静态 IP，MAC `0c:c4:7a:85:78:14`，可作为 source / compute / sink |

当前阶段默认 `admin-server` 是管理节点，`compute-*` 是业务节点。矩阵乘法演示仍按随路计算数据流 `source -> compute -> sink` 验证，业务数据不通过共享宿主机文件传递。

## 固定 IP 与空间维护

`compute-1`、`compute-2` 原为 DHCP 动态地址，重启后可能变更。当前已将两台机器按现网地址改为 NetworkManager manual 静态 IPv4；`compute-3` 已使用 netplan 静态 IPv4。

| 节点 | 网卡 | IPv4 配置 | 网关 | DNS |
|------|------|-----------|------|-----|
| compute-1 | `enp6s0` | `10.112.38.25/16` | `10.112.0.1` | `10.3.9.4, 10.3.9.5, 10.3.9.6` |
| compute-2 | `enp5s0` | `10.112.17.51/16` | `10.112.0.1` | `10.3.9.5, 10.3.9.4, 10.3.9.6` |
| compute-3 | `enp129s0f0` | `10.112.59.209/16` | `10.112.0.1` | 见 `/etc/netplan/99-static-enp129s0f0.yaml` |

2026-06-18 已执行低风险空间清理：Docker build cache、已停止容器、未使用 volume、apt cache、旧日志归档。未删除任何用户家目录或数据盘用户文件。

当前需关注的空间项：

| 节点 | 现状 | 说明 |
|------|------|------|
| compute-1 | `/home` 约 `114G/137G`，剩余约 `16G` | 主要占用为 `/home/bupt`、`/home/zhujie`、`/home/citens`、`/home/yanshuo`、`/home/yanw`、`/home/newip` 等；删除前需人工确认归属。 |
| compute-2 | `/` 约 `117G/234G`，剩余约 `105G` | `/home/chengyubin`、`/home/zhujie`、`/home/ymy` 占用较大；Docker 镜像可回收较多，但为避免影响演示镜像，未主动删除镜像。 |
| compute-3 | `/data` 约 `120G/1.8T`，剩余约 `1.6T` | Docker 与 containerd 已迁移到 `/data`，暂无空间压力。 |

## Docker / containerd 存储

Docker `data-root` 和 containerd `root/state` 是两套路径；即使 Docker `data-root` 已经放在数据盘，containerd 仍可能默认写入系统盘 `/var/lib/containerd`，导致拉取大镜像时报 `no space left on device`。

当前已完成如下迁移：

| 节点 | Docker data-root | containerd root | containerd state | 备注 |
|------|------------------|-----------------|------------------|------|
| admin-server | `/mnt/data/docker` | `/mnt/data/containerd-root` | `/mnt/data/containerd-state` | 已从系统盘迁移，Registry/MySQL/前端已恢复 |
| compute-1 | `/data/hdd1/docker` | `/data/hdd1/containerd-root` | `/data/hdd1/containerd-state` | 已显式迁移，Docker 与 containerd 均不写系统盘 |
| compute-2 | `/disk/sdb/docker` | `/disk/sdc/containerd-root` | `/disk/sdc/containerd-state` | 已从系统盘迁移，解决拉大镜像空间不足 |
| compute-3 | `/data/docker` | `/data/containerd-root` | `/data/containerd-state` | 已从系统盘迁移，Docker 与 containerd 均不写系统盘 |

迁移后应通过以下命令复核：

```bash
sudo grep -E '^(root|state) =' /etc/containerd/config.toml
sudo du -sh /var/lib/containerd
docker ps
```

## SSH 访问

本机已配置 SSH alias，供 Codex / Claude CLI / E2E Deploy Test Agent 使用：

```bash
ssh manage-admin hostname
ssh manage-compute-1 hostname
ssh manage-compute-2 hostname
ssh manage-compute-3 hostname
```

这些 alias 使用本机专用 key `~/.ssh/manage_deploy_test_lab_ed25519`。公钥已上传到四台机器；不要把私钥、密码或 sudo 密码复制到仓库。

原始连接方式：

```bash
ssh -p 22 bupt@10.112.244.94 hostname
ssh -p 2345 chengyubin@10.112.38.25 hostname
ssh -p 2345 chengyubin@10.112.17.51 hostname
ssh -p 22 compute@10.112.59.209 hostname
```

## 管理面服务

| 服务 | 地址 |
|------|------|
| 前端 | `http://10.112.244.94:8182` |
| 后端 API | `http://10.112.244.94:8181` |
| 业务测评页 | `http://10.112.244.94:8182/benchmark` |
| MySQL | `10.112.244.94:3306`，db=`task_manager` |
| MinIO | `http://10.112.244.94:9000` |
| Docker Registry | `10.112.244.94:5000`，HTTP insecure registry |
| Portainer | `10.112.244.94:8000`，不要占用 |

admin-server 后端代码路径：

```bash
/home/bupt/manage_deploy/backend
```

后端启动命令：

```bash
cd /home/bupt/manage_deploy/backend
nohup /home/bupt/miniconda3/bin/python3.13 -m uvicorn main:app --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 &
```

注意：admin-server 上的 `/home/bupt/manage_deploy/backend/venv` 是历史同步遗留目录，内部 Python 链接指向本机 macOS Homebrew 路径，不能作为远端启动环境。管理节点后端当前使用 `/home/bupt/miniconda3/bin/python3.13` 启动；若重装环境，至少需要安装 `backend/pyproject.toml` 中的运行依赖，并额外确认 `minio`、`pillow` 可导入。

## 管理面 .env

以下内容记录字段形态，真实文件不纳入 git：

```text
DATABASE_URL=mysql+aiomysql://root:<password>@10.112.244.94:3306/task_manager
MINIO_ENDPOINT=http://10.112.244.94:9000
MINIO_BUCKET=task-results
MINIO_ACCESS_KEY=<access-key>
MINIO_SECRET_KEY=<secret-key>
BACKEND_HOSTNAME=admin-server
BACKEND_PORT=8181
MANAGER_PUBLIC_URL=http://10.112.244.94:8181
INTENT_PARSER_ENGINE=llm
```

## 推荐项目目录

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

## 部署更新流程

admin-server 当前 `/home/bupt/manage_deploy` 可能是 Git 仓库，也可能是手工同步目录。更新前先检查：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && git status --short"
```

如果返回 `not a git repository`，不要继续使用 `git pull`；改用本地 `rsync` 同步源码和构建产物，同时排除 `.env`、数据库、虚拟环境和缓存文件。

```bash
# 方式 A：admin-server 是 Git 仓库
git push origin main
ssh manage-admin "cd /home/bupt/manage_deploy && git pull"

# 方式 B：admin-server 是手工同步目录
rsync -az --exclude '.env' --exclude '*.db' --exclude 'venv' --exclude '__pycache__' backend/ manage-admin:/home/bupt/manage_deploy/backend/
rsync -az frontend/dist/ manage-admin:/home/bupt/manage_deploy/frontend/dist/
rsync -az workers/low-latency-video/ manage-admin:/home/bupt/manage_deploy/workers/low-latency-video/

# 重启后端。避免 pkill -f 匹配到当前 SSH 命令本身。
ssh manage-admin "pids=\$(pgrep -f '[u]vicorn main:app.*8181' || true); [ -n \"\$pids\" ] && kill \$pids || true; sleep 1; cd /home/bupt/manage_deploy/backend && nohup /home/bupt/miniconda3/bin/python3.13 -m uvicorn main:app --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 &"

# 刷新前端静态文件
# 当前 8182 由 admin-server 宿主机 nginx 提供，root 为 /home/bupt/manage_deploy/frontend/dist。
# 同步 frontend/dist 后通常无需 docker cp；若另行启用 idn-frontend 容器预览，再单独复制到容器目录。
ssh manage-admin "curl -s http://127.0.0.1:8182/ | grep -o 'assets/index-[^\"<>]*' | head"

# 验证节点 API
ssh manage-admin "curl -s http://localhost:8181/api/nodes | python3 -c 'import sys,json; print(len(json.load(sys.stdin)), \"nodes\")'"
```

节点资源同步说明：

- 工作节点页面的“同步资源”会调用 Node Agent `/resources`，用于补齐 CPU 核数、CPU 型号和内存等展示字段。
- 如果 Node Agent 容器内没有 `nvidia-smi`，系统不会把 `nodes` 表里已有 GPU 数量、型号、显存和驱动版本覆盖为空；CUDA 版本只作为诊断字段，不作为业务目标成功率判定条件。
- 验收前如需确认 GPU 真实可用，应在业务基线或 worker 日志中核对实际后端，例如矩阵业务 `onnxruntime_cuda/cuda:0`，视频业务 `opencv_dnn_cuda/cuda:0` 或对应 GPU 推理后端。

worker 代码或 Dockerfile 变更后，需要在 AMD64 环境构建并推送镜像：

```bash
cd /home/bupt/manage_deploy
./scripts/build_workers.sh
docker tag manage-deploy/scientific-matmul:dev 10.112.244.94:5000/scientific-matmul:dev
docker push 10.112.244.94:5000/scientific-matmul:dev
```

## 业务节点 Docker 配置

业务节点拉取 admin-server 私有镜像仓库前，需要在 `/etc/docker/daemon.json` 中保留原有字段并加入：

```json
{
  "insecure-registries": ["10.112.244.94:5000"]
}
```

然后重启 Docker：

```bash
sudo systemctl restart docker
```

## 当前准备状态

- 四台机器均可通过 SSH key 免密登录。
- 四台机器登录用户均可使用 sudo；sudo 密码见本地 ignored 凭据文件。
- compute-1 的 `/disk/sdc/manage_deploy` 已创建并可写。
- compute-2 的 `/data/hdd1/manage_deploy` 已创建并可写。
- compute-2 当前按 1 张 TITAN X 记录。
- compute-3 已固定为静态 IP `10.112.59.209/16`，默认路由 `10.112.0.1`，Node Agent 地址 `http://10.112.59.209:8001`。
- admin-server 上已有私有 registry 容器 `registry:2`，地址为 `10.112.244.94:5000`。

## 业务面 IPv6 配置

当前调试拓扑采用“控制面 IPv4、业务面 IPv6”。`management_ip` / `agent_address` 仍使用 10.112 IPv4，业务容器之间的 `PEER_*_URL` 优先使用同一物理网卡上的全局 IPv6。注意：下表是当前校园网 IPv6 调试地址，重启或网络切换后可能变化；正式验收时会替换为验收数据面 IPv6，并按 [管理节点跳板与网络迁移方案](/Users/yanjia/codes/manage_deploy/docs/deployment/管理节点跳板与网络迁移方案.md) 更新 `nodes.business_ipv6`。

| 节点 | 10.112 网卡 | 业务 IPv6 | 调度 |
|------|-------------|-----------|------|
| admin-server | `eno1` | `2001:da8:215:6a01:d6ae:52ff:fec9:1188` | 否 |
| compute-1 | `enp6s0` | `2001:da8:215:6a01:e381:3ba8:e0:c6c9` | 是 |
| compute-2 | `enp5s0` | `2001:da8:215:6a01:7e:a98d:5fc5:6ca7` | 是 |
| compute-3 | `enp129s0f0` | `2001:da8:215:6a01:ec4:7aff:fe85:7814` | 是 |

切换要求：

- 后端 `.env` 设置 `PREFER_BUSINESS_IPV6=true`。
- 后端 `.env` 设置 `BACKEND_PORT=8181`，确保 worker 指标回写到 `http://10.112.244.94:8181`。
- `nodes.business_ipv6` 写入上表地址；admin 节点保持 `is_schedulable=false`。
- 重启后端后，日志应出现 `Resolved MANAGER_PUBLIC_URL=http://10.112.244.94:8181`。

连通性核验：

```bash
ssh manage-admin "ping -6 -c 2 2001:da8:215:6a01:e381:3ba8:e0:c6c9"
ssh manage-admin "ping -6 -c 2 2001:da8:215:6a01:7e:a98d:5fc5:6ca7"
ssh manage-admin "ping -6 -c 2 2001:da8:215:6a01:ec4:7aff:fe85:7814"
```

如果 ping 不通或地址与表格不一致，先通过跳板登录对应节点执行 `ip -br -6 addr`，再更新 `nodes.business_ipv6`；不要继续使用过期 IPv6 做业务链路验收。

业务核验不只看实例 `running`。需要抽查真实容器环境变量和日志，确认：

- `PEER_COMPUTE_URL` / `PEER_SINK_URL` 形如 `http://[2001:...]:18000`。
- `TASK_PEERS_JSON[*].business_address` 为 IPv6。
- sink 日志出现 `SINK_DONE` 或 `VIDEO_SINK_DONE`，且业务评估接口返回 `business_success=true`。

## 给 E2E Deploy Test Agent 的提示

- 测试部署固定围绕以上四台机器，不要回退到本地 mock 环境，除非 work item 明确要求。
- 先确认 SSH 连通性、数据盘可写、Docker/NVIDIA runtime、Node Agent 状态。
- 需要 sudo 时读取 `ops/secrets/test-lab-credentials.local.md`，不要把密码打印到日志。
- 需要私有镜像仓库时，优先使用 `10.112.244.94:5000`，并按需配置业务节点 Docker daemon。
- 部署验证应记录每台机器的 `hostname`、`docker --version`、`nvidia-smi` 或无 GPU 可用的原因。
- 注册平台 Node 时，管理地址和业务 IPv4 可使用 10.112 地址；正式验收前必须按“业务面 IPv6 配置”更新 `business_ipv6`。
- 当前业务测评页面是 `http://10.112.244.94:8182/benchmark`，管理面后端是 `http://10.112.244.94:8181`。
