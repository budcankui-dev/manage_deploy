# 测试部署机器清单

本文档记录当前业务端到端测试可用机器。不要在本文件中记录密码、token、私钥或其他凭据；凭据应放在本地密码管理器，或放在被 `.gitignore` 忽略的本地文件 `ops/secrets/test-lab-credentials.local.md`。

## 拓扑角色

| 名称 | 角色 | IP | SSH 端口 | SSH 用户 | GPU | 备注 |
|------|------|-----|----------|----------|-----|------|
| admin-server | 管理面主控 | `10.112.244.94` | `22` | `bupt` | — | 运行后端(8181)、DB(3306)、MinIO(9000)、Registry(5000) |
| compute-1 | 业务节点 | `10.112.249.191` | `2345` | `chengyubin` | TITAN X × 1 | Node Agent :8001，可作 source/compute/sink |
| compute-2 | 业务节点 | `10.112.150.166` | `2345` | `chengyubin` | TITAN X × 1 | Node Agent :8001，可作 source/compute/sink |
| compute-3 | 业务节点 | `10.112.116.165` | `22` | `compute` | Tesla P40 × 8 | Node Agent :8001，可作 source/compute/sink |

## SSH 别名（~/.ssh/config 已配置）

```bash
ssh manage-admin      # bupt@10.112.244.94:22       key: manage_deploy_test_lab_ed25519
ssh manage-compute-1  # chengyubin@10.112.249.191:2345
ssh manage-compute-2  # chengyubin@10.112.150.166:2345
ssh manage-compute-3  # compute@10.112.116.165:22
```

## 管理面服务（admin-server）

| 服务 | 地址 |
|------|------|
| 后端 API | `http://10.112.244.94:8181` |
| MySQL | `10.112.244.94:3306` db=`task_manager` |
| MinIO | `http://10.112.244.94:9000` |
| Docker Registry | `10.112.244.94:5000` (HTTP, insecure) |
| Portainer | `10.112.244.94:8000` (勿占用) |

后端代码路径：`/home/bupt/manage_deploy/backend`  
后端启动命令：
```bash
cd /home/bupt/manage_deploy/backend
nohup /home/bupt/miniconda3/envs/manage_deploy/bin/uvicorn main:app --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 &
```

## 关键 .env（admin-server，不纳入 git）

```
DATABASE_URL=mysql+aiomysql://root:Bupt%401234@10.112.244.94:3306/task_manager
MINIO_ENDPOINT=http://10.112.244.94:9000
MINIO_BUCKET=task-results
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=admin1234
BACKEND_HOSTNAME=admin-server
BACKEND_PORT=8181
MANAGER_PUBLIC_URL=http://10.112.244.94:8181
INTENT_PARSER_ENGINE=llm
```

## 部署更新流程（每次代码变更后）

```bash
# 1. 推送代码到 GitHub
git push origin main

# 2. 在 admin-server 拉取最新代码
ssh manage-admin "cd /home/bupt/manage_deploy && git pull"

# 3. 重启后端
ssh manage-admin "pkill -f 'uvicorn main:app' 2>/dev/null; sleep 1; cd /home/bupt/manage_deploy/backend && nohup /home/bupt/miniconda3/envs/manage_deploy/bin/uvicorn main:app --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 &"
sleep 5

# 4. 验证
ssh manage-admin "curl -s http://localhost:8181/api/nodes | python3 -c 'import sys,json; print(len(json.load(sys.stdin)), \"nodes\")'  "

# 5. 重新构建 worker 镜像（如 worker 代码有改动）
cd workers && docker build -f high-throughput-matmul/Dockerfile -t 10.112.244.94:5000/scientific-matmul:dev .
docker push 10.112.244.94:5000/scientific-matmul:dev
```

## 业务节点 Docker 配置要求

业务节点需在 `/etc/docker/daemon.json` 中配置 insecure registry：
```json
{"insecure-registries": ["10.112.244.94:5000"]}
```

## 清理残留容器（测试后）

```bash
# 清理 compute-1 ghost 容器
curl -s http://10.112.249.191:8001/containers/managed | python3 -c "import sys,json; d=json.load(sys.stdin); [print(c['name']) for c in d]"

# 按 task_id/node_id 删除
curl -X DELETE http://10.112.249.191:8001/containers/{task_id}/{node_id}
```


本文档记录当前业务端到端测试可用机器。不要在本文件中记录密码、token、私钥或其他凭据；凭据应放在本地密码管理器，或放在被 `.gitignore` 忽略的本地文件 `ops/secrets/test-lab-credentials.local.md`。

## 拓扑角色

| 名称 | 角色 | 管理 IP | SSH 端口 | SSH 用户 | GPU | 数据盘 | 备注 |
|------|------|---------|----------|----------|-----|--------|------|
| admin-server | 管理面主控机器 | `10.112.244.94` | `22` | `bupt` | 未记录 | `/mnt/data` | Task Manager、Frontend、数据库/对象存储等管理面组件优先部署在这里 |
| compute-1 | 业务节点 | `10.112.249.191` | `2345` | `chengyubin` | TITAN X * 1 | `/disk/sdc` | 当前阶段也可作为 source 或 sink |
| compute-2 | 业务节点 | `10.112.150.166` | `2345` | `chengyubin` | TITAN X * 1 | `/data/hdd1` | 当前阶段也可作为 source、compute 或 sink |
| compute-3 | 业务节点 | `10.112.116.165` | `22` | `compute` | Tesla P40 * 8 | `/data` | 当前阶段也可作为 source、compute 或 sink |

## 本地凭据文件

本机可选存在 ignored 文件：

```text
ops/secrets/test-lab-credentials.local.md
```

该文件可记录 SSH 用户的 sudo 密码，供 E2E Deploy Test Agent 在需要 `sudo` 时读取。它不受版本管理控制，不应被复制进 work item、日志或提交信息。

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

本机已配置项目级 SSH alias，供 Claude CLI / E2E Deploy Test Agent 使用：

```bash
ssh manage-admin hostname
ssh manage-compute-1 hostname
ssh manage-compute-2 hostname
ssh manage-compute-3 hostname
```

这些 alias 使用本机专用 key `~/.ssh/manage_deploy_test_lab_ed25519`。公钥已上传到四台机器；不要把私钥或密码复制到仓库。

原始连接方式：

```bash
ssh -p 22 bupt@10.112.244.94 hostname
ssh -p 2345 chengyubin@10.112.249.191 hostname
ssh -p 2345 chengyubin@10.112.150.166 hostname
ssh -p 22 compute@10.112.116.165 hostname
```

## 当前准备状态

已确认：

- 四台机器均可通过 SSH key 免密登录。
- 四台机器登录用户均可使用 sudo；sudo 密码见本地 ignored 凭据文件。
- compute-1 的 `/disk/sdc/manage_deploy` 已创建并可写。
- compute-2 的 `/data/hdd1/manage_deploy` 已创建并可写。
- compute-2 当前实测 GPU 为 1 张 TITAN Xp。
- admin-server 上已有私有 registry 容器 `registry:2`，地址为 `10.112.244.94:5000`。

待 E2E Deploy Test Agent 处理：

- admin-server 的 `/mnt/data/manage_deploy` 创建时当前用户权限不足，需要用合适权限或 sudo 处理。
- compute-3 的 `/data/manage_deploy` 创建时当前用户权限不足，需要用合适权限或 sudo 处理。
- 确认每台机器 Docker、NVIDIA runtime、Node Agent 部署路径和运行方式。

## 私有镜像仓库

admin-server 上已部署 Docker registry：

```text
10.112.244.94:5000
```

E2E Deploy Test Agent 如需让业务节点拉取该私有仓库镜像，可在业务节点上配置 Docker daemon。若该 registry 使用 HTTP 而非 HTTPS，通常需要在业务节点 `/etc/docker/daemon.json` 中加入：

```json
{
  "insecure-registries": ["10.112.244.94:5000"]
}
```

然后重启 Docker：

```bash
sudo systemctl restart docker
```

配置前应先读取现有 `/etc/docker/daemon.json` 并保留已有字段，避免覆盖节点现有 Docker 配置。

## 给 E2E Deploy Test Agent 的提示

- 先确认 SSH 连通性、数据盘可写、Docker/NVIDIA runtime 状态。
- 不要把密码写入 git tracked 文件。
- 如果需要记录临时凭据位置，只记录本地 ignored 文件路径，不记录具体内容。
- 需要 sudo 时读取 `ops/secrets/test-lab-credentials.local.md`，不要把密码打印到日志。
- 需要私有镜像仓库时，优先使用 `10.112.244.94:5000`，并按需配置业务节点 Docker daemon。
- 部署验证应记录每台机器的 `hostname`、`docker --version`、`nvidia-smi` 或无 GPU 可用的原因。
- 注册平台 Node 时，管理地址和业务地址初期可都使用上述 IP；后续如启用业务 IPv6，再更新 `business_ipv6`。
