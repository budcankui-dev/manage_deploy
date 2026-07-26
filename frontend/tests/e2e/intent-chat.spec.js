import { expect, test } from '@playwright/test'

const username = process.env.E2E_ADMIN_USERNAME || 'admin'
const password = process.env.E2E_ADMIN_PASSWORD || 'admin'

async function loginByApi(request) {
  let login = await request.post('/api/auth/login', {
    data: { username, password },
  })

  if (!login.ok()) {
    await request.post('/api/auth/bootstrap', {
      data: { username, password, role: 'admin' },
    })
    login = await request.post('/api/auth/login', {
      data: { username, password },
    })
  }

  expect(login.ok()).toBeTruthy()
  return login.json()
}

async function forceRuleParser(request) {
  const auth = await loginByApi(request)
  const current = await request.get('/api/admin/system-settings', {
    headers: { Authorization: `Bearer ${auth.access_token}` },
  })
  expect(current.ok()).toBeTruthy()
  const settings = await current.json()
  const updated = await request.put('/api/admin/system-settings', {
    headers: { Authorization: `Bearer ${auth.access_token}` },
    data: {
      ...settings,
      intent_parser_mode: 'rule',
      intent_rule_fallback_enabled: true,
      benchmark_routing_mode: 'internal_auto',
    },
  })
  expect(updated.ok()).toBeTruthy()
  return { auth, settings }
}

async function loginUserByApi(request, suffix = Date.now().toString(36)) {
  const userPrefix = process.env.E2E_USER_USERNAME || 'intent-user'
  const user = `${userPrefix}-${suffix}`
  const userPassword = process.env.E2E_USER_PASSWORD || '123456'
  let login = await request.post('/api/auth/login', {
    data: { username: user, password: userPassword },
  })

  if (!login.ok()) {
    await request.post('/api/auth/register', {
      data: { username: user, password: userPassword, role: 'user' },
    })
    login = await request.post('/api/auth/login', {
      data: { username: user, password: userPassword },
    })
  }

  expect(login.ok()).toBeTruthy()
  return { ...(await login.json()), username: user }
}

async function restoreSystemSettings(request, auth, settings) {
  if (!auth || !settings) return
  const restored = await request.put('/api/admin/system-settings', {
    headers: { Authorization: `Bearer ${auth.access_token}` },
    data: settings,
  })
  expect(restored.ok()).toBeTruthy()
}

async function officialEndpointPair(request) {
  const response = await request.get('/api/nodes?official_only=true')
  expect(response.ok()).toBeTruthy()
  const nodes = await response.json()
  const terminals = nodes
    .filter(node => node.node_kind === 'terminal' && node.is_routable !== false)
    .map(node => node.hostname)
  expect(terminals).toEqual(expect.arrayContaining(['h1', 'h2']))
  return {
    source: 'h1',
    destination: 'h2',
  }
}

async function expectCatalogAvailable(request, taskType) {
  const response = await request.get('/api/business-template-catalog')
  expect(response.ok()).toBeTruthy()
  const rows = await response.json()
  expect(rows.some(row => row.task_type === taskType && row.template_id)).toBeTruthy()
}

async function createConversation(request, token) {
  const response = await request.post('/api/conversations', {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    data: {},
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function parseUtteranceByApi(request, token, conversationId, utterance) {
  const response = await request.post(`/api/conversations/${conversationId}/messages`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { content: utterance },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function enableRouteOnlySubmit(request, token, conversationId, page) {
  const response = await request.patch(`/api/conversations/${conversationId}/draft`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { route_only: true },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  await page.reload()
  await expect(page.getByText('参数完整')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('button', { name: /高级提交选项/ })).toBeVisible()
}

test('intent chat parses matrix task and submits order', async ({ page, request }, testInfo) => {
  const { auth: adminAuth, settings } = await forceRuleParser(request)
  try {
    await expectCatalogAvailable(request, 'high_throughput_matmul')
    const auth = await loginUserByApi(request)
    const { source, destination } = await officialEndpointPair(request)
    const conversation = await createConversation(request, auth.access_token)

    await page.addInitScript(({ token, role, username, conversationId }) => {
      window.localStorage.setItem('access_token', token)
      window.localStorage.setItem('role', role)
      window.localStorage.setItem('username', username)
      window.localStorage.setItem('lastConversationId', conversationId)
    }, {
      token: auth.access_token,
      role: auth.role,
      username: auth.username,
      conversationId: conversation.id,
    })

    const utterance = `矩阵乘法任务，从 ${source} 到 ${destination}，1024阶矩阵，50批，现在开始跑2小时，资源保障策略`
    await parseUtteranceByApi(request, auth.access_token, conversation.id, utterance)

    await page.goto('/intent-chat')
    await expect(page.getByPlaceholder(/描述您的计算任务需求/)).toBeVisible()

    await expect(page.getByText('参数完整')).toBeVisible({ timeout: 20_000 })
    const panel = page.locator('.intent-panel')
    await expect(panel.locator('.intent-summary-row', { hasText: '任务类型' }).getByText('矩阵乘法计算任务')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '所属模态' }).getByText('高通量计算模态')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '源节点' }).getByText(source)).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '目的节点' }).getByText(destination)).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '矩阵规模' }).getByText('1024')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '批次数' }).getByText('50')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '路由策略' }).getByText('资源预留保障', { exact: true })).toBeVisible()

    await page.screenshot({
      path: testInfo.outputPath('intent-chat-parsed.png'),
      fullPage: true,
    })

    await enableRouteOnlySubmit(request, auth.access_token, conversation.id, page)
    await page.getByRole('button', { name: '确认提交任务' }).first().click()
    await expect(page.locator('.confirm-card').getByText('任务已提交')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.bubble-text').getByText(/待启动|手动启动计算节点/)).toBeVisible()

    await page.screenshot({
      path: testInfo.outputPath('intent-chat-submitted.png'),
      fullPage: true,
    })
  } finally {
    await restoreSystemSettings(request, adminAuth, settings)
  }
})

test('intent chat parses video task and submits order', async ({ page, request }, testInfo) => {
  const { auth: adminAuth, settings } = await forceRuleParser(request)
  try {
    await expectCatalogAvailable(request, 'low_latency_video_pipeline')
    const auth = await loginUserByApi(request)
    const { source, destination } = await officialEndpointPair(request)
    const conversation = await createConversation(request, auth.access_token)

    await page.addInitScript(({ token, role, username, conversationId }) => {
      window.localStorage.setItem('access_token', token)
      window.localStorage.setItem('role', role)
      window.localStorage.setItem('username', username)
      window.localStorage.setItem('lastConversationId', conversationId)
    }, {
      token: auth.access_token,
      role: auth.role,
      username: auth.username,
      conversationId: conversation.id,
    })

    const utterance = `视频AI推理任务，从 ${source} 到 ${destination}，720p视频片段100帧，统计30帧P90，30fps，现在开始跑2小时，低时延策略`
    await parseUtteranceByApi(request, auth.access_token, conversation.id, utterance)

    await page.goto('/intent-chat')
    await expect(page.getByPlaceholder(/描述您的计算任务需求/)).toBeVisible()

    await expect(page.getByText('参数完整')).toBeVisible({ timeout: 20_000 })
    const panel = page.locator('.intent-panel')
    await expect(panel.locator('.intent-summary-row', { hasText: '任务类型' }).getByText('视频AI推理任务')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '所属模态' }).getByText('低时延转发模态')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '输入视频规格' }).getByText('720p / 30fps')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '视频片段帧范围' }).getByText('100 帧')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '参与统计帧数' }).getByText('30 帧')).toBeVisible()

    await enableRouteOnlySubmit(request, auth.access_token, conversation.id, page)
    await page.getByRole('button', { name: '确认提交任务' }).first().click()
    await expect(page.locator('.confirm-card').getByText('任务已提交')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.bubble-text').getByText(/待启动|手动启动计算节点/)).toBeVisible()

    await page.screenshot({
      path: testInfo.outputPath('intent-chat-video-submitted.png'),
      fullPage: true,
    })
  } finally {
    await restoreSystemSettings(request, adminAuth, settings)
  }
})

test('intent chat keeps incomplete video draft unsubmitted and compactly shows node help', async ({ page, request }, testInfo) => {
  const { auth: adminAuth, settings } = await forceRuleParser(request)
  try {
    const auth = await loginUserByApi(request)
    const conversation = await createConversation(request, auth.access_token)

    await page.addInitScript(({ token, role, username, conversationId }) => {
      window.localStorage.setItem('access_token', token)
      window.localStorage.setItem('role', role)
      window.localStorage.setItem('username', username)
      window.localStorage.setItem('lastConversationId', conversationId)
    }, {
      token: auth.access_token,
      role: auth.role,
      username: auth.username,
      conversationId: conversation.id,
    })

    const utterance = '视频AI推理任务，从 h3 到 h4，720p视频，100帧，现在开始跑2小时，低时延策略'
    await parseUtteranceByApi(request, auth.access_token, conversation.id, utterance)

    await page.goto('/intent-chat')
    await expect(page.getByPlaceholder(/描述您的计算任务需求/)).toBeVisible()
    await expect(page.getByRole('button', { name: /可用节点/ })).toBeVisible()
    await expect(page.getByText(/终端节点：/)).toBeHidden()

    await page.getByRole('button', { name: /可用节点/ }).click()
    await expect(page.getByText(/终端节点：/)).toBeVisible()
    await expect(page.getByText(/计算节点：/)).toBeVisible()
    await expect(page.getByText(/不作为源\/目的输入/)).toBeVisible()

    await expect(page.getByText('参数待补充')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('补全后系统才会允许提交任务')).toBeVisible()
    await expect(page.locator('.pending-card').getByText(/帧率.*30fps/)).toBeVisible()
    await expect(page.getByRole('button', { name: '确认提交任务' })).toHaveCount(0)

    await page.screenshot({
      path: testInfo.outputPath('intent-chat-incomplete-video.png'),
      fullPage: false,
    })
  } finally {
    await restoreSystemSettings(request, adminAuth, settings)
  }
})

test('expired admin session shows Chinese login prompt and returns to admin home', async ({ page, request }) => {
  const auth = await loginByApi(request)
  const staleConversation = await createConversation(request, auth.access_token)

  await page.goto('/login')
  await page.evaluate(({ staleConversationId }) => {
    window.localStorage.setItem('access_token', 'expired-token')
    window.localStorage.setItem('role', 'user')
    window.localStorage.setItem('username', 'stale-user')
    window.localStorage.setItem('lastConversationId', staleConversationId)
  }, {
    staleConversationId: staleConversation.id,
  })

  await page.goto('/intent-chat')
  await expect(page).toHaveURL(/\/login\?redirect=/)
  await expect(page.getByText('登录已过期，请重新登录')).toBeVisible()
  await expect.poll(
    () => page.evaluate(() => window.localStorage.getItem('lastConversationId'))
  ).toBeNull()

  await page.getByPlaceholder('admin').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()

  await expect(page).toHaveURL(/\/business-tasks/)
  await expect(page.getByRole('heading', { name: '业务工单中心' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '新对话' })).toHaveCount(0)
})

test('admin user cannot stay on intent chat route', async ({ page, request }) => {
  const auth = await loginByApi(request)

  await page.goto('/login')
  await page.evaluate(({ token, role, username }) => {
    window.localStorage.setItem('access_token', token)
    window.localStorage.setItem('role', role)
    window.localStorage.setItem('username', username)
  }, {
    token: auth.access_token,
    role: auth.role,
    username,
  })

  await page.goto('/intent-chat')

  await expect(page).toHaveURL(/\/business-tasks/)
  await expect(page.getByRole('heading', { name: '业务工单中心' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '新对话' })).toHaveCount(0)
})

test('user matmul order detail shows authenticated endpoint startup guide', async ({ page }, testInfo) => {
  const orderId = 'order-user-access-matmul'
  const instanceId = 'instance-user-access-matmul'
  const detail = {
    id: orderId,
    status: 'completed',
    routing_status: 'completed',
    materialized_instance_id: instanceId,
    instance_exists: true,
    source_name: 'h1',
    destination_name: 'h2',
    task_type: 'high_throughput_matmul',
    business_start_time: '2026-06-28T10:00:00+08:00',
    business_end_time: '2026-06-28T12:00:00+08:00',
    created_at: '2026-06-28T10:00:00+08:00',
    runtime_config: {
      platform_deployment: {
        mode: 'user_access_demo',
        deployable_roles: ['compute'],
        external_endpoints: {
          source: {
            topology_node_id: 'h1',
            business_ipv6: '3012:9::11',
          },
          sink: {
            topology_node_id: 'h2',
            business_ipv6: '3012:9::12',
            business_port: 9000,
            callback_url: 'http://[3012:9::12]:9000/callback',
          },
        },
      },
    },
    user_access_guide: {
      task_label: '矩阵乘法计算任务',
      receiver_url: 'http://[3012:9::12]:9000',
      receiver_command: 'docker run -d --name user-order-receiver --network host scientific-matmul-endpoint python3 /app/src/receiver_main.py --port 9000',
      compute_url: 'http://[3012:a::ec4:7aff:fe85:7815]:18000',
      compute_status: 'running',
      compute_ready: true,
      source_command: 'docker run --rm --name user-order-source --network host PEER_COMPUTE_URL=http://[3012:a::ec4:7aff:fe85:7815]:18000 scientific-matmul-endpoint python3 /app/src/source_main.py',
      result_hint: 'receiver 页面会展示实际有效计算吞吐量、参数和业务目标判定。',
      source: { hostname: 'h1', management_ip: '172.16.0.151', business_address: '3012:9::11', ssh_command: 'ssh -p 22 switchpc1@172.16.0.151', ssh_password: 'demo-password' },
      sink: { hostname: 'h2', port: 9000, management_ip: '172.16.0.152', business_address: '3012:9::12', ssh_command: 'ssh -p 22 switchpc1@172.16.0.152', ssh_password: 'demo-password' },
    },
    business_task: {
      task_type: 'high_throughput_matmul',
      modality: 'high_throughput_compute',
      source_name: 'h1',
      destination_name: 'h2',
      source_endpoint: {
        topology_node_id: 'h1',
        business_ipv6: '3012:9::11',
      },
      destination_endpoint: {
        topology_node_id: 'h2',
        business_ipv6: '3012:9::12',
        business_port: 9000,
        callback_url: 'http://[3012:9::12]:9000/callback',
      },
      callback_url: 'http://[3012:9::12]:9000/callback',
      data_profile: {
        matrix_size: 1024,
        batch_count: 50,
        seed: 42,
      },
      runtime_plan: {
        routing_strategy: 'resource_guarantee',
        destination_port: 9000,
      },
      business_objective: {
        metric_key: 'effective_gflops',
        operator: '>=',
        target_value: 4000,
        unit: 'GFLOPS',
      },
    },
    routing_result: {
      strategy: 'resource_guarantee',
      network_ready: true,
      network_ready_required: false,
      placements: [
        { task_node_id: 'source', topology_node_id: 'h1' },
        { task_node_id: 'compute', topology_node_id: 'compute-3', gpu_device: '0' },
        { task_node_id: 'sink', topology_node_id: 'h2' },
      ],
      network_bindings: [
        {
          from: 'source',
          to: 'compute',
          src_external: true,
          dst_external: false,
          src_host: 'h1',
          dst_host: 'compute-3',
          src_ip: '3012:9::11',
          dst_ip: '3012:a::ec4:7aff:fe85:7815',
          dst_port: 18000,
          dst_access_url: 'http://[3012:a::ec4:7aff:fe85:7815]:18000',
          dst_named_ports: { compute: 18000 },
        },
        {
          from: 'compute',
          to: 'sink',
          src_external: false,
          dst_external: true,
          src_host: 'compute-3',
          dst_host: 'h2',
          src_ip: '3012:a::ec4:7aff:fe85:7815',
          dst_ip: '3012:9::12',
          dst_port: 9000,
          dst_access_url: 'http://[3012:9::12]:9000',
          dst_named_ports: { external: 9000 },
        },
      ],
    },
    instance: {
      id: instanceId,
      status: 'stopped',
      node_count: 1,
      error_message: null,
      port_access_urls: {
        'compute/compute': 'http://[3012:a::ec4:7aff:fe85:7815]:18000',
      },
    },
    evaluation: {
      task_type: 'high_throughput_matmul',
      metric_key: 'effective_gflops',
      actual_value: 5200.5,
      target_value: 4000,
      operator: '>=',
      unit: 'GFLOPS',
      business_success: true,
      result_metadata: {
        matrix_size: 1024,
        batch_count: 50,
        compute_latency_ms: 1024.25,
        sample_count: 6,
        backend: 'cuda',
        gpu_device: '0',
        effective_gflops: 5200.5,
      },
    },
  }

  await page.route('**/api/auth/me', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'user-id', username: 'demo-user', role: 'user' }),
  }))
  await page.route('**/api/orders?**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{
        id: orderId,
        order_id: orderId,
        task_type: 'high_throughput_matmul',
        status: 'completed',
        order_status: 'completed',
        routing_status: 'completed',
        deployment_status: 'stopped',
        created_at: detail.created_at,
      }],
      total: 1,
    }),
  }))
  await page.route(`**/api/orders/${orderId}`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(detail),
  }))
  await page.route(`**/api/business-tasks/${instanceId}/results**`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route(/.*\/api\/demo-assets\/video\/.*/, route => route.fulfill({
    status: 204,
    body: '',
  }))

  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-user-token')
    window.localStorage.setItem('role', 'user')
    window.localStorage.setItem('username', 'demo-user')
  })

  await page.goto('/my-orders')
  await expect(page.getByText('我的工单').first()).toBeVisible()
  await page.getByText('矩阵乘法计算任务').first().click()

  await expect(page.getByText('矩阵乘法计算任务').first()).toBeVisible()
  await page.getByRole('tab', { name: '部署' }).click()
  await expect(page.getByText('按顺序启动用户侧容器')).toBeVisible()
  await expect(page.getByText('目的端：启动 receiver 并保持运行')).toBeVisible()
  await expect(page.getByText('ssh -p 22 switchpc1@172.16.0.152')).toBeVisible()
  await expect(page.getByText(/python3 \/app\/src\/receiver_main.py --port 9000/)).toBeVisible()
  await expect(page.getByText(/PEER_COMPUTE_URL=http:\/\/\[3012:a::ec4:7aff:fe85:7815\]:18000/)).toBeVisible()

  await page.getByText('矩阵乘法计算任务').first().scrollIntoViewIfNeeded()
  await page.screenshot({
    path: testInfo.outputPath('my-orders-user-access-summary.png'),
    fullPage: true,
  })

  await page.getByRole('tab', { name: '结果' }).click()
  await expect(page.getByText('验收证据')).toBeVisible()
  await expect(page.getByText('业务目标已达标')).toBeVisible()
  await expect(page.getByText(/有效计算吞吐量：/)).toBeVisible()
  await expect(page.getByText('采样次数：')).toBeVisible()
  await expect(page.getByText('执行后端：')).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('my-orders-user-access-commands-and-result.png'),
    fullPage: true,
  })
})

test('user video order detail shows startup guide and receiver result evidence', async ({ page }, testInfo) => {
  const orderId = 'order-user-access-video'
  const instanceId = 'instance-user-access-video'
  const previewSvg = encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#0f172a"/><rect x="210" y="92" width="180" height="170" fill="none" stroke="#22c55e" stroke-width="8"/><text x="220" y="84" fill="#fff" font-size="28">瓶子 0.91</text></svg>')
  const detail = {
    id: orderId,
    status: 'completed',
    routing_status: 'completed',
    materialized_instance_id: instanceId,
    instance_exists: true,
    source_name: 'h3',
    destination_name: 'h4',
    task_type: 'low_latency_video_pipeline',
    business_start_time: '2026-06-28T10:00:00+08:00',
    business_end_time: '2026-06-28T12:00:00+08:00',
    created_at: '2026-06-28T10:00:00+08:00',
    runtime_config: {
      platform_deployment: {
        mode: 'user_access_demo',
        deployable_roles: ['compute'],
        external_endpoints: {
          source: { topology_node_id: 'h3', business_ipv6: '3012:9::13' },
          sink: {
            topology_node_id: 'h4',
            business_ipv6: '3012:9::14',
            business_port: 9100,
            callback_url: 'http://[3012:9::14]:9100/callback',
          },
        },
      },
    },
    user_access_guide: {
      task_label: '视频AI推理任务',
      receiver_url: 'http://[3012:9::14]:9100',
      receiver_command: 'docker run -d --name user-video-receiver --network host low-latency-video-endpoint python3 /app/src/receiver_main.py --port 9100',
      compute_url: 'http://[3012:a::2]:18000',
      compute_status: 'running',
      compute_ready: true,
      source_command: 'docker run --rm --name user-video-source --network host PEER_COMPUTE_URL=http://[3012:a::2]:18000 low-latency-video-endpoint python3 /app/src/source_main.py',
      result_hint: '视频 receiver 页面会自动展示带框推理帧、检测类别、置信度与时延。',
      source: { hostname: 'h3', management_ip: '172.16.0.153', business_address: '3012:9::13', ssh_command: 'ssh -p 22 switchpc1@172.16.0.153', ssh_password: 'demo-password' },
      sink: { hostname: 'h4', port: 9100, management_ip: '172.16.0.154', business_address: '3012:9::14', ssh_command: 'ssh -p 22 switchpc1@172.16.0.154', ssh_password: 'demo-password' },
    },
    business_task: {
      task_type: 'low_latency_video_pipeline',
      modality: 'low_latency_forwarding',
      source_name: 'h3',
      destination_name: 'h4',
      source_endpoint: { topology_node_id: 'h3', business_ipv6: '3012:9::13' },
      destination_endpoint: {
        topology_node_id: 'h4',
        business_ipv6: '3012:9::14',
        business_port: 9100,
        callback_url: 'http://[3012:9::14]:9100/callback',
      },
      callback_url: 'http://[3012:9::14]:9100/callback',
      data_profile: {
        profile_id: 'video_industrial_inspection_720p',
        resolution: '720p',
        fps: 30,
        frame_count: 100,
        frame_stride: 30,
        warmup_frames: 10,
        measured_frames: 30,
        model_name: 'yolov5n',
      },
      runtime_plan: {
        routing_strategy: 'low_latency_forwarding',
        destination_port: 9100,
      },
      business_objective: {
        metric_key: 'frame_latency_p90_ms',
        operator: '<=',
        target_value: 80,
        unit: 'ms',
      },
    },
    routing_result: {
      strategy: 'low_latency_forwarding',
      network_ready: true,
      network_ready_required: false,
      placements: [
        { task_node_id: 'source', topology_node_id: 'h3' },
        { task_node_id: 'compute', topology_node_id: 'compute-2', gpu_device: '0' },
        { task_node_id: 'sink', topology_node_id: 'h4' },
      ],
      network_bindings: [
        {
          from: 'source',
          to: 'compute',
          src_external: true,
          dst_external: false,
          src_host: 'h3',
          dst_host: 'compute-2',
          src_ip: '3012:9::13',
          dst_ip: '3012:a::2',
          dst_port: 18000,
          dst_access_url: 'http://[3012:a::2]:18000',
          dst_named_ports: { compute: 18000 },
        },
        {
          from: 'compute',
          to: 'sink',
          src_external: false,
          dst_external: true,
          src_host: 'compute-2',
          dst_host: 'h4',
          src_ip: '3012:a::2',
          dst_ip: '3012:9::14',
          dst_port: 9100,
          dst_access_url: 'http://[3012:9::14]:9100',
          dst_named_ports: { external: 9100 },
        },
      ],
    },
    instance: {
      id: instanceId,
      status: 'stopped',
      node_count: 1,
      error_message: null,
      port_access_urls: {
        'compute/compute': 'http://[3012:a::2]:18000',
      },
    },
    evaluation: {
      task_type: 'low_latency_video_pipeline',
      metric_key: 'frame_latency_p90_ms',
      actual_value: 42.6,
      target_value: 80,
      operator: '<=',
      unit: 'ms',
      business_success: true,
      result_metadata: {
        model_name: 'yolov5n',
        video_asset: 'bottle-detection.mp4',
        detector_backend: 'onnxruntime',
        actual_backend: 'cuda',
        device: 'GPU',
        gpu_assigned: true,
        measured_frames: 30,
        frame_latency_avg_ms: 31.2,
        frame_latency_p90_ms: 42.6,
        annotated_frame_index: 60,
        annotated_frame_latency_ms: 38.5,
        annotated_frame_data_url: `data:image/svg+xml,${previewSvg}`,
        annotated_frame_overlay: 'embedded_boxes_v1',
        detection_count: 1,
        top_label: 'bottle',
        top_label_zh: '瓶子',
        top_confidence: 0.91,
        detections: [
          { label: 'bottle', label_zh: '瓶子', confidence: 0.91, bbox_xyxy: [210, 92, 390, 262] },
        ],
      },
    },
  }

  await page.route('**/api/auth/me', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'user-id', username: 'demo-user', role: 'user' }),
  }))
  await page.route('**/api/orders?**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{
        id: orderId,
        order_id: orderId,
        task_type: 'low_latency_video_pipeline',
        status: 'completed',
        order_status: 'completed',
        routing_status: 'completed',
        deployment_status: 'stopped',
        created_at: detail.created_at,
      }],
      total: 1,
    }),
  }))
  await page.route(`**/api/orders/${orderId}`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(detail),
  }))
  await page.route(`**/api/business-tasks/${instanceId}/results**`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))

  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-user-token')
    window.localStorage.setItem('role', 'user')
    window.localStorage.setItem('username', 'demo-user')
  })

  await page.goto('/my-orders')
  await expect(page.getByText('我的工单').first()).toBeVisible()
  await page.getByText('视频AI推理任务').first().click()

  await expect(page.getByText('视频AI推理任务').first()).toBeVisible()
  await page.getByRole('tab', { name: '部署' }).click()
  await expect(page.getByText('按顺序启动用户侧容器')).toBeVisible()
  await expect(page.getByText('ssh -p 22 switchpc1@172.16.0.154')).toBeVisible()
  await expect(page.getByText(/python3 \/app\/src\/receiver_main.py --port 9100/)).toBeVisible()
  await expect(page.getByText(/PEER_COMPUTE_URL=http:\/\/\[3012:a::2\]:18000/)).toBeVisible()

  await page.getByText('视频AI推理任务').first().scrollIntoViewIfNeeded()
  await page.screenshot({
    path: testInfo.outputPath('my-orders-video-user-access-summary.png'),
    fullPage: true,
  })

  await page.getByRole('tab', { name: '结果' }).click()
  await expect(page.getByText('业务目标已达标')).toBeVisible()
  await expect(page.getByText(/帧推理时延 P90：42.60 ms/)).toBeVisible()
  await expect(page.getByText('参与统计帧数：')).toBeVisible()
  await expect(page.getByText('识别目标：瓶子', { exact: true })).toBeVisible()
  await expect(page.locator('.el-table').getByText('瓶子 / bottle', { exact: true })).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('my-orders-video-user-access-result.png'),
    fullPage: true,
  })
})
