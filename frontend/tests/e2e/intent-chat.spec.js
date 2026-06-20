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

    const utterance = `视频AI推理任务，从 ${source} 到 ${destination}，720p视频，100帧，30fps，现在开始跑2小时，低时延策略`
    await parseUtteranceByApi(request, auth.access_token, conversation.id, utterance)

    await page.goto('/intent-chat')
    await expect(page.getByPlaceholder(/描述您的计算任务需求/)).toBeVisible()

    await expect(page.getByText('参数完整')).toBeVisible({ timeout: 20_000 })
    const panel = page.locator('.intent-panel')
    await expect(panel.locator('.intent-summary-row', { hasText: '任务类型' }).getByText('视频AI推理任务')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '所属模态' }).getByText('低时延转发模态')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '输入视频规格' }).getByText('720p / 30fps')).toBeVisible()
    await expect(panel.locator('.intent-summary-row', { hasText: '本次抽检帧数' }).getByText('100 帧')).toBeVisible()

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
    await expect(page.getByText('帧率不能为空（例如：30fps）').first()).toBeVisible()
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
