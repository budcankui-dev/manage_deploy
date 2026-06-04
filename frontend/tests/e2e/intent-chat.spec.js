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
  await expect(panel.getByRole('cell', { name: source })).toBeVisible()
  await expect(panel.getByRole('cell', { name: destination })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '1024' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '50' })).toBeVisible()
  await expect(panel.getByRole('cell', { name: '资源保障', exact: true })).toBeVisible()

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
