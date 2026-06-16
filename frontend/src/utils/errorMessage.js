const MESSAGE_MAP = [
  [/missing bearer token/i, '登录状态已失效，请重新登录'],
  [/token expired/i, '登录已过期，请重新登录'],
  [/invalid token/i, '登录状态无效，请重新登录'],
  [/invalid username or password/i, '用户名或密码错误'],
  [/admin role required/i, '当前账号没有管理员权限'],
  [/users already exist/i, '管理员账号已初始化'],
  [/username already exists/i, '用户名已存在'],
  [/username and password are required/i, '请填写用户名和密码'],
  [/order_ids or benchmark_run_id is required/i, '请选择工单或测评轮次'],
  [/external_task_id already exists/i, '外部任务 ID 已存在'],
  [/template node\(s\) not found/i, '模板节点不存在'],
  [/scheduled_start_time is required/i, '请选择计划启动时间'],
  [/routing completed but no placements provided/i, '路由已完成，但未返回节点分配结果'],
  [/no catalog entry for template_id=/i, '未找到对应的业务模板配置'],
  [/failed to build overrides/i, '生成部署参数失败'],
  [/materialization failed/i, '物化部署实例失败'],
  [/order has no materialized instance/i, '工单尚未生成部署实例'],
  [/materialized instance not found/i, '部署实例不存在或已被清理'],
  [/order missing business objective metric_key/i, '工单缺少业务指标配置'],
  [/no reported metric found/i, '尚未上报业务指标'],
  [/metric exists but evaluation could not be built/i, '指标已上报，但无法生成评估结果'],
  [/cannot start instance in status/i, '当前实例状态不允许启动'],
  [/valid intent draft required/i, '请先生成有效的意图解析结果'],
  [/routing request not found/i, '路由请求不存在'],
  [/conversation not found/i, '对话不存在'],
  [/file not found/i, '文件不存在'],
  [/demo video asset not found/i, '演示视频文件不存在'],
  [/failed to upload to minio/i, '上传结果文件失败'],
  [/template not found/i, '模板不存在'],
  [/node machine not found/i, '节点机器不存在'],
  [/node not found/i, '节点不存在'],
  [/baseline already exists/i, '该节点的基线记录已存在'],
  [/baseline not found/i, '基线记录不存在'],
  [/user not found/i, '用户不存在'],
  [/order not found/i, '工单不存在'],
  [/instance not found/i, '实例不存在'],
  [/not found/i, '数据不存在'],
  [/unknown error/i, '未知错误'],
  [/network error/i, '网络连接失败，请检查服务是否可用'],
  [/timeout/i, '请求超时，请稍后重试'],
]

function hasChinese(text) {
  return /[\u4e00-\u9fff]/.test(text)
}

export function normalizeErrorMessage(message, fallback = '请求失败') {
  if (message == null) return fallback
  const text = typeof message === 'string' ? message : JSON.stringify(message)
  if (!text) return fallback
  if (hasChinese(text)) return text

  const matched = MESSAGE_MAP.find(([pattern]) => pattern.test(text))
  return matched ? matched[1] : fallback
}

export function extractErrorMessage(error, fallback = '请求失败') {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((item) => normalizeErrorMessage(item, fallback)).join('；')
  }
  return normalizeErrorMessage(detail || error?.message, fallback)
}
