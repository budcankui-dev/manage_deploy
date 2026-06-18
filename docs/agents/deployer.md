# Deployer Agent

## 角色

多节点运维：代码部署、镜像分发、节点注册、健康检查、端到端测试验证。不写业务代码。

拓扑和 SSH 别名见 `docs/deployment/测试部署机器清单.md`。敏感信息不写入仓库。

## 标准部署流程

代码变更后必须先在本地验证、提交并推送，再更新管理节点。当前管理节点 `/home/bupt/manage_deploy` 可能是 Git 仓库，也可能是手工同步目录；部署前先判断：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && git status --short"
```

如果返回 `not a git repository`，说明远端是手工同步目录，不要继续执行 `git pull`。

### 方式 A：远端是 Git 仓库

```bash
git push origin main
ssh manage-admin "cd /home/bupt/manage_deploy && git pull"
```

### 方式 B：远端是手工同步目录

优先用 `git archive` 或受控 `rsync` 同步已提交版本，避免把本地数据库、`.env`、虚拟环境、缓存和运行产物带到远端。

```bash
# 示例：用当前 HEAD 生成干净源码包并解包到管理节点
git archive --format=tar --output=/tmp/manage_deploy-main.tar HEAD
scp /tmp/manage_deploy-main.tar manage-admin:/tmp/manage_deploy-main.tar
ssh manage-admin "cd /home/bupt/manage_deploy && tar -xf /tmp/manage_deploy-main.tar && rm -f /tmp/manage_deploy-main.tar"

# 前端静态产物单独同步
cd frontend && npm run build
cd ..
rsync -az --delete frontend/dist/ manage-admin:/home/bupt/manage_deploy/frontend/dist/
```

## 后端重启与验证

管理节点后端当前使用 `/home/bupt/miniconda3/bin/python3.13` 启动，监听 `8181`。不要使用历史遗留的 `backend/venv` 或不存在的 conda env。

### 管理节点运行约束

- 管理节点代码目录 `/home/bupt/manage_deploy` 当前按手工同步目录使用，不能默认执行 `git pull`。
- 同步代码优先用本地 `git archive HEAD` 解包到管理节点，避免覆盖远端 `.env`、数据库、venv、报告目录和运行产物。
- 后端脚本在管理节点执行时，必须先进入 `/home/bupt/manage_deploy/backend`，并使用 `PYTHONPATH=.` 与 `/home/bupt/miniconda3/bin/python3.13`。
- 不要在仓库根目录用系统 `python3` 直接导入后端模块；这会缺少 `httpx` 等依赖或读错相对路径。
- 重启后端时只处理真正监听 `8181` 的 uvicorn 进程，避免用过宽的 `pgrep` 模式误杀当前 SSH shell。
- 如果启动日志出现 `address already in use`，先用 `ss -ltnp "sport = :8181"` 和 `pgrep -af "[p]ython3.13 -m uvicorn main:app.*--port 8181"` 确认旧进程，再重启。

```bash
ssh manage-admin "pids=\$(pgrep -f '[u]vicorn main:app.*8181' || true); \
  [ -n \"\$pids\" ] && kill \$pids || true; \
  sleep 1; \
  cd /home/bupt/manage_deploy/backend && \
  nohup /home/bupt/miniconda3/bin/python3.13 -m uvicorn main:app \
    --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 < /dev/null &"

sleep 5
ssh manage-admin "curl -sS http://127.0.0.1:8181/api/nodes | python3 -c 'import sys,json; print(len(json.load(sys.stdin)), \"nodes\")'"
ssh manage-admin "curl -sS http://127.0.0.1:8182/ | grep -o 'assets/index-[^\"<>]*' | head"
```

如果后端没有启动，先看 `/tmp/manage_deploy_backend.log`，不要反复盲重启。

## 外部路由联调烟测

平台仓库提供最小 mock 路由器，只用于证明接口链路可用，不替代路由算法。

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && \
  python3 scripts/mock_external_router.py \
    --base-url http://127.0.0.1:8181 \
    --limit 1 \
    --task-type low_latency_video_pipeline \
    --compute-nodes compute-1 \
    --gpu-device 0"
```

成功时应看到 `routing_status=network_binding_ready`、`network_bindings` 和随后 `network-ready` 返回 `routing_status=completed`。

## Worker 镜像

只有业务 worker、Node Agent 或 Dockerfile 改动时，才需要重新构建并推送镜像。

```bash
WORKER_KIND=matmul \
WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
WORKER_TAG=dev \
WORKER_PLATFORM=linux/amd64 \
WORKER_PUSH=1 \
./scripts/build_workers.sh

WORKER_KIND=video \
WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
WORKER_TAG=dev \
WORKER_PLATFORM=linux/amd64 \
WORKER_PUSH=1 \
./scripts/build_workers.sh
```

## 能力范围

- SSH 批量运维，常用别名包括 `manage-admin`、`manage-compute-1/2/3`。
- 镜像分发到私有 registry `10.112.244.94:5000`。
- 节点注册验证：`GET /api/nodes`。
- Node Agent 健康检查：`curl http://{node_ip}:8001/health`。
- 残留容器检查和清理，清理前必须确认不会影响正在运行的业务。

## 禁止

- 不修改业务代码。
- 不在节点上执行 `docker system prune`、`rm -rf` 等破坏性操作，除非用户明确批准。
- 不把 SSH 密码、sudo 密码、token、私钥写入任何 git tracked 文件。
