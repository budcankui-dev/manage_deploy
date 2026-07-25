# Worker 数据输入输出设计草案

本文记录主会话关于业务 Worker 数据输入输出的设计讨论。当前是设计草案，不代表已完全实现。

## 当前 matmul 状态

当前科学计算矩阵乘法 worker 镜像：

- 镜像内只打包代码和依赖，不打包用户业务输入数据。
- `source` 通过 `DATA_PROFILE` 环境变量读取 `matrix_size`、`batch_count`、`seed`，并合成矩阵计算任务。
- `source -> compute -> sink` 的业务数据通过 HTTP 网络传递。
- `sink` 可选把 `result.json` 上传到 MinIO，并向 Manager 上报业务指标。
- 当前 matmul 演示不依赖 `/scratch` 共享目录传递业务数据。

这符合“镜像只包含程序，不包含用户数据”的方向，但还没有完整支持“用户上传文件 -> Worker 拉取输入”的通用链路。

## 核心原则

- Worker 镜像应是不可变程序包，只包含代码、依赖和少量静态配置。
- 用户输入数据不应预先打包进镜像。
- 用户上传数据的首选承载方式是对象存储，例如 MinIO。
- 平台应把输入对象 URI、访问配置和数据画像注入 Worker，而不是把文件复制进镜像。
- 挂载目录可作为开发/高性能场景的补充，但不能作为跨业务节点的数据传递总线。
- 节点之间业务数据流仍应通过网络路径传递，保持随路计算语义。

## 推荐数据来源优先级

第一优先级：MinIO / 对象存储

- 用户上传文件后，后端保存到 MinIO。
- 数据库记录对象 URI、文件名、content type、大小、校验和。
- Worker 通过注入的 `INPUT_OBJECTS` 或 `INPUT_MANIFEST_URI` 拉取输入。
- 适合用户对话提交工单和外部路由验收。

第二优先级：受控挂载

- 管理员或测试环境可把数据目录挂载到 Worker。
- 适合大文件、本地数据集、离线测试。
- 挂载路径必须通过模板/实例配置显式声明，不能隐式依赖宿主机路径。
- 不允许把挂载目录作为 source/compute/sink 之间的共享通信路径。

第三优先级：合成数据

- 适合 matmul 这类验收 demo。
- 通过 `DATA_PROFILE` 指定规模和 seed。
- 不代表真实用户文件上传链路。

## 建议 Worker 输入契约

平台注入环境变量：

```text
DATA_PROFILE        # JSON，业务数据画像
INPUT_OBJECTS       # JSON array，直接列出输入对象
INPUT_MANIFEST_URI  # 可选，MinIO 中的 manifest JSON
RESULT_STORAGE      # JSON，结果保存位置
MINIO_ENDPOINT
MINIO_BUCKET
MINIO_ACCESS_KEY
MINIO_SECRET_KEY
```

`INPUT_OBJECTS` 示例：

```json
[
  {
    "name": "input.csv",
    "uri": "s3://task-inputs/user-123/order-456/input.csv",
    "content_type": "text/csv",
    "size_bytes": 1024,
    "sha256": "optional"
  }
]
```

`INPUT_MANIFEST_URI` 指向的 manifest 示例：

```json
{
  "objects": [
    {
      "name": "matrix-a.npy",
      "uri": "s3://task-inputs/user-123/order-456/matrix-a.npy",
      "content_type": "application/octet-stream"
    },
    {
      "name": "matrix-b.npy",
      "uri": "s3://task-inputs/user-123/order-456/matrix-b.npy",
      "content_type": "application/octet-stream"
    }
  ],
  "profile": {
    "matrix_size": 1024,
    "batch_count": 1
  }
}
```

## 推荐 Worker 行为

`source`：

- 如果存在 `INPUT_OBJECTS` 或 `INPUT_MANIFEST_URI`，优先从 MinIO 拉取用户输入。
- 如果不存在输入对象，则按 `DATA_PROFILE` 生成 synthetic 数据。
- 生成或读取后的业务 job 继续通过 HTTP 发给 `compute`。

`compute`：

- 不直接读取用户上传对象，除非业务本身要求 compute 节点拉取大文件。
- 第一阶段仍建议从 `source` 接收 job，保持 source -> compute -> sink 数据路径清晰。

`sink`：

- 接收结果。
- 上报业务指标。
- 将完整结果对象写入 MinIO。
- 只把前端展示需要的白名单摘要写入 metric tags。

## 用户上传文件链路

后续对话式工单可扩展：

```text
用户上传文件
 -> backend 保存到 MinIO
 -> user_uploaded_objects 记录元数据
 -> IntentDraft 引用 uploaded object ids
 -> TaskOrder 关联 input objects
 -> TaskInstance 注入 INPUT_OBJECTS / INPUT_MANIFEST_URI
 -> Worker source 拉取输入
 -> source 通过网络把 job 发给 compute
 -> sink 上传结果并上报指标
```

建议数据库表：

`user_uploaded_objects`：

- `id`
- `user_id`
- `conversation_id` nullable
- `order_id` nullable
- `bucket`
- `object_key`
- `uri`
- `filename`
- `content_type`
- `size_bytes`
- `sha256`
- `status`
- `created_at`

## 与镜像构建的边界

镜像中允许包含：

- Worker 代码。
- 通用依赖。
- 小型静态配置。
- 测试用最小 fixtures，但不能作为生产/验收主路径。

镜像中不应包含：

- 用户上传数据。
- 会随工单变化的数据集。
- 路由结果。
- 业务结果。
- 私密凭据。

## 挂载目录使用边界

允许：

- 管理员为特定任务配置只读输入数据挂载。
- Worker 使用本地临时目录作为计算缓存。
- 高性能场景把大文件预热到节点本地数据盘。

不允许：

- source、compute、sink 通过同一个共享挂载目录传递业务数据。
- 用 `/scratch` 作为节点间业务数据 IPC。
- 把宿主机路径写死在 Worker 镜像或代码里。

## 建议拆分 Work Items

- `worker-input-object-contract.md`
  - 定义 `INPUT_OBJECTS` / `INPUT_MANIFEST_URI` / `RESULT_STORAGE` 契约。
  - 更新 worker env 文档。

- `user-uploaded-objects.md`
  - 增加用户上传对象表和上传 API。
  - 文件保存到 MinIO。
  - 对话和工单可引用上传对象。

- `matmul-source-minio-input.md`
  - matmul source 支持从 MinIO manifest 拉取输入。
  - 未提供输入时保留 synthetic 数据 fallback。

- `result-object-storage-hardening.md`
  - 统一结果对象上传、登记和前端展示。
  - 明确 metric tags 只保存摘要，完整结果在 MinIO。

## Review 重点

- 是否把用户数据打进镜像。
- 是否重新引入 `/scratch` 作为业务节点间数据传递路径。
- Worker 是否能在没有输入对象时继续跑 synthetic demo。
- MinIO 凭据是否只通过环境变量/密钥注入，不写入镜像或日志。
- 结果对象是否进入 MinIO，并在数据库中有可追踪元数据。
