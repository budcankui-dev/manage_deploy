import { expect, test } from '@playwright/test'

const username = process.env.E2E_ADMIN_USERNAME || 'codex-e2e-admin'
const password = process.env.E2E_ADMIN_PASSWORD || '123456'

async function ensureAdminUser(request) {
  let login = await request.post('/api/auth/login', {
    data: { username, password },
  })
  if (login.ok()) return

  await request.post('/api/auth/users', {
    data: { username, password, role: 'admin' },
  }).catch(() => null)
  await request.post('/api/auth/bootstrap', {
    data: { username, password, role: 'admin' },
  }).catch(() => null)

  login = await request.post('/api/auth/login', {
    data: { username, password },
  })
  expect(login.ok()).toBeTruthy()
}

async function fillCredentials(page) {
  await page.getByPlaceholder('admin').fill(username)
  await page.locator('input[type="password"]').fill(password)
}

async function loginOrBootstrap(page, request) {
  await ensureAdminUser(request)
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()

  await fillCredentials(page)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/business-tasks/, { timeout: 10_000 })
}

test('admin can inspect the business task hub', async ({ page, request }, testInfo) => {
  await loginOrBootstrap(page, request)

  await expect(page.getByRole('heading', { name: '业务工单中心' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '工单列表' })).toBeVisible()
  await expect(page.getByRole('button', { name: '应用筛选' })).toBeVisible()
  await expect(page.getByText('清理实例会释放远端容器和实例记录')).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('business-tasks-hub.png'),
    fullPage: true,
  })
})

test('admin sidebar navigation responds from benchmark page', async ({ page, request }, testInfo) => {
  await loginOrBootstrap(page, request)

  await page.goto('/benchmark')
  await expect(page.getByRole('button', { name: '拓扑节点' })).toBeVisible()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await expect(page.getByRole('heading', { name: '拓扑节点' })).toBeVisible()

  await page.getByRole('button', { name: '系统设置' }).click()
  await page.waitForURL(/\/settings/, { timeout: 10_000 })
  await expect(page.getByRole('heading', { name: '运行配置与系统参数' })).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('admin-sidebar-navigation.png'),
    fullPage: true,
  })
})

test('benchmark running state survives sidebar navigation', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-admin-token')
    window.localStorage.setItem('role', 'admin')
    window.localStorage.setItem('username', 'admin')
    window.localStorage.setItem('manage-deploy:benchmark-run-id', 'high_throughput_matmul-e2e-running')
    window.localStorage.setItem('manage-deploy:benchmark-run-session', JSON.stringify({
      taskType: 'high_throughput_matmul',
      benchmarkRunId: 'high_throughput_matmul-e2e-running',
      phase: 'running',
      updatedAt: new Date().toISOString(),
    }))
  })
  await page.route('**/api/auth/me', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'admin', username: 'admin', role: 'admin' }),
  }))
  await page.route('**/api/admin/system-settings', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      benchmark_routing_mode: 'internal_auto',
      expert_mode: true,
      show_internal_controls: false,
      show_routing_dag_json: false,
      benchmark_execution_defaults: {
        default_task_count: 30,
        max_parallel: 2,
        per_compute_slot_limit: 1,
      },
    }),
  }))
  await page.route('**/api/nodes**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        id: 'compute-1-id',
        hostname: 'compute-1',
        node_kind: 'worker',
        is_schedulable: true,
        gpu_count: 1,
        gpu_model: 'NVIDIA TITAN Xp',
      },
      {
        id: 'h1-id',
        hostname: 'h1',
        node_kind: 'terminal',
        is_schedulable: true,
      },
    ]),
  }))
  await page.route('**/api/baselines**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        node_id: 'compute-1-id',
        task_type: 'high_throughput_matmul',
        metric_key: 'effective_gflops',
        baseline_value: 5500,
        unit: 'GFLOPS',
        stable: true,
        raw_values: [5480, 5500, 5520],
      },
    ]),
  }))
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        task_type: 'high_throughput_matmul',
        count: 30,
        evaluated_count: 3,
        success_count: 3,
        business_success_rate: 1,
      },
    ]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [
        {
          id: 'order-running-1',
          task_type: 'high_throughput_matmul',
          status: 'materialized',
          routing_status: 'completed',
          deployment_status: 'running',
          materialized_instance_id: 'instance-running-1',
          runtime_config: {
            benchmark: { run_id: 'high_throughput_matmul-e2e-running' },
            business_task: { modality: '高通量计算模态' },
            routing_result: { placements: [{ task_node_id: 'compute', topology_node_id: 'compute-1', gpu_device: '0' }] },
          },
          created_at: new Date().toISOString(),
        },
      ],
    }),
  }))
  await page.route('**/api/orders/start-controlled-routed', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      total: 30,
      evaluated: 3,
      active: 1,
      started: 0,
      cleaned: 0,
      pending_to_start: 26,
    }),
  }))

  await page.goto('/benchmark')
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()
  await expect(page.locator('.step-card').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await page.getByRole('button', { name: '业务测评' }).click()
  await page.waitForURL(/\/benchmark/, { timeout: 10_000 })
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()
  await expect(page.locator('.step-card').getByRole('button', { name: '测评运行中' })).toBeDisabled()
  await expect(page.getByText('当前测评轮次正在执行')).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('benchmark-running-state-survives-navigation.png'),
    fullPage: true,
  })
})

test('benchmark full-flow click locks immediately before batch API returns', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-admin-token')
    window.localStorage.setItem('role', 'admin')
    window.localStorage.setItem('username', 'admin')
  })
  await page.route('**/api/auth/me', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'admin', username: 'admin', role: 'admin' }),
  }))
  await page.route('**/api/admin/system-settings', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      benchmark_routing_mode: 'internal_auto',
      expert_mode: true,
      show_internal_controls: false,
      show_routing_dag_json: false,
      benchmark_execution_defaults: {
        default_task_count: 30,
        max_parallel: 2,
        per_compute_slot_limit: 1,
      },
    }),
  }))
  await page.route('**/api/nodes**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        id: 'compute-1-id',
        hostname: 'compute-1',
        node_kind: 'worker',
        is_schedulable: true,
        gpu_count: 1,
        gpu_model: 'NVIDIA TITAN Xp',
      },
      {
        id: 'h1-id',
        hostname: 'h1',
        node_kind: 'terminal',
        is_schedulable: true,
      },
      {
        id: 'h2-id',
        hostname: 'h2',
        node_kind: 'terminal',
        is_schedulable: true,
      },
    ]),
  }))
  await page.route('**/api/baselines**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        node_id: 'compute-1-id',
        task_type: 'high_throughput_matmul',
        metric_key: 'effective_gflops',
        baseline_value: 5500,
        unit: 'GFLOPS',
        stable: true,
        raw_values: [5480, 5500, 5520],
      },
    ]),
  }))
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ items: [] }),
  }))
  await page.route('**/api/orders/batch-benchmark', async () => {
    await new Promise(() => {})
  })

  await page.goto('/benchmark')
  await page.getByRole('button', { name: '开始完整测试流程' }).click()
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await page.getByRole('button', { name: '业务测评' }).click()
  await page.waitForURL(/\/benchmark/, { timeout: 10_000 })
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  const session = await page.evaluate(() => JSON.parse(window.localStorage.getItem('manage-deploy:benchmark-run-session')))
  expect(session.taskType).toBe('high_throughput_matmul')
  expect(session.phase).toBe('creating')
  expect(session.benchmarkRunId).toContain('high_throughput_matmul-')
})

test('benchmark full-flow click locks while refreshing page data', async ({ page }) => {
  let baselineRequests = 0
  await page.addInitScript(() => {
    window.localStorage.setItem('access_token', 'fake-admin-token')
    window.localStorage.setItem('role', 'admin')
    window.localStorage.setItem('username', 'admin')
  })
  await page.route('**/api/auth/me', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'admin', username: 'admin', role: 'admin' }),
  }))
  await page.route('**/api/admin/system-settings', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      benchmark_routing_mode: 'internal_auto',
      expert_mode: true,
      show_internal_controls: false,
      show_routing_dag_json: false,
      benchmark_execution_defaults: {
        default_task_count: 30,
        max_parallel: 2,
        per_compute_slot_limit: 1,
      },
    }),
  }))
  await page.route('**/api/nodes**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        id: 'compute-1-id',
        hostname: 'compute-1',
        node_kind: 'worker',
        is_schedulable: true,
        gpu_count: 1,
        gpu_model: 'NVIDIA TITAN Xp',
      },
      {
        id: 'h1-id',
        hostname: 'h1',
        node_kind: 'terminal',
        is_schedulable: true,
      },
      {
        id: 'h2-id',
        hostname: 'h2',
        node_kind: 'terminal',
        is_schedulable: true,
      },
    ]),
  }))
  await page.route('**/api/baselines**', async route => {
    baselineRequests += 1
    if (baselineRequests > 1) {
      await new Promise(() => {})
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          node_id: 'compute-1-id',
          task_type: 'high_throughput_matmul',
          metric_key: 'effective_gflops',
          baseline_value: 5500,
          unit: 'GFLOPS',
          stable: true,
          raw_values: [5480, 5500, 5520],
        },
      ]),
    })
  })
  await page.route('**/api/orders/benchmark/recalculate', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ succeeded: [], failed: {} }),
  }))
  await page.route('**/api/business-tasks/summary**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route('**/api/orders?**', async route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ items: [] }),
  }))

  await page.goto('/benchmark')
  await page.getByRole('button', { name: '开始完整测试流程' }).click()
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  await page.getByRole('button', { name: '拓扑节点' }).click()
  await page.waitForURL(/\/nodes/, { timeout: 10_000 })
  await page.getByRole('button', { name: '业务测评' }).click()
  await page.waitForURL(/\/benchmark/, { timeout: 10_000 })
  await expect(page.locator('section').getByRole('button', { name: '测评运行中' })).toBeDisabled()

  const session = await page.evaluate(() => JSON.parse(window.localStorage.getItem('manage-deploy:benchmark-run-session')))
  expect(session.phase).toBe('creating')
})

test('optional headed matmul demo trigger is visible', async ({ page, request }, testInfo) => {
  test.skip(
    process.env.E2E_TRIGGER_MATMUL_DEMO !== '1',
    'Set E2E_TRIGGER_MATMUL_DEMO=1 to click the UI demo button.'
  )

  await loginOrBootstrap(page, request)

  await page.getByRole('button', { name: '一键演示矩阵乘法' }).click()
  await expect(
    page.getByText(/矩阵乘法示例任务|至少需要 3 个可调度拓扑节点|任务已提交|演示完成/)
  ).toBeVisible({ timeout: 300_000 })

  await page.screenshot({
    path: testInfo.outputPath('matmul-demo-trigger.png'),
    fullPage: true,
  })
})
