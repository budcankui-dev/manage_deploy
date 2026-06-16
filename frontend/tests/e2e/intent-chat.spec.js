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

async function createNode(request, suffix, index) {
  const response = await request.post('/api/nodes', {
    data: {
      hostname: `intent-${suffix}-${index}`,
      agent_address: `http://127.0.0.1:81${index}`,
      management_ip: `10.20.${index}.1`,
      business_ip: `10.21.${index}.1`,
      node_kind: 'both',
      is_schedulable: true,
      is_routable: true,
    },
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function prepareMatmulCatalog(request) {
  const suffix = Date.now().toString(36)
  const nodes = [
    await createNode(request, suffix, 1),
    await createNode(request, suffix, 2),
    await createNode(request, suffix, 3),
  ]

  const templateResponse = await request.post('/api/templates', {
    data: {
      name: `intent-chat-e2e-${suffix}`,
      description: 'Intent chat E2E source/compute/sink template',
      nodes: [
        {
          client_id: 'source',
          name: 'source',
          image: 'busybox:latest',
          command: 'sleep 3600',
          node_id: nodes[0].id,
        },
        {
          client_id: 'compute',
          name: 'compute',
          image: 'busybox:latest',
          command: 'sleep 3600',
          node_id: nodes[1].id,
        },
        {
          client_id: 'sink',
          name: 'sink',
          image: 'busybox:latest',
          command: 'sleep 3600',
          node_id: nodes[2].id,
        },
      ],
      edges: [
        { from_node_id: 'source', to_node_id: 'compute' },
        { from_node_id: 'compute', to_node_id: 'sink' },
      ],
    },
  })
  expect(templateResponse.ok()).toBeTruthy()
  const template = await templateResponse.json()

  const catalogResponse = await request.put('/api/business-template-catalog/high_throughput_matmul', {
    data: {
      task_type: 'high_throughput_matmul',
      modality: 'high_throughput_compute',
      template_id: template.id,
      source_node_name: 'source',
      compute_node_name: 'compute',
      sink_node_name: 'sink',
    },
  })
  expect(catalogResponse.ok()).toBeTruthy()

  const videoCatalogResponse = await request.put('/api/business-template-catalog/low_latency_video_pipeline', {
    data: {
      task_type: 'low_latency_video_pipeline',
      modality: 'low_latency_forwarding',
      template_id: template.id,
      source_node_name: 'source',
      compute_node_name: 'compute',
      sink_node_name: 'sink',
    },
  })
  expect(videoCatalogResponse.ok()).toBeTruthy()

  return {
    source: nodes[0].hostname,
    destination: nodes[2].hostname,
  }
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

test('intent chat parses matrix task and submits order', async ({ page, request }, testInfo) => {
  const auth = await loginByApi(request)
  const { source, destination } = await prepareMatmulCatalog(request)
  const conversation = await createConversation(request, auth.access_token)

  await page.addInitScript(({ token, role, username, conversationId }) => {
    window.localStorage.setItem('access_token', token)
    window.localStorage.setItem('role', role)
    window.localStorage.setItem('username', username)
    window.localStorage.setItem('lastConversationId', conversationId)
  }, {
    token: auth.access_token,
    role: auth.role,
    username,
    conversationId: conversation.id,
  })

  await page.goto('/intent-chat')
  await expect(page.getByPlaceholder(/描述您的计算任务需求/)).toBeVisible()

  const utterance = `矩阵乘法任务，从 ${source} 到 ${destination}，1024阶矩阵，50批，现在开始跑2小时，资源保障策略`
  await page.getByPlaceholder(/描述您的计算任务需求/).fill(utterance)
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('参数完整')).toBeVisible({ timeout: 20_000 })
  const panel = page.locator('.intent-panel')
  await expect(panel.getByRole('cell', { name: '矩阵乘法计算任务' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '高通量计算模态' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: source })).toBeVisible()
  await expect(panel.getByRole('cell', { name: destination })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '1024' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '50' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '资源保障', exact: true })).toBeVisible()
  await expect(panel.getByText('路由 DAG JSON 预览')).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('intent-chat-parsed.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: '确认提交任务' }).first().click()
  await expect(page.locator('.confirm-card').getByText('任务已提交')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('.confirm-card').getByText('待路由')).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('intent-chat-submitted.png'),
    fullPage: true,
  })
})

test('intent chat parses video task and demo-routes deployment', async ({ page, request }, testInfo) => {
  const auth = await loginByApi(request)
  const { source, destination } = await prepareMatmulCatalog(request)
  const conversation = await createConversation(request, auth.access_token)

  await page.addInitScript(({ token, role, username, conversationId }) => {
    window.localStorage.setItem('access_token', token)
    window.localStorage.setItem('role', role)
    window.localStorage.setItem('username', username)
    window.localStorage.setItem('lastConversationId', conversationId)
  }, {
    token: auth.access_token,
    role: auth.role,
    username,
    conversationId: conversation.id,
  })

  await page.goto('/intent-chat')
  await expect(page.getByPlaceholder(/描述您的计算任务需求/)).toBeVisible()

  const utterance = `视频AI推理任务，从 ${source} 到 ${destination}，720p视频，100帧，30fps，现在开始跑2小时，低时延策略`
  await page.getByPlaceholder(/描述您的计算任务需求/).fill(utterance)
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('参数完整')).toBeVisible({ timeout: 20_000 })
  const panel = page.locator('.intent-panel')
  await expect(panel.getByRole('cell', { name: '视频AI推理任务' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '低时延转发模态' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '720p' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '100' })).toBeVisible()
  await expect(panel.getByText('路由 DAG JSON 预览')).toBeVisible()

  await page.getByRole('button', { name: '确认提交任务' }).first().click()
  await expect(page.locator('.confirm-card').getByText('任务已提交')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('button', { name: '执行部署流程' }).first()).toBeVisible()

  await page.getByRole('button', { name: '执行部署流程' }).first().click()
  await expect(page.locator('.confirm-card').getByText('已部署')).toBeVisible({ timeout: 20_000 })

  await page.screenshot({
    path: testInfo.outputPath('intent-chat-video-demo-routed.png'),
    fullPage: true,
  })
})

test('intent chat keeps incomplete video draft unsubmitted and compactly shows node help', async ({ page, request }, testInfo) => {
  const auth = await loginByApi(request)
  const conversation = await createConversation(request, auth.access_token)

  await page.addInitScript(({ token, role, username, conversationId }) => {
    window.localStorage.setItem('access_token', token)
    window.localStorage.setItem('role', role)
    window.localStorage.setItem('username', username)
    window.localStorage.setItem('lastConversationId', conversationId)
  }, {
    token: auth.access_token,
    role: auth.role,
    username,
    conversationId: conversation.id,
  })

  await page.goto('/intent-chat')
  await expect(page.getByPlaceholder(/描述您的计算任务需求/)).toBeVisible()
  await expect(page.getByRole('button', { name: /可用节点/ })).toBeVisible()
  await expect(page.getByText('终端节点：h1-h13')).toBeHidden()

  await page.getByRole('button', { name: /可用节点/ }).click()
  await expect(page.getByText('终端节点：h1-h13')).toBeVisible()
  await expect(page.getByText('计算节点：compute-1、compute-2、compute-3')).toBeVisible()

  await page.getByPlaceholder(/描述您的计算任务需求/).fill('视频AI推理任务，从 h3 到 h4，720p视频，100帧，现在开始跑2小时，低时延策略')
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('参数待补充')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('帧率不能为空（例如：30fps）').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '确认提交任务' })).toHaveCount(0)
  await expect(page.getByText('请先补全参数')).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('intent-chat-incomplete-video.png'),
    fullPage: false,
  })
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
