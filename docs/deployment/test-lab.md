# 测试部署机器清单

本文档记录当前真实验收测试环境。不要在本文件中记录密码、token、私钥或其他凭据；sudo 密码等临时信息只允许放在被 `.gitignore` 忽略的本地文件 `ops/secrets/test-lab-credentials.local.md`。

矩阵乘法业务目标验收的完整迁移、构建、预检和页面操作步骤见 [matmul-acceptance-runbook.md](/Users/yanjia/codes/manage_deploy/docs/deployment/matmul-acceptance-runbook.md)。

## 当前拓扑

| 名称 | 角色 | IP | SSH 端口 | SSH 用户 | GPU | 数据盘 | 备注 |
|------|------|----|----------|----------|-----|--------|------|
| admin-server | 管理面主控 | `10.112.244.94` | `22` | `bupt` | - | `/mnt/data` | 部署前端、后端、MySQL、MinIO、私有 Registry |
| compute-1 | 业务节点 | `10.112.249.191` | `2345` | `chengyubin` | TITAN X x 1 | `/disk/sdc` | 可作为 source / compute / sink |
| compute-2 | 业务节点 | `10.112.150.166` | `2345` | `chengyubin` | TITAN X x 1 | `/data/hdd1` | 可作为 source / compute / sink |
| compute-3 | 业务节点 | `10.112.59.209` | `22` | `compute` | Tesla P40 x 8 | `/data` | 静态 IP，MAC `0c:c4:7a:85:78:14`，可作为 source / compute / sink |

当前阶段默认 `admin-server` 是管理节点，`compute-*` 是业务节点。矩阵乘法演示仍按随路计算数据流 `source -> compute -> sink` 验证，业务数据不通过共享宿主机文件传递。

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
ssh -p 2345 chengyubin@10.112.249.191 hostname
ssh -p 2345 chengyubin@10.112.150.166 hostname
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
nohup /home/bupt/miniconda3/envs/manage_deploy/bin/uvicorn main:app --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 &
```

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
ssh manage-admin "pids=\$(pgrep -f '[u]vicorn main:app.*8181' || true); [ -n \"\$pids\" ] && kill \$pids || true; sleep 1; cd /home/bupt/manage_deploy/backend && nohup /home/bupt/miniconda3/envs/manage_deploy/bin/uvicorn main:app --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 &"

# 刷新前端静态文件
ssh manage-admin "docker cp /home/bupt/manage_deploy/frontend/dist/. idn-frontend:/usr/share/nginx/html/"

# 验证节点 API
ssh manage-admin "curl -s http://localhost:8181/api/nodes | python3 -c 'import sys,json; print(len(json.load(sys.stdin)), \"nodes\")'"
```

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

## 给 E2E Deploy Test Agent 的提示

- 测试部署固定围绕以上四台机器，不要回退到本地 mock 环境，除非 work item 明确要求。
- 先确认 SSH 连通性、数据盘可写、Docker/NVIDIA runtime、Node Agent 状态。
- 需要 sudo 时读取 `ops/secrets/test-lab-credentials.local.md`，不要把密码打印到日志。
- 需要私有镜像仓库时，优先使用 `10.112.244.94:5000`，并按需配置业务节点 Docker daemon。
- 部署验证应记录每台机器的 `hostname`、`docker --version`、`nvidia-smi` 或无 GPU 可用的原因。
- 注册平台 Node 时，管理地址和业务地址初期可都使用上述 IP；后续如启用业务 IPv6，再更新 `business_ipv6`。
- 当前业务测评页面是 `http://10.112.244.94:8182/benchmark`，管理面后端是 `http://10.112.244.94:8181`。
